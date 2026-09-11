"""Buck converter, described as a netlist and laid out by the engine.

Power flow left to right: source -> input filter -> switching leg -> output
filter -> load.  Q1 sits above D1 with the switching node between them.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aipe_sketch.engine import Schematic

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, 'Inkscape_Symbols_All.svg')


def build(out_path):
    s = Schematic(SRC, 140, 80, 'Buck Converter')

    # column plan (grid units): input | filter | leg | output filter | load
    X_IN, X_CIN, X_SW, X_L, X_COUT, X_LOAD = 8, 14, 22, 30, 36, 44
    Y_DC_P, Y_SW, Y_DC_N = 8, 12, 24          # DC+ / switching node / DC-
    Y_MID = (Y_DC_P + Y_DC_N) // 2
    Y_OUT = (Y_SW + Y_DC_N) // 2
    HALF = 2                                   # symbol half-height, in G

    s.add('V1',   'vsource', X_IN,   Y_MID,  label='V', sub='in',  side='left')
    s.add('Cin',  'cap',     X_CIN,  Y_MID,  label='C', sub='in',  side='left')
    s.add('Q1',   'nmos',    X_SW,   Y_DC_P + HALF, label='Q', sub='1')
    s.add('D1',   'diode',   X_SW,   Y_DC_N - HALF, label='D', sub='1')
    s.add('L1',   'ind',     X_L,    Y_SW, rot=-90, label='L', sub='1',
          side='above')
    s.add('Cout', 'cap',     X_COUT, Y_OUT,  label='C', sub='out', side='left')
    s.add('RL',   'res',     X_LOAD, Y_OUT,  label='R', sub='L')
    s.add('GND1', 'gnd',     X_SW,   Y_DC_N)

    # nets -- connectivity only; the engine decides the wire geometry
    s.net('DCP', 'V1.p', 'Cin.a', 'Q1.d',            trunk=('h', Y_DC_P))
    s.net('SW',  'Q1.s', 'D1.k',  'L1.a',            trunk=('h', Y_SW))
    s.net('VOUT', 'L1.b', 'Cout.a', 'RL.a',          trunk=('h', Y_SW))
    s.net('DCN', 'V1.n', 'Cin.b', 'D1.a', 'Cout.b', 'RL.b', 'GND1.t',
          trunk=('h', Y_DC_N))
    s.net('PWM', 'Q1.g', (17 * s.grid, s.parts['Q1'].pin('g')[1]))

    # net names
    s.text(X_SW + 5.0, Y_SW - 0.7, 'SW')
    s.text(X_LOAD - 0.6, Y_SW - 0.7, 'V', sub='out', anchor='end', italic=True)
    s.text(16.6, (s.parts['Q1'].pin('g')[1] + 0.9) / s.grid, 'PWM', anchor='end')

    report = s.render(out_path)
    return out_path, report


if __name__ == '__main__':
    path, report = build(os.path.join(ROOT, 'out', 'buck_converter.svg'))
    print(report)
    print('\nwrote', path)
