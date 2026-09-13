"""The six reference converters, as netlists plus layout plans.

Reference designators follow conventional practice: V/I sources, R, L, C,
Q for switching devices, D for diodes, T for transformers.  Every exposed
node is a real terminal component, so it renders as an open circle and no
wire ever ends in mid-air.
"""
from .netlist import Netlist
from .plan import (ANCHOR_PITCH, Group, Item, LayoutPlan, ROWS, ROWS_TALL,
                   Slot)
from . import analysis

GATE_DX = -4          # gate terminal, one component dimension left of its leg
OUT_DX = 3            # output terminal, clear of the last component

# Notation for the input source.  VIN and VOUT are semantic ideas, not
# mandatory ink: an explicit source carries the input name itself rather than
# having a second VIN label placed beside it.  Subscript form matches the rest
# of the drawing's typography (C_1, Q_1, R_1).
INPUT_LABEL = ('V', 'in')


def _gnd(nl, ref='GND1'):
    nl.add(ref, 'power_ground')
    return ref


def _gate(nl, ref):
    """A gate drive port.

    It is an interface, so it stays a real component and connectivity stays
    checkable -- but it is control, not power, so it is drawn as an ordinary
    wire endpoint with no boundary marker.
    """
    nl.add(ref, 'terminal', interface='control')
    return ref


# ------------------------------------------------------------------ buck
def buck():
    n = Netlist('Buck Converter')
    n.add('V1', 'vsource', label=INPUT_LABEL[0], sub=INPUT_LABEL[1])
    n.add('C1', 'cap', label='C', sub='1')
    n.add('Q1', 'nmos', label='Q', sub='1')
    n.add('D1', 'diode', label='D', sub='1')
    n.add('L1', 'ind', label='L', sub='1')
    n.add('C2', 'cap', label='C', sub='2')
    n.add('R1', 'res', label='R', sub='1')
    _gnd(n)
    _gate(n, 'G1')

    n.connect('DC_POS', 'V1.p', 'C1.a', 'Q1.d')
    n.connect('SW', 'Q1.s', 'D1.k', 'L1.a')
    # the net keeps its semantic name; that does not imply a rendered label
    n.connect('VOUT_N', 'L1.b', 'C2.a', 'R1.a')
    n.connect('DC_NEG', 'V1.n', 'C1.b', 'D1.a', 'C2.b', 'R1.b', 'GND1.t')
    n.connect('GATE', 'Q1.g', 'G1.t')

    leg = analysis.find_legs(n)[0]
    plan = LayoutPlan([
        Group('input_dc_link', 'source', [
            Slot(Item('V1', ('dc_pos', 'dc_neg'))),
            Slot(Item('C1', ('dc_pos', 'dc_neg')))]),
        Group('bridge', 'bridge', [
            Slot(Item(leg.high, 'high'), Item(leg.low, 'low'),
                 Item('GND1', 'dc_neg'),
                 Item('G1', 'gate_high', dx=GATE_DX))]),
        Group('output', 'filter', [
            Slot(Item('L1', 'mid', rot=-90)),
            Slot(Item('C2', ('mid', 'dc_neg'))),
            Slot(Item('R1', ('mid', 'dc_neg')))]),
    ])
    return n, plan, dict(
                         trunks={'VOUT_N': ('h', 'mid')})


# ------------------------------------------------------------------ boost
def boost():
    n = Netlist('Boost Converter')
    n.add('V1', 'vsource', label=INPUT_LABEL[0], sub=INPUT_LABEL[1])
    n.add('L1', 'ind', label='L', sub='1')
    n.add('D1', 'diode', label='D', sub='1')
    n.add('Q1', 'nmos', label='Q', sub='1')
    n.add('C1', 'cap', label='C', sub='1')
    n.add('R1', 'res', label='R', sub='1')
    _gnd(n)
    _gate(n, 'G1')

    n.connect('VIN', 'V1.p', 'L1.a')
    n.connect('SW', 'L1.b', 'D1.a', 'Q1.d')
    n.connect('VOUT_N', 'D1.k', 'C1.a', 'R1.a')
    n.connect('DC_NEG', 'V1.n', 'Q1.s', 'C1.b', 'R1.b', 'GND1.t')
    n.connect('GATE', 'Q1.g', 'G1.t')

    # A boost is not a half bridge.  L1, the switching node and D1 stay on
    # one horizontal main path, and Q1 hangs from that node down to the
    # return rail -- centred in its own branch, not dropped into a bridge row.
    plan = LayoutPlan([
        Group('input_dc_link', 'source', [
            Slot(Item('V1', ('dc_pos', 'dc_neg')))]),
        Group('conversion', 'conversion', [
            Slot(Item('L1', 'dc_pos', rot=-90)),
            Slot(Item('Q1', ('dc_pos', 'dc_neg')),
                 Item('GND1', 'dc_neg'),
                 Item('G1', ('dc_pos', 'dc_neg'), dy=1, dx=GATE_DX)),
            Slot(Item('D1', 'dc_pos', rot=90))]),
        Group('output', 'filter', [
            Slot(Item('C1', ('dc_pos', 'dc_neg'))),
            Slot(Item('R1', ('dc_pos', 'dc_neg')))]),
    ])
    return n, plan, dict(
                         trunks={'VIN': ('h', 'dc_pos'),
                                 'VOUT_N': ('h', 'dc_pos'),
                                 'SW': ('v', 'Q1')})


# ------------------------------------------------------------------ bridges
def _dc_link(n):
    n.add('V1', 'vsource', label=INPUT_LABEL[0], sub=INPUT_LABEL[1])
    n.add('C1', 'cap', label='C', sub='1')
    _gnd(n)
    return Group('input_dc_link', 'source', [
        Slot(Item('V1', ('dc_pos', 'dc_neg'))),
        Slot(Item('C1', ('dc_pos', 'dc_neg')))])


def _leg_slot(high, low, gate_hi, gate_lo, extra=()):
    return Slot(Item(high, 'high'), Item(low, 'low'),
                Item(gate_hi, 'gate_high', dx=GATE_DX),
                Item(gate_lo, 'gate_low', dx=GATE_DX),
                *extra)


def _switches(n, count, kind='nmos', start=1):
    refs = []
    for i in range(count):
        ref = f'Q{start + i}'
        n.add(ref, kind, label='Q', sub=str(start + i))
        _gate(n, f'G{start + i}')
        refs.append(ref)
    return refs


def half_bridge():
    n = Netlist('Half Bridge')
    link = _dc_link(n)
    _switches(n, 2)
    # a half bridge has no load of its own: its midpoint is intentionally
    # exposed for whatever comes next, so it is a real external interface
    n.add('VOUT', 'terminal', label='VOUT', italic=False,
          interface='power')

    n.connect('DC_POS', 'V1.p', 'C1.a', 'Q1.d')
    n.connect('SW', 'Q1.s', 'Q2.d', 'VOUT.t')
    n.connect('DC_NEG', 'V1.n', 'C1.b', 'Q2.s', 'GND1.t')
    n.connect('G_1', 'Q1.g', 'G1.t')
    n.connect('G_2', 'Q2.g', 'G2.t')

    plan = LayoutPlan([
        link,
        Group('bridge', 'bridge', [
            _leg_slot('Q1', 'Q2', 'G1', 'G2', (Item('GND1', 'dc_neg'),))]),
        Group('output', 'output', [
            Slot(Item('VOUT', 'mid'))]),
    ])
    return n, plan, dict()


def full_bridge():
    n = Netlist('Full Bridge')
    link = _dc_link(n)
    _switches(n, 4)
    n.add('R1', 'res', label='R', sub='1')

    n.connect('DC_POS', 'V1.p', 'C1.a', 'Q1.d', 'Q3.d')
    n.connect('OUT_A', 'Q1.s', 'Q2.d', 'R1.a')
    n.connect('OUT_B', 'Q3.s', 'Q4.d', 'R1.b')
    n.connect('DC_NEG', 'V1.n', 'C1.b', 'Q2.s', 'Q4.s', 'GND1.t')
    for i in range(1, 5):
        n.connect(f'G_{i}', f'Q{i}.g', f'G{i}.t')

    plan = LayoutPlan([
        link,
        Group('bridge', 'bridge', [
            _leg_slot('Q1', 'Q2', 'G1', 'G2',
                      (Item('GND1', 'dc_neg'),
                       Item('R1', 'mid', dx=5, rot=-90))),
            _leg_slot('Q3', 'Q4', 'G3', 'G4')]),
    ])
    return n, plan, dict()


def three_phase_inverter():
    n = Netlist('Three-Phase Two-Level Inverter')
    link = _dc_link(n)
    _switches(n, 6, kind='igbt')
    phases = ('A', 'B', 'C')
    for ph in phases:
        n.add(f'PH{ph}', 'terminal', label=ph, interface='power')

    n.connect('DC_POS', 'V1.p', 'C1.a', 'Q1.c', 'Q3.c', 'Q5.c')
    n.connect('DC_NEG', 'V1.n', 'C1.b', 'Q2.e', 'Q4.e', 'Q6.e', 'GND1.t')
    for i, ph in enumerate(phases):
        hi, lo = f'Q{2 * i + 1}', f'Q{2 * i + 2}'
        n.connect(f'PH_{ph}', f'{hi}.e', f'{lo}.c', f'PH{ph}.t')
    for i in range(1, 7):
        n.connect(f'G_{i}', f'Q{i}.g', f'G{i}.t')

    slots = []
    for i in range(3):
        extra = (Item('GND1', 'dc_neg'),) if i == 0 else ()
        slots.append(_leg_slot(f'Q{2 * i + 1}', f'Q{2 * i + 2}',
                               f'G{2 * i + 1}', f'G{2 * i + 2}', extra))
    # three take-off corridors, evenly spaced inside the midpoint window
    taps = {'A': 11, 'B': 13, 'C': 15}
    plan = LayoutPlan([
        link,
        Group('bridge', 'bridge', slots),
        Group('output', 'output', [
            Slot(*[Item(f'PH{ph}', taps[ph]) for ph in phases])]),
    ], rows=ROWS_TALL)
    return n, plan, dict()


# ------------------------------------------------------------------ DAB
def dab():
    n = Netlist('Dual Active Bridge')
    n.add('V1', 'vsource', label=INPUT_LABEL[0], sub=INPUT_LABEL[1])
    n.add('C1', 'cap', label='C', sub='1')
    n.add('T1', 'transformer', label='T', sub='1')
    n.add('C2', 'cap', label='C', sub='2')
    n.add('R1', 'res', label='R', sub='1')
    _gnd(n, 'GND1')
    _gnd(n, 'GND2')
    _switches(n, 8)

    n.connect('DCP1', 'V1.p', 'C1.a', 'Q1.d', 'Q3.d')
    n.connect('DCN1', 'V1.n', 'C1.b', 'Q2.s', 'Q4.s', 'GND1.t')
    n.connect('PRI_A', 'Q1.s', 'Q2.d', 'T1.p1')
    n.connect('PRI_B', 'Q3.s', 'Q4.d', 'T1.p2')
    n.connect('SEC_A', 'Q5.s', 'Q6.d', 'T1.s1')
    n.connect('SEC_B', 'Q7.s', 'Q8.d', 'T1.s2')
    n.connect('DCP2', 'Q5.d', 'Q7.d', 'C2.a', 'R1.a')
    n.connect('DCN2', 'Q6.s', 'Q8.s', 'C2.b', 'R1.b', 'GND2.t')
    for i in range(1, 9):
        n.connect(f'G_{i}', f'Q{i}.g', f'G{i}.t')

    plan = LayoutPlan([
        Group('input_dc_link', 'source', [
            Slot(Item('V1', ('dc_pos', 'dc_neg'))),
            Slot(Item('C1', ('dc_pos', 'dc_neg')))]),
        Group('primary_bridge', 'bridge', [
            _leg_slot('Q1', 'Q2', 'G1', 'G2', (Item('GND1', 'dc_neg'),)),
            _leg_slot('Q3', 'Q4', 'G3', 'G4')]),
        # a transformer is visually dense, so it is given more room than an
        # ordinary passive on both sides
        Group('isolation', 'isolation', [
            Slot(Item('T1', 'mid'))],
            gap_before=ANCHOR_PITCH),
        Group('secondary_bridge', 'bridge', [
            _leg_slot('Q5', 'Q6', 'G5', 'G6'),
            _leg_slot('Q7', 'Q8', 'G7', 'G8', (Item('GND2', 'dc_neg'),))],
            gap_before=ANCHOR_PITCH),
        Group('output', 'filter', [
            Slot(Item('C2', ('dc_pos', 'dc_neg'))),
            Slot(Item('R1', ('dc_pos', 'dc_neg')))]),
    ], rows=ROWS_TALL)
    return n, plan, dict(
                         trunks={'DCP1': ('h', 'dc_pos'),
                                 'DCN1': ('h', 'dc_neg'),
                                 'DCP2': ('h', 'dc_pos'),
                                 'DCN2': ('h', 'dc_neg')})


# ------------------------------------------------------------------ resonant
def llc_resonant():
    """Half bridge driving a series resonant tank into a transformer.

    The primary power path -- switching node, Cr, Lr, transformer primary --
    is the case the centreline rules exist for.  The transformer is placed
    so that its primary top terminal lands exactly on the switching-node
    row, which is what lets the whole chain sit on one horizontal line.
    """
    n = Netlist('LLC Resonant Converter')
    n.add('V1', 'vsource', label=INPUT_LABEL[0], sub=INPUT_LABEL[1])
    n.add('C1', 'cap', label='C', sub='1')
    _gnd(n, 'GND1')
    _switches(n, 2)
    n.add('Cr', 'cap', label='C', sub='r')
    n.add('Lr', 'ind', label='L', sub='r')
    n.add('T1', 'transformer', label='T', sub='1')
    n.add('D1', 'diode', label='D', sub='1')
    n.add('C2', 'cap', label='C', sub='2')
    n.add('R1', 'res', label='R', sub='1')
    _gnd(n, 'GND2')

    n.connect('DC_POS', 'V1.p', 'C1.a', 'Q1.d')
    n.connect('DC_NEG', 'V1.n', 'C1.b', 'Q2.s', 'GND1.t', 'T1.p2')
    n.connect('SW', 'Q1.s', 'Q2.d', 'Cr.a')
    n.connect('RES', 'Cr.b', 'Lr.a')
    n.connect('PRI', 'Lr.b', 'T1.p1')
    n.connect('SEC', 'T1.s1', 'D1.a')
    n.connect('VOUT_N', 'D1.k', 'C2.a', 'R1.a')
    n.connect('SEC_RTN', 'T1.s2', 'C2.b', 'R1.b', 'GND2.t')
    n.connect('G_1', 'Q1.g', 'G1.t')
    n.connect('G_2', 'Q2.g', 'G2.t')

    plan = LayoutPlan([
        Group('input_dc_link', 'source', [
            Slot(Item('V1', ('dc_pos', 'dc_neg'))),
            Slot(Item('C1', ('dc_pos', 'dc_neg')))]),
        Group('bridge', 'bridge', [
            _leg_slot('Q1', 'Q2', 'G1', 'G2', (Item('GND1', 'dc_neg'),))]),
        # the tank rides the switching-node row, laid flat
        Group('resonant_tank', 'filter', [
            Slot(Item('Cr', 'mid', rot=-90)),
            Slot(Item('Lr', 'mid', rot=-90))]),
        # centred a half symbol below 'mid', so its primary top terminal
        # lands on the switching-node row and the tank stays collinear
        Group('isolation', 'isolation', [
            Slot(Item('T1', ('mid', 'low')))]),
        Group('rectifier', 'filter', [
            Slot(Item('D1', 'mid', rot=90))]),
        Group('output', 'filter', [
            Slot(Item('C2', ('mid', 'dc_neg'))),
            Slot(Item('R1', ('mid', 'dc_neg')),
                 Item('GND2', 'dc_neg'))]),
    ])
    return n, plan, dict(trunks={'VOUT_N': ('h', 'mid'),
                                 'SEC_RTN': ('h', 'dc_neg')})


CATALOGUE = {
    'llc_resonant': llc_resonant,
    'buck': buck,
    'boost': boost,
    'half_bridge': half_bridge,
    'full_bridge': full_bridge,
    'three_phase_inverter': three_phase_inverter,
    'dab': dab,
}
