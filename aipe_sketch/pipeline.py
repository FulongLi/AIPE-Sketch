"""The pipeline.

    netlist -> analysis -> plan -> placement -> routing
            -> scoring -> repair -> connectivity check -> render

Only geometry is ever repaired.  The netlist is never touched, and the
drawing is checked back against it before anything is written out.
"""
import math
import os

from . import (analysis, config, labels, placement, router, score, symlib,
               validate)
from .config import LABEL_SIZE, NOTE_SIZE
from .labels import LabelPlacer, text_bbox
from .parts import build_specs, port_table
from .pins import COARSE as G
from .sketch import Sketch

# kept for callers that import them from here
LABEL_PAD_X = config.LABEL_PAD_X_MM
LABEL_PAD_Y = config.LABEL_PAD_Y_MM
MIN_STACK_OFFSET = config.MIN_STACK_OFFSET_MM
GLYPH_W, LINE_H = config.GLYPH_W, config.LINE_H


class Schematic:
    """A schematic view of Circuit IR, with automatic or expert planning."""

    MARGIN = 2 * G          # breathing room around the drawn content

    def __init__(self, source, netlist, plan=None, size=None, title=None, text=None):
        self.source = source
        self.netlist = netlist
        self.fixed_size = size            # None means fit the sheet to content
        self.size = size or (0, 0)
        self.title = title or netlist.name
        self.symbols = symlib.load(source)[1]
        self.specs = build_specs(self.symbols)

        problems = netlist.validate() + netlist.validate(port_table(self.symbols))
        if problems:
            raise ValueError('netlist is not well formed:\n  ' +
                             '\n  '.join(problems))

        self.analysis = analysis.analyse(netlist)
        self.classes = analysis.repeated_classes(netlist)
        self.auto = plan is None
        if plan is None:
            from .planner import auto_plan
            from .grammar import lower
            self.semantic_plan = auto_plan(netlist, self.analysis)
            plan = lower(self.semantic_plan, netlist)
        else:
            self.semantic_plan = getattr(plan, 'semantic', None)
        self.plan = plan
        self.placed, self.extents = placement.place(plan, netlist, self.specs, text=text)
        self._coalesce_gate_interfaces()

        if text:
            for ref, style in text.items():
                part = self.placed[ref]
                part.label, part.sub, part.italic = style.label, style.sub, style.italic

        regularity = placement.check_regularity(self.placed, self.classes)
        if regularity:
            raise ValueError('placement breaks a repeated structure:\n  ' +
                             '\n  '.join(regularity))

        self.trunks = dict(getattr(plan, "trunks", {}))
        self._route_offset = (0.0, 0.0)
        self.candidate_report = []
        self.selected_candidate = None
        self.free_nets = set()
        self.paths = {}
        self.labels = []
        self.texts = []
        self._notes = []          # free annotations, kept across label rebuilds
        self.homeless_labels = []

    def _coalesce_gate_interfaces(self):
        """Put an invisible control interface directly on its switch gate.

        The library symbol already contains the visible gate lead.  A control
        terminal remains in Circuit IR so connectivity is explicit, but its
        port is made coincident with the gate instead of drawing an extra stub.
        """
        from .electrical import CONTROL_PORTS
        for members in self.netlist.nets.values():
            gates = [(ref, port) for ref, port in members
                     if port in CONTROL_PORTS.get(
                         self.netlist.components[ref].kind, ())]
            controls = [(ref, port) for ref, port in members
                        if self.netlist.components[ref].interface == 'control']
            if len(gates) != 1:
                continue
            target = self.placed[gates[0][0]].port(gates[0][1])
            for ref, port in controls:
                part = self.placed[ref]
                ox, oy = placement._transform(
                    part.spec.ports[port], part.rot, part.mirror)
                part.x, part.y = target[0] - ox, target[1] - oy
                part.ports = {name: tuple(round(v, 4) for v in (
                    part.x + placement._transform(offset, part.rot,
                                                  part.mirror)[0],
                    part.y + placement._transform(offset, part.rot,
                                                  part.mirror)[1]))
                    for name, offset in part.spec.ports.items()}
                part.bbox = (target[0], target[1], target[0], target[1])

    @classmethod
    def from_netlist(cls, circuit, *, source=None, plan=None, text=None,
                     size=None, title=None, candidates=12):
        """Generate a schematic view; manual geometry is an optional override."""
        from .paths import MASTER
        if not 1 <= candidates <= 12:
            raise ValueError('candidate count must be between 1 and 12')
        schematic = cls(source or MASTER, circuit, plan, size=size, title=title, text=text)
        if plan is None and candidates > 1:
            from .candidates import select
            return select(schematic, candidates, text=text)
        return schematic

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
                trunks[leg['mid']] = ('v', (high.x - self._route_offset[0]) / G)
        return trunks

    def route(self):
        trunks = self.default_trunks()
        trunks.update(self.trunks)
        obstacles = [p.bbox for p in self.placed.values()
                     if not p.spec.is_terminal]
        self.paths = {}
        ordered = list(self.netlist.nets.items())
        if self.semantic_plan:
            main = set(self.semantic_plan.main_power_nets)
            ordered.sort(key=lambda entry: (entry[0] not in main, entry[0]))
        for net, members in ordered:
            pts = [self.placed[ref].port(port) for ref, port in members]
            if len(pts) < 2:
                continue
            if (max(p[0] for p in pts) - min(p[0] for p in pts) < router.TOL
                    and max(p[1] for p in pts) - min(p[1] for p in pts)
                    < router.TOL):
                self.paths[net] = []
                continue
            spec = trunks.get(net)
            local_trunk = False
            if spec is None and len(pts) > 2:
                spread_x = max(p[0] for p in pts) - min(p[0] for p in pts)
                spread_y = max(p[1] for p in pts) - min(p[1] for p in pts)
                orient = 'h' if spread_x >= spread_y else 'v'
                pos = router.choose_trunk(pts, orient, obstacles, G)
                spec = (orient, pos / G)
                local_trunk = True
            if spec is not None:
                orient, gpos = spec
                offset = 0.0 if local_trunk else self._route_offset[0 if orient == 'v' else 1]
                if isinstance(gpos, str):
                    if gpos in self.plan.rows:       # a named row
                        gpos = self.plan.rows[gpos]
                    else:                            # a component's own axis
                        ref = self.placed[gpos]
                        gpos = (ref.x if orient == 'v' else ref.y) / G
                        offset = 0.0
                self.paths[net] = router.route_trunk(pts, orient, gpos * G + offset,
                                                     obstacles)
            else:
                self.paths[net] = [router.route_pair(pts[0], pts[1],
                                                     obstacles, G)]
        return self.paths

    # -------------------------------------------------------------- labels
    def build_labels(self):
        """Place every label through the one global engine.

        Free annotations are reserved first so component labels route around
        them, then each label takes the cheapest legal side.
        """
        junctions = []
        for net, net_paths in self.paths.items():
            terms = [self.placed[r].port(p)
                     for r, p in self.netlist.nets.get(net, [])
                     if r in self.placed]
            junctions += router.junction_points(net_paths, terms)

        placer = LabelPlacer(self.placed, self.paths, junctions)
        for note in self._notes:
            placer.reserve(note['key'], note['box'])

        for part in self.placed.values():
            part.label_keepout = None
        placements, homeless = placer.place_all()
        self.homeless_labels = homeless
        self.labels, self.texts = [], []
        for item in placements:
            part = self.placed[item['ref']]
            part.label_side = item['side']
            part.label_keepout = item['box']
            self.labels.append((item['ref'], item['box']))
            self.texts.append(dict(x=item['x'], y=item['y'],
                                   text=item['text'], sub=item['sub'],
                                   anchor=item['anchor'], size=item['size'],
                                   italic=item['italic']))
        for note in self._notes:
            self.texts.append(note['text_op'])
            self.labels.append((note['key'], note['box']))
        return self.labels

    def note(self, ref, row, text, sub=None, dx=0, dy=0, anchor='middle',
             size=NOTE_SIZE, italic=True):
        """Free text positioned relative to a placed component and a row."""
        gx = self.placed[ref].x / G + dx
        gy = (self.plan.row_y(row) if isinstance(row, str) else row) + dy
        self.annotate(gx, gy, text, sub=sub, anchor=anchor, size=size,
                      italic=italic)

    def annotate(self, gx, gy, text, sub=None, anchor='middle',
                 size=NOTE_SIZE, italic=False):
        x, y = gx * G, gy * G
        op = dict(x=x, y=y, text=text, sub=sub, anchor=anchor, size=size,
                  italic=italic)
        self._notes.append(dict(text_op=op, key=f'"{text}"',
                                box=text_bbox(x, y, text, sub, anchor, size)))
        self.build_labels()

    # -------------------------------------------------------------- markers
    def resolve_markers(self):
        """Place the boundary circle of every power interface.

        The circle sits just outside the wire's end, along the wire's own
        axis, so the wire stops at the circumference instead of running to
        the centre.  The outward direction is taken from the wire that
        actually arrives, so nothing has to be declared by hand.
        """
        from .parts import TERMINAL_R
        for ref, part in self.placed.items():
            part.marker = None
            if not part.marks_boundary:
                continue
            pt = part.port(next(iter(part.ports)))
            outward = self._outward(pt)
            cx = pt[0] + outward[0] * TERMINAL_R
            cy = pt[1] + outward[1] * TERMINAL_R
            part.marker = (round(cx, 4), round(cy, 4), TERMINAL_R)
            # the circle is part of the symbol's visual extent
            part.bbox = (min(part.bbox[0], cx - TERMINAL_R),
                         min(part.bbox[1], cy - TERMINAL_R),
                         max(part.bbox[2], cx + TERMINAL_R),
                         max(part.bbox[3], cy + TERMINAL_R))

    def _outward(self, pt):
        """Unit vector pointing away from the wire that reaches this point."""
        for net_paths in self.paths.values():
            for pts in net_paths:
                for a, b in router.path_segments(pts):
                    for end, other in ((a, b), (b, a)):
                        if (abs(end[0] - pt[0]) < router.TOL
                                and abs(end[1] - pt[1]) < router.TOL):
                            dx, dy = end[0] - other[0], end[1] - other[1]
                            length = (dx * dx + dy * dy) ** 0.5
                            if length > router.TOL:
                                return (dx / length, dy / length)
        return (1.0, 0.0)

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
        card = score.evaluate(self.netlist, self.placed, self.paths,
                              self.labels, self.classes,
                              bounds=((0, 0, self.size[0], self.size[1])
                                      if self.size != (0, 0) else self.content_box()),
                              connectivity_faults=faults,
                              structure=self.analysis,
                              plan_groups=[
                                  (g.id, [i.ref for s in g.slots
                                          for i in s.items])
                                  for g in self.plan.groups],
                              notes=self._notes,
                              registry=self.specs)
        card.raw['unplaced_labels'] = len(self.homeless_labels)
        if self.homeless_labels:
            card.sub['labelling'] = max(0, card.sub['labelling'] - 20 * len(self.homeless_labels))
            card.cost += 10000 * len(self.homeless_labels)
            card.faults.extend(f'{ref}: label has no collision-free position'
                               for ref in self.homeless_labels)
        return card

    def repair(self):
        """Report geometry selection and any unresolved label placement.

        The automatic factory scores and repairs geometry through the bounded
        candidate search before rendering. Manual overrides remain unchanged.
        Every final drawing is validated again below.
        """
        log = []
        if self.candidate_report and self.selected_candidate:
            initial = self.candidate_report[0].get('score', 'invalid')
            chosen = self.candidate_report[self.selected_candidate]
            log.append(f'geometry candidate {self.selected_candidate}: '
                       f'score {initial} -> {chosen.get("score")}; '
                       'rerouted, relabelled and connectivity validated')
        for ref in getattr(self, 'homeless_labels', ()):
            log.append(f'no collision-free position for label {ref}')
        return self.evaluate(), log

    # -------------------------------------------------------------- render
    def render(self, path, force=False):
        if not self.paths:
            self.route()
        if not self.labels:
            self.build_labels()
        self.resolve_markers()
        self.build_labels()
        dx, dy = self.fit_sheet()
        if dx or dy:
            self._shift(dx, dy)
        card, log = self.repair()

        faults = validate.check(self.netlist, self.placed, self.paths)
        if faults:
            from . import drawing_rules
            hints = drawing_rules.port_facing(self.netlist, self.placed)
            message = ('CONNECTIVITY FAULT -- drawing does not match the '
                       'netlist:\n  ' + '\n  '.join(faults))
            if hints:
                message += ('\nprobable cause:\n  ' + '\n  '.join(hints))
            raise RuntimeError(message)
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
        self._route_offset = (self._route_offset[0] + dx,
                              self._route_offset[1] + dy)
        for part in self.placed.values():
            part.x += dx
            part.y += dy
            part.ports = {p: (x + dx, y + dy) for p, (x, y) in part.ports.items()}
            x0, y0, x1, y1 = part.bbox
            part.bbox = (x0 + dx, y0 + dy, x1 + dx, y1 + dy)
            if part.marker:
                cx, cy, r = part.marker
                part.marker = (cx + dx, cy + dy, r)
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
        # An open ring marks a main power-side boundary and nothing else:
        # not a gate drive, not a control port, never an internal node.
        if part.marker:
            sketch.open_circle(*part.marker)
        for tx, ty, text, size in decor.get('texts', ()):
            x, y = at((tx, ty))
            sketch.label(x, y, text, size=size, anchor='middle', italic=False)
