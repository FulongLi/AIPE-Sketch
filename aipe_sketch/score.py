"""Layout cost and the 0-100 quality scorecard.

Regularity outranks wire length: a slightly longer connection that keeps a
repeated structure uniform scores better than a shorter irregular one.
"""
from statistics import mean, pstdev

from . import drawing_rules, router
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
    # general drawing rules
    'rail_step': 40000,
    'floating_end': 40000,
    'midpoint_detour': 5000,
    'label_side': 3000,
    'clearance': 200,
    'rhythm': 250,
    'local_spread': 250,
    'length_band': 200,
    'label_distance': 400,
    'external_marker': 40000,
    'transformer_spread': 20000,
    'redundant_annotation': 2000,
    'symbol_distortion': 60000,
}

FATAL = ('connectivity', 'component_overlap', 'wire_component_collision',
         'label_overlap', 'out_of_bounds', 'rail_step', 'floating_end',
         'external_marker', 'transformer_spread', 'symbol_distortion')

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
    def __init__(self, raw, faults, sub, cost, checks=None):
        self.raw = raw
        self.faults = faults
        self.sub = sub
        self.cost = cost
        self.checks = checks or {}

    @property
    def overall(self):
        weights = {'connectivity': 3, 'symmetry': 2, 'spacing_uniformity': 2,
                   'alignment': 2, 'routing': 1, 'crossings': 1,
                   'collision': 3, 'topology_readability': 1,
                   'visual_rhythm': 2, 'clearance': 2, 'conventions': 2,
                   'labelling': 2}
        total = sum(weights.values())
        return round(sum(self.sub[k] * w for k, w in weights.items()) / total)

    @property
    def acceptable(self):
        return (self.sub['connectivity'] == 100 and
                self.sub['collision'] == 100 and
                not self.raw.get('rail_step') and
                not self.raw.get('floating_end') and
                not self.raw.get('external_marker') and
                not self.raw.get('transformer_spread') and
                not self.raw.get('symbol_distortion'))

    def as_dict(self):
        out = dict(self.sub)
        out['overall'] = self.overall
        return out

    def __str__(self):
        lines = [f'quality  (cost {self.cost:,.0f})']
        for key in ('connectivity', 'symmetry', 'spacing_uniformity',
                    'alignment', 'routing', 'crossings', 'collision',
                    'topology_readability', 'visual_rhythm', 'clearance',
                    'labelling', 'conventions'):
            lines.append(f'  {key:<22} {self.sub[key]:>3}')
        lines.append(f'  {"overall":<22} {self.overall:>3}')
        if self.faults:
            lines.append('  faults:')
            lines += [f'    - {f}' for f in self.faults]
        return '\n'.join(lines)


def _clamp(value):
    return int(max(0, min(100, round(value))))


def evaluate(netlist, placed, paths, labels, classes, bounds=None,
             connectivity_faults=None, structure=None, plan_groups=(),
             notes=(), registry=None):
    raw, faults = {}, []
    parts = list(placed.values())
    bodies = [p for p in parts if p.spec.width > TOL or p.spec.height > TOL]
    # an external terminal's ring sits on the wire end by design, so it is a
    # body for label and overlap purposes but never a routing obstacle
    solid = [p for p in bodies if not p.spec.is_terminal]

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
                for part in solid:
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
        for ref, box in labels:          # a clipped label is a lost label
            if (box[0] < bx0 or box[1] < by0
                    or box[2] > bx1 or box[3] > by1):
                out += 1
                faults.append(f'label {ref} lies outside the drawing bounds')
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

    # -- general drawing rules ---------------------------------------
    structure = structure or {}
    raw['clearance'], tight_bodies = drawing_rules.clearance(solid)
    raw['rhythm'], raw['scales'] = drawing_rules.rhythm(paths)
    raw['local_spread'], uneven = drawing_rules.local_consistency(placed, paths)
    raw['clearance_tight'] = tight_bodies

    rails = [structure.get('rails', {}).get('positive'),
             structure.get('rails', {}).get('negative')]
    rail_faults = drawing_rules.rail_straightness(paths, rails)
    raw['rail_step'] = len(rail_faults)
    faults += rail_faults

    mid_faults = drawing_rules.midpoint_directness(paths,
                                                   structure.get('legs', []))
    raw['midpoint_detour'] = len(mid_faults)
    faults += mid_faults

    loose = drawing_rules.floating_ends(placed, paths)
    raw['floating_end'] = len(loose)
    faults += loose

    side_faults = drawing_rules.label_side_consistency(placed, classes)
    raw['label_side'] = len(side_faults)
    faults += side_faults

    raw['length_band'], strays = drawing_rules.length_band(
        paths, placed, netlist)
    for net, gap in strays[:4]:
        faults.append(f'net {net}: a {gap} cell run between adjacent '
                      f'components is outside the 0.75-1.5 band')
    raw['label_distance'], label_faults = \
        drawing_rules.label_distance_irregularity(placed, labels, classes)
    faults += label_faults

    redundant = drawing_rules.redundant_annotation(placed, netlist, notes)
    raw['redundant_annotation'] = len(redundant)
    faults += redundant

    marker_faults = drawing_rules.external_markers(netlist, placed, paths)
    raw['marker_count'] = sum(1 for p in parts
                              if getattr(p, 'marker', None))
    raw['external_marker'] = len(marker_faults)
    faults += marker_faults

    # how much of the drawing comes from the master sheet, and whether any
    # symbol was distorted on the way in
    seen = {p.spec.kind: p.spec for p in parts}
    raw['library_symbols'] = sum(1 for s in seen.values()
                                 if s.source == 'library')
    raw['assembled_symbols'] = sum(1 for s in seen.values()
                                   if s.source == 'compound')
    raw['custom_symbols'] = sum(1 for s in seen.values()
                                if s.source == 'custom'
                                and s.role != 'terminal')
    if registry is not None:
        distorted = drawing_rules.symbol_integrity(placed, registry)
        raw['symbol_distortion'] = len(distorted)
        faults += distorted
    else:
        raw['symbol_distortion'] = 0

    tx_faults, raw['tx_ratio'] = drawing_rules.transformer_spread(placed)
    raw['transformer_spread'] = len(tx_faults)
    faults += tx_faults

    raw['fill'], raw['aspect'] = drawing_rules.compactness(solid, paths)
    raw['largest_void'] = drawing_rules.occupancy(solid, paths)
    for ref, lo, hi in uneven[:6]:
        faults.append(f'{ref}: local wires differ by {hi - lo:.1f} cells '
                      f'({lo} vs {hi})')

    # -- cost --------------------------------------------------------
    cost = sum(WEIGHTS[k] * raw[k] for k in WEIGHTS
               if k in raw and isinstance(raw[k], (int, float)))
    nb = max(1, len(solid))

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
        'visual_rhythm': _clamp(100 - 30 * raw['rhythm']
                                - 30 * raw['local_spread'] / nb
                                - 25 * raw['length_band'] / nb),
        'labelling': _clamp(100 - 25 * raw['label_distance']
                            - 50 * raw['label_side']
                            - 25 * raw['redundant_annotation']),
        'clearance': _clamp(100 - 35 * raw['clearance'] / nb
                            - 10 * raw['clearance_tight']),
        'conventions': _clamp(100 - 30 * raw['rail_step']
                              - 25 * raw['midpoint_detour']
                              - 20 * raw['label_side']
                              - 40 * raw['floating_end']),
    }
    checks = drawing_rules.checklist(raw, netlist, placed, paths,
                                     structure, plan_groups, notes)
    return Scorecard(raw, faults, sub, cost, checks)
