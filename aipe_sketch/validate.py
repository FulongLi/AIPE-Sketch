"""Read connectivity back out of the drawn geometry and compare it to the
netlist.

This is the safety net for the whole pipeline.  It ignores net names and the
router's intentions: it looks only at where wires actually ended up and which
ports they actually touch.  A crossing is deliberately *not* a connection, so
this also proves that crossings never became nodes.
"""
from .router import TOL


class _Union:
    def __init__(self):
        self.parent = {}

    def find(self, a):
        self.parent.setdefault(a, a)
        while self.parent[a] != a:
            self.parent[a] = self.parent[self.parent[a]]
            a = self.parent[a]
        return a

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[ra] = rb


def _is_h(seg):
    return abs(seg[0][1] - seg[1][1]) < TOL


def _on_segment(pt, seg):
    (x0, y0), (x1, y1) = seg
    x, y = pt
    if _is_h(seg):
        return (abs(y - y0) < TOL and
                min(x0, x1) - TOL <= x <= max(x0, x1) + TOL)
    return (abs(x - x0) < TOL and
            min(y0, y1) - TOL <= y <= max(y0, y1) + TOL)

def _segments_connect(a, b):
    """True if two wire segments are electrically joined.

    Sharing an endpoint joins them.  An endpoint landing anywhere on the
    other segment joins them (a tee).  Two interiors merely crossing do not.
    """
    for e in a:
        if _on_segment(e, b):
            return True
    for e in b:
        if _on_segment(e, a):
            return True
    if _is_h(a) == _is_h(b):                      # collinear overlap
        if _is_h(a) and abs(a[0][1] - b[0][1]) < TOL:
            lo = max(min(a[0][0], a[1][0]), min(b[0][0], b[1][0]))
            hi = min(max(a[0][0], a[1][0]), max(b[0][0], b[1][0]))
            return hi - lo > TOL
        if not _is_h(a) and abs(a[0][0] - b[0][0]) < TOL:
            lo = max(min(a[0][1], a[1][1]), min(b[0][1], b[1][1]))
            hi = min(max(a[0][1], a[1][1]), max(b[0][1], b[1][1]))
            return hi - lo > TOL
    return False


def extract(placed, paths):
    """Recover nets from geometry alone: {frozenset of (ref, port)}."""
    from .router import path_segments
    segs = []
    for net_paths in paths.values():
        for pts in net_paths:
            segs.extend(path_segments(pts))

    uf = _Union()
    for i, a in enumerate(segs):
        uf.find(('s', i))
        for j in range(i + 1, len(segs)):
            if _segments_connect(a, segs[j]):
                uf.union(('s', i), ('s', j))

    terminals = []
    for ref, part in placed.items():
        for port, pt in part.ports.items():
            terminals.append(((ref, port), pt))

    for index, (key, pt) in enumerate(terminals):
        uf.find(('t', key))
        # Coincident ports are a direct connection even when no extra wire is
        # drawn.  Gate-control interfaces use this intentionally because the
        # switch symbol already contains its visible gate lead.
        for other, other_pt in terminals[:index]:
            if (abs(pt[0] - other_pt[0]) < TOL
                    and abs(pt[1] - other_pt[1]) < TOL):
                uf.union(('t', key), ('t', other))
        for i, seg in enumerate(segs):
            if _on_segment(pt, seg):
                uf.union(('t', key), ('s', i))

    buckets = {}
    for key, _ in terminals:
        buckets.setdefault(uf.find(('t', key)), set()).add(key)
    return {frozenset(v) for v in buckets.values() if len(v) > 1}


def check(netlist, placed, paths):
    """Compare drawn connectivity to the netlist.  Returns a list of faults."""
    want = netlist.partition()
    got = extract(placed, paths)
    if want == got:
        return []

    faults = []
    got_index = {}
    for group in got:
        for term in group:
            got_index[term] = group

    for group in sorted(want, key=lambda g: sorted(g)):
        members = sorted(group)
        drawn = {got_index.get(t) for t in group}
        if len(drawn) > 1 or None in drawn:
            missing = [t for t in members if got_index.get(t) is None]
            if missing:
                faults.append(
                    f'net {members[0][0]}.{members[0][1]}...: terminal(s) '
                    f'{["%s.%s" % m for m in missing]} not connected by any wire')
            else:
                faults.append(
                    f'net {["%s.%s" % m for m in members]} was drawn as '
                    f'{len(drawn)} separate nets')

    for group in sorted(got, key=lambda g: sorted(g)):
        if group not in want:
            merged = [w for w in want if w & group]
            if len(merged) > 1:
                faults.append(
                    'nets ' + ' and '.join(
                        '/'.join('%s.%s' % m for m in sorted(w))
                        for w in merged) + ' were shorted together')
    return faults or ['connectivity differs from the netlist']
