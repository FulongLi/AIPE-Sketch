"""Three-phase two-level voltage-source inverter (B6).

Exercises the hard layout rules: three topologically identical legs drawn as
equally spaced parallel columns, high-side above low-side, switching node
centred between them, DC+ above and DC- below.

Phase outputs leave to the right at staggered heights.  Phase A must get
past legs B and C, so three wire crossings are unavoidable; they are drawn
plainly with no junction dot, which is the convention the source library
itself uses for its full bridge.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aipe_sketch.engine import Schematic

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, 'Inkscape_Symbols_All.svg')

# geometry, in grid units
X_SRC, X_CDC = 6, 13
X_LEGS = (22, 30, 38)              # equally spaced parallel columns
X_OUT = 48
Y_DCP, Y_DCN = 8, 24               # DC+ above, DC- below
HALF = 2                           # device half-height
Y_HS = Y_DCP + HALF                # high-side row
Y_LS = Y_DCN - HALF                # low-side row
Y_TAPS = (14, 16, 18)              # staggered phase take-offs
GATE_DX, GATE_DY = -2.5, 1.0       # gate lead, in grid units
PHASES = ('a', 'b', 'c')


def build(out_path):
    s = Schematic(SRC, 150, 72, 'Three-Phase Two-Level Inverter')

    s.add('V1', 'vsource', X_SRC, (Y_DCP + Y_DCN) // 2,
          label='V', sub='dc', side='left')
    s.add('Cdc', 'cap', X_CDC, (Y_DCP + Y_DCN) // 2,
          label='C', sub='dc', side='left')

    # three identical legs
    for ph, xl in zip(PHASES, X_LEGS):
        s.add(f'S{ph}p', 'igbt', xl, Y_HS, label='S', sub=f'{ph}+')
        s.add(f'S{ph}n', 'igbt', xl, Y_LS, label='S', sub=f'{ph}-')
    s.repeated(*[f'S{p}p' for p in PHASES])
    s.repeated(*[f'S{p}n' for p in PHASES])

    # DC link
    s.net('DC+', 'V1.p', 'Cdc.a', *[f'S{p}p.c' for p in PHASES],
          trunk=('h', Y_DCP))
    s.net('DC-', 'V1.n', 'Cdc.b', *[f'S{p}n.e' for p in PHASES],
          trunk=('h', Y_DCN))

    # phase legs: the switching node is the vertical run between the two
    # devices; the take-off is a stub onto that run
    for ph, xl, yt in zip(PHASES, X_LEGS, Y_TAPS):
        s.net(ph.upper(), f'S{ph}p.e', f'S{ph}n.c',
              (X_OUT * s.grid, yt * s.grid), trunk=('v', xl))
        s.text(X_OUT + 0.7, yt + 0.35, ph.upper(), anchor='start', italic=True)

    # gate drives, approaching each switch from the side
    for ph, xl in zip(PHASES, X_LEGS):
        for suffix, yrow in (('p', Y_HS), ('n', Y_LS)):
            gx, gy = xl + GATE_DX, yrow + GATE_DY
            s.net(f'G{ph}{suffix}', f'S{ph}{suffix}.g',
                  ((gx - 1.6) * s.grid, gy * s.grid))

    # rail names
    s.text(X_SRC - 1.0, Y_DCP - 0.6, 'DC+', anchor='start')
    s.text(X_SRC - 1.0, Y_DCN + 1.6, 'DC-', anchor='start')

    report = s.render(out_path)
    return out_path, report


if __name__ == '__main__':
    path, report = build(os.path.join(ROOT, 'out', 'three_phase_inverter.svg'))
    print(report)
    print('\nwrote', path)
