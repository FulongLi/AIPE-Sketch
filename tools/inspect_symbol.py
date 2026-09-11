#!/usr/bin/env python3
"""Measure symbols in the master sheet so they can be added to pins.py.

    python3 tools/inspect_symbol.py                 # list every symbol
    python3 tools/inspect_symbol.py g4046 g13419    # measure specific ids
    python3 tools/inspect_symbol.py --name MOSFET   # search by title
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from aipe_sketch import symlib

SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   'Inkscape_Symbols_All.svg')


def report(sym):
    x0, y0, x1, y1 = sym.bbox
    fe = sym.free_ends
    print(f'{sym.id:<22} {sym.name}')
    print(f'  bbox      {x1 - x0:7.3f} x {y1 - y0:7.3f}  '
          f'at ({x0:.3f}, {y0:.3f})')
    if fe:
        ytop, ybot = min(p[1] for p in fe), max(p[1] for p in fe)
        top = [p for p in fe if abs(p[1] - ytop) < 1e-6]
        bot = [p for p in fe if abs(p[1] - ybot) < 1e-6]
        print(f'  top/bot   {top} / {bot}')
        print(f'  anchor    ({top[0][0]:.4f}, {(ytop + ybot) / 2:.4f})   '
              f'half-height {(ybot - ytop) / 2:.4f}')
    print(f'  free ends {fe}')
    print()


def main(argv):
    _, syms = symlib.load(SRC)
    if not argv:
        for s in sorted(syms.values(), key=lambda s: s.name):
            x0, y0, x1, y1 = s.bbox
            print(f'{s.id:<22} {s.name:<26} {x1 - x0:7.3f} x {y1 - y0:7.3f}')
        return
    if argv[0] == '--name':
        needle = argv[1].lower()
        for s in syms.values():
            if needle in s.name.lower():
                report(s)
        return
    for sid in argv:
        if sid in syms:
            report(syms[sid])
        else:
            print(f'{sid}: not found', file=sys.stderr)


if __name__ == '__main__':
    main(sys.argv[1:])
