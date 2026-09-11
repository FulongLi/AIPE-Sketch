"""Schematic engine: netlist in, verified publication-quality SVG out.

Connectivity is declared as nets over named component pins, never as
coordinates, so routing can never silently change the circuit.  Junction
dots are derived from the netlist, so a visual crossing is never an
electrical node.
"""
import os

from . import router, verify
from .pins import PARTS, COARSE
from .sketch import Sketch

# spacing rules, in multiples of the base grid G
MIN_PART_GAP = 3
LABEL_GAP = 1.3          # mm from body edge to label box
CLEARANCE = 1            # G of wire-to-body clearance


class Part:
    """A placed component."""

    def __init__(self, ref, kind, x, y, rot, mirror, pins, bbox, grid):
        self.ref, self.kind = ref, kind
        self.x, self.y = x, y
        self.rot, self.mirror = rot, mirror
        self.pins = pins
        self.bbox = bbox
        self.grid = grid

    @property
    def clearance_bbox(self):
        c = CLEARANCE * self.grid
        x0, y0, x1, y1 = self.bbox
        return (x0 - c, y0 - c, x1 + c, y1 + c)

    def pin(self, name):
        if name not in self.pins:
            raise KeyError(f'{self.ref} ({self.kind}) has no pin {name!r}; '
                           f'available: {sorted(self.pins)}')
        return self.pins[name]


class Schematic:
    def __init__(self, source, width, height, title='Schematic', grid=COARSE):
        self.sketch = Sketch(source, width, height, title)
        self.grid = grid
        self.parts = {}
        self.order = []
        self.nets = {}
        self.paths = {}
        self.labels = []
        self.groups = []
        self._texts = []

    # ------------------------------------------------------------ placing
    def add(self, ref, kind, gx, gy, rot=0, mirror=False,
            label=None, sub=None, side='right'):
        """Place a part at grid coordinates (gx, gy). Returns a Part."""
        if ref in self.parts:
            raise ValueError(f'duplicate reference {ref}')
        x, y = gx * self.grid, gy * self.grid
        pins = self.sketch.place(kind, x, y, rot=rot, mirror=mirror)

        spec = PARTS[kind]
        sym = self.sketch.symbols[spec['sym']]
        ax, ay = spec['anchor']
        bx0, by0, bx1, by1 = sym.bbox
        dx0, dy0 = bx0 - ax, by0 - ay
        dx1, dy1 = bx1 - ax, by1 - ay
        corners = [(dx0, dy0), (dx1, dy0), (dx0, dy1), (dx1, dy1)]
        if mirror:
            corners = [(-cx, cy) for cx, cy in corners]
        if rot:
            import math
            th = math.radians(rot)
            cos, sin = math.cos(th), math.sin(th)
            corners = [(cx * cos - cy * sin, cx * sin + cy * cos)
                       for cx, cy in corners]
        xs = [x + cx for cx, _ in corners]
        ys = [y + cy for _, cy in corners]
        bbox = (min(xs), min(ys), max(xs), max(ys))

        part = Part(ref, kind, x, y, rot, mirror, pins, bbox, self.grid)
        self.parts[ref] = part
        self.order.append(part)

        if label:
            self._add_label(part, label, sub, side)
        return part

    def _add_label(self, part, text, sub, side):
        """Consistent label placement relative to the body (rule 7)."""
        x0, y0, x1, y1 = part.bbox
        cy = (y0 + y1) / 2
        if side == 'right':
            lx, ly, anchor = x1 + LABEL_GAP, cy + 0.9, 'start'
        elif side == 'left':
            lx, ly, anchor = x0 - LABEL_GAP, cy + 0.9, 'end'
        elif side == 'above':
            lx, ly, anchor = (x0 + x1) / 2, y0 - LABEL_GAP, 'middle'
        else:
            lx, ly, anchor = (x0 + x1) / 2, y1 + LABEL_GAP + 2.2, 'middle'
        self._texts.append(dict(x=lx, y=ly, text=text, sub=sub,
                                anchor=anchor, size=2.82222, italic=True))
        self.labels.append((part.ref, self._text_bbox(lx, ly, text, sub,
                                                      anchor, 2.82222)))

    # text metrics are estimated, so they are deliberately pessimistic:
    # a label that merely looks tight should be reported, not waved through
    GLYPH_W = 0.62          # em per glyph, sans-serif average
    LINE_H = 1.15           # em, cap height plus descender
    TEXT_PAD = 0.35         # mm of breathing room demanded around a label

    @classmethod
    def _text_bbox(cls, x, y, text, sub, anchor, size):
        n = len(text) + (len(sub) * 0.72 if sub else 0)
        w = n * size * cls.GLYPH_W
        h = size * cls.LINE_H
        if anchor == 'start':
            x0 = x
        elif anchor == 'end':
            x0 = x - w
        else:
            x0 = x - w / 2
        pad = cls.TEXT_PAD
        return (x0 - pad, y - h * 0.80 - pad, x0 + w + pad, y + h * 0.25 + pad)

    def text(self, gx, gy, text, sub=None, anchor='middle',
             size=2.5, italic=False, track=True):
        """Free-standing text such as a net name."""
        x, y = gx * self.grid, gy * self.grid
        self._texts.append(dict(x=x, y=y, text=text, sub=sub, anchor=anchor,
                                size=size, italic=italic))
        if track:
            self.labels.append(('"%s"' % text,
                                self._text_bbox(x, y, text, sub, anchor, size)))

    def repeated(self, *refs):
        """Declare refs as a topologically equivalent group (rule 3)."""
        self.groups.append(list(refs))

    # ------------------------------------------------------------ nets
    def net(self, name, *terminals, trunk=None):
        """Declare a net over 'REF.pin' terminals.

        trunk: ('h', gy) or ('v', gx) to force a rail, or None to route
        point-to-point (2 terminals) / auto-pick a trunk (3 or more).
        """
        points = []
        for t in terminals:
            if isinstance(t, str):
                ref, pin = t.split('.')
                points.append(self.parts[ref].pin(pin))
            else:
                points.append(tuple(t))
        self.nets[name] = dict(points=points, trunk=trunk)
        return points

    def _obstacles(self, exclude_points):
        """Bodies to route around, minus the parts this net connects to."""
        out = []
        for part in self.order:
            if any(p in part.pins.values() for p in exclude_points):
                out.append(part.bbox)      # still avoid, pins are on the edge
            else:
                out.append(part.bbox)
        return out

    def build(self):
        """Route every net."""
        self.paths = {}
        for name, spec in self.nets.items():
            pts = spec['points']
            obstacles = self._obstacles(pts)
            trunk = spec['trunk']
            if trunk is None and len(pts) > 2:
                orient = 'h' if (max(p[0] for p in pts) - min(p[0] for p in pts)) \
                    >= (max(p[1] for p in pts) - min(p[1] for p in pts)) else 'v'
                pos = router.choose_trunk(pts, orient, obstacles, self.grid)
                trunk = (orient, pos / self.grid)
            if trunk is not None:
                orient, gpos = trunk
                self.paths[name] = router.route_trunk(
                    pts, orient, gpos * self.grid, obstacles)
            elif len(pts) == 2:
                self.paths[name] = [router.route_pair(
                    pts[0], pts[1], obstacles, self.grid)]
            else:
                self.paths[name] = [[pts[0], pts[0]]]
        return self.paths

    # ------------------------------------------------------------ output
    def verify(self):
        if not self.paths:
            self.build()
        net_parts = {}
        for name, spec in self.nets.items():
            refs = set()
            for pt in spec['points']:
                for part in self.order:
                    if pt in part.pins.values():
                        refs.add(part.ref)
            net_parts[name] = refs
        return verify.evaluate(self.order, self.paths, self.labels,
                               self.grid, self.groups, net_parts)

    def render(self, path, force=False):
        """Draw and save.  Refuses to render a layout that fails §11."""
        report = self.verify()
        if not report.passed and not force:
            raise RuntimeError('layout rejected\n' + str(report))

        for name, net_paths in self.paths.items():
            for pts in net_paths:
                self.sketch.wire(*pts)
            terms = self.nets[name]['points']
            for dot in router.junction_points(net_paths, terms):
                self.sketch.dot(dot)

        for t in self._texts:
            self.sketch.label(t['x'], t['y'], t['text'], sub=t['sub'],
                              size=t['size'], anchor=t['anchor'],
                              italic=t['italic'])

        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        self.sketch.save(path)
        return report
