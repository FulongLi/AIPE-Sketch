"""The six reference converters, as netlists plus layout plans.

Each entry returns (netlist, plan, options).  The netlist is the circuit;
the plan says only what belongs where relative to what.  All coordinates
come from the placer.
"""
from .netlist import Netlist
from .plan import Group, Item, LayoutPlan, Slot, bridge_group
from . import analysis

GATE_DX = -4          # gate terminal, grid units left of its leg
OUT_DX = 3            # output terminal, grid units right of its column


def _gnd(nl, ref='GND1'):
    nl.add(ref, 'gnd')
    return ref


# ------------------------------------------------------------------ buck
def buck():
    n = Netlist('Buck Converter')
    n.add('V1', 'vsource', label='V', sub='in')
    n.add('Cin', 'cap', label='C', sub='in')
    n.add('Q1', 'nmos', label='Q', sub='1')
    n.add('D1', 'diode', label='D', sub='1')
    n.add('L1', 'ind', label='L', sub='1')
    n.add('Cout', 'cap', label='C', sub='out')
    n.add('RL', 'res', label='R', sub='L')
    _gnd(n)
    n.add('PWM', 'terminal', label='PWM', italic=False)
    n.add('VOUT', 'terminal', label='V', sub='out')

    n.connect('DC_POS', 'V1.p', 'Cin.a', 'Q1.d')
    n.connect('SW', 'Q1.s', 'D1.k', 'L1.a')
    n.connect('VOUT_N', 'L1.b', 'Cout.a', 'RL.a', 'VOUT.t')
    n.connect('DC_NEG', 'V1.n', 'Cin.b', 'D1.a', 'Cout.b', 'RL.b', 'GND1.t')
    n.connect('GATE', 'Q1.g', 'PWM.t')

    legs = analysis.find_legs(n)
    plan = LayoutPlan([
        Group('input_dc_link', 'source', [
            Slot(Item('V1', ('dc_pos', 'dc_neg'), label_side='left')),
            Slot(Item('Cin', ('dc_pos', 'dc_neg'), label_side='left'))]),
        Group('bridge', 'bridge', [
            Slot(Item(legs[0].high, 'high'),
                 Item(legs[0].low, 'low', label_side='right'),
                 Item('GND1', 'dc_neg'),
                 Item('PWM', 'gate_high', dx=GATE_DX, label_side='left'))]),
        Group('output_filter', 'filter', [
            Slot(Item('L1', 'mid', rot=-90, label_side='above')),
            Slot(Item('Cout', ('mid', 'dc_neg'), label_side='left'))]),
        Group('load', 'load', [
            Slot(Item('RL', ('mid', 'dc_neg')),
                 Item('VOUT', 'mid', dx=OUT_DX))]),
    ])
    return n, plan, dict(size=(150, 80), trunks={'VOUT_N': ('h', 16)})


# ------------------------------------------------------------------ boost
def boost():
    n = Netlist('Boost Converter')
    n.add('V1', 'vsource', label='V', sub='in')
    n.add('L1', 'ind', label='L', sub='1')
    n.add('D1', 'diode', label='D', sub='1')
    n.add('Q1', 'nmos', label='Q', sub='1')
    n.add('Cout', 'cap', label='C', sub='out')
    n.add('RL', 'res', label='R', sub='L')
    _gnd(n)
    n.add('PWM', 'terminal', label='PWM', italic=False)
    n.add('VOUT', 'terminal', label='V', sub='out')

    n.connect('VIN', 'V1.p', 'L1.a')
    n.connect('SW', 'L1.b', 'D1.a', 'Q1.d')
    n.connect('VOUT_N', 'D1.k', 'Cout.a', 'RL.a', 'VOUT.t')
    n.connect('DC_NEG', 'V1.n', 'Q1.s', 'Cout.b', 'RL.b', 'GND1.t')
    n.connect('GATE', 'Q1.g', 'PWM.t')

    # A boost is a leg topologically -- D1 above the switching node, Q1
    # below -- but it is drawn the conventional way: the inductor and diode
    # sit in series along the top rail with the switch hanging below the node.
    plan = LayoutPlan([
        Group('input_dc_link', 'source', [
            Slot(Item('V1', ('dc_pos', 'dc_neg'), label_side='left'))]),
        Group('conversion', 'conversion', [
            Slot(Item('L1', 'dc_pos', rot=-90, label_side='above')),
            Slot(Item('Q1', 'low'),
                 Item('GND1', 'dc_neg'),
                 Item('PWM', 'gate_low', dx=GATE_DX, label_side='left')),
            Slot(Item('D1', 'dc_pos', rot=90, label_side='above'))],
            pitch=6),
        Group('output_filter', 'filter', [
            Slot(Item('Cout', ('dc_pos', 'dc_neg'), label_side='left'))]),
        Group('load', 'load', [
            Slot(Item('RL', ('dc_pos', 'dc_neg')),
                 Item('VOUT', 'dc_pos', dx=OUT_DX, label_side='above'))]),
    ])
    return n, plan, dict(size=(150, 80),
                         trunks={'VIN': ('h', 8), 'VOUT_N': ('h', 8),
                                 'SW': ('v', 'Q1')})


# ------------------------------------------------------------------ bridges
def _switch_bridge(name, nlegs, kind='nmos', with_load=False):
    n = Netlist(name)
    n.add('V1', 'vsource', label='V', sub='dc')
    n.add('Cdc', 'cap', label='C', sub='dc')
    _gnd(n)
    phases = 'abc'[:nlegs] if nlegs <= 3 else None
    tags = list(phases) if phases else [str(i + 1) for i in range(nlegs)]

    pos = [f'S{t}p' for t in tags]
    neg = [f'S{t}n' for t in tags]
    for t in tags:
        n.add(f'S{t}p', kind, label='S', sub=f'{t}+')
        n.add(f'S{t}n', kind, label='S', sub=f'{t}-')
        n.add(f'G{t}p', 'terminal')
        n.add(f'G{t}n', 'terminal')

    hi = 'd' if kind.startswith('nmos') else 'c'
    lo = 's' if kind.startswith('nmos') else 'e'
    n.connect('DC_POS', 'V1.p', 'Cdc.a', *[f'{r}.{hi}' for r in pos])
    n.connect('DC_NEG', 'V1.n', 'Cdc.b', 'GND1.t', *[f'{r}.{lo}' for r in neg])
    for t in tags:
        n.connect(f'G_{t}p', f'S{t}p.g', f'G{t}p.t')
        n.connect(f'G_{t}n', f'S{t}n.g', f'G{t}n.t')
    return n, tags, hi, lo


def half_bridge():
    n, tags, hi, lo = _switch_bridge('Half Bridge', 1)
    n.add('OUT', 'terminal', label='V', sub='sw')
    n.connect('SW_A', 'Sap.s', 'San.d', 'OUT.t')

    legs = analysis.find_legs(n)
    plan = LayoutPlan([
        Group('input_dc_link', 'source', [
            Slot(Item('V1', ('dc_pos', 'dc_neg'), label_side='left')),
            Slot(Item('Cdc', ('dc_pos', 'dc_neg'), label_side='left'))]),
        Group('bridge', 'bridge', [
            Slot(Item(legs[0].high, 'high'), Item(legs[0].low, 'low'),
                 Item('GND1', 'dc_neg'),
                 Item('Gap', 'gate_high', dx=GATE_DX),
                 Item('Gan', 'gate_low', dx=GATE_DX))]),
        Group('output', 'output', [
            Slot(Item('OUT', 'mid'))], gap_before=8),
    ])
    return n, plan, dict(size=(120, 80))


def full_bridge():
    n, tags, hi, lo = _switch_bridge('Full Bridge', 2)
    n.add('RL', 'res', label='R', sub='L')
    n.connect('OUT_A', 'Sap.s', 'San.d', 'RL.a')
    n.connect('OUT_B', 'Sbp.s', 'Sbn.d', 'RL.b')

    legs = analysis.find_legs(n)
    by_mid = {l.mid: l for l in legs}
    order = [by_mid['OUT_A'], by_mid['OUT_B']]
    slots = []
    for i, leg in enumerate(order):
        items = [Item(leg.high, 'high'), Item(leg.low, 'low'),
                 Item(f'G{tags[i]}p', 'gate_high', dx=GATE_DX),
                 Item(f'G{tags[i]}n', 'gate_low', dx=GATE_DX)]
        if i == 0:
            items.append(Item('GND1', 'dc_neg'))
            items.append(Item('RL', 'mid', dx=4, rot=-90, label_side='above'))
        slots.append(Slot(*items))
    plan = LayoutPlan([
        Group('input_dc_link', 'source', [
            Slot(Item('V1', ('dc_pos', 'dc_neg'), label_side='left')),
            Slot(Item('Cdc', ('dc_pos', 'dc_neg'), label_side='left'))]),
        Group('bridge', 'bridge', slots),
    ])
    return n, plan, dict(size=(140, 80))


def three_phase_inverter():
    n, tags, hi, lo = _switch_bridge('Three-Phase Two-Level Inverter', 3,
                                     kind='igbt')
    for t in tags:
        n.add(f'PH{t.upper()}', 'terminal', label=t.upper())
        n.connect(f'PH_{t.upper()}', f'S{t}p.e', f'S{t}n.c',
                  f'PH{t.upper()}.t')

    legs = analysis.find_legs(n)
    by_mid = {l.mid: l for l in legs}
    slots = []
    for t in tags:
        leg = by_mid[f'PH_{t.upper()}']
        items = [Item(leg.high, 'high'), Item(leg.low, 'low'),
                 Item(f'G{t}p', 'gate_high', dx=GATE_DX),
                 Item(f'G{t}n', 'gate_low', dx=GATE_DX)]
        if t == 'a':
            items.append(Item('GND1', 'dc_neg'))
        slots.append(Slot(*items))
    # phase take-offs are staggered so each run to the right is a straight
    # line; equal spacing keeps the three of them visually parallel
    taps = {'a': 14, 'b': 16, 'c': 18}
    plan = LayoutPlan([
        Group('input_dc_link', 'source', [
            Slot(Item('V1', ('dc_pos', 'dc_neg'), label_side='left')),
            Slot(Item('Cdc', ('dc_pos', 'dc_neg'), label_side='left'))]),
        Group('bridge', 'bridge', slots),
        Group('output', 'output', [
            Slot(*[Item(f'PH{t.upper()}', taps[t]) for t in tags])],
            gap_before=9),
    ])
    return n, plan, dict(size=(165, 80))


# ------------------------------------------------------------------ DAB
def dab():
    n = Netlist('Dual Active Bridge')
    n.add('V1', 'vsource', label='V', sub='1')
    n.add('C1', 'cap', label='C', sub='1')
    n.add('TX', 'transformer', label='T', sub='x')
    n.add('C2', 'cap', label='C', sub='2')
    n.add('RL', 'res', label='R', sub='L')
    _gnd(n, 'GND1')
    _gnd(n, 'GND2')
    n.add('VOUT', 'terminal', label='V', sub='2')

    for tag in ('1', '2', '3', '4'):
        n.add(f'Q{tag}', 'nmos', label='Q', sub=tag)
        n.add(f'G{tag}', 'terminal')
    for tag in ('5', '6', '7', '8'):
        n.add(f'Q{tag}', 'nmos', label='Q', sub=tag)
        n.add(f'G{tag}', 'terminal')

    n.connect('DCP1', 'V1.p', 'C1.a', 'Q1.d', 'Q3.d')
    n.connect('DCN1', 'V1.n', 'C1.b', 'Q2.s', 'Q4.s', 'GND1.t')
    n.connect('PRI_A', 'Q1.s', 'Q2.d', 'TX.p1')
    n.connect('PRI_B', 'Q3.s', 'Q4.d', 'TX.p2')
    n.connect('SEC_A', 'Q5.s', 'Q6.d', 'TX.s1')
    n.connect('SEC_B', 'Q7.s', 'Q8.d', 'TX.s2')
    n.connect('DCP2', 'Q5.d', 'Q7.d', 'C2.a', 'RL.a', 'VOUT.t')
    n.connect('DCN2', 'Q6.s', 'Q8.s', 'C2.b', 'RL.b', 'GND2.t')
    for tag in '12345678':
        n.connect(f'G_{tag}', f'Q{tag}.g', f'G{tag}.t')

    def leg_slot(high, low, gh, gl, extra=()):
        return Slot(Item(high, 'high'), Item(low, 'low'),
                    Item(gh, 'gate_high', dx=GATE_DX),
                    Item(gl, 'gate_low', dx=GATE_DX), *extra)

    plan = LayoutPlan([
        Group('input_dc_link', 'source', [
            Slot(Item('V1', ('dc_pos', 'dc_neg'), label_side='left')),
            Slot(Item('C1', ('dc_pos', 'dc_neg'), label_side='left'))]),
        Group('primary_bridge', 'bridge', [
            leg_slot('Q1', 'Q2', 'G1', 'G2', (Item('GND1', 'dc_neg'),)),
            leg_slot('Q3', 'Q4', 'G3', 'G4')]),
        Group('isolation', 'isolation', [
            Slot(Item('TX', 'mid', label_side='above'))]),
        Group('secondary_bridge', 'bridge', [
            leg_slot('Q5', 'Q6', 'G5', 'G6'),
            leg_slot('Q7', 'Q8', 'G7', 'G8', (Item('GND2', 'dc_neg'),))]),
        Group('output_filter', 'filter', [
            Slot(Item('C2', ('dc_pos', 'dc_neg'), label_side='left'))]),
        Group('load', 'load', [
            Slot(Item('RL', ('dc_pos', 'dc_neg')),
                 Item('VOUT', 'dc_pos', dx=OUT_DX, label_side='above'))]),
    ])
    return n, plan, dict(size=(230, 80),
                         trunks={'DCP1': ('h', 8), 'DCN1': ('h', 24),
                                 'DCP2': ('h', 8), 'DCN2': ('h', 24)})


CATALOGUE = {
    'buck': buck,
    'boost': boost,
    'half_bridge': half_bridge,
    'full_bridge': full_bridge,
    'three_phase_inverter': three_phase_inverter,
    'dab': dab,
}
