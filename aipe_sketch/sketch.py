"""Compose a schematic from the Inkscape electric-symbols library.

The output is a plain Inkscape-compatible SVG: symbols land in ``<defs>``
as ``<g>`` blocks and are instantiated with ``<use>``, so the drawing stays
editable by hand afterwards.
"""
import copy
import math
import re
import xml.etree.ElementTree as ET

from . import symlib
from .pins import PARTS, COARSE, GRID

NS = symlib.NS
XLINK = 'http://www.w3.org/1999/xlink'

WIRE = ('fill:none;stroke:#000000;stroke-width:0.264583;'
        'stroke-linecap:round;stroke-linejoin:miter')
DOT = 'fill:#000000;stroke:none'
DOT_R = 0.4                      # matches the junction dots inside the library


class Sketch:
    """A schematic sheet.  All coordinates are millimetres, y down."""

    def __init__(self, source, width, height, title='Schematic'):
        self.src_root, self.symbols = symlib.load(source)
        self.width, self.height = width, height
        self.svg = ET.Element(NS + 'svg', {
            'width': f'{width}mm', 'height': f'{height}mm',
            'viewBox': f'0 0 {width} {height}', 'version': '1.1'})
        ET.SubElement(self.svg, NS + 'title').text = title
        self.defs = ET.SubElement(self.svg, NS + 'defs')
        # carry over the source defs so nested <use> references still resolve
        for d in self.src_root.iter(NS + 'defs'):
            for child in d:
                self.defs.append(copy.deepcopy(child))
            break
        self._emitted = set()
        self.layer = ET.SubElement(self.svg, NS + 'g', {'id': 'schematic'})

    # -- geometry helpers ------------------------------------------------
    @staticmethod
    def snap(value, grid=COARSE):
        return round(value / grid) * grid

    def _ensure_symbol(self, kind):
        gid = f'sym-{kind}'
        if gid not in self._emitted:
            spec = PARTS[kind]
            ax, ay = spec['anchor']
            g = ET.SubElement(self.defs, NS + 'g',
                              {'id': gid, 'transform': f'translate({-ax},{-ay})'})
            for child in self.symbols[spec['sym']].body():
                g.append(child)
            self._emitted.add(gid)
        return gid

    # -- drawing ---------------------------------------------------------
    def place(self, kind, x, y, rot=0, mirror=False):
        """Drop a part at (x, y).  Returns {pin name: absolute (x, y)}."""
        gid = self._ensure_symbol(kind)
        tf = f'translate({x},{y})'
        if rot:
            tf += f' rotate({rot})'
        if mirror:
            tf += ' scale(-1,1)'
        ET.SubElement(self.layer, NS + 'use',
                      {'{%s}href' % XLINK: '#' + gid, 'transform': tf})
        th = math.radians(rot)
        cos, sin = math.cos(th), math.sin(th)
        out = {}
        for pin, (dx, dy) in PARTS[kind]['pins'].items():
            if mirror:
                dx = -dx
            out[pin] = (round(x + dx * cos - dy * sin, 4),
                        round(y + dx * sin + dy * cos, 4))
        return out

    def wire(self, *points):
        d = 'M ' + ' L '.join(f'{p[0]},{p[1]}' for p in points)
        ET.SubElement(self.layer, NS + 'path', {'d': d, 'style': WIRE})

    def elbow(self, a, b, first='h'):
        """Two-segment orthogonal wire between a and b."""
        mid = (b[0], a[1]) if first == 'h' else (a[0], b[1])
        self.wire(a, mid, b)

    def open_circle(self, x, y, r):
        """An external terminal: filled with the page colour so the wire end
        is hidden, outlined so it reads as an open ring."""
        ET.SubElement(self.layer, NS + 'circle', {
            'cx': str(round(x, 4)), 'cy': str(round(y, 4)), 'r': str(r),
            'style': 'fill:#ffffff;stroke:#000000;stroke-width:0.264583'})

    def dot(self, *points):
        for p in points:
            ET.SubElement(self.layer, NS + 'circle',
                          {'cx': str(p[0]), 'cy': str(p[1]),
                           'r': str(DOT_R), 'style': DOT})

    def label(self, x, y, text, sub=None, size=2.82222,
              anchor='middle', italic=True):
        """Designator text.  ``sub`` renders as a subscript, e.g. C/'out'."""
        style = (f"font-style:{'italic' if italic else 'normal'};"
                 f"font-weight:normal;font-size:{size}px;"
                 f"font-family:sans-serif;fill:#000000;stroke:none")
        t = ET.SubElement(self.layer, NS + 'text',
                          {'x': str(x), 'y': str(y),
                           'text-anchor': anchor, 'style': style})
        span = ET.SubElement(t, NS + 'tspan', {'x': str(x), 'y': str(y)})
        span.text = text
        if sub:
            ET.SubElement(span, NS + 'tspan', {
                'style': f'font-size:{size * 0.72}px;'
                         'baseline-shift:sub;font-style:normal'}).text = sub
        return t

    # -- output ----------------------------------------------------------
    def _prune_defs(self):
        """Drop the source defs that nothing in this drawing references."""
        index = {}          # id -> top-level defs child providing it
        for child in self.defs:
            for el in child.iter():
                if el.get('id'):
                    index.setdefault(el.get('id'), child)

        def hrefs(el):
            for e in el.iter():
                for key in ('{%s}href' % XLINK, 'href'):
                    v = e.get(key)
                    if v and v.startswith('#'):
                        yield v[1:]
                style = e.get('style') or ''
                for m in re.finditer(r'url\(#([^)]+)\)', style):
                    yield m.group(1)

        keep, queue = set(), list(hrefs(self.layer))
        while queue:
            name = queue.pop()
            child = index.get(name)
            if child is None or id(child) in keep:
                continue
            keep.add(id(child))
            queue.extend(hrefs(child))

        for child in list(self.defs):
            if id(child) not in keep:
                self.defs.remove(child)

    def save(self, path):
        self._prune_defs()
        ET.ElementTree(self.svg).write(path, xml_declaration=True,
                                       encoding='utf-8')
        return path
