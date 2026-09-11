#!/usr/bin/env python3
"""Render a contact sheet of every <symbol> in the master sheet.

Each tile shows the symbol, its bounding box (blue) and its free path
endpoints (red) -- the candidates for terminals.

    python3 tools/catalog.py            # all symbols -> out/catalog.svg
    python3 tools/catalog.py --curated  # only the parts wired up in pins.py
"""
import os
import sys
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from aipe_sketch import symlib
from aipe_sketch.pins import PARTS

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, 'Inkscape_Symbols_All.svg')
NS = symlib.NS

COLS, CW, CH = 8, 26.0, 28.0
MAX_SPAN = 30.0          # skip symbols that drag in neighbouring geometry


def build(ids, out_path):
    rows = (len(ids) + COLS - 1) // COLS
    svg = ET.Element(NS + 'svg', {
        'width': f'{COLS * CW}mm', 'height': f'{rows * CH}mm',
        'viewBox': f'0 0 {COLS * CW} {rows * CH}', 'version': '1.1'})
    ET.SubElement(svg, NS + 'rect', {
        'x': '0', 'y': '0', 'width': str(COLS * CW), 'height': str(rows * CH),
        'fill': '#ffffff'})
    _, syms = symlib.load(SRC)

    for i, sid in enumerate(ids):
        s = syms[sid]
        x0, y0, x1, y1 = s.bbox
        cx = (i % COLS) * CW + CW / 2
        cy = (i // COLS) * CH + CH / 2 - 1
        sx, sy = (x0 + x1) / 2, (y0 + y1) / 2
        g = ET.SubElement(svg, NS + 'g',
                          {'transform': f'translate({cx - sx},{cy - sy})'})
        for c in s.body():
            g.append(c)
        for px, py in s.free_ends:
            ET.SubElement(g, NS + 'circle', {
                'cx': str(px), 'cy': str(py), 'r': '0.45', 'fill': 'none',
                'stroke': '#e01b24', 'stroke-width': '0.15'})
        ET.SubElement(g, NS + 'rect', {
            'x': str(x0), 'y': str(y0), 'width': str(x1 - x0),
            'height': str(y1 - y0), 'fill': 'none', 'stroke': '#3584e4',
            'stroke-width': '0.1', 'stroke-dasharray': '0.4,0.4'})
        for text, dy, size, fill in (
                (s.name, CH - 4.0, 2.0, '#000000'),
                (f'{sid}  {x1 - x0:.2f}x{y1 - y0:.2f}', CH - 1.6, 1.5, '#777777')):
            t = ET.SubElement(svg, NS + 'text', {
                'x': str(cx), 'y': str((i // COLS) * CH + dy),
                'text-anchor': 'middle',
                'style': f'font-size:{size}px;font-family:sans-serif;fill:{fill}'})
            t.text = text
    ET.ElementTree(svg).write(out_path, xml_declaration=True, encoding='utf-8')
    return out_path


if __name__ == '__main__':
    _, syms = symlib.load(SRC)
    if '--curated' in sys.argv:
        ids = [p['sym'] for p in PARTS.values()]
        name = 'catalog_curated.svg'
    else:
        ids = [s.id for s in sorted(syms.values(), key=lambda s: s.name)
               if (s.bbox[2] - s.bbox[0]) < MAX_SPAN
               and (s.bbox[3] - s.bbox[1]) < MAX_SPAN]
        name = 'catalog.svg'
    os.makedirs(os.path.join(ROOT, 'out'), exist_ok=True)
    print(build(ids, os.path.join(ROOT, 'out', name)), f'({len(ids)} symbols)')
