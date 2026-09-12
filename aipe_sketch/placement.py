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
                 'italic', 'interface', 'label_offset', 'marker',
                 'margin_override')

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
        self.margin_override = None  # tightened keep-out on chain-facing sides

    @property
    def clearance_bbox(self):
        """The body grown by its keep-out.

        A component in a series passive chain carries a reduced keep-out on
        the side that faces its neighbour, so the chain can close up without
        shrinking clearance anywhere else.
        """
        if not self.margin_override:
            return self.spec.margin_box(self.bbox)
        margin = dict(self.spec.visual_margin)
        margin.update(self.margin_override)
        x0, y0, x1, y1 = self.bbox
        return (x0 - margin['left'] * G, y0 - margin['top'] * G,
                x1 + margin['right'] * G, y1 + margin['bottom'] * G)

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


def _bodies(slot, netlist, specs):
    out = []
    for item in slot.items:
        spec = specs[netlist.components[item.ref].kind]
        if not spec.is_terminal:
            out.append((item.ref, spec, item))
    return out


def _chain_bodies(slot, netlist, specs):
    """Slot members that count towards the power path.

    A ground glyph riding in the same slot is neutral -- it should not stop
    the surrounding components forming a chain.
    """
    from .plan import CHAIN_NEUTRAL
    return [(ref, spec, item)
            for ref, spec, item in _bodies(slot, netlist, specs)
            if spec.role not in CHAIN_NEUTRAL]


def _drawn_width(spec, item):
    """Footprint across the row, which is the height once laid on its side."""
    return (spec.height if item.rot % 180 else spec.width) / G


def _slot_half_width(slot, netlist, specs):
    bodies = _bodies(slot, netlist, specs)
    if not bodies:
        return 0.0
    return max(_drawn_width(spec, item) for _, spec, item in bodies) / 2.0


def _linked_passives(left_slot, right_slot, netlist, specs):
    """True when two slots hold passives on one shared series path.

    Used across a functional boundary as well as inside a group: a resonant
    tank running into a transformer is one continuous chain even though the
    tank and the transformer are different functional blocks.
    """
    from .plan import CHAIN_ROLES
    left = _chain_bodies(left_slot, netlist, specs)
    right = _chain_bodies(right_slot, netlist, specs)
    if not left or not right:
        return False
    if any(spec.role not in CHAIN_ROLES for _, spec, _ in left):
        return False
    if any(spec.role not in CHAIN_ROLES for _, spec, _ in right):
        return False
    for a, _, _ in left:
        for b, _, _ in right:
            if set(n for n, _ in netlist.ports_of(a)) & \
                    set(n for n, _ in netlist.ports_of(b)):
                return True
    return False


def _is_series_chain(group, netlist, specs):
    """True when the group is a run of passives on one series path.

    Such a chain -- Cr, Lr, then the transformer -- should read as a single
    continuous run rather than as separate components sharing a row.
    """
    from .plan import CHAIN_ROLES
    if len(group.slots) < 2:
        return False
    refs = []
    for slot in group.slots:
        bodies = _chain_bodies(slot, netlist, specs)
        if not bodies:
            return False
        for ref, spec, _ in bodies:
            if spec.role not in CHAIN_ROLES:
                return False
        refs.append([ref for ref, _, _ in bodies])
    # consecutive slots must actually be wired to each other
    for left, right in zip(refs, refs[1:]):
        shared = False
        for a in left:
            for b in right:
                if set(n for n, _ in netlist.ports_of(a)) & \
                        set(n for n, _ in netlist.ports_of(b)):
                    shared = True
        if not shared:
            return False
    return True


def _natural_pitch(group, netlist, specs, opts):
    """Centre-to-centre for a group: its widest body plus the right gap.

    The gap is chosen by what the group is -- a bridge, a series passive
    chain, or ordinary neighbours -- so an inductor does not inherit the
    spacing of a switching leg merely because its cell is large.
    """
    widths = [_drawn_width(spec, item)
              for slot in group.slots
              for _, spec, item in _bodies(slot, netlist, specs)]
    if not widths:
        return opts['slot_pitch']
    if group.role == 'bridge':
        gap = opts['gap_bridge']
    elif _is_series_chain(group, netlist, specs):
        gap = opts['gap_series']
    else:
        gap = opts['gap_adjacent']
    return max(2, math.ceil(max(widths) - 1e-6)) + gap


def place(plan, netlist, specs):
    """Return {ref: Placed} and the column each group occupies."""
    opts = plan.opts
    cursor = opts['start_col']
    placed = {}
    extents = {}

    previous_half = 0.0
    previous_group = None
    for gi, group in enumerate(plan.groups):
        if gi:
            if group.gap_before is not None:
                gap = group.gap_before
            elif _linked_passives(previous_group.slots[-1], group.slots[0],
                                  netlist, specs):
                # the chain continues across the boundary, so it keeps
                # chain spacing rather than being pushed apart
                gap = opts['gap_series']
            else:
                gap = opts['group_gap']
            # measured edge to edge, so the gap means the same thing whatever
            # sits on either side of the boundary
            # rounded up so the boundary lands on the grid and the gap is
            # never tighter than asked for
            cursor += math.ceil(previous_half + gap + _slot_half_width(
                group.slots[0], netlist, specs))
        pitch = group.pitch
        if pitch is None:
            pitch = _natural_pitch(group, netlist, specs, opts)

        # A repeated structure keeps one pitch so its members stay evenly
        # spaced.  A series chain of differing widths instead keeps one
        # *gap*, which is what makes it read as a single continuous run.
        chain = _is_series_chain(group, netlist, specs)
        gap = opts['gap_series'] if chain else None
        columns, at = [], cursor
        for si, slot in enumerate(group.slots):
            if si == 0:
                columns.append(at)
            elif chain:
                at = math.ceil(at + _slot_half_width(group.slots[si - 1],
                                                     netlist, specs)
                               + gap
                               + _slot_half_width(slot, netlist, specs))
                columns.append(at)
            else:
                at = cursor + si * pitch
                columns.append(at)

        first = cursor
        for si, slot in enumerate(group.slots):
            gx = columns[si]
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
        last = columns[-1]
        extents[group.id] = (first, last)
        cursor = last
        previous_half = _slot_half_width(group.slots[-1], netlist, specs)
        previous_group = group

    missing = set(netlist.components) - set(placed)
    if missing:
        raise ValueError(f'plan does not place: {sorted(missing)}')
    relax_series_margins(plan, placed, netlist, specs)
    return placed, extents


CHAIN_MARGIN = 0.5          # grid units on a side that faces a chain neighbour


def relax_series_margins(plan, placed, netlist, specs):
    """Tighten the keep-out between neighbours on one series passive path.

    Only the facing sides are reduced; top, bottom and the outward side keep
    their normal clearance, so the chain closes up without loosening
    anything else.
    """
    from .plan import CHAIN_ROLES

    def _relax(left_parts, right_parts):
        for left in left_parts:
            for right in right_parts:
                if (min(left.bbox[3], right.bbox[3])
                        - max(left.bbox[1], right.bbox[1])) <= 0:
                    continue
                if left.spec.role not in CHAIN_ROLES or \
                        right.spec.role not in CHAIN_ROLES:
                    continue
                left.margin_override = dict(left.margin_override or {},
                                            right=CHAIN_MARGIN)
                right.margin_override = dict(right.margin_override or {},
                                             left=CHAIN_MARGIN)

    def _slot_parts(slot):
        return [placed[ref] for ref, _, _ in _bodies(slot, netlist, specs)
                if ref in placed]

    for previous, group in zip(plan.groups, plan.groups[1:]):
        if _linked_passives(previous.slots[-1], group.slots[0],
                            netlist, specs):
            _relax(_slot_parts(previous.slots[-1]),
                   _slot_parts(group.slots[0]))

    for group in plan.groups:
        if not _is_series_chain(group, netlist, specs):
            continue
        rows = []
        for slot in group.slots:
            rows.append([placed[ref] for ref, _, _ in
                         _bodies(slot, netlist, specs) if ref in placed])
        for left_slot, right_slot in zip(rows, rows[1:]):
            _relax(left_slot, right_slot)


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
