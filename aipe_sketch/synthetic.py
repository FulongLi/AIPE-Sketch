"""Synthetic circuits that exercise one motif each.

None of these is a named converter.  They exist so the drawing grammar can
be tested on structure alone: if a rule only works because it was tuned on
a Buck or an LLC, it fails here.
"""
from .netlist import Netlist
from .plan import Group, Item, LayoutPlan, ROWS, Slot

GATE_DX = -4


def _gnd(n, ref='GND1'):
    n.add(ref, 'gnd')
    return ref


# ------------------------------------------------------------------ series
def series_rlc():
    """A plain R-L-C chain: the series-path motif, nothing else."""
    n = Netlist('Series R-L-C Chain')
    n.add('V1', 'vsource', label='V', sub='in')
    n.add('R1', 'res', label='R', sub='1')
    n.add('L1', 'ind', label='L', sub='1')
    n.add('C1', 'cap', label='C', sub='1')
    _gnd(n)
    n.connect('N1', 'V1.p', 'R1.a')
    n.connect('N2', 'R1.b', 'L1.a')
    n.connect('N3', 'L1.b', 'C1.a')
    n.connect('RTN', 'V1.n', 'C1.b', 'GND1.t')
    # The chain rides the row of the port that feeds it -- the source's
    # positive terminal -- so the whole path is collinear and needs no bends.
    line = ROWS['mid'] - 2
    plan = LayoutPlan([
        Group('source', 'source', [Slot(Item('V1', 'mid'))]),
        Group('chain', 'filter', [
            Slot(Item('R1', line, rot=-90)),
            Slot(Item('L1', line, rot=-90)),
            Slot(Item('C1', 'mid'), Item('GND1', 'dc_neg'))]),
    ])
    return n, plan, dict(trunks={'RTN': ('h', 'dc_neg')})


# ------------------------------------------------------------------ shunts
def twin_shunt_branches():
    """Two equivalent shunt switches on one rail.

    Their branches must come out balanced *and* identical to each other --
    the repeated-structure rule applied to shunts rather than bridge legs.
    """
    n = Netlist('Twin Shunt Branches')
    n.add('V1', 'vsource', label='V', sub='in')
    n.add('L1', 'ind', label='L', sub='1')
    n.add('L2', 'ind', label='L', sub='2')
    n.add('R1', 'res', label='R', sub='1')
    _gnd(n)
    for tag in ('1', '2'):
        n.add(f'Q{tag}', 'nmos', label='Q', sub=tag)
        n.add(f'G{tag}', 'terminal', interface='control')

    n.connect('IN', 'V1.p', 'L1.a')
    n.connect('MID', 'L1.b', 'Q1.d', 'L2.a')
    n.connect('OUT', 'L2.b', 'Q2.d', 'R1.a')
    n.connect('RTN', 'V1.n', 'Q1.s', 'Q2.s', 'R1.b', 'GND1.t')
    n.connect('G_1', 'Q1.g', 'G1.t')
    n.connect('G_2', 'Q2.g', 'G2.t')

    def shunt(ref, gate):
        return Slot(Item(ref, ('dc_pos', 'dc_neg')),
                    Item(gate, ('dc_pos', 'dc_neg'), dy=1, dx=GATE_DX))

    plan = LayoutPlan([
        Group('source', 'source', [Slot(Item('V1', ('dc_pos', 'dc_neg')))]),
        Group('cell_1', 'conversion', [
            Slot(Item('L1', 'dc_pos', rot=-90)), shunt('Q1', 'G1')]),
        Group('cell_2', 'conversion', [
            Slot(Item('L2', 'dc_pos', rot=-90)), shunt('Q2', 'G2')]),
        Group('load', 'load', [
            Slot(Item('R1', ('dc_pos', 'dc_neg')),
                 Item('GND1', 'dc_neg'))]),
    ])
    return n, plan, dict(trunks={'RTN': ('h', 'dc_neg')})


# ------------------------------------------------------------------ bridges
def three_repeated_legs():
    """Three identical legs with no converter semantics attached."""
    n = Netlist('Three Repeated Legs')
    n.add('V1', 'vsource', label='V', sub='in')
    n.add('C1', 'cap', label='C', sub='1')
    _gnd(n)
    tags = ('1', '2', '3')
    for t in tags:
        n.add(f'Qh{t}', 'nmos', label='Q', sub=f'h{t}')
        n.add(f'Ql{t}', 'nmos', label='Q', sub=f'l{t}')
        n.add(f'Gh{t}', 'terminal', interface='control')
        n.add(f'Gl{t}', 'terminal', interface='control')
        n.add(f'T{t}', 'terminal', label=f'A{t}', interface='power')
    n.connect('DC_POS', 'V1.p', 'C1.a', *[f'Qh{t}.d' for t in tags])
    n.connect('DC_NEG', 'V1.n', 'C1.b', 'GND1.t',
              *[f'Ql{t}.s' for t in tags])
    for i, t in enumerate(tags):
        n.connect(f'MID_{t}', f'Qh{t}.s', f'Ql{t}.d', f'T{t}.t')
        n.connect(f'GH_{t}', f'Qh{t}.g', f'Gh{t}.t')
        n.connect(f'GL_{t}', f'Ql{t}.g', f'Gl{t}.t')

    taps = {'1': 11, '2': 13, '3': 15}
    slots = []
    for i, t in enumerate(tags):
        extra = (Item('GND1', 'dc_neg'),) if i == 0 else ()
        slots.append(Slot(Item(f'Qh{t}', 'high'), Item(f'Ql{t}', 'low'),
                          Item(f'Gh{t}', 'gate_high', dx=GATE_DX),
                          Item(f'Gl{t}', 'gate_low', dx=GATE_DX), *extra))
    from .plan import ROWS_TALL
    plan = LayoutPlan([
        Group('dc_link', 'source', [
            Slot(Item('V1', ('dc_pos', 'dc_neg'))),
            Slot(Item('C1', ('dc_pos', 'dc_neg')))]),
        Group('bridge', 'bridge', slots),
        Group('outputs', 'output', [
            Slot(*[Item(f'T{t}', taps[t]) for t in tags])]),
    ], rows=ROWS_TALL)
    return n, plan, {}


# ------------------------------------------------------------------ parallel
def parallel_rc_block():
    """A bare parallel block across one node pair."""
    n = Netlist('Parallel R-C Block')
    n.add('I1', 'isource', label='I', sub='in')
    n.add('C1', 'cap', label='C', sub='1')
    n.add('R1', 'res', label='R', sub='1')
    _gnd(n)
    n.connect('TOP', 'I1.p', 'C1.a', 'R1.a')
    n.connect('RTN', 'I1.n', 'C1.b', 'R1.b', 'GND1.t')
    plan = LayoutPlan([
        Group('source', 'source', [Slot(Item('I1', ('dc_pos', 'dc_neg')))]),
        Group('block', 'filter', [
            Slot(Item('C1', ('dc_pos', 'dc_neg'))),
            Slot(Item('R1', ('dc_pos', 'dc_neg')),
                 Item('GND1', 'dc_neg'))]),
    ])
    return n, plan, dict(trunks={'TOP': ('h', 'dc_pos'),
                                 'RTN': ('h', 'dc_neg')})


# ------------------------------------------------------------------ magnetics
def transformer_between_networks():
    """A transformer joining two unrelated R-C networks."""
    n = Netlist('Transformer Between Networks')
    n.add('V1', 'vsource', label='V', sub='in')
    n.add('R1', 'res', label='R', sub='1')
    n.add('T1', 'transformer', label='T', sub='1')
    n.add('R2', 'res', label='R', sub='2')
    n.add('C1', 'cap', label='C', sub='1')
    _gnd(n, 'GND1')
    _gnd(n, 'GND2')
    n.add('OUT', 'terminal', label='VOUT', italic=False, interface='power')

    n.connect('P_IN', 'V1.p', 'R1.a')
    n.connect('P_TOP', 'R1.b', 'T1.p1')
    n.connect('P_RTN', 'V1.n', 'T1.p2', 'GND1.t')
    n.connect('S_TOP', 'T1.s1', 'R2.a')
    n.connect('S_OUT', 'R2.b', 'C1.a', 'OUT.t')
    n.connect('S_RTN', 'T1.s2', 'C1.b', 'GND2.t')

    plan = LayoutPlan([
        Group('primary', 'source', [
            Slot(Item('V1', ('dc_pos', 'dc_neg'))),
            Slot(Item('R1', 'mid', rot=-90),
                 Item('GND1', 'dc_neg'))]),
        Group('isolation', 'isolation', [
            Slot(Item('T1', ('mid', 'low')))]),
        Group('secondary', 'filter', [
            Slot(Item('R2', 'mid', rot=-90)),
            Slot(Item('C1', ('mid', 'dc_neg')),
                 Item('GND2', 'dc_neg'),
                 Item('OUT', 'mid', dx=3))]),
    ])
    return n, plan, dict(trunks={'P_RTN': ('h', 'dc_neg'),
                                 'S_RTN': ('h', 'dc_neg')})


SYNTHETIC = {
    'series_rlc': series_rlc,
    'twin_shunt_branches': twin_shunt_branches,
    'three_repeated_legs': three_repeated_legs,
    'parallel_rc_block': parallel_rc_block,
    'transformer_between_networks': transformer_between_networks,
}
