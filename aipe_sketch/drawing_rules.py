"""Metrics for the general drawing rules.

Every symbol in the library is exactly one CELL tall, so CELL is the unit of
visual scale: clearances, local wire lengths and component spacing are all
measured against it.  These functions only measure; repair lives elsewhere.
"""
from statistics import mean, pstdev

from . import router
from .router import TOL
from .pins import COARSE as G

CELL = 4 * G                 # one component dimension, millimetres
LONG_RUN = 2 * CELL          # beyond this a wire is a deliberate long haul
CONTROL_PORTS = ('g',)       # gate leads are not part of the power path


def _segments(paths):
    return [(net, seg) for net, ps in paths.items()
            for pts in ps for seg in router.path_segments(pts)]


def _length(seg):
    return abs(seg[1][0] - seg[0][0]) + abs(seg[1][1] - seg[0][1])


def _same(a, b):
    return abs(a[0] - b[0]) < TOL and abs(a[1] - b[1]) < TOL


# ------------------------------------------------------------------ rule 3
def clearance(bodies):
    """Gap between neighbouring bodies against the one-cell target.

    Only nearest neighbours sharing a band are compared; distant components
    are separated by whitespace on purpose.
    """
    penalty, tight = 0.0, 0
    for axis in (0, 1):
        other = 1 - axis
        for a in bodies:
            best = None
            for b in bodies:
                if a is b:
                    continue
                lo_a, hi_a = a.bbox[other], a.bbox[other + 2]
                lo_b, hi_b = b.bbox[other], b.bbox[other + 2]
                if min(hi_a, hi_b) - max(lo_a, lo_b) <= TOL:
                    continue                      # not in the same band
                gap = b.bbox[axis] - a.bbox[axis + 2]
                if gap <= TOL:
                    continue                      # behind or touching
                if best is None or gap < best:
                    best = gap
            if best is None or best > LONG_RUN:
                continue
            if best < 0.75 * CELL:
                tight += 1
            penalty += ((best - CELL) / CELL) ** 2
    return round(penalty, 4), tight


# ------------------------------------------------------------------ rule 22
def rhythm(paths, tol=0.15):
    """How many distinct local length scales the drawing uses.

    Rule 22 asks for a small number of repeated spacing scales rather than
    arbitrary distances, so this counts the clusters of local run length --
    it does not demand any particular length.  Rails and buses are excluded:
    their length is set by the floorplan, not by local rhythm.
    """
    lengths = []
    for _, seg in _segments(paths):
        length = _length(seg)
        if TOL < length <= LONG_RUN:
            lengths.append(length / CELL)
    if not lengths:
        return 0.0, []
    scales = []
    for value in sorted(lengths):
        if not scales or value - scales[-1][-1] > tol:
            scales.append([value])
        else:
            scales[-1].append(value)
    modes = [round(mean(group), 3) for group in scales]
    # a handful of repeated scales is the goal; beyond that it reads arbitrary
    # The hard requirement is few scales.  Four is still few: a converter
    # legitimately has gate stubs, rail stubs, leg midpoints and inter-stage
    # runs, each a different purpose.  Consistency *within* a role is
    # measured exactly by local_consistency and wire_uniformity, so this
    # only catches genuinely arbitrary distances.
    excess = max(0, len(modes) - 4)
    dominant = max(scales, key=len)
    drift = abs(mean(dominant) - 1.0)
    return round(excess + 0.3 * drift, 4), modes


# ------------------------------------------------------------------ rule 23
def local_consistency(placed, paths):
    """Spread of the wire lengths leaving one component's ports.

    A device with a very short wire on one side and a very long one on the
    other reads as irregular even when both are legal.

    Only the power path is compared: rails are long hauls set by the
    floorplan, and a gate stub is squeezed by the leg pitch, so neither says
    anything about local regularity.
    """
    segs = [seg for _, seg in _segments(paths)]
    penalty = 0.0
    worst = []
    for ref, part in placed.items():
        if part.spec.is_terminal:
            continue
        lengths = []
        for port, pt in part.ports.items():
            if port in CONTROL_PORTS:
                continue
            attached = [s for s in segs
                        if (_same(s[0], pt) or _same(s[1], pt))
                        and _length(s) <= LONG_RUN]
            if attached:
                lengths.append(min(_length(s) for s in attached))
        if len(lengths) < 2:
            continue
        lo, hi = min(lengths), max(lengths)
        if lo < TOL:
            continue
        spread = (hi - lo) / CELL
        if spread > 1.0:
            worst.append((ref, round(lo / CELL, 2), round(hi / CELL, 2)))
        penalty += spread ** 2
    return round(penalty, 4), worst


# ------------------------------------------------------------------ rule 20
def rail_straightness(paths, rails):
    """A DC rail must be one straight run, with no vertical steps."""
    faults = []
    for net in rails:
        if not net or net not in paths:
            continue
        horizontals = [s for s in
                       (seg for pts in paths[net]
                        for seg in router.path_segments(pts))
                       if abs(s[0][1] - s[1][1]) < TOL]
        levels = {round(s[0][1], 3) for s in horizontals}
        if len(levels) > 1:
            faults.append(f'rail {net} runs at {len(levels)} different heights')
    return faults


# ------------------------------------------------------------------ rule 7/8
def midpoint_directness(paths, legs):
    """A switching-node take-off must leave straight, with no detour."""
    faults = []
    for leg in legs:
        net = leg['mid']
        if net not in paths:
            continue
        for pts in paths[net]:
            if router.bend_count(pts) > 0:
                faults.append(
                    f'switching node {net} leaves with '
                    f'{router.bend_count(pts)} bend(s)')
    return faults


# ------------------------------------------------------------------ rule 25
def floating_ends(placed, paths):
    """Every wire end must be a port, a corner, or a tee onto another wire."""
    ports = [pt for p in placed.values() for pt in p.ports.values()]
    segs = [seg for _, seg in _segments(paths)]
    loose = []
    for net, ps in paths.items():
        for pts in ps:
            for end in (pts[0], pts[-1]):
                if any(_same(end, pt) for pt in ports):
                    continue
                shared = sum(1 for s in segs
                             if _same(s[0], end) or _same(s[1], end))
                if shared >= 2:
                    continue                       # a corner or a junction
                if any(_on_interior(end, s) for s in segs):
                    continue                       # a tee onto a run
                loose.append(f'net {net} ends free at '
                             f'({end[0]:.2f}, {end[1]:.2f})')
    return loose


def _on_interior(pt, seg):
    (x0, y0), (x1, y1) = seg
    if abs(y0 - y1) < TOL:
        return (abs(pt[1] - y0) < TOL and
                min(x0, x1) + TOL < pt[0] < max(x0, x1) - TOL)
    if abs(x0 - x1) < TOL:
        return (abs(pt[0] - x0) < TOL and
                min(y0, y1) + TOL < pt[1] < max(y0, y1) - TOL)
    return False


# ------------------------------------------------------------------ rule 6/15
def label_side_consistency(placed, classes):
    """Equivalent components must carry their labels on the same side."""
    faults = []
    for cid, refs in sorted(classes.items()):
        sides = {placed[r].label_side for r in refs if r in placed}
        if len(sides) > 1:
            faults.append(f'{cid}: labels on {sorted(sides)}')
    return faults


# ------------------------------------------------------------------ rule 21
def compactness(bodies, paths):
    """Ink-and-cell coverage of the drawing's bounding box."""
    if not bodies:
        return 1.0, 0.0
    xs = [v for p in bodies for v in (p.bbox[0], p.bbox[2])]
    ys = [v for p in bodies for v in (p.bbox[1], p.bbox[3])]
    for _, seg in _segments(paths):
        xs += [seg[0][0], seg[1][0]]
        ys += [seg[0][1], seg[1][1]]
    area = max(TOL, (max(xs) - min(xs)) * (max(ys) - min(ys)))
    cells = sum((p.spec.width + CELL) * (p.spec.height + CELL)
                for p in bodies)
    aspect = (max(xs) - min(xs)) / max(TOL, max(ys) - min(ys))
    return round(cells / area, 4), round(aspect, 3)


# ------------------------------------------------------------------ rule 26
def occupancy(bodies, paths, cell=None):
    """Grid the drawing and find the largest wholly empty rectangle.

    Reported as a fraction of the drawing area.  Converters legitimately
    enclose empty loops, so this is information, not a verdict.
    """
    cell = cell or CELL
    xs, ys = [], []
    for p in bodies:
        xs += [p.bbox[0], p.bbox[2]]
        ys += [p.bbox[1], p.bbox[3]]
    for _, seg in _segments(paths):
        xs += [seg[0][0], seg[1][0]]
        ys += [seg[0][1], seg[1][1]]
    if not xs:
        return 0.0
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    cols = max(1, int((x1 - x0) / cell) + 1)
    rows = max(1, int((y1 - y0) / cell) + 1)
    grid = [[0] * cols for _ in range(rows)]

    def mark(px, py):
        c = min(cols - 1, max(0, int((px - x0) / cell)))
        r = min(rows - 1, max(0, int((py - y0) / cell)))
        grid[r][c] = 1

    for p in bodies:
        bx0, by0, bx1, by1 = p.bbox
        gy = by0
        while gy <= by1 + TOL:
            gx = bx0
            while gx <= bx1 + TOL:
                mark(gx, gy)
                gx += cell / 2
            gy += cell / 2
    for _, seg in _segments(paths):
        steps = max(1, int(_length(seg) / (cell / 2)))
        for i in range(steps + 1):
            t = i / steps
            mark(seg[0][0] + t * (seg[1][0] - seg[0][0]),
                 seg[0][1] + t * (seg[1][1] - seg[0][1]))

    # largest all-zero rectangle, histogram method
    best = 0
    heights = [0] * cols
    for row in grid:
        for c in range(cols):
            heights[c] = 0 if row[c] else heights[c] + 1
        stack = []
        for c in range(cols + 1):
            h = heights[c] if c < cols else 0
            start = c
            while stack and stack[-1][1] >= h:
                s, sh = stack.pop()
                best = max(best, sh * (c - s))
                start = s
            stack.append((start, h))
    return round(best / max(1, rows * cols), 4)


def checklist(raw, netlist, placed, paths, structure, groups, notes=()):
    """The whole-drawing questions, answered from the measurements.

    ``groups`` is the plan's declared left-to-right order, which is what
    power-flow direction should be judged against.
    """
    def ok(flag, detail=''):
        return ('PASS' if flag else 'CHECK', detail)

    kinds = {ref: p.kind for ref, p in placed.items()}
    terminals = [r for r, k in kinds.items() if k == 'terminal']
    # a terminal sharing a net with a gate lead is a control port, not an
    # input or output of the power stage
    gate_ports = set()
    for net, members in netlist.nets.items():
        if any(port in CONTROL_PORTS for _, port in members):
            gate_ports.update(r for r, _ in members if kinds.get(r) == 'terminal')
    power_ports = [r for r in terminals if r not in gate_ports]
    sources = [r for r, k in kinds.items()
               if k in ('vsource', 'isource', 'battery')]
    has_tx = any(k == 'transformer' for k in kinds.values())
    labels = {(p.label, p.sub) for p in placed.values() if p.label}
    labels |= {(n['text_op']['text'], n['text_op']['sub']) for n in notes}
    named = {f'{t}{s or ""}' for t, s in labels}

    order, left_to_right = [], True
    previous = None
    for gid, refs in groups:
        present = [placed[r].x for r in refs if r in placed]
        if not present:
            continue
        order.append(gid)
        here = min(present)
        if previous is not None and here < previous - TOL:
            left_to_right = False
        previous = here

    tx_note, tx_ok = '', True
    if has_tx:
        ref = next(r for r, k in kinds.items() if k == 'transformer')
        segs = [seg for _, seg in _segments(paths)]
        nearest, horizontal = [], True
        for pt in placed[ref].ports.values():
            attached = [s for s in segs if _same(s[0], pt) or _same(s[1], pt)]
            if not attached:
                continue
            run = min(attached, key=_length)
            nearest.append(_length(run) / CELL)
            if abs(run[0][1] - run[1][1]) >= TOL:
                horizontal = False       # rule 24: enter from the side
        closest = round(min(nearest), 2) if nearest else 0.0
        furthest = round(max(nearest), 2) if nearest else 0.0
        tx_ok = horizontal and closest <= 2.0
        tx_note = (f'entries {"horizontal" if horizontal else "NOT horizontal"}, '
                   f'nearest {closest} / furthest {furthest} cells')

    return {
        '1 compact': ok(raw['fill'] >= 0.4 and raw['aspect'] <= 6,
                        f"fill {raw['fill']}, aspect {raw['aspect']}"),
        '2 equivalent wire lengths similar': ok(
            raw['wire_uniformity'] < 0.5, f"dispersion {raw['wire_uniformity']}"),
        '3 repeated components equally spaced': ok(
            raw['spacing_variance'] == 0 and raw['symmetry'] == 0),
        '4 half-bridge midpoints straight': ok(raw['midpoint_detour'] == 0),
        '5 bridge midpoints direct and symmetric': ok(
            raw['midpoint_detour'] == 0 and raw['symmetry'] == 0),
        '6 external ports terminated': ok(
            bool(terminals),
            f'{len(terminals)} open circle(s): {len(power_ports)} power, '
            f'{len(gate_ports)} control'),
        '7 sources drawn conventionally': ok(
            all(placed[r].spec.decor for r in sources) if sources else True,
            f'{len(sources)} source(s)'),
        '8 Vin and Vout identifiable': (
            ok('Vin' in named and ('Vout' in named or 'A' in named),
               f'{sorted(n for n in named if n.startswith("V") or len(n) == 1)}')
            if power_ports else
            ('N/A', 'differential output, no single-ended node')),
        '9 labels consistently positioned': ok(raw['label_side'] == 0),
        '10 transformer compactly connected': (
            ok(tx_ok, tx_note) if has_tx else ('N/A', 'no transformer')),
        '11 no unnecessary bends': ok(raw['bend'] == 0, f"{raw['bend']} bend(s)"),
        '12 no abnormally long local wires': ok(
            raw['local_spread'] < 1.0, f"spread {raw['local_spread']}"),
        '13 labels close, no overlap': ok(raw['label_overlap'] == 0),
        '14 power path reads left to right': ok(left_to_right,
                                                ' -> '.join(order)),
        '15 no unexplained empty region': ok(
            raw['largest_void'] <= 0.25, f"largest void {raw['largest_void']}"),
    }
