"""The global label placement engine.

Every component label goes through the same procedure: take the preferred
side from the symbol registry, rotate it with the component, generate
candidates in a deterministic order, reject any that collide with anything
already on the page, and keep the cheapest survivor.

Topology definitions do not choose label positions.  They describe the
circuit; this decides where its labels go.
"""
import math

from . import config, router
from .config import (GLYPH_W, LABEL_FALLBACK, LABEL_PAD_X_MM, LABEL_PAD_Y_MM,
                     LABEL_SIZE, LINE_H, MIN_STACK_OFFSET_MM, SUBSCRIPT)
from .router import TOL

OPPOSITE = {'left': 'right', 'right': 'left',
            'above': 'below', 'below': 'above'}
# unit vector of each side in the symbol's own frame, y down
SIDE_VECTOR = {'right': (1.0, 0.0), 'left': (-1.0, 0.0),
               'above': (0.0, -1.0), 'below': (0.0, 1.0)}


# ------------------------------------------------------------------ geometry
def text_size(text, sub=None, size=LABEL_SIZE):
    """Estimated ink extent of a designator.  Deliberately pessimistic."""
    glyphs = len(text) + (len(sub) * SUBSCRIPT if sub else 0)
    return glyphs * size * GLYPH_W, size * LINE_H


def text_bbox(x, y, text, sub=None, anchor='start', size=LABEL_SIZE,
              pad_x=LABEL_PAD_X_MM, pad_y=LABEL_PAD_Y_MM):
    """Keep-out box of a label: its glyphs plus the clearance margin."""
    w, h = text_size(text, sub, size)
    x0 = x if anchor == 'start' else (x - w if anchor == 'end' else x - w / 2)
    return (x0 - pad_x, y - h * 0.80 - pad_y,
            x0 + w + pad_x, y + h * 0.25 + pad_y)


def ink_bbox(x, y, text, sub=None, anchor='start', size=LABEL_SIZE):
    """The glyphs alone, without the clearance margin."""
    return text_bbox(x, y, text, sub, anchor, size, pad_x=0.0, pad_y=0.0)


def preferred_side(part):
    """The page-side this part's label should prefer, after rotation.

    A part laid on its side uses the registry's flat preference directly --
    a horizontal R, L, C or D is labelled above whichever way it was turned.
    Otherwise the upright preference is rotated with the symbol.
    """
    if part.rot % 180:
        return part.label_side_flat
    return rotated_side(part.label_side_local, part.rot, part.mirror)


def rotated_side(side, rot, mirror=False):
    """The page-side a symbol-frame side points to once the part is placed."""
    dx, dy = SIDE_VECTOR[side]
    if mirror:
        dx = -dx
    if rot:
        th = math.radians(rot)
        cos, sin = math.cos(th), math.sin(th)
        dx, dy = dx * cos - dy * sin, dx * sin + dy * cos
    if abs(dx) >= abs(dy):
        return 'right' if dx > 0 else 'left'
    return 'below' if dy > 0 else 'above'


def anchor_for(bbox, side, offset):
    """Where the text sits, and how it is anchored, for one side."""
    x0, y0, x1, y1 = bbox
    cy = (y0 + y1) / 2
    if side in ('above', 'below'):
        offset = max(offset, MIN_STACK_OFFSET_MM)
    if side == 'right':
        return x1 + offset, cy + 0.9, 'start'
    if side == 'left':
        return x0 - offset, cy + 0.9, 'end'
    if side == 'above':
        return (x0 + x1) / 2, y0 - offset, 'middle'
    return (x0 + x1) / 2, y1 + offset + 2.2, 'middle'


def overlaps(a, b):
    return (min(a[2], b[2]) - max(a[0], b[0]) > TOL and
            min(a[3], b[3]) - max(a[1], b[1]) > TOL)


def _box_around(point, radius):
    x, y = point
    return (x - radius, y - radius, x + radius, y + radius)


# ------------------------------------------------------------------ engine
class LabelPlacer:
    """Places every label on a sheet against one shared set of obstacles."""

    def __init__(self, placed, paths, junctions=()):
        self.placed = placed
        self.paths = paths
        self.bodies = [p for p in placed.values()
                       if p.spec.width > TOL or p.spec.height > TOL]
        self.segments = [seg for net_paths in paths.values()
                         for pts in net_paths
                         for seg in router.path_segments(pts)]
        self.markers = [_box_around((p.marker[0], p.marker[1]), p.marker[2])
                        for p in placed.values()
                        if getattr(p, 'marker', None)]
        self.junctions = [_box_around(pt, config.JUNCTION_R_MM)
                          for pt in junctions]
        self.boxes = {}          # ref -> keep-out box, filled as we go

    # -- candidate generation -----------------------------------------
    def candidates(self, part):
        """Sides to try, preferred first, in a deterministic order."""
        preferred = preferred_side(part)
        order = []
        for name in LABEL_FALLBACK:
            side = (preferred if name == 'preferred'
                    else OPPOSITE[preferred] if name == 'opposite' else name)
            if side not in order:
                order.append(side)
        return order

    # -- collision ----------------------------------------------------
    def blockers(self, part, box):
        """What, if anything, this label box runs into."""
        hits = []
        for other in self.bodies:
            if other is part:
                continue
            if overlaps(box, other.bbox):
                hits.append(f'body {other.ref}')
        for ref, other in self.boxes.items():
            if ref != part.ref and overlaps(box, other):
                hits.append(f'label {ref}')
        for seg in self.segments:
            if router.seg_penetrates(seg, box):
                hits.append('wire')
                break
        for marker in self.markers:
            if overlaps(box, marker):
                hits.append('terminal marker')
                break
        for dot in self.junctions:
            if overlaps(box, dot):
                hits.append('junction')
                break
        return hits

    # -- ranking ------------------------------------------------------
    def cost(self, part, side, box, preferred, port_anchor):
        """Lower is better.  Only legal candidates are ranked."""
        cx = (box[0] + box[2]) / 2
        cy = (box[1] + box[3]) / 2
        bx = (part.bbox[0] + part.bbox[2]) / 2
        by = (part.bbox[1] + part.bbox[3]) / 2
        score = 0.0
        if side != preferred:
            score += 40.0                                  # honour the default
        score += (abs(cx - bx) + abs(cy - by)) / config.CELL_MM * 6.0
        if port_anchor is not None:
            score += (abs(cx - port_anchor[0]) +
                      abs(cy - port_anchor[1])) / config.CELL_MM
        clear = min((self._clearance(box, other.bbox)
                     for other in self.bodies if other is not part),
                    default=config.CELL_MM)
        score += max(0.0, config.CELL_MM - clear) / config.CELL_MM * 8.0
        return score

    @staticmethod
    def _clearance(a, b):
        dx = max(a[0] - b[2], b[0] - a[2], 0.0)
        dy = max(a[1] - b[3], b[1] - a[3], 0.0)
        return math.hypot(dx, dy)

    # -- placement ----------------------------------------------------
    def place(self, part):
        """Best legal position for one label, or None if every side fails."""
        if not part.label:
            return None
        preferred = preferred_side(part)
        port_anchor = next(iter(part.ports.values()), None)
        best = None
        for side in self.candidates(part):
            x, y, anchor = anchor_for(part.bbox, side, part.label_offset)
            box = text_bbox(x, y, part.label, part.sub, anchor)
            if self.blockers(part, box):
                continue
            cost = self.cost(part, side, box, preferred, port_anchor)
            if best is None or cost < best[0]:
                best = (cost, side, x, y, anchor, box)
        if best is None:
            return None
        _, side, x, y, anchor, box = best
        self.boxes[part.ref] = box
        return dict(ref=part.ref, side=side, x=x, y=y, anchor=anchor,
                    box=box, size=LABEL_SIZE, text=part.label, sub=part.sub,
                    italic=part.italic, preferred=preferred)

    def place_all(self, order=None):
        """Place every label.  Returns placements and any that had no home."""
        parts = [self.placed[r] for r in order] if order else \
            sorted(self.placed.values(), key=lambda p: (p.x, p.y, p.ref))
        placements, homeless = [], []
        for part in parts:
            if not part.label:
                continue
            result = self.place(part)
            if result is None:
                homeless.append(part.ref)
            else:
                placements.append(result)
        return placements, homeless

    def reserve(self, key, box):
        """Block out a region -- a free annotation, say -- before placing."""
        self.boxes[key] = box
