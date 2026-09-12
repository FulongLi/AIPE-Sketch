#!/usr/bin/env python3
"""Measure symbols in the master sheet so they can be added to pins.py.

    python3 tools/inspect_symbol.py                  # list every symbol
    python3 tools/inspect_symbol.py g4046 g13419     # measure specific ids
    python3 tools/inspect_symbol.py --name MOSFET    # search by title
    python3 tools/inspect_symbol.py --transformers   # every candidate, with
                                                     # previews for comparison
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from aipe_sketch import library, symlib

from aipe_sketch.paths import MASTER as SRC


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


def _stroke_count(elements):
    paths = strokes = 0
    for el in elements:
        for e in el.iter():
            tag = e.tag.replace(symlib.NS, '')
            if tag == 'path':
                paths += 1
            if tag in ('path', 'circle', 'ellipse', 'rect', 'line'):
                strokes += 1
    return paths, strokes


def inspect_candidates(syms, needle, out_dir=None):
    """Deep inspection of every symbol whose title matches `needle`.

    Reports what the wrapper actually contains, how much of it is unrelated
    neighbouring geometry, and where the device's own terminals are -- the
    questions that decide whether a wrapper is usable as it stands.
    """
    import xml.etree.ElementTree as ET
    import copy
    matches = [s for s in syms.values() if needle.lower() in s.name.lower()]
    if not matches:
        print(f'no symbol titled like {needle!r}', file=sys.stderr)
        return []
    written = []
    for sym in sorted(matches, key=lambda s: s.id):
        info = library.analyse(sym)
        if info.get('empty'):
            print(f'{sym.id}: no drawable geometry')
            continue
        main, stray = info['main_elements'], info['stray_elements']
        paths, strokes = _stroke_count(main)
        ox0, oy0, ox1, oy1 = info['original_bbox']
        cx0, cy0, cx1, cy1 = info['clean_bbox']
        print(f'{sym.id}  "{sym.name}"   [{info["status"]}]')
        print(f'   descendants   {sum(1 for _ in sym.el.iter())} '
              f'({len(main)} device, {len(stray)} unrelated)')
        print(f'   paths/strokes {paths} / {strokes}')
        print(f'   wrapper bbox  {ox1 - ox0:8.3f} x {oy1 - oy0:8.3f} mm')
        print(f'   device bbox   {cx1 - cx0:8.3f} x {cy1 - cy0:8.3f} mm')
        if info['flags']:
            print(f'   suspected     {"; ".join(info["flags"])}')
        ends = library.free_endpoints(main)
        left = [p for p in ends if abs(p[0] - cx0) < 0.05]
        right = [p for p in ends if abs(p[0] - cx1) < 0.05]
        print(f'   terminals     {len(ends)} candidates; '
              f'primary(left)={left} secondary(right)={right}')
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)
            pad = 1.5
            w, h = (cx1 - cx0) + 2 * pad, (cy1 - cy0) + 2 * pad
            svg = ET.Element(symlib.NS + 'svg', {
                'width': f'{w:.3f}mm', 'height': f'{h:.3f}mm',
                'viewBox': f'0 0 {w:.3f} {h:.3f}'})
            ET.SubElement(svg, symlib.NS + 'rect', {
                'x': '0', 'y': '0', 'width': str(w), 'height': str(h),
                'fill': '#ffffff'})
            g = ET.SubElement(svg, symlib.NS + 'g', {
                'transform': f'translate({pad - cx0:.3f},{pad - cy0:.3f})'})
            for el in main:
                g.append(copy.deepcopy(el))
            path = os.path.join(out_dir, f'{sym.id}.svg')
            ET.ElementTree(svg).write(path, xml_declaration=True,
                                      encoding='utf-8')
            written.append(path)
            print(f'   preview       {os.path.relpath(path)}')
        print()
    return written


def main(argv):
    _, syms = symlib.load(SRC)
    if not argv:
        for s in sorted(syms.values(), key=lambda s: s.name):
            x0, y0, x1, y1 = s.bbox
            print(f'{s.id:<22} {s.name:<26} {x1 - x0:7.3f} x {y1 - y0:7.3f}')
        return
    if argv[0] == '--transformers':
        out = os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), 'out', 'transformer_candidates')
        files = inspect_candidates(syms, 'transformer', out)
        print(f'{len(files)} previews written to {os.path.relpath(out)}')
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
