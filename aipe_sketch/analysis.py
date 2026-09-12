"""Topology analysis: structure discovery, before any geometry exists.

Nothing here knows about coordinates.  It answers the structural questions --
which components form switching legs, which nets are rails, which structures
repeat -- so the placer can turn repeated topology into repeated geometry.
"""
import hashlib
from collections import defaultdict

# which port sits electrically above which, per switch-like kind
POLARITY = {
    'nmos': ('d', 's'), 'nmos_don': ('d', 's'),
    'igbt': ('c', 'e'),
    'diode': ('k', 'a'),
}
SWITCHING_ROLES = ('power_switch', 'rectifier')


def _digest(value):
    return hashlib.blake2s(repr(value).encode(), digest_size=8).hexdigest()


# ------------------------------------------------------------------ legs
class Leg:
    """A half-bridge leg: one device above another, joined at a midpoint."""

    __slots__ = ('high', 'low', 'mid', 'top_net', 'bottom_net')

    def __init__(self, high, low, mid, top_net, bottom_net):
        self.high, self.low, self.mid = high, low, mid
        self.top_net, self.bottom_net = top_net, bottom_net

    def __repr__(self):
        return (f'Leg({self.high}/{self.low} @ {self.mid}, '
                f'{self.top_net}..{self.bottom_net})')


def find_legs(netlist):
    """Find every midpoint net joining one device's low port to another's high."""
    legs = []
    for net, members in sorted(netlist.nets.items()):
        highs, lows = [], []          # devices whose high/low port is on this net
        for ref, port in members:
            kind = netlist.components[ref].kind
            polarity = POLARITY.get(kind)
            if not polarity:
                continue
            if port == polarity[0]:
                highs.append(ref)     # this device sits *below* the net
            elif port == polarity[1]:
                lows.append(ref)      # this device sits *above* the net
        if len(lows) == 1 and len(highs) == 1:
            upper, lower = lows[0], highs[0]
            top = netlist.net_of(upper, POLARITY[netlist.components[upper].kind][0])
            bot = netlist.net_of(lower, POLARITY[netlist.components[lower].kind][1])
            legs.append(Leg(upper, lower, net, top, bot))
    return legs


# ------------------------------------------------------------------ rails
def find_rails(netlist):
    """Return (positive rail, negative rail) net names, or (None, None).

    A rail is a net carrying the same polarity port of two or more switching
    devices, or the terminal of a source.
    """
    pos, neg = defaultdict(int), defaultdict(int)
    for net, members in netlist.nets.items():
        for ref, port in members:
            comp = netlist.components[ref]
            polarity = POLARITY.get(comp.kind)
            if polarity:
                if port == polarity[0]:
                    pos[net] += 1
                elif port == polarity[1]:
                    neg[net] += 1
            elif comp.role == 'source' or comp.kind in (
                    'vsource', 'isource', 'battery'):
                if port == 'p':
                    pos[net] += 1
                elif port == 'n':
                    neg[net] += 1

    def best(counter):
        ranked = sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))
        return ranked[0][0] if ranked and ranked[0][1] >= 2 else None

    return best(pos), best(neg)


def find_bridges(legs):
    """Group legs sharing a rail pair; each group is one bridge."""
    bridges = defaultdict(list)
    for leg in legs:
        bridges[(leg.top_net, leg.bottom_net)].append(leg)
    return [sorted(v, key=lambda l: l.high) for _, v in sorted(bridges.items())]


# ------------------------------------------------------------------ symmetry
def refine_colours(netlist, rounds=3):
    """Colour refinement over the component/net bipartite graph.

    Components that end up the same colour are topologically
    indistinguishable, which is exactly the condition for demanding
    identical geometry.
    """
    from .electrical import canonical_port

    comp = {ref: (c.kind, c.role, c.interface, c.attrs.get('direction'))
            for ref, c in netlist.components.items()}
    net = {name: 'net' for name in netlist.nets}
    nets = netlist.nets
    kinds = {ref: c.kind for ref, c in netlist.components.items()}

    def cport(ref, port):
        return canonical_port(kinds[ref], port)

    for _ in range(rounds):
        new_net = {}
        for name, members in nets.items():
            new_net[name] = _digest(sorted((cport(ref, port), comp[ref])
                                           for ref, port in members))
        new_comp = {}
        for ref, kind in comp.items():
            incident = sorted((cport(ref, port), new_net[n])
                              for n, port in netlist.ports_of(ref))
            new_comp[ref] = _digest((kind, incident))
        if new_comp == comp and new_net == net:
            break
        comp, net = new_comp, new_net
    return comp, net


def equivalence_classes(netlist, rounds=3):
    """{class id: [refs]} for components that are topologically equivalent."""
    comp, _ = refine_colours(netlist, rounds)
    buckets = defaultdict(list)
    for ref, colour in comp.items():
        buckets[colour].append(ref)
    classes = {}
    for i, (_, refs) in enumerate(
            sorted(buckets.items(), key=lambda kv: sorted(kv[1]))):
        classes[f'class_{i}'] = sorted(refs)
    return classes


def repeated_classes(netlist, rounds=3):
    """Only the classes with more than one member -- the repeated motifs."""
    return {k: v for k, v in equivalence_classes(netlist, rounds).items()
            if len(v) > 1}


# ------------------------------------------------------------------ grouping
def functional_groups(netlist):
    """Assign every component to a functional block.

    Deterministic and role-driven: bridges come from leg detection, the rest
    from semantic role and which side of the isolation barrier they sit on.
    """
    legs = find_legs(netlist)
    bridges = find_bridges(legs)
    groups = defaultdict(list)

    in_bridge = {}
    for i, bridge in enumerate(bridges):
        name = 'bridge' if len(bridges) == 1 else f'bridge_{i + 1}'
        for leg in bridge:
            for ref in (leg.high, leg.low):
                in_bridge[ref] = name
                groups[name].append(ref)

    for ref, comp in netlist.components.items():
        if ref in in_bridge:
            continue
        role = comp.role
        if role is None:
            from .electrical import ROLES
            role = ROLES.get(comp.kind, 'generic')
        groups[{
            'source': 'input_dc_link', 'filter': 'filter', 'load': 'load',
            'magnetic': 'filter', 'isolation': 'isolation',
            'reference': 'reference',
        }.get(role, 'other')].append(ref)

    return {k: sorted(v) for k, v in sorted(groups.items())}


def analyse(netlist):
    """Everything the layout stage needs to know about structure."""
    legs = find_legs(netlist)
    pos, neg = find_rails(netlist)
    from .planner import graph_analysis
    return {
        'power_path': graph_analysis(netlist).describe(),
        'rails': {'positive': pos, 'negative': neg},
        'legs': [{'high': l.high, 'low': l.low, 'mid': l.mid} for l in legs],
        'bridges': [[l.mid for l in b] for b in find_bridges(legs)],
        'repeated': repeated_classes(netlist),
        'groups': functional_groups(netlist),
    }


# ------------------------------------------------------------------ motifs
BRIDGE_LEG = 'bridge_leg'
SHUNT_SWITCH = 'shunt_switch'
SERIES_POWER_PATH = 'series_power_path'
PARALLEL_OUTPUT_BLOCK = 'parallel_output_block'


def supply_nets(netlist):
    """(positive supply, reference) as named by the source and the ground."""
    positive = reference = None
    for net, members in netlist.nets.items():
        for ref, port in members:
            kind = netlist.components[ref].kind
            if kind in ('vsource', 'isource', 'battery') and port == 'p':
                positive = positive or net
            if kind == 'gnd':
                reference = reference or net
    return positive, reference


def classify_motifs(netlist):
    """Name the local electrical motif each device belongs to.

    A switching device is not automatically half of a bridge.  A device
    hanging from a main-path node down to the reference is a shunt, and must
    be placed by balancing its own branch rather than by bridge geometry.
    """
    positive, reference = supply_nets(netlist)
    legs = find_legs(netlist)
    motifs = {BRIDGE_LEG: [], SHUNT_SWITCH: [], PARALLEL_OUTPUT_BLOCK: []}

    for leg in legs:
        # a bridge leg hangs its high device from the positive supply; a
        # boost's diode sits on the main path instead, and is not one
        if positive is not None and leg.top_net == positive:
            motifs[BRIDGE_LEG].append(
                {'high': leg.high, 'low': leg.low, 'mid': leg.mid})

    in_bridge = {r for m in motifs[BRIDGE_LEG] for r in (m['high'], m['low'])}
    for ref, comp in sorted(netlist.components.items()):
        polarity = POLARITY.get(comp.kind)
        if not polarity or ref in in_bridge:
            continue
        high_net = netlist.net_of(ref, polarity[0])
        low_net = netlist.net_of(ref, polarity[1])
        if low_net == reference and high_net != reference:
            motifs[SHUNT_SWITCH].append(
                {'device': ref, 'node': high_net, 'rail': low_net})

    by_pair = {}
    for ref in sorted(netlist.components):
        nets = tuple(sorted({n for n, _ in netlist.ports_of(ref)}))
        if len(nets) == 2:
            by_pair.setdefault(nets, []).append(ref)
    for nets, refs in sorted(by_pair.items()):
        shunts = [r for r in refs
                  if netlist.components[r].kind in ('cap', 'cap_pol', 'res')]
        if len(shunts) >= 2:
            motifs[PARALLEL_OUTPUT_BLOCK].append(
                {'members': shunts, 'nets': list(nets)})
    return motifs
