"""Deterministic graph-to-relations planning. No drawing or symbol imports.

Bridge and parallel motifs are contracted before power-path traversal. Return
and control nets do not create shortcuts through the energy-transfer graph.
A transformer is an energy-transfer edge, never an electrical net union.
Ambiguous order is deterministic and reported in diagnostics.
"""
from __future__ import annotations
from collections import defaultdict, deque
from dataclasses import dataclass

from .analysis import find_legs, find_bridges, repeated_classes
from .electrical import CONTROL_PORTS, ROLES, is_reference, power_ports


@dataclass(frozen=True)
class Block:
    id: str
    motif: str
    members: tuple
    legs: tuple = ()                # (upper, lower, midpoint)
    incoming: str | None = None
    returns: tuple = ()


@dataclass(frozen=True)
class AutoPlan:
    blocks: tuple
    control_interfaces: tuple      # (interface ref, device ref, device port)
    power_interfaces: tuple        # (interface ref, net)
    references: tuple              # (reference ref, net)
    main_power_nets: tuple
    return_nets: tuple
    repeated: tuple
    branches: tuple
    motifs: tuple = ()
    main_power_path: tuple = ()
    diagnostics: tuple = ()

    def describe(self):
        from dataclasses import asdict
        return asdict(self)


def graph_analysis(netlist):
    """Reusable electrical motifs and an inferred dominant transfer ordering."""
    n = netlist
    faults = n.validate()
    if faults:
        raise ValueError('invalid Circuit IR: ' + '; '.join(faults))
    returns = {net for net, members in n.nets.items()
               if any(is_reference(n.components[r]) or
                      ((n.components[r].role == 'source' or ROLES.get(n.components[r].kind) == 'source') and p == 'n')
                      for r, p in members)}
    sources = {r for r, c in n.components.items()
               if c.kind != 'terminal' and (c.role == 'source' or ROLES.get(c.kind) == 'source')}
    controls, interfaces, references = [], [], []
    for r, c in sorted(n.components.items()):
        if is_reference(c):
            references.append((r, n.ports_of(r)[0][0]))
        elif c.external:
            net = n.ports_of(r)[0][0]
            if c.interface == 'power':
                interfaces.append((r, net))
            else:
                target = [(x, p) for x, p in n.nets[net]
                          if p in CONTROL_PORTS.get(n.components[x].kind, ())]
                if target:
                    controls.append((r, *sorted(target)[0]))
                else:
                    controls.append((r, None, net))
    control_nets = {net for net, members in n.nets.items()
                    if any(p in CONTROL_PORTS.get(n.components[r].kind, ())
                           or n.components[r].interface == 'control'
                           for r, p in members)}
    # A pair of devices is a bridge only with evidence of supply rails:
    # repeated legs or a source/passive connected across the outer pair.
    bridges = []
    occupied = set()
    for family in find_bridges(find_legs(n)):
        leg = family[0]
        if not leg.top_net or not leg.bottom_net or leg.top_net == leg.bottom_net:
            continue
        pair = {leg.top_net, leg.bottom_net}
        support = any(set(net for net, p in n.ports_of(r)) == pair
                      and (r in sources or c.kind in ('cap', 'cap_pol', 'res'))
                      for r, c in n.components.items())
        source_pair = any({net for net, p in n.ports_of(r)} == pair for r in sources)
        mixed_reverse = (n.components[leg.high].kind == 'diode' and
                         n.components[leg.low].kind != 'diode')
        if len(family) < 2 and (not support or (mixed_reverse and not source_pair)):
            continue
        valid = [l for l in family
                 if len({r for r, p in n.nets[l.mid]
                         if p not in CONTROL_PORTS.get(n.components[r].kind, ())}) >= 3]
        valid = [l for l in valid if l.high not in occupied and l.low not in occupied]
        if valid:
            bridges.append(valid)
            occupied.update(r for l in valid for r in (l.high, l.low))
            returns.add(leg.bottom_net)
    power = {r for r, c in n.components.items()
             if c.kind != 'terminal' and not is_reference(c)}
    pairs = defaultdict(list)
    for r in sorted(power - occupied):
        c = n.components[r]
        if len(power_ports(c)) == 2 and not CONTROL_PORTS.get(c.kind):
            pair = tuple(sorted({n.net_of(r, p) for p in power_ports(c)}))
            if len(pair) == 2:
                pairs[pair].append(r)
    if not sources and not returns and pairs:
        # A passive circuit has no intrinsic DC polarity. Pick a deterministic
        # reference for the view; this never renames or merges an electrical net.
        reference_pair = min(pairs, key=lambda pair: (-len(pairs[pair]), pair))
        if len(pairs[reference_pair]) > 1:
            returns.add(reference_pair[-1])
    blocks = []
    def add(motif, refs, legs=()):
        refs = tuple(refs)
        blocks.append(Block('block_' + str(len(blocks)), motif, refs, tuple(legs)))
        occupied.update(refs)
    for family in bridges:
        add('bridge', [r for l in family for r in (l.high, l.low)],
            [(l.high, l.low, l.mid) for l in family])
    for pair, refs in sorted(pairs.items()):
        if len(refs) > 1:
            add('source' if set(refs) & sources else 'parallel_block',
                sorted(refs, key=lambda r: (r not in sources, r)))
    for r in sorted(power - occupied):
        c = n.components[r]
        nets = {n.net_of(r, p) for p in power_ports(c)}
        motif = ('source' if r in sources else
                 'isolation' if c.kind == 'transformer' else
                 'shunt_branch' if nets & returns else
                 'rectifier' if c.kind == 'diode' else 'series_chain')
        add(motif, [r])
    owner = {r: i for i, b in enumerate(blocks) for r in b.members}
    graph = defaultdict(set)
    net_blocks = {}
    for net, members in n.nets.items():
        if net in returns or net in control_nets:
            continue
        ids = {owner[r] for r, p in members if r in owner
               and p in power_ports(n.components[r])}
        net_blocks[net] = ids
        for i in ids:
            graph[i].update(ids - {i})
    roots = sorted({owner[r] for r in sources})
    if not roots:
        inputs = [(r, net) for r, net in interfaces
                  if n.components[r].attrs.get('direction') == 'input' or n.components[r].role == 'source']
        roots = sorted({i for _, net in inputs or interfaces for i in net_blocks.get(net, ())})[:1]
    if not roots and blocks:
        roots = [min(range(len(blocks)), key=lambda i: (len(graph[i]), blocks[i].members))]
    parent = {}
    dist = {i: 0 for i in roots}
    queue = deque(roots)
    while queue:
        i = queue.popleft()
        for j in sorted(graph[i]):
            if j not in dist:
                dist[j] = dist[i] + 1
                parent[j] = i
                queue.append(j)
    priority = {'source': 0, 'shunt_branch': 1, 'bridge': 2,
                'series_chain': 3, 'isolation': 3, 'rectifier': 3, 'parallel_block': 4}
    order = sorted(range(len(blocks)), key=lambda i:
                   (dist.get(i, len(blocks)), priority[blocks[i].motif], blocks[i].members))
    result = []
    for i in order:
        b = blocks[i]
        incident = {net for r in b.members for net, p in n.ports_of(r)
                    if p in power_ports(n.components[r])}
        incoming = sorted(incident - returns - control_nets,
                          key=lambda net: (min((dist.get(j, len(blocks))
                                               for j in net_blocks.get(net, ()) if j != i),
                                              default=len(blocks)), net))
        result.append(Block(b.id, b.motif, b.members, b.legs,
                            incoming[0] if incoming else None,
                            tuple(sorted(incident & returns))))
    branches = tuple((b.members, 'sensing' if any(n.components[r].role == 'sensing' for r in b.members)
                      else 'auxiliary' if any(n.components[r].role == 'auxiliary' for r in b.members)
                      else 'shunt') for b in result
                     if b.motif in ('shunt_branch', 'parallel_block') or
                     any(n.components[r].role in ('sensing', 'auxiliary') for r in b.members))
    diagnostics = []
    if len(dist) < len(blocks):
        diagnostics.append('Disconnected power blocks ordered after reachable blocks.')
    if any(len([j for j in graph[i] if dist.get(j) == dist.get(i)]) > 0 for i in dist):
        diagnostics.append('Branched or cyclic transfer order uses deterministic motif tie-breaking.')
    # Pick a dominant source-to-sink transfer chain; side branches remain
    # explicit motifs. This is an inference, not an operating-point simulation.
    path_ids = []
    if dist:
        sinks = [i for i in dist if not all(n.components[r].role in ('sensing', 'auxiliary', 'control')
                                           for r in blocks[i].members)] or list(dist)
        sink = max(sinks, key=lambda i: (dist[i],
                   blocks[i].motif == 'parallel_block',
                   blocks[i].motif != 'shunt_branch', blocks[i].members))
        while True:
            path_ids.append(sink)
            if sink not in parent:
                break
            sink = parent[sink]
        path_ids.reverse()
    main_nets = set()
    for a, b in zip(path_ids, path_ids[1:]):
        main_nets.update(net for net, ids in net_blocks.items() if a in ids and b in ids)
    repeats = tuple(tuple(v) for v in repeated_classes(n).values())
    motif_refs = (
        ('source_input', tuple(sorted(sources))),
        ('dc_link', tuple(r for b in result if b.motif == 'source'
                          for r in b.members if r not in sources)),
        ('series_chain', tuple(r for b in result if b.motif == 'series_chain' for r in b.members)),
        ('shunt_branch', tuple(r for b in result if b.motif == 'shunt_branch' for r in b.members)),
        ('bridge_leg', tuple((hi, lo) for b in result for hi, lo, mid in b.legs)),
        ('repeated_bridge_legs', tuple(b.members for b in result if len(b.legs) > 1)),
        ('parallel_block', tuple(b.members for b in result if b.motif == 'parallel_block')),
        ('isolation', tuple(r for r, c in sorted(n.components.items()) if c.kind == 'transformer')),
        ('rectifier_stage', tuple(sorted(r for r, c in n.components.items() if c.kind == 'diode'))),
        ('load', tuple(r for b in result if b.motif in ('parallel_block', 'shunt_branch')
                       for r in b.members if n.components[r].kind == 'res' or n.components[r].role == 'load')),
        ('external_power_interface', tuple(r for r, _ in interfaces)),
        ('control_interface', tuple(r for r, _, _ in controls)),
        ('repeated_modules', repeats),
    )
    return AutoPlan(tuple(result), tuple(controls), tuple(interfaces), tuple(references),
                    tuple(sorted(main_nets)), tuple(sorted(returns)),
                    repeats, branches, motif_refs,
                    tuple(blocks[i].members for i in path_ids), tuple(diagnostics))



def auto_plan(netlist, analysis=None):
    """Return a coordinate-free plan; optional analysis is graph_analysis output."""
    if isinstance(analysis, AutoPlan):
        return analysis
    if isinstance(analysis, dict) and 'power_path' in analysis:
        data = dict(analysis['power_path'])
        data['blocks'] = tuple(Block(**b) for b in data['blocks'])
        return AutoPlan(**data)
    return graph_analysis(netlist)
