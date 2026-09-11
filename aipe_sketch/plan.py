"""The logical layout plan: relationships, not coordinates.

A plan says what belongs together, what sits left of what, and which row a
device occupies.  It never contains an x or a y.  The placer turns it into
geometry deterministically, so equivalent topology becomes equivalent
geometry by construction rather than by optimisation.
"""

# Named rows, in grid units.  A converter leg spans dc_pos..dc_neg with the
# switching node exactly centred between the two devices.
ROWS = {
    'dc_pos': 8,
    'high': 10,          # centre of the high-side device
    'gate_high': 11,     # gate lead of a high-side device
    'mid': 16,           # switching node
    'low': 22,           # centre of the low-side device
    'gate_low': 23,      # gate lead of a low-side device
    'dc_neg': 24,
}

DEFAULTS = dict(
    leg_pitch=8,         # between legs of one bridge
    slot_pitch=6,        # between slots of a non-bridge group
    group_gap=7,         # whitespace between functional groups
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
