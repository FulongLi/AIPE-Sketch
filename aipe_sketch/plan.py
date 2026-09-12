"""The logical layout plan: relationships, not coordinates.

A plan says what belongs together, what sits left of what, and which row a
device occupies.  It never contains an x or a y.  The placer turns it into
geometry deterministically, so equivalent topology becomes equivalent
geometry by construction rather than by optimisation.
"""

# Every symbol in the library is exactly 4 G tall, so 4 G is the natural unit
# of visual scale: one component dimension.  Every spacing below is a multiple
# of it, which is what gives the drawing a repeating rhythm.
CELL = 4                 # one component dimension, in grid units
CLEARANCE = CELL         # preferred gap between neighbouring bodies
PITCH = 2 * CELL         # centre-to-centre for adjacent components
GROUP_PITCH = 10         # centre-to-centre across a functional boundary
ANCHOR_PITCH = 9         # around a visually dense anchor such as a transformer

# Named rows.  A leg spans dc_pos..dc_neg, the two devices are one component
# dimension apart, and the switching node sits exactly between them.
ROWS = {
    'dc_pos': 6,
    'high': 8,           # device spans 6..10
    'gate_high': 9,      # gate lead of a high-side device
    'mid': 12,           # switching node, 4 G clear of both devices
    'low': 16,           # device spans 14..18
    'gate_low': 17,
    'dc_neg': 18,
}

# A leg whose midpoint has to carry several take-off corridors needs a taller
# gap: three phase outputs 2 G apart do not fit in a 4 G window.
ROWS_TALL = {
    'dc_pos': 6,
    'high': 8,           # device spans 6..10
    'gate_high': 9,
    'mid': 13,           # midpoint window is 10..16
    'low': 18,           # device spans 16..20
    'gate_low': 19,
    'dc_neg': 20,
}

DEFAULTS = dict(
    clearance=CLEARANCE,  # gap added around the widest body in a group
    leg_pitch=PITCH,      # fallback between legs of one bridge
    slot_pitch=PITCH,     # fallback between slots of a group
    group_gap=GROUP_PITCH,
    start_col=6,
)


class Item:
    """One component in a slot.

    ``row`` is a row name, a pair of names to centre between, or a grid
    value.  ``dx``/``dy`` are fixed grid offsets from the slot; giving every
    member of a repeated structure the same offset keeps them identical.
    """

    __slots__ = ('ref', 'row', 'rot', 'mirror', 'label_side', 'dx', 'dy')

    def __init__(self, ref, row, rot=0, mirror=False, label_side='right',
                 dx=0, dy=0):
        self.ref = ref
        self.row = row
        self.rot = rot
        self.mirror = mirror
        self.label_side = label_side
        self.dx = dx
        self.dy = dy


class Slot:
    """One x column.  Items in a slot share an exact x coordinate."""

    def __init__(self, *items):
        self.items = list(items)


class Group:
    """A functional block: a run of slots with uniform internal pitch."""

    def __init__(self, gid, role, slots, pitch=None, gap_before=None):
        self.id = gid
        self.role = role
        self.slots = list(slots)
        self.pitch = pitch
        self.gap_before = gap_before


class LayoutPlan:
    def __init__(self, groups, rows=None, **opts):
        self.groups = list(groups)
        self.rows = dict(rows or ROWS)
        self.opts = dict(DEFAULTS)
        self.opts.update(opts)

    # -------------------------------------------------------------- helpers
    def row_y(self, row):
        if isinstance(row, (int, float)):
            return row
        if isinstance(row, (tuple, list)):
            return sum(self.row_y(r) for r in row) / len(row)
        return self.rows[row]

    def items(self):
        for group in self.groups:
            for si, slot in enumerate(group.slots):
                for item in slot.items:
                    yield group, si, item

    def describe(self):
        """The relational view -- what the plan asserts, without geometry."""
        return {
            'groups': [
                {'id': g.id, 'role': g.role, 'slots': len(g.slots),
                 'members': [i.ref for s in g.slots for i in s.items]}
                for g in self.groups],
            'constraints': self.constraints(),
        }

    def constraints(self):
        out = []
        for g in self.groups:
            for si, slot in enumerate(g.slots):
                refs = [i.ref for i in slot.items]
                if len(refs) > 1:
                    out.append(f'{" = ".join("x(%s)" % r for r in refs)}')
            if len(g.slots) > 1:
                out.append(f'{g.id}: slots equally spaced')
        rows = {}
        for _, _, item in self.items():
            if isinstance(item.row, str):
                rows.setdefault(item.row, []).append(item.ref)
        for row, refs in sorted(rows.items()):
            if len(refs) > 1:
                out.append(f'{" = ".join("y(%s)" % r for r in refs)}  [{row}]')
        return out


# ------------------------------------------------------------------ builders
def bridge_group(legs, gid='bridge', pitch=None, label_side='right'):
    """One slot per leg: high-side above low-side, identical geometry."""
    slots = []
    for leg in legs:
        slots.append(Slot(Item(leg.high, 'high', label_side=label_side),
                          Item(leg.low, 'low', label_side=label_side)))
    return Group(gid, 'bridge', slots, pitch=pitch)
