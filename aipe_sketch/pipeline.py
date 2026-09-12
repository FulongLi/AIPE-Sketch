"""The pipeline.

    netlist -> analysis -> plan -> placement -> routing
            -> scoring -> repair -> connectivity check -> render

Only geometry is ever repaired.  The netlist is never touched, and the
drawing is checked back against it before anything is written out.
"""
import math
import os
import xml.etree.ElementTree as ET

from . import analysis, placement, router, score, symlib, validate
from .parts import build_specs, port_table
from .pins import COARSE as G
from .sketch import Sketch

LABEL_GAP = 1.3
GLYPH_W, LINE_H, TEXT_PAD = 0.62, 1.15, 0.35
LABEL_SIDES = ('right', 'left', 'above', 'below')


def text_bbox(x, y, text, sub, anchor, size):
    n = len(text) + (len(sub) * 0.72 if sub else 0)
    w = n * size * GLYPH_W
    h = size * LINE_H
    x0 = x if anchor == 'start' else (x - w if anchor == 'end' else x - w / 2)
    return (x0 - TEXT_PAD, y - h * 0.80 - TEXT_PAD,
            x0 + w + TEXT_PAD, y + h * 0.25 + TEXT_PAD)


def label_anchor(part, side):
    x0, y0, x1, y1 = part.bbox
    cy = (y0 + y1) / 2
    if side == 'right':
        return x1 + LABEL_GAP, cy + 0.9, 'start'
    if side == 'left':
        return x0 - LABEL_GAP, cy + 0.9, 'end'
    if side == 'above':
        return (x0 + x1) / 2, y0 - LABEL_GAP, 'middle'
    return (x0 + x1) / 2, y1 + LABEL_GAP + 2.2, 'middle'


class Schematic:
    """One run of the pipeline for one netlist and one plan."""

    MARGIN = 2 * G          # breathing room around the drawn content

    def __init__(self, source, netlist, plan, size=None, title=None):
        self.source = source
        self.netlist = netlist
        self.plan = plan
        self.fixed_size = size            # None means fit the sheet to content
        self.size = size or (0, 0)
        self.title = title or netlist.name
        self.symbols = symlib.load(source)[1]
        self.specs = build_specs(self.symbols)

        problems = netlist.validate(port_table(self.symbols))
        if problems:
            raise ValueError('netlist is not well formed:\n  ' +
                             '\n  '.join(problems))

        self.analysis = analysis.analyse(netlist)
        self.classes = analysis.repeated_classes(netlist)
        self.placed, self.extents = placement.place(plan, netlist, self.specs)

        regularity = placement.check_regularity(self.placed, self.classes)
        if regularity:
            raise ValueError('placement breaks a repeated structure:\n  ' +
                             '\n  '.join(regularity))

        self.trunks = {}
        self.free_nets = set()
        self.paths = {}
        self.labels = []
        self.texts = []
        self._notes = []          # free annotations, kept across label rebuilds
        self._sides = {ref: p.label_side for ref, p in self.placed.items()}

    # -------------------------------------------------------------- routing
    def default_trunks(self):
        """Derive a routing style per net from topology, not from geometry.

        Equivalent nets get equivalent treatment, which is what keeps the
        three legs of a bridge looking alike.
        """
        trunks = {}
        rails = self.analysis['rails']
        for net in self.netlist.nets:
            if net == rails['positive']:
                trunks[net] = ('h', self.plan.rows['dc_pos'])
            elif net == rails['negative']:
                trunks[net] = ('h', self.plan.rows['dc_neg'])
        for leg in self.analysis['legs']:
            high, low = self.placed[leg['high']], self.placed[leg['low']]
            # only a vertically stacked leg gets a vertical midpoint rail;
            # if the two devices sit side by side the caller must say where
            if abs(high.x - low.x) < 1e-6:
                trunks[leg['mid']] = ('v', high.x / G)
        return trunks

    def route(self):
        trunks = self.default_trunks()
        trunks.update(self.trunks)
        obstacles = [p.bbox for p in self.placed.values()
                     if not p.spec.is_terminal]
        self.paths = {}
        for net, members in self.netlist.nets.items():
            pts = [self.placed[ref].port(port) for ref, port in members]
            if len(pts) < 2:
                continue
            spec = trunks.get(net)
            if spec is None and len(pts) > 2:
                spread_x = max(p[0] for p in pts) - min(p[0] for p in pts)
                spread_y = max(p[1] for p in pts) - min(p[1] for p in pts)
                orient = 'h' if spread_x >= spread_y else 'v'
                pos = router.choose_trunk(pts, orient, obstacles, G)
                spec = (orient, pos / G)
            if spec is not None:
                orient, gpos = spec
                if isinstance(gpos, str):
                    if gpos in self.plan.rows:       # a named row
                        gpos = self.plan.rows[gpos]
                    else:                            # a component's own axis
                        ref = self.placed[gpos]
                        gpos = (ref.x if orient == 'v' else ref.y) / G
                self.paths[net] = router.route_trunk(pts, orient, gpos * G,
                                                     obstacles)
            else:
                self.paths[net] = [router.route_pair(pts[0], pts[1],
                                                     obstacles, G)]
        return self.paths

    # -------------------------------------------------------------- labels
    def build_labels(self):
        """Rebuild component labels, preserving any free annotations."""
        self.labels, self.texts = [], []
        for ref, part in self.placed.items():
            if not part.label:
                continue
            x, y, anchor = label_anchor(part, self._sides[ref])
            box = text_bbox(x, y, part.label, part.sub, anchor, 2.82222)
            self.labels.append((ref, box))
            self.texts.append(dict(x=x, y=y, text=part.label, sub=part.sub,
                                   anchor=anchor, size=2.82222,
                                   italic=part.italic))
        for note in self._notes:
            self.texts.append(note['text_op'])
            self.labels.append((note['key'], note['box']))
        return self.labels

    def note(self, ref, row, text, sub=None, dx=0, dy=0, anchor='middle',
             size=2.5, italic=True):
        """Free text positioned relative to a placed component and a row."""
        gx = self.placed[ref].x / G + dx
        gy = (self.plan.row_y(row) if isinstance(row, str) else row) + dy
        self.annotate(gx, gy, text, sub=sub, anchor=anchor, size=size,
                      italic=italic)

    def annotate(self, gx, gy, text, sub=None, anchor='middle', size=2.5,
                 italic=False):
        x, y = gx * G, gy * G
        op = dict(x=x, y=y, text=text, sub=sub, anchor=anchor, size=size,
                  italic=italic)
        self._notes.append(dict(text_op=op, key=f'"{text}"',
                                box=text_bbox(x, y, text, sub, anchor, size)))
        self.build_labels()

    # -------------------------------------------------------------- sheet
    def content_box(self):
        """Bounding box of everything that will be drawn."""
        xs, ys = [], []
        for part in self.placed.values():
            x0, y0, x1, y1 = part.bbox
            xs += [x0, x1]
            ys += [y0, y1]
        for net_paths in self.paths.values():
            for pts in net_paths:
                xs += [p[0] for p in pts]
                ys += [p[1] for p in pts]
        for _, box in self.labels:
            xs += [box[0], box[2]]
            ys += [box[1], box[3]]
        if not xs:
            return (0.0, 0.0, 0.0, 0.0)
        return (min(xs), min(ys), max(xs), max(ys))

    def fit_sheet(self):
        """Size the sheet to its content and shift it into the margin."""
        if self.fixed_size:
            self.size = self.fixed_size
            return 0.0, 0.0
        x0, y0, x1, y1 = self.content_box()
        # snap the offset to whole grid steps so placement stays on the grid
        dx = math.ceil((self.MARGIN - x0) / G) * G
        dy = math.ceil((self.MARGIN - y0) / G) * G
        # content ends up spanning [x0+dx, x1+dx], so the sheet must reach
        # x1+dx plus the far margin
        self.size = (round(x1 + dx + self.MARGIN, 3),
                     round(y1 + dy + self.MARGIN, 3))
        return dx, dy

    # -------------------------------------------------------------- scoring
    def evaluate(self):
        faults = validate.check(self.netlist, self.placed, self.paths)
        return score.evaluate(self.netlist, self.placed, self.paths,
                              self.labels, self.classes,
                              bounds=(0, 0, self.size[0], self.size[1]),
                              connectivity_faults=faults,
                              structure=self.analysis,
                              plan_groups=[
                                  (g.id, [i.ref for s in g.slots
                                          for i in s.items])
                                  for g in self.plan.groups],
                              notes=self._notes)

    def repair(self, max_iterations=8):
        """Fix geometry only: move labels, widen rails, reroute."""
        log = []
        card = self.evaluate()
        for _ in range(max_iterations):
            if card.acceptable and not card.faults:
                break
            before = card.cost
            if not self._repair_labels(card, log):
                break
            self.build_labels()
            card = self.evaluate()
            if card.cost >= before:
                break
        return card, log

    def _repair_labels(self, card, log):
        """Try the other sides for any label that collides."""
        offenders = set()
        for fault in card.faults:
            if fault.startswith('label '):
                token = fault.split()[1]
                if token in self.placed:
                    offenders.add(token)
        if not offenders:
            return False
        moved = False
        for ref in sorted(offenders):
            part = self.placed[ref]
            for side in LABEL_SIDES:
                if side == self._sides[ref]:
                    continue
                self._sides[ref] = side
                self.build_labels()
                trial = self.evaluate()
                if not any(f.startswith(f'label {ref} ') for f in trial.faults):
                    log.append(f'moved label {ref} to the {side}')
                    moved = True
                    break
            else:
                continue
        return moved

    # -------------------------------------------------------------- render
    def render(self, path, force=False):
        if not self.paths:
            self.route()
        if not self.labels:
            self.build_labels()
        dx, dy = self.fit_sheet()
        if dx or dy:
            self._shift(dx, dy)
        card, log = self.repair()

        faults = validate.check(self.netlist, self.placed, self.paths)
        if faults:
            raise RuntimeError('CONNECTIVITY FAULT -- drawing does not match '
                               'the netlist:\n  ' + '\n  '.join(faults))
        if not card.acceptable and not force:
            raise RuntimeError('layout rejected\n' + str(card))

        sketch = Sketch(self.source, self.size[0], self.size[1], self.title)
        for ref, part in self.placed.items():
            self._draw(sketch, part)
        for net, net_paths in self.paths.items():
            for pts in net_paths:
                sketch.wire(*pts)
            terms = [self.placed[r].port(p)
                     for r, p in self.netlist.nets[net]]
            for dot in router.junction_points(net_paths, terms):
                sketch.dot(dot)
        for t in self.texts:
            sketch.label(t['x'], t['y'], t['text'], sub=t['sub'],
                         size=t['size'], anchor=t['anchor'], italic=t['italic'])

        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        sketch.save(path)
        return card, log

    def _shift(self, dx, dy):
        """Translate the whole drawing; relative geometry is untouched."""
        for part in self.placed.values():
            part.x += dx
            part.y += dy
            part.ports = {p: (x + dx, y + dy) for p, (x, y) in part.ports.items()}
            x0, y0, x1, y1 = part.bbox
            part.bbox = (x0 + dx, y0 + dy, x1 + dx, y1 + dy)
        self.paths = {net: [[(x + dx, y + dy) for x, y in pts] for pts in ps]
                      for net, ps in self.paths.items()}
        for note in self._notes:
            note['text_op']['x'] += dx
            note['text_op']['y'] += dy
            b = note['box']
            note['box'] = (b[0] + dx, b[1] + dy, b[2] + dx, b[3] + dy)
        self.build_labels()

    def _draw(self, sketch, part):
        spec = part.spec
        if spec.compound is None:
            sketch.place(part.kind, part.x, part.y, rot=part.rot,
                         mirror=part.mirror)
        else:
            for kind, dx, dy, rot, mirror in spec.compound['symbols']:
                ox, oy = placement._transform((dx, dy), part.rot, part.mirror)
                sketch.place(kind, part.x + ox, part.y + oy,
                             rot=rot + part.rot, mirror=mirror ^ part.mirror)
        self._draw_decor(sketch, part)

    def _draw_decor(self, sketch, part):
        """Marks laid over the symbol: polarity, arrows, terminal rings."""
        decor = part.spec.decor

        def at(point):
            dx, dy = placement._transform(point, part.rot, part.mirror)
            return part.x + dx, part.y + dy

        for a, b in decor.get('strokes', ()):
            sketch.wire(at(a), at(b))
        for cx, cy, r in decor.get('circles', ()):
            x, y = at((cx, cy))
            sketch.open_circle(x, y, r)
        for tx, ty, text, size in decor.get('texts', ()):
            x, y = at((tx, ty))
            sketch.label(x, y, text, size=size, anchor='middle', italic=False)
