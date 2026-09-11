"""The pipeline.

    netlist -> analysis -> plan -> placement -> routing
            -> scoring -> repair -> connectivity check -> render

Only geometry is ever repaired.  The netlist is never touched, and the
drawing is checked back against it before anything is written out.
"""
import os
import xml.etree.ElementTree as ET

from . import analysis, placement, router, score, symlib, validate
from .parts import build_specs, port_table
from .pins import COARSE as G
from .plan import ROWS
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

    def __init__(self, source, netlist, plan, size=(160, 80), title=None):
        self.source = source
        self.netlist = netlist
        self.plan = plan
        self.size = size
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
                trunks[net] = ('h', ROWS['dc_pos'])
            elif net == rails['negative']:
                trunks[net] = ('h', ROWS['dc_neg'])
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
        obstacles = [p.bbox for p in self.placed.values()]
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
                if isinstance(gpos, str):        # 'at this component's axis'
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
        return self.labels

    def annotate(self, gx, gy, text, sub=None, anchor='middle', size=2.5,
                 italic=False):
        x, y = gx * G, gy * G
        self.texts.append(dict(x=x, y=y, text=text, sub=sub, anchor=anchor,
                               size=size, italic=italic))
        self.labels.append((f'"{text}"',
                            text_bbox(x, y, text, sub, anchor, size)))

    # -------------------------------------------------------------- scoring
    def evaluate(self):
        faults = validate.check(self.netlist, self.placed, self.paths)
        return score.evaluate(self.netlist, self.placed, self.paths,
                              self.labels, self.classes,
                              bounds=(0, 0, self.size[0], self.size[1]),
                              connectivity_faults=faults)

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

    def _draw(self, sketch, part):
        compound = part.spec.compound
        if compound is None:
            sketch.place(part.kind, part.x, part.y, rot=part.rot,
                         mirror=part.mirror)
            return
        for kind, dx, dy, rot, mirror in compound['symbols']:
            ox, oy = placement._transform((dx, dy), part.rot, part.mirror)
            sketch.place(kind, part.x + ox, part.y + oy,
                         rot=rot + part.rot, mirror=mirror ^ part.mirror)
        for a, b in compound['strokes']:
            pa = placement._transform(a, part.rot, part.mirror)
            pb = placement._transform(b, part.rot, part.mirror)
            sketch.wire((part.x + pa[0], part.y + pa[1]),
                        (part.x + pb[0], part.y + pb[1]))
