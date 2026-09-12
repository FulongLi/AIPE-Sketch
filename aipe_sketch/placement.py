"""Deterministic placement: layout plan in, coordinates out.

Columns advance left to right, so power flows that way.  Slots inside a
group share one pitch and items inside a slot share one x, which makes
alignment exact and spacing uniform by construction rather than by repair.
"""
import math

from .pins import COARSE as G


class Placed:
    """A component with a position, a port map and a body box."""

    __slots__ = ('ref', 'kind', 'x', 'y', 'rot', 'mirror', 'ports', 'bbox',
                 'group', 'slot', 'row', 'spec', 'label', 'sub', 'label_side',
                 'italic', 'interface', 'label_offset', 'marker')

    def __init__(self, ref, kind, x, y, rot, mirror, ports, bbox, spec):
        self.ref, self.kind = ref, kind
        self.x, self.y = x, y
        self.rot, self.mirror = rot, mirror
        self.ports, self.bbox, self.spec = ports, bbox, spec
        self.group = self.slot = self.row = None
        self.label = self.sub = None
        self.label_side = spec.label_side
        self.label_offset = spec.label_offset
        self.italic = True
        self.interface = None
        self.marker = None          # (cx, cy, r) once routing is known

    @property
    def clearance_bbox(self):
        """The body grown by this symbol's own keep-out, not a fixed margin."""
        return self.spec.margin_box(self.bbox)

    @property
    def external(self):
        return self.interface is not None

    @property
    def marks_boundary(self):
        return self.interface == 'power'

    def port(self, name):
        if name not in self.ports:
            raise KeyError(f'{self.ref} ({self.kind}) has no port {name!r}; '
                           f'has {sorted(self.ports)}')
        return self.ports[name]


def _transform(offset, rot, mirror):
    dx, dy = offset
    if mirror:
        dx = -dx
    if rot:
        th = math.radians(rot)
        cos, sin = math.cos(th), math.sin(th)
        dx, dy = dx * cos - dy * sin, dx * sin + dy * cos
    return dx, dy


def _bbox_after(bbox, rot, mirror, x, y):
    bx0, by0, bx1, by1 = bbox
    corners = [(bx0, by0), (bx1, by0), (bx0, by1), (bx1, by1)]
    corners = [_transform(c, rot, mirror) for c in corners]
    xs = [x + cx for cx, _ in corners]
    ys = [y + cy for _, cy in corners]
    return (min(xs), min(ys), max(xs), max(ys))


def _natural_pitch(group, netlist, specs, opts):
    """Cell width for a group: its widest body plus one component dimension.

    Deriving it from the group's own contents keeps narrow passives close
    together while leaving switching devices a full cell apart, and because
    every slot of a repeated structure holds the same devices, repeated
    structures still come out evenly spaced.
    """
    widths = []
    for slot in group.slots:
        for item in slot.items:
            spec = specs[netlist.components[item.ref].kind]
            if not spec.is_terminal:
                widths.append(spec.width / G)
    if not widths:
        return opts['slot_pitch']
    return max(2, math.ceil(max(widths) - 1e-6)) + opts['clearance']


def place(plan, netlist, specs):
    """Return {ref: Placed} and the column each group occupies."""
    opts = plan.opts
    cursor = opts['start_col']
    placed = {}
    extents = {}

    for gi, group in enumerate(plan.groups):
        if gi:
            cursor += (group.gap_before if group.gap_before is not None
                       else opts['group_gap'])
        pitch = group.pitch
        if pitch is None:
            pitch = _natural_pitch(group, netlist, specs, opts)

        first = cursor
        for si, slot in enumerate(group.slots):
            gx = first + si * pitch
            for item in slot.items:
                gxi = gx + item.dx
                comp = netlist.components[item.ref]
                spec = specs[comp.kind]
                x = gxi * G
                y = (plan.row_y(item.row) + item.dy) * G
                ports = {p: tuple(round(v, 4) for v in (
                    x + _transform(o, item.rot, item.mirror)[0],
                    y + _transform(o, item.rot, item.mirror)[1]))
                    for p, o in spec.ports.items()}
                obj = Placed(item.ref, comp.kind, x, y, item.rot, item.mirror,
                             ports,
                             _bbox_after(spec.bbox, item.rot, item.mirror, x, y),
                             spec)
                obj.group, obj.slot, obj.row = group.id, si, item.row
                obj.label, obj.sub = comp.label, comp.sub
                obj.italic = comp.italic
                obj.interface = comp.interface
                if item.label_side is not None:
                    obj.label_side = item.label_side
                elif item.rot % 180 and spec.orientation == 'vertical':
                    # laid on its side: a horizontal L/C/R/D is labelled above
                    obj.label_side = 'above'
                    obj.label_offset = max(obj.label_offset, 2.2)
                placed[item.ref] = obj
        last = first + (len(group.slots) - 1) * pitch
        extents[group.id] = (first, last)
        cursor = last

    missing = set(netlist.components) - set(placed)
    if missing:
        raise ValueError(f'plan does not place: {sorted(missing)}')
    return placed, extents


# ------------------------------------------------------------------ checks

def cluster(values, tol=1e-4):
    """Distinct values within a tolerance, as sorted representatives.

    Never round before differencing: quantising to a few decimals and then
    subtracting turns exactly equal spacings into unequal ones.
    """
    reps = []
    for v in sorted(values):
        if not reps or abs(v - reps[-1]) > tol:
            reps.append(v)
    return reps


def check_regularity(placed, classes, tol=1e-4):
    """Equivalent components must share a row and be evenly spaced."""
    problems = []
    for cid, refs in sorted(classes.items()):
        members = [placed[r] for r in refs if r in placed]
        if len(members) < 2:
            continue
        rots = {(m.rot, m.mirror) for m in members}
        if len(rots) > 1:
            problems.append(f'{cid}: differing orientation {sorted(rots)}')
        ys = cluster([m.y for m in members], tol)
        xs = cluster([m.x for m in members], tol)
        if len(ys) > 1 and len(xs) > 1:
            problems.append(f'{cid}: members share neither a row nor a column')
            continue
        varying = xs if len(ys) == 1 else ys
        if len(varying) > 2:
            steps = [b - a for a, b in zip(varying, varying[1:])]
            if max(steps) - min(steps) > tol:
                problems.append(
                    f'{cid}: uneven spacing '
                    f'{[round(s, 4) for s in steps]}')
    return problems
