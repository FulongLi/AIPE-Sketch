"""Electrical regression circuits. These builders return Circuit IR only.

Manual comparison fixtures live in manual_topologies.py.
"""
from .netlist import Netlist

def _gnd(nl, ref='GND1'):
    nl.add(ref, 'gnd')
    return ref

def _gate(nl, ref):
    """A gate drive port.

    It is an interface, so it stays a real component and connectivity stays
    checkable -- but it is control, not power, so it is drawn as an ordinary
    wire endpoint with no boundary marker.
    """
    nl.add(ref, 'terminal', interface='control')
    return ref

def buck():
    n = Netlist('Buck Converter')
    n.add('V1', 'vsource')
    n.add('C1', 'cap')
    n.add('Q1', 'nmos')
    n.add('D1', 'diode')
    n.add('L1', 'ind')
    n.add('C2', 'cap')
    n.add('R1', 'res')
    _gnd(n)
    _gate(n, 'G1')
    n.connect('DC_POS', 'V1.p', 'C1.a', 'Q1.d')
    n.connect('SW', 'Q1.s', 'D1.k', 'L1.a')
    n.connect('VOUT_N', 'L1.b', 'C2.a', 'R1.a')
    n.connect('DC_NEG', 'V1.n', 'C1.b', 'D1.a', 'C2.b', 'R1.b', 'GND1.t')
    n.connect('GATE', 'Q1.g', 'G1.t')
    return n

def boost():
    n = Netlist('Boost Converter')
    n.add('V1', 'vsource')
    n.add('L1', 'ind')
    n.add('D1', 'diode')
    n.add('Q1', 'nmos')
    n.add('C1', 'cap')
    n.add('R1', 'res')
    _gnd(n)
    _gate(n, 'G1')
    n.connect('VIN', 'V1.p', 'L1.a')
    n.connect('SW', 'L1.b', 'D1.a', 'Q1.d')
    n.connect('VOUT_N', 'D1.k', 'C1.a', 'R1.a')
    n.connect('DC_NEG', 'V1.n', 'Q1.s', 'C1.b', 'R1.b', 'GND1.t')
    n.connect('GATE', 'Q1.g', 'G1.t')
    return n

def _dc_link(n):
    n.add('V1', 'vsource')
    n.add('C1', 'cap')
    _gnd(n)

def _switches(n, count, kind='nmos', start=1):
    refs = []
    for i in range(count):
        ref = f'Q{start + i}'
        n.add(ref, kind)
        _gate(n, f'G{start + i}')
        refs.append(ref)
    return refs

def half_bridge():
    n = Netlist('Half Bridge')
    _dc_link(n)
    _switches(n, 2)
    n.add('VOUT', 'terminal', interface='power', name='VOUT')
    n.connect('DC_POS', 'V1.p', 'C1.a', 'Q1.d')
    n.connect('SW', 'Q1.s', 'Q2.d', 'VOUT.t')
    n.connect('DC_NEG', 'V1.n', 'C1.b', 'Q2.s', 'GND1.t')
    n.connect('G_1', 'Q1.g', 'G1.t')
    n.connect('G_2', 'Q2.g', 'G2.t')
    return n

def full_bridge():
    n = Netlist('Full Bridge')
    _dc_link(n)
    _switches(n, 4)
    n.add('R1', 'res')
    n.connect('DC_POS', 'V1.p', 'C1.a', 'Q1.d', 'Q3.d')
    n.connect('OUT_A', 'Q1.s', 'Q2.d', 'R1.a')
    n.connect('OUT_B', 'Q3.s', 'Q4.d', 'R1.b')
    n.connect('DC_NEG', 'V1.n', 'C1.b', 'Q2.s', 'Q4.s', 'GND1.t')
    for i in range(1, 5):
        n.connect(f'G_{i}', f'Q{i}.g', f'G{i}.t')
    return n

def three_phase_inverter():
    n = Netlist('Three-Phase Two-Level Inverter')
    _dc_link(n)
    _switches(n, 6, kind='igbt')
    phases = ('A', 'B', 'C')
    for ph in phases:
        n.add(f'PH{ph}', 'terminal', interface='power', name=ph)
    n.connect('DC_POS', 'V1.p', 'C1.a', 'Q1.c', 'Q3.c', 'Q5.c')
    n.connect('DC_NEG', 'V1.n', 'C1.b', 'Q2.e', 'Q4.e', 'Q6.e', 'GND1.t')
    for (i, ph) in enumerate(phases):
        (hi, lo) = (f'Q{2 * i + 1}', f'Q{2 * i + 2}')
        n.connect(f'PH_{ph}', f'{hi}.e', f'{lo}.c', f'PH{ph}.t')
    for i in range(1, 7):
        n.connect(f'G_{i}', f'Q{i}.g', f'G{i}.t')
    return n

def dab():
    n = Netlist('Dual Active Bridge')
    n.add('V1', 'vsource')
    n.add('C1', 'cap')
    n.add('T1', 'transformer')
    n.add('C2', 'cap')
    n.add('R1', 'res')
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
    return n

def llc_resonant():
    """Half bridge driving a series resonant tank into a transformer.

    The primary power path -- switching node, Cr, Lr, transformer primary --
    is the case the centreline rules exist for.  The transformer is placed
    so that its primary top terminal lands exactly on the switching-node
    row, which is what lets the whole chain sit on one horizontal line.
    """
    n = Netlist('LLC Resonant Converter')
    n.add('V1', 'vsource')
    n.add('C1', 'cap')
    _gnd(n, 'GND1')
    _switches(n, 2)
    n.add('Cr', 'cap')
    n.add('Lr', 'ind')
    n.add('T1', 'transformer')
    n.add('D1', 'diode')
    n.add('C2', 'cap')
    n.add('R1', 'res')
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
    return n
CIRCUITS = {'buck': buck, 'boost': boost, 'half_bridge': half_bridge, 'full_bridge': full_bridge, 'three_phase_inverter': three_phase_inverter, 'dab': dab, 'llc_resonant': llc_resonant}
from .manual_topologies import CATALOGUE
