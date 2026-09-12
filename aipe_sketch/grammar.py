"""Global drawing grammar: semantic relations to placement constraints.

This is the only auto-planning layer that knows rows, orientations or spacing.
No circuit name or reference designator has drawing significance here.
"""
from .plan import Group, Item, LayoutPlan, ROWS, ROWS_TALL, Slot
from .electrical import power_ports
from .analysis import POLARITY


def lower(plan, netlist):
    repeated_legs = max((len(b.legs) for b in plan.blocks), default=0)
    rows = dict(ROWS_TALL if repeated_legs > 2 or
                sum(b.motif == 'bridge' for b in plan.blocks) > 1 else ROWS)
    groups, locations, trunks = [], {}, {}
    net_rows = {n: 'dc_neg' for n in plan.return_nets}
    controls = {}
    for ref, target, port in plan.control_interfaces:
        if target:
            controls.setdefault(target, []).append((ref, port))
    level = 'dc_pos'

    def slot(ref, row, rot=0):
        s = Slot(Item(ref, row, rot=rot))
        locations[ref] = s
        for gate, port in controls.get(ref, ()):
            # Local attachment: a control interface follows its actual gate,
            # rather than acquiring a power boundary marker or a power row.
            s.items.append(Item(gate, row, dx=-4, dy=1))
            locations[gate] = s
        return s

    def row_for(net):
        return net_rows.get(net, level)

    for block in plan.blocks:
        motif = block.motif
        if block.incoming in net_rows and block.incoming not in plan.return_nets:
            level = net_rows[block.incoming]
        slots = []
        if motif == 'bridge':
            for hi, lo, mid in block.legs:
                s = slot(hi, 'high')
                other = slot(lo, 'low')
                s.items.extend(other.items)
                locations[lo] = s
                for item in other.items:
                    locations[item.ref] = s
                slots.append(s)
                net_rows[mid] = 'mid'
                # Every bridge has its own rails, including an isolated one.
                for ref, port in ((hi, POLARITY[netlist.components[hi].kind][0]),
                                  (lo, POLARITY[netlist.components[lo].kind][1])):
                    net = netlist.net_of(ref, port)
                    net_rows[net] = 'dc_pos' if ref == hi else 'dc_neg'
            level = 'dc_pos' if block.incoming in [l[2] for l in block.legs] else 'mid'
        elif motif == 'source':
            slots = [slot(r, ('dc_pos', 'dc_neg')) for r in block.members]
            for r in block.members:
                for net, p in netlist.ports_of(r):
                    if net not in plan.return_nets:
                        net_rows[net] = 'dc_pos'
            level = 'dc_pos'
        elif motif in ('shunt_branch', 'parallel_block'):
            slots = [slot(r, (level, 'dc_neg')) for r in block.members]
            for r in block.members:
                for net, p in netlist.ports_of(r):
                    if net not in plan.return_nets and p in power_ports(netlist.components[r]):
                        net_rows[net] = level
            if motif == 'shunt_branch':
                r = block.members[0]
                # A local vertical tap keeps incoming/outgoing chain ports
                # straight even when a third member hangs below their node.
                if netlist.components[r].kind in ('nmos', 'nmos_don', 'igbt', 'diode'):
                    trunks[block.incoming] = ('v', r)
        elif motif == 'isolation':
            r = block.members[0]
            winding_nets = {netlist.net_of(r, p) for p in ('p1', 'p2', 's1', 's2')}
            bridge_mids = {l[2] for b in plan.blocks for l in b.legs}
            between_bridges = winding_nets <= bridge_mids
            # Port alignment is lowered using actual symbol offsets at placement.
            slots = [slot(r, 'mid' if between_bridges else level)]
            if not between_bridges:
                slots[0].items[0].align_port = 'p1'
            for p in ('p1', 's1'):
                net_rows[netlist.net_of(r, p)] = level
        else:
            for r in block.members:
                c = netlist.components[r]
                nets = {net for net, p in netlist.ports_of(r) if p in power_ports(c)}
                bridge = next((b for b in plan.blocks
                               if len(b.legs) == 2 and nets == {l[2] for l in b.legs}), None)
                if bridge and len(c.ports) == 2:
                    # A transverse two-terminal branch between repeated legs.
                    s = locations[bridge.legs[0][0]]
                    s.items.append(Item(r, 'mid', rot=-90, dx=5))
                    locations[r] = s
                    continue
                incoming_port = next((p for net, p in netlist.ports_of(r)
                                      if net == block.incoming and p in power_ports(c)), None)
                # a/b passives enter at a; a diode enters at its anode.
                top_port = 'k' if c.kind == 'diode' else power_ports(c)[0]
                rotation = -90 if incoming_port == top_port else 90
                slots.append(slot(r, level, rot=rotation))
                for net in nets - set(plan.return_nets):
                    net_rows[net] = level
        if slots:
            groups.append(Group(block.id, 'bridge' if motif == 'bridge' else
                                'source' if motif == 'source' else 'filter', slots))

    # Attach ground/reference glyphs to a nearby branch on their actual net.
    for ref, net in plan.references:
        candidates = [r for r, p in netlist.nets[net] if r in locations
                      and netlist.components[r].kind != 'terminal']
        order = {item.ref: (gi, si) for gi, group in enumerate(groups)
                 for si, sl in enumerate(group.slots) for item in sl.items}
        candidates.sort(key=lambda r: order[r])
        target = next((r for r in candidates
                       if netlist.components[r].kind in ('nmos', 'igbt', 'diode')),
                      next((r for r in reversed(candidates)
                            if netlist.components[r].kind != 'transformer'), candidates[-1]))
        locations[target].items.append(Item(ref, 'dc_neg'))
        locations[ref] = locations[target]

    if plan.power_interfaces:
        # One boundary column; independent midpoint takeoffs get equal corridors.
        slots, inputs = [], []
        mids = [net for _, net in plan.power_interfaces
                if any(net == l[2] for b in plan.blocks for l in b.legs)]
        taps = {net: rows['mid'] + 2 * i - (len(mids) - 1)
                for i, net in enumerate(sorted(set(mids)))}
        for ref, net in plan.power_interfaces:
            row = taps.get(net, row_for(net))
            component = netlist.components[ref]
            inferred_input = bool(plan.blocks and net == plan.blocks[0].incoming
                                  and plan.blocks[0].motif != 'source')
            is_input = component.attrs.get('direction') == 'input' or component.role == 'source'
            (inputs if is_input or inferred_input else slots).append(Item(ref, row))
        if inputs:
            groups.insert(0, Group('inputs', 'source', [Slot(*inputs)]))
        if slots:
            groups.append(Group('interfaces', 'output', [Slot(*slots)]))
    for ref, target, net in plan.control_interfaces:
        if not target:
            groups.append(Group('control_' + ref, 'control', [slot(ref, 'dc_neg')]))
    for net, row in net_rows.items():
        # Bridge midpoint nets use local vertical trunks in Schematic.
        if any(net == l[2] for b in plan.blocks for l in b.legs):
            continue
        trunks.setdefault(net, ('h', row))
    result = LayoutPlan(groups, rows=rows)
    result.trunks = trunks
    result.semantic = plan
    return result
