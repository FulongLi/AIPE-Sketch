"""Manhattan routing with obstacle awareness.

All wires are axis-aligned.  Routes are ranked straight -> one bend ->
two bends, and any candidate whose segments penetrate a component body is
discarded before ranking (rule 5 / rule 11).
"""

EPS = 1e-6

# Geometric tolerance in millimetres.  Symbol coordinates in the master sheet
# are rounded to three decimals, so exact-grid arithmetic grazes a body by a
# fraction of a micron.  Anything below this is noise: it is a fifth of a
# stroke width (0.2646 mm) and a fiftieth of the coarse grid.
TOL = 0.05


# ---------------------------------------------------------------- geometry
def seg_penetrates(seg, rect, tol=TOL):
    """True if an axis-aligned segment passes through a rectangle's interior.

    Both the depth into the body and the length of the shared run must
    exceed ``tol``, so a wire leaving a pin or running along an edge does
    not register as a collision.
    """
    (x0, y0), (x1, y1) = seg
    rx0, ry0, rx1, ry1 = rect
    if abs(y0 - y1) < TOL:                                  # horizontal
        if not (ry0 + tol < y0 < ry1 - tol):
            return False
        lo, hi = min(x0, x1), max(x0, x1)
        return min(hi, rx1) - max(lo, rx0) > tol
    if abs(x0 - x1) < TOL:                                  # vertical
        if not (rx0 + tol < x0 < rx1 - tol):
            return False
        lo, hi = min(y0, y1), max(y0, y1)
        return min(hi, ry1) - max(lo, ry0) > tol
    raise ValueError('diagonal segment')


def path_segments(points):
    """Consecutive point pairs, dropping runs shorter than the tolerance."""
    out = []
    for a, b in zip(points, points[1:]):
        if abs(b[0] - a[0]) > TOL or abs(b[1] - a[1]) > TOL:
            out.append((a, b))
    return out


def path_clear(points, obstacles):
    for seg in path_segments(points):
        for rect in obstacles:
            if seg_penetrates(seg, rect):
                return False
    return True


def path_length(points):
    return sum(abs(b[0] - a[0]) + abs(b[1] - a[1])
               for a, b in path_segments(points))


def bend_count(points):
    pts = [points[0]]
    for p in points[1:]:
        if p != pts[-1]:
            pts.append(p)
    bends = 0
    for i in range(1, len(pts) - 1):
        ax = abs(pts[i][0] - pts[i - 1][0]) > TOL
        bx = abs(pts[i + 1][0] - pts[i][0]) > TOL
        if ax != bx:
            bends += 1
    return bends


def segments_cross(s1, s2):
    """True if two segments cross at a point interior to both."""
    (a0, a1), (b0, b1) = s1, s2
    a_horiz = abs(a0[1] - a1[1]) < TOL
    b_horiz = abs(b0[1] - b1[1]) < TOL
    if a_horiz == b_horiz:
        return False
    h, v = (s1, s2) if a_horiz else (s2, s1)
    (hx0, hy), (hx1, _) = h
    (vx, vy0), (_, vy1) = v
    return (min(hx0, hx1) + TOL < vx < max(hx0, hx1) - TOL and
            min(vy0, vy1) + TOL < hy < max(vy0, vy1) - TOL)


# ---------------------------------------------------------------- routing
def route_pair(a, b, obstacles, grid, span=None):
    """Best Manhattan route from a to b.  Returns a list of points.

    Endpoints that are within ``TOL`` of being aligned are snapped onto a
    common axis, so the rounding in the source symbol coordinates cannot
    turn a straight run into a sub-micron dog-leg.
    """
    if EPS < abs(a[1] - b[1]) < TOL:
        b = (b[0], a[1])
    elif EPS < abs(a[0] - b[0]) < TOL:
        b = (a[0], b[1])

    candidates = []

    if abs(a[0] - b[0]) < EPS or abs(a[1] - b[1]) < EPS:
        candidates.append([a, b])                                   # straight

    candidates.append([a, (b[0], a[1]), b])                         # one bend
    candidates.append([a, (a[0], b[1]), b])

    if span is None:
        span = 8
    lo, hi = sorted((a[0], b[0]))
    for k in range(-span, span + 1):                                # two bends
        mx = round((lo + hi) / 2 / grid + k) * grid
        candidates.append([a, (mx, a[1]), (mx, b[1]), b])
    lo, hi = sorted((a[1], b[1]))
    for k in range(-span, span + 1):
        my = round((lo + hi) / 2 / grid + k) * grid
        candidates.append([a, (a[0], my), (b[0], my), b])

    best, best_key = None, None
    for pts in candidates:
        if not path_clear(pts, obstacles):
            continue
        key = (bend_count(pts), path_length(pts))
        if best_key is None or key < best_key:
            best, best_key = pts, key
    return best or [a, (b[0], a[1]), b]


def route_trunk(terminals, orientation, position, obstacles):
    """Bus route: one trunk line with a perpendicular stub per terminal.

    This is how an engineer draws a rail, and it keeps parallel nets
    visually parallel (rule 5) with one bend per terminal at most.
    """
    paths = []
    if orientation == 'h':
        xs = [t[0] for t in terminals]
        paths.append([(min(xs), position), (max(xs), position)])
        for t in terminals:
            if abs(t[1] - position) > TOL:
                paths.append([t, (t[0], position)])
    else:
        ys = [t[1] for t in terminals]
        paths.append([(position, min(ys)), (position, max(ys))])
        for t in terminals:
            if abs(t[0] - position) > TOL:
                paths.append([t, (position, t[1])])
    return paths


def choose_trunk(terminals, orientation, obstacles, grid, limit=14):
    """Pick the trunk line that minimises stub length and hits no bodies."""
    if orientation == 'h':
        base = sum(t[1] for t in terminals) / len(terminals)
        fixed = [t[1] for t in terminals]
    else:
        base = sum(t[0] for t in terminals) / len(terminals)
        fixed = [t[0] for t in terminals]

    best, best_key = None, None
    for k in range(-limit, limit + 1):
        pos = round(base / grid + k) * grid
        paths = route_trunk(terminals, orientation, pos, obstacles)
        blocked = sum(0 if path_clear(p, obstacles) else 1 for p in paths)
        stub = sum(abs(f - pos) for f in fixed)
        key = (blocked, stub)
        if best_key is None or key < best_key:
            best, best_key = pos, key
    return best


# ---------------------------------------------------------------- junctions
def junction_points(paths, terminals=()):
    """Points where three or more wire ends of one net meet.

    A segment ending at a point counts once; a segment passing through it
    counts twice.  Degree >= 3 is a junction; degree 2 is just a corner.
    A component terminal at the point contributes one more branch -- the
    device lead itself -- so a rail ending on a pin that also has a stub is
    correctly marked as a node.

    Wires of different nets crossing never reach this function, so a visual
    crossing never becomes an electrical node (rule 1).
    """
    # points are clustered within TOL so that coordinates differing only by
    # the source file's rounding are treated as the same node
    reps = []
    degree = {}

    def canon(pt):
        for r in reps:
            if abs(r[0] - pt[0]) < TOL and abs(r[1] - pt[1]) < TOL:
                return r
        r = (round(pt[0], 4), round(pt[1], 4))
        reps.append(r)
        return r

    def bump(pt, amount):
        key = canon(pt)
        degree[key] = degree.get(key, 0) + amount

    segs = [s for p in paths for s in path_segments(p)]
    # candidate nodes are every wire end *and* every component terminal: a
    # device tapping the middle of a rail is a terminal, not a wire end
    candidates = []
    for (a, b) in segs:
        candidates.append(canon(a))
        candidates.append(canon(b))
    for t in terminals:
        candidates.append(canon(t))
    candidates = list(dict.fromkeys(candidates))

    for (a, b) in segs:
        ca, cb = canon(a), canon(b)
        bump(a, 1)
        bump(b, 1)
        for pt in candidates:
            if pt in (ca, cb):
                continue
            x, y = pt
            if abs(a[1] - b[1]) < TOL and abs(y - a[1]) < TOL:
                if min(a[0], b[0]) + TOL < x < max(a[0], b[0]) - TOL:
                    bump(pt, 2)
            elif abs(a[0] - b[0]) < TOL and abs(x - a[0]) < TOL:
                if min(a[1], b[1]) + TOL < y < max(a[1], b[1]) - TOL:
                    bump(pt, 2)

    for t in terminals:
        bump(t, 1)

    return [pt for pt, deg in degree.items() if deg >= 3]
