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


def _gnd(nl, ref='GND1'):
    nl.add(ref, 'gnd')
    return ref


def _gate(nl, ref):
    """A gate drive port: external, so it gets an open circle."""
    nl.add(ref, 'terminal')
    return ref


# ------------------------------------------------------------------ buck
def buck():
    n = Netlist('Buck Converter')
    n.add('V1', 'vsource', label='V', sub='1')
    n.add('C1', 'cap', label='C', sub='1')
    n.add('Q1', 'nmos', label='Q', sub='1')
    n.add('D1', 'diode', label='D', sub='1')
    n.add('L1', 'ind', label='L', sub='1')
    n.add('C2', 'cap', label='C', sub='2')
    n.add('R1', 'res', label='R', sub='1')
    _gnd(n)
    _gate(n, 'G1')
    n.add('VOUT', 'terminal', label='V', sub='out')

    n.connect('DC_POS', 'V1.p', 'C1.a', 'Q1.d')
    n.connect('SW', 'Q1.s', 'D1.k', 'L1.a')
    n.connect('VOUT_N', 'L1.b', 'C2.a', 'R1.a', 'VOUT.t')
    n.connect('DC_NEG', 'V1.n', 'C1.b', 'D1.a', 'C2.b', 'R1.b', 'GND1.t')
    n.connect('GATE', 'Q1.g', 'G1.t')

    leg = analysis.find_legs(n)[0]
    plan = LayoutPlan([
        Group('input_dc_link', 'source', [
            Slot(Item('V1', ('dc_pos', 'dc_neg'), label_side='left')),
            Slot(Item('C1', ('dc_pos', 'dc_neg'), label_side='left'))]),
        Group('bridge', 'bridge', [
            Slot(Item(leg.high, 'high'), Item(leg.low, 'low'),
                 Item('GND1', 'dc_neg'),
                 Item('G1', 'gate_high', dx=GATE_DX, label_side='left'))]),
        Group('output', 'filter', [
            Slot(Item('L1', 'mid', rot=-90, label_side='above')),
            Slot(Item('C2', ('mid', 'dc_neg'), label_side='left')),
            Slot(Item('R1', ('mid', 'dc_neg')),
                 Item('VOUT', 'mid', dx=OUT_DX, label_side='above'))]),
    ])
    return n, plan, dict(
                         trunks={'VOUT_N': ('h', 'mid')},
                         notes=[('V1', 'dc_pos', 0.4, -1.3, 'V', 'in')])


# ------------------------------------------------------------------ boost
def boost():
    n = Netlist('Boost Converter')
    n.add('V1', 'vsource', label='V', sub='1')
    n.add('L1', 'ind', label='L', sub='1')
    n.add('D1', 'diode', label='D', sub='1')
    n.add('Q1', 'nmos', label='Q', sub='1')
    n.add('C1', 'cap', label='C', sub='1')
    n.add('R1', 'res', label='R', sub='1')
    _gnd(n)
    _gate(n, 'G1')
    n.add('VOUT', 'terminal', label='V', sub='out')

    n.connect('VIN', 'V1.p', 'L1.a')
    n.connect('SW', 'L1.b', 'D1.a', 'Q1.d')
    n.connect('VOUT_N', 'D1.k', 'C1.a', 'R1.a', 'VOUT.t')
    n.connect('DC_NEG', 'V1.n', 'Q1.s', 'C1.b', 'R1.b', 'GND1.t')
    n.connect('GATE', 'Q1.g', 'G1.t')

    # Topologically a leg -- D1 above the node, Q1 below -- but drawn the
    # conventional way: L and D in series along the rail, switch below.
    plan = LayoutPlan([
        Group('input_dc_link', 'source', [
            Slot(Item('V1', ('dc_pos', 'dc_neg'), label_side='left'))]),
        Group('conversion', 'conversion', [
            Slot(Item('L1', 'dc_pos', rot=-90, label_side='above')),
            Slot(Item('Q1', 'low'), Item('GND1', 'dc_neg'),
                 Item('G1', 'gate_low', dx=GATE_DX, label_side='left')),
            Slot(Item('D1', 'dc_pos', rot=90, label_side='above'))]),
        Group('output', 'filter', [
            Slot(Item('C1', ('dc_pos', 'dc_neg'), label_side='left')),
            Slot(Item('R1', ('dc_pos', 'dc_neg')),
                 Item('VOUT', 'dc_pos', dx=OUT_DX, label_side='above'))]),
    ])
    return n, plan, dict(
                         trunks={'VIN': ('h', 'dc_pos'),
                                 'VOUT_N': ('h', 'dc_pos'),
                                 'SW': ('v', 'Q1')},
                         notes=[('V1', 'dc_pos', 0.4, -1.3, 'V', 'in')])


# ------------------------------------------------------------------ bridges
def _dc_link(n):
    n.add('V1', 'vsource', label='V', sub='1')
    n.add('C1', 'cap', label='C', sub='1')
    _gnd(n)
    return Group('input_dc_link', 'source', [
        Slot(Item('V1', ('dc_pos', 'dc_neg'), label_side='left')),
        Slot(Item('C1', ('dc_pos', 'dc_neg'), label_side='left'))])


def _leg_slot(high, low, gate_hi, gate_lo, extra=()):
    return Slot(Item(high, 'high'), Item(low, 'low'),
                Item(gate_hi, 'gate_high', dx=GATE_DX, label_side='left'),
                Item(gate_lo, 'gate_low', dx=GATE_DX, label_side='left'),
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
    n.add('VOUT', 'terminal', label='V', sub='out')

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
            Slot(Item('VOUT', 'mid', label_side='above'))]),
    ])
    return n, plan, dict(
                         notes=[('V1', 'dc_pos', 0.4, -1.3, 'V', 'in')])


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
                       Item('R1', 'mid', dx=4, rot=-90, label_side='above'))),
            _leg_slot('Q3', 'Q4', 'G3', 'G4')]),
    ])
    return n, plan, dict(
                         notes=[('V1', 'dc_pos', 0.4, -1.3, 'V', 'in')])


def three_phase_inverter():
    n = Netlist('Three-Phase Two-Level Inverter')
    link = _dc_link(n)
    _switches(n, 6, kind='igbt')
    phases = ('A', 'B', 'C')
    for ph in phases:
        n.add(f'PH{ph}', 'terminal', label=ph)

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
    return n, plan, dict(
                         notes=[('V1', 'dc_pos', 0.4, -1.3, 'V', 'in')])


# ------------------------------------------------------------------ DAB
def dab():
    n = Netlist('Dual Active Bridge')
    n.add('V1', 'vsource', label='V', sub='1')
    n.add('C1', 'cap', label='C', sub='1')
    n.add('T1', 'transformer', label='T', sub='1')
    n.add('C2', 'cap', label='C', sub='2')
    n.add('R1', 'res', label='R', sub='1')
    _gnd(n, 'GND1')
    _gnd(n, 'GND2')
    n.add('VOUT', 'terminal', label='V', sub='out')
    _switches(n, 8)

    n.connect('DCP1', 'V1.p', 'C1.a', 'Q1.d', 'Q3.d')
    n.connect('DCN1', 'V1.n', 'C1.b', 'Q2.s', 'Q4.s', 'GND1.t')
    n.connect('PRI_A', 'Q1.s', 'Q2.d', 'T1.p1')
    n.connect('PRI_B', 'Q3.s', 'Q4.d', 'T1.p2')
    n.connect('SEC_A', 'Q5.s', 'Q6.d', 'T1.s1')
    n.connect('SEC_B', 'Q7.s', 'Q8.d', 'T1.s2')
    n.connect('DCP2', 'Q5.d', 'Q7.d', 'C2.a', 'R1.a', 'VOUT.t')
    n.connect('DCN2', 'Q6.s', 'Q8.s', 'C2.b', 'R1.b', 'GND2.t')
    for i in range(1, 9):
        n.connect(f'G_{i}', f'Q{i}.g', f'G{i}.t')

    plan = LayoutPlan([
        Group('input_dc_link', 'source', [
            Slot(Item('V1', ('dc_pos', 'dc_neg'), label_side='left')),
            Slot(Item('C1', ('dc_pos', 'dc_neg'), label_side='left'))]),
        Group('primary_bridge', 'bridge', [
            _leg_slot('Q1', 'Q2', 'G1', 'G2', (Item('GND1', 'dc_neg'),)),
            _leg_slot('Q3', 'Q4', 'G3', 'G4')]),
        # a transformer is visually dense, so it is given more room than an
        # ordinary passive on both sides
        Group('isolation', 'isolation', [
            Slot(Item('T1', 'mid', label_side='above'))],
            gap_before=ANCHOR_PITCH),
        Group('secondary_bridge', 'bridge', [
            _leg_slot('Q5', 'Q6', 'G5', 'G6'),
            _leg_slot('Q7', 'Q8', 'G7', 'G8', (Item('GND2', 'dc_neg'),))],
            gap_before=ANCHOR_PITCH),
        Group('output', 'filter', [
            Slot(Item('C2', ('dc_pos', 'dc_neg'), label_side='left')),
            Slot(Item('R1', ('dc_pos', 'dc_neg')),
                 Item('VOUT', 'dc_pos', dx=OUT_DX, label_side='above'))]),
    ], rows=ROWS_TALL)
    return n, plan, dict(
                         trunks={'DCP1': ('h', 'dc_pos'),
                                 'DCN1': ('h', 'dc_neg'),
                                 'DCP2': ('h', 'dc_pos'),
                                 'DCN2': ('h', 'dc_neg')},
                         notes=[('V1', 'dc_pos', 0.4, -1.3, 'V', 'in')])


CATALOGUE = {
    'buck': buck,
    'boost': boost,
    'half_bridge': half_bridge,
    'full_bridge': full_bridge,
    'three_phase_inverter': three_phase_inverter,
    'dab': dab,
}
