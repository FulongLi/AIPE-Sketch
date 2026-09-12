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
                 'margin_override', 'label_side_local', 'label_side_flat', 'label_keepout')

    def __init__(self, ref, kind, x, y, rot, mirror, ports, bbox, spec):
        self.ref, self.kind = ref, kind
        self.x, self.y = x, y
        self.rot, self.mirror = rot, mirror
        self.ports, self.bbox, self.spec = ports, bbox, spec
        self.group = self.slot = self.row = None
        self.label = self.sub = None
        # the registry's preference, in the symbol's own frame; the label
        # engine rotates it with the part
        self.label_side_local = spec.label_side
        self.label_side_flat = spec.label_side_flat
        self.label_side = spec.label_side      # filled in once placed
        self.label_offset = spec.label_offset
        self.italic = True
        self.interface = None
        self.marker = None          # (cx, cy, r) once routing is known
        self.label_keepout = None
        self.margin_override = None  # tightened keep-out on chain-facing sides

    @property
    def body_bbox(self):
        return _bbox_after(self.spec.bbox, self.rot, self.mirror, self.x, self.y)

    @property
    def visual_bbox(self):
        box = self.clearance_bbox
        if self.label_keepout:
            label = self.label_keepout
            return (min(box[0], label[0]), min(box[1], label[1]),
                    max(box[2], label[2]), max(box[3], label[3]))
        return box

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


def _visual_half_width(slot, netlist, specs, side, compact=False, text=None):
    """Provisional visual cell extent, before final collision-aware labelling.

    Facing margins share the relationship gap rather than accumulating on top
    of it. Horizontal labels reserve their projected width; the global label
    solver may subsequently choose a different side.
    """
    from .labels import text_size
    from .presentation import text_for
    from .config import LABEL_PAD_X_MM, CHAIN_FACING_MARGIN_G
    half = _slot_half_width(slot, netlist, specs)
    extent = half
    for ref, spec, item in _bodies(slot, netlist, specs):
        margin = CHAIN_FACING_MARGIN_G if compact else spec.visual_margin[side]
        extent = max(extent, half + margin)
        style = (text or {}).get(ref, text_for(netlist.components[ref]))
        if style.label and (item.rot % 180 or spec.label_side in ('above', 'below')):
            width, _ = text_size(style.label, style.sub)
            extent = max(extent, (width / 2 + LABEL_PAD_X_MM) / G)
    return extent


def _visual_distance(left, right, netlist, specs, gap, text=None):
    compact = _linked_passives(left, right, netlist, specs)
    a = _slot_half_width(left, netlist, specs)
    b = _slot_half_width(right, netlist, specs)
    va = _visual_half_width(left, netlist, specs, 'right', compact, text)
    vb = _visual_half_width(right, netlist, specs, 'left', compact, text)
    # A gap is an edge-to-edge budget, not extra padding outside two cells.
    return va + vb + max(0, gap - (va - a) - (vb - b))


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
    return any(_series_link(netlist, specs, a, b)
               for a, _, _ in left for b, _, _ in right)


def _series_link(netlist, specs, a, b):
    """True when a joins b through a genuine two-terminal net.

    Merely sharing a net is not enough: a source and its DC-link capacitor
    share both rails but sit in parallel, and packing them like a series
    chain is wrong.
    """
    from .plan import CHAIN_NEUTRAL
    shared = {n for n, _ in netlist.ports_of(a)} & \
             {n for n, _ in netlist.ports_of(b)}
    for net in shared:
        real = [r for r, _ in netlist.nets[net]
                if r in netlist.components
                and specs[netlist.components[r].kind].role
                not in CHAIN_NEUTRAL]
        if len(real) == 2:
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
    # consecutive slots must be joined in series, not merely share a net
    for left, right in zip(refs, refs[1:]):
        if not any(_series_link(netlist, specs, a, b)
                   for a in left for b in right):
            return False
    return True


def _shared_nets(netlist, refs):
    sets = [{n for n, _ in netlist.ports_of(r)} for r in refs]
    return set.intersection(*sets) if sets else set()


def _is_parallel_block(group, netlist, specs):
    """True when every slot holds shunt parts across the same node pair.

    Cout || Rload is one visual block, and so is any other parallel shunt
    group: same top rail, same bottom rail, packed close together.
    """
    from .plan import CHAIN_NEUTRAL
    members = []
    for slot in group.slots:
        bodies = _chain_bodies(slot, netlist, specs)
        if len(bodies) != 1:
            return False
        members.append(bodies[0][0])
    if len(members) < 2:
        return False
    if any(specs[netlist.components[r].kind].role in CHAIN_NEUTRAL
           for r in members):
        return False
    shared = _shared_nets(netlist, members)
    return len(shared) >= 2


def _parallel_across(left_group, right_group, netlist, specs):
    """True when the facing slots hold parts shunted across the same pair."""
    left = _chain_bodies(left_group.slots[-1], netlist, specs)
    right = _chain_bodies(right_group.slots[0], netlist, specs)
    if not left or not right:
        return False
    refs = [r for r, _, _ in left] + [r for r, _, _ in right]
    return len(_shared_nets(netlist, refs)) >= 2


def pair_gap(left_slot, right_slot, netlist, specs, opts, default=None):
    """The gap two neighbouring slots should keep, from their relationship.

    Decided per adjacent pair rather than per group: a group may hold a
    series element feeding a parallel block, and classifying the whole group
    gives neither of them the right spacing.  This is the one place the
    spacing vocabulary is chosen.
    """
    left = _chain_bodies(left_slot, netlist, specs)
    right = _chain_bodies(right_slot, netlist, specs)
    if not left or not right:
        return default if default is not None else opts['gap_adjacent']
    if any(_series_link(netlist, specs, a, b)
           for a, _, _ in left for b, _, _ in right):
        return opts['gap_series']
    refs = [r for r, _, _ in left] + [r for r, _, _ in right]
    shared = _shared_nets(netlist, refs)
    if len(shared) >= 2:
        return opts['gap_parallel']            # shunted across one node pair
    if shared:
        return opts['gap_adjacent']            # directly connected
    return default if default is not None else opts['gap_adjacent']


def _natural_pitch(group, netlist, specs, opts):
    """Uniform centre-to-centre pitch, for repeated structures.

    A bridge's legs must stay evenly spaced, so they keep one pitch rather
    than being spaced pairwise.
    """
    widths = [_drawn_width(spec, item)
              for slot in group.slots
              for _, spec, item in _bodies(slot, netlist, specs)]
    if not widths:
        return opts['slot_pitch']
    return max(2, math.ceil(max(widths) - 1e-6)) + opts['gap_bridge']


def place(plan, netlist, specs, text=None):
    """Return {ref: Placed} and the column each group occupies."""
    opts = plan.opts
    cursor = opts['start_col']
    placed = {}
    extents = {}

    previous_half = 0.0
    previous_group = None
    for gi, group in enumerate(plan.groups):
        if gi:
            # An electrical relationship crossing a functional boundary
            # overrides the boundary: directly connected components stay
            # close even when they belong to different blocks.
            gap = (group.gap_before if group.gap_before is not None
                   else pair_gap(previous_group.slots[-1], group.slots[0],
                                 netlist, specs, opts,
                                 default=opts['group_gap']))
            # measured edge to edge, so the gap means the same thing whatever
            # sits on either side of the boundary
            # rounded up so the boundary lands on the grid and the gap is
            # never tighter than asked for
            cursor += math.ceil(_visual_distance(previous_group.slots[-1],
                                                 group.slots[0], netlist, specs, gap, text))
        pitch = group.pitch
        if pitch is None:
            pitch = _natural_pitch(group, netlist, specs, opts)

        # A repeated structure keeps one pitch so its members stay evenly
        # spaced.  Everything else is spaced pairwise, by relationship.
        uniform = group.role == 'bridge'
        columns, at = [], cursor
        for si, slot in enumerate(group.slots):
            if si == 0:
                columns.append(at)
            elif uniform:
                at = cursor + si * pitch
                columns.append(at)
            else:
                gap = pair_gap(group.slots[si - 1], slot,
                               netlist, specs, opts)
                at = math.ceil(at + _visual_distance(group.slots[si - 1], slot,
                                                    netlist, specs, gap, text))
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
                if item.align_port:
                    y -= _transform(spec.ports[item.align_port], item.rot, item.mirror)[1]
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
                    obj.label_side_local = item.label_side
                    obj.label_side_flat = item.label_side
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


from .config import CHAIN_FACING_MARGIN_G as CHAIN_MARGIN


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
                            netlist, specs) or \
                _parallel_across(previous, group, netlist, specs):
            _relax(_slot_parts(previous.slots[-1]),
                   _slot_parts(group.slots[0]))

    for group in plan.groups:
        if not (_is_series_chain(group, netlist, specs)
                or _is_parallel_block(group, netlist, specs)):
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
