"""Electrical regression circuits. These builders return Circuit IR only.

Manual comparison fixtures live in manual_synthetic.py.
"""
from .netlist import Netlist

def _gnd(n, ref='GND1'):
    n.add(ref, 'gnd')
    return ref

def series_rlc():
    """A plain R-L-C chain: the series-path motif, nothing else."""
    n = Netlist('Series R-L-C Chain')
    n.add('V1', 'vsource')
    n.add('R1', 'res')
    n.add('L1', 'ind')
    n.add('C1', 'cap')
    _gnd(n)
    n.connect('N1', 'V1.p', 'R1.a')
    n.connect('N2', 'R1.b', 'L1.a')
    n.connect('N3', 'L1.b', 'C1.a')
    n.connect('RTN', 'V1.n', 'C1.b', 'GND1.t')
    return n

def twin_shunt_branches():
    """Two equivalent shunt switches on one rail.

    Their branches must come out balanced *and* identical to each other --
    the repeated-structure rule applied to shunts rather than bridge legs.
    """
    n = Netlist('Twin Shunt Branches')
    n.add('V1', 'vsource')
    n.add('L1', 'ind')
    n.add('L2', 'ind')
    n.add('R1', 'res')
    _gnd(n)
    for tag in ('1', '2'):
        n.add(f'Q{tag}', 'nmos')
        n.add(f'G{tag}', 'terminal', interface='control')
    n.connect('IN', 'V1.p', 'L1.a')
    n.connect('MID', 'L1.b', 'Q1.d', 'L2.a')
    n.connect('OUT', 'L2.b', 'Q2.d', 'R1.a')
    n.connect('RTN', 'V1.n', 'Q1.s', 'Q2.s', 'R1.b', 'GND1.t')
    n.connect('G_1', 'Q1.g', 'G1.t')
    n.connect('G_2', 'Q2.g', 'G2.t')
    return n

def three_repeated_legs():
    """Three identical legs with no converter semantics attached."""
    n = Netlist('Three Repeated Legs')
    n.add('V1', 'vsource')
    n.add('C1', 'cap')
    _gnd(n)
    tags = ('1', '2', '3')
    for t in tags:
        n.add(f'Qh{t}', 'nmos')
        n.add(f'Ql{t}', 'nmos')
        n.add(f'Gh{t}', 'terminal', interface='control')
        n.add(f'Gl{t}', 'terminal', interface='control')
        n.add(f'T{t}', 'terminal', interface='power', name=f'A{t}')
    n.connect('DC_POS', 'V1.p', 'C1.a', *[f'Qh{t}.d' for t in tags])
    n.connect('DC_NEG', 'V1.n', 'C1.b', 'GND1.t', *[f'Ql{t}.s' for t in tags])
    for (i, t) in enumerate(tags):
        n.connect(f'MID_{t}', f'Qh{t}.s', f'Ql{t}.d', f'T{t}.t')
        n.connect(f'GH_{t}', f'Qh{t}.g', f'Gh{t}.t')
        n.connect(f'GL_{t}', f'Ql{t}.g', f'Gl{t}.t')
    return n

def parallel_rc_block():
    """A bare parallel block across one node pair."""
    n = Netlist('Parallel R-C Block')
    n.add('I1', 'isource')
    n.add('C1', 'cap')
    n.add('R1', 'res')
    _gnd(n)
    n.connect('TOP', 'I1.p', 'C1.a', 'R1.a')
    n.connect('RTN', 'I1.n', 'C1.b', 'R1.b', 'GND1.t')
    return n

def transformer_between_networks():
    """A transformer joining two unrelated R-C networks."""
    n = Netlist('Transformer Between Networks')
    n.add('V1', 'vsource')
    n.add('R1', 'res')
    n.add('T1', 'transformer')
    n.add('R2', 'res')
    n.add('C1', 'cap')
    _gnd(n, 'GND1')
    _gnd(n, 'GND2')
    n.add('OUT', 'terminal', interface='power', name='VOUT')
    n.connect('P_IN', 'V1.p', 'R1.a')
    n.connect('P_TOP', 'R1.b', 'T1.p1')
    n.connect('P_RTN', 'V1.n', 'T1.p2', 'GND1.t')
    n.connect('S_TOP', 'T1.s1', 'R2.a')
    n.connect('S_OUT', 'R2.b', 'C1.a', 'OUT.t')
    n.connect('S_RTN', 'T1.s2', 'C1.b', 'GND2.t')
    return n
CIRCUITS = {'series_rlc': series_rlc, 'twin_shunt_branches': twin_shunt_branches, 'three_repeated_legs': three_repeated_legs, 'parallel_rc_block': parallel_rc_block, 'transformer_between_networks': transformer_between_networks}
from .manual_synthetic import SYNTHETIC


def source_l_r():
    """A source feeding one series inductor and a resistive return."""
    n = Netlist('Inductive branch')
    n.add('V1', 'voltage_source')
    n.add('L1', 'inductor')
    n.add('R1', 'resistor')
    n.connect('supply', 'V1.p', 'L1.a')
    n.connect('load', 'L1.b', 'R1.a')
    n.connect('return', 'R1.b', 'V1.n')
    return n


def isolated_series_chain():
    """A C-L-isolation-diode path with independent primary/secondary returns."""
    n = Netlist('Isolated passive network')
    for ref, kind in (('V1', 'vsource'), ('C1', 'cap'), ('L1', 'ind'),
                      ('T1', 'transformer'), ('D1', 'diode'), ('C2', 'cap'),
                      ('R1', 'res'), ('GND1', 'gnd'), ('GND2', 'gnd')):
        n.add(ref, kind)
    n.connect('a', 'V1.p', 'C1.a')
    n.connect('b', 'C1.b', 'L1.a')
    n.connect('c', 'L1.b', 'T1.p1')
    n.connect('d', 'T1.s1', 'D1.a')
    n.connect('e', 'D1.k', 'C2.a', 'R1.a')
    n.connect('primary_return', 'V1.n', 'T1.p2', 'GND1.t')
    n.connect('secondary_return', 'C2.b', 'R1.b', 'T1.s2', 'GND2.t')
    return n


CIRCUITS.update(source_l_r=source_l_r, isolated_series_chain=isolated_series_chain)
