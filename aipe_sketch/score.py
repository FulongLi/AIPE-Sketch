"""Layout cost and the 0-100 quality scorecard.

Regularity outranks wire length: a slightly longer connection that keeps a
repeated structure uniform scores better than a shorter irregular one.
"""
from statistics import mean, pstdev

from . import router
from .router import TOL
from .pins import COARSE as G
from .placement import cluster

WEIGHTS = {
    'connectivity': 10 ** 9,        # fatal
    'component_overlap': 100000,
    'wire_component_collision': 50000,
    'label_overlap': 50000,
    'out_of_bounds': 100000,
    'symmetry': 4000,
    'spacing_variance': 3000,
    'alignment': 3000,
    'wire_uniformity': 1500,
    'routing_shape': 2000,
    'crossing': 300,
    'spacing_target': 120,
    'bend': 60,
    'wire_length': 1,
}

FATAL = ('connectivity', 'component_overlap', 'wire_component_collision',
         'label_overlap', 'out_of_bounds')

SPACING = dict(minimum=3 * G, target_lo=4 * G, target_hi=6 * G,
               group_lo=6 * G, group_hi=10 * G)


def _overlap(r1, r2):
    ax0, ay0, ax1, ay1 = r1
    bx0, by0, bx1, by1 = r2
    return (min(ax1, bx1) - max(ax0, bx0) > TOL and
            min(ay1, by1) - max(ay0, by0) > TOL)


def _gap(r1, r2):
    """Clear distance between two boxes; 0 if they touch or overlap."""
    dx = max(r1[0] - r2[2], r2[0] - r1[2], 0.0)
    dy = max(r1[1] - r2[3], r2[1] - r1[3], 0.0)
    return (dx * dx + dy * dy) ** 0.5


class Scorecard:
    def __init__(self, raw, faults, sub, cost):
        self.raw = raw
        self.faults = faults
        self.sub = sub
        self.cost = cost

    @property
    def overall(self):
        weights = {'connectivity': 3, 'symmetry': 2, 'spacing_uniformity': 2,
                   'alignment': 2, 'routing': 1, 'crossings': 1,
                   'collision': 3, 'topology_readability': 1}
        total = sum(weights.values())
        return round(sum(self.sub[k] * w for k, w in weights.items()) / total)

    @property
    def acceptable(self):
        return self.sub['connectivity'] == 100 and self.sub['collision'] == 100

    def as_dict(self):
        out = dict(self.sub)
        out['overall'] = self.overall
        return out

    def __str__(self):
        lines = [f'quality  (cost {self.cost:,.0f})']
        for key in ('connectivity', 'symmetry', 'spacing_uniformity',
                    'alignment', 'routing', 'crossings', 'collision',
                    'topology_readability'):
            lines.append(f'  {key:<22} {self.sub[key]:>3}')
        lines.append(f'  {"overall":<22} {self.overall:>3}')
        if self.faults:
            lines.append('  faults:')
            lines += [f'    - {f}' for f in self.faults]
        return '\n'.join(lines)


def _clamp(value):
    return int(max(0, min(100, round(value))))


def evaluate(netlist, placed, paths, labels, classes, bounds=None,
             connectivity_faults=None):
    raw, faults = {}, []
    parts = list(placed.values())
    bodies = [p for p in parts if p.spec.width > TOL or p.spec.height > TOL]

    # -- connectivity ------------------------------------------------
    cfaults = list(connectivity_faults or [])
    raw['connectivity'] = len(cfaults)
    faults += cfaults

    # -- overlaps ----------------------------------------------------
    overlaps = 0
    for i, a in enumerate(bodies):
        for b in bodies[i + 1:]:
            if _overlap(a.bbox, b.bbox):
                overlaps += 1
                faults.append(f'{a.ref} overlaps {b.ref}')
    raw['component_overlap'] = overlaps

    hits = 0
    for i, (ref_a, box_a) in enumerate(labels):
        for ref_b, box_b in labels[i + 1:]:
            if _overlap(box_a, box_b):
                hits += 1
                faults.append(f'label {ref_a} overlaps label {ref_b}')
        for part in bodies:
            if _overlap(box_a, part.bbox):
                hits += 1
                faults.append(f'label {ref_a} overlaps {part.ref}')
        for net, net_paths in paths.items():
            if any(router.seg_penetrates(seg, box_a)
                   for pts in net_paths for seg in router.path_segments(pts)):
                hits += 1
                faults.append(f'label {ref_a} sits on net {net}')
    raw['label_overlap'] = hits

    collisions = 0
    for net, net_paths in paths.items():
        for pts in net_paths:
            for seg in router.path_segments(pts):
                for part in bodies:
                    if router.seg_penetrates(seg, part.bbox):
                        collisions += 1
                        faults.append(f'net {net} crosses body of {part.ref}')
    raw['wire_component_collision'] = collisions

    out = 0
    if bounds:
        bx0, by0, bx1, by1 = bounds
        for part in bodies:
            x0, y0, x1, y1 = part.bbox
            if x0 < bx0 or y0 < by0 or x1 > bx1 or y1 > by1:
                out += 1
                faults.append(f'{part.ref} lies outside the drawing bounds')
    raw['out_of_bounds'] = out

    # -- crossings, bends, length ------------------------------------
    flat = [(net, seg) for net, ps in paths.items()
            for pts in ps for seg in router.path_segments(pts)]
    crossings = sum(1 for i, (na, sa) in enumerate(flat)
                    for nb, sb in flat[i + 1:]
                    if na != nb and router.segments_cross(sa, sb))
    raw['crossing'] = crossings
    raw['bend'] = sum(router.bend_count(pts)
                      for ps in paths.values() for pts in ps)
    raw['wire_length'] = round(sum(router.path_length(pts)
                                   for ps in paths.values() for pts in ps), 3)

    # -- alignment ---------------------------------------------------
    off = sum(1 for p in parts for v in (p.x, p.y)
              if abs(v / G - round(v / G)) > 1e-3)
    raw['alignment'] = off

    # -- symmetry and spacing uniformity across repeated classes -----
    sym, variance = 0, 0.0
    for cid, refs in sorted(classes.items()):
        members = [placed[r] for r in refs if r in placed]
        if len(members) < 2:
            continue
        if len({(m.rot, m.mirror) for m in members}) > 1:
            sym += 1
            faults.append(f'{cid}: members drawn at different orientations')
        ys = cluster([m.y for m in members])
        xs = cluster([m.x for m in members])
        if len(ys) > 1 and len(xs) > 1:
            sym += 1
            faults.append(f'{cid}: members share neither a row nor a column')
            continue
        varying = xs if len(ys) == 1 else ys
        if len(varying) > 2:
            steps = [b - a for a, b in zip(varying, varying[1:])]
            variance += pstdev(steps) / G if len(steps) > 1 else 0.0
    raw['symmetry'] = sym
    raw['spacing_variance'] = round(variance, 4)

    # -- wire uniformity within equivalent nets ----------------------
    by_shape = {}
    for net, net_paths in paths.items():
        terms = tuple(sorted(
            (placed[r].kind, p) for r, p in netlist.nets.get(net, [])))
        by_shape.setdefault(terms, []).append(
            (sum(router.path_length(pts) for pts in net_paths),
             sum(router.bend_count(pts) for pts in net_paths),
             len(net_paths)))
    uniformity, shape_mismatch = 0.0, 0
    for group in by_shape.values():
        if len(group) < 2:
            continue
        lengths = [g[0] for g in group]
        if mean(lengths) > TOL:
            uniformity += pstdev(lengths) / mean(lengths)
        if len({(g[1], g[2]) for g in group}) > 1:
            shape_mismatch += 1
            faults.append('equivalent nets routed with different shapes')
    raw['wire_uniformity'] = round(uniformity, 4)
    raw['routing_shape'] = shape_mismatch

    # -- target spacing ----------------------------------------------
    penalty, tight = 0.0, 0
    ordered = sorted(bodies, key=lambda p: (round(p.y, 3), p.x))
    for a, b in zip(ordered, ordered[1:]):
        if abs(a.y - b.y) > TOL:
            continue
        d = _gap(a.bbox, b.bbox)
        if d < SPACING['minimum'] - TOL:
            tight += 1
            penalty += (SPACING['minimum'] - d) ** 2 * 10
        elif d < SPACING['target_lo']:
            penalty += (SPACING['target_lo'] - d) ** 2
        elif d > SPACING['target_hi'] and a.group == b.group:
            penalty += (d - SPACING['target_hi']) ** 2
    raw['spacing_target'] = round(penalty, 3)
    raw['spacing_tight'] = tight

    # -- cost --------------------------------------------------------
    cost = sum(WEIGHTS[k] * raw[k] for k in WEIGHTS if k in raw)

    # -- 0..100 subscores --------------------------------------------
    nparts = max(1, len(bodies))
    nnets = max(1, len(paths))
    sub = {
        'connectivity': 100 if not raw['connectivity'] else 0,
        'collision': 100 if not (raw['component_overlap'] +
                                 raw['label_overlap'] +
                                 raw['wire_component_collision'] +
                                 raw['out_of_bounds']) else 0,
        'symmetry': _clamp(100 - 25 * raw['symmetry']),
        'spacing_uniformity': _clamp(100 - 40 * raw['spacing_variance']
                                     - 12 * raw['spacing_tight']),
        'alignment': _clamp(100 - 20 * raw['alignment']),
        'routing': _clamp(100 - 100 * raw['bend'] / (3 * nnets)
                          - 60 * raw['wire_uniformity'] / max(1, nnets)
                          - 25 * raw['routing_shape']),
        'crossings': _clamp(100 - 100 * raw['crossing'] / (2 * nnets)),
        'topology_readability': _clamp(
            100 - raw['spacing_target'] / (8 * nparts)
            - 40 * raw['crossing'] / max(1, nparts)),
    }
    return Scorecard(raw, faults, sub, cost)
