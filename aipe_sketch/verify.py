"""Layout quality metrics and the pre-render acceptance gate.

Implements the aesthetic cost function and the mandatory checks that a
layout must pass before it is rendered.
"""
from . import router
from .router import EPS

WEIGHTS = {
    'component_overlap': 10000,
    'label_overlap': 5000,
    'wire_component_collision': 1000,
    'wire_crossing': 100,
    'extra_bend': 20,
    'alignment_error': 20,
    'symmetry_error': 30,
    'spacing_irregularity': 10,
    'wire_length': 1,
}

# checks that must pass; everything else only contributes to the cost
MANDATORY = ('component_overlap', 'label_overlap', 'wire_component_collision')


def _overlap(r1, r2):
    ax0, ay0, ax1, ay1 = r1
    bx0, by0, bx1, by1 = r2
    dx = min(ax1, bx1) - max(ax0, bx0)
    dy = min(ay1, by1) - max(ay0, by0)
    return dx > EPS and dy > EPS


class Report:
    def __init__(self, metrics, failures):
        self.metrics = metrics
        self.failures = failures

    @property
    def cost(self):
        return sum(WEIGHTS[k] * v for k, v in self.metrics.items()
                   if k in WEIGHTS)

    @property
    def passed(self):
        return not self.failures

    def __str__(self):
        order = ['component_overlap', 'label_overlap',
                 'wire_component_collision', 'wire_crossing', 'extra_bend',
                 'alignment_error', 'symmetry_error', 'spacing_irregularity',
                 'wire_length']
        lines = ['layout verification']
        for key in order:
            value = self.metrics.get(key, 0)
            mark = 'FAIL' if key in MANDATORY and value else 'PASS'
            tag = mark if key in MANDATORY else '    '
            lines.append(f'  {tag}  {key:<26} {value:>10.3f}')
        lines.append(f'        {"AestheticCost":<26} {self.cost:>10.1f}')
        if self.failures:
            lines.append('  REJECTED: ' + '; '.join(self.failures))
        return '\n'.join(lines)


def evaluate(parts, paths, labels, grid, groups=None, net_parts=None):
    """Score a layout.

    parts   -- objects with .ref, .bbox, .clearance_bbox
    paths   -- {net name: [list of point lists]}
    labels  -- list of (ref, bbox)
    groups  -- list of lists of refs expected to be geometrically identical
    net_parts -- {net name: set of refs it terminates on}; clearance to a
               part a net actually connects to is not a spacing defect
    """
    net_parts = net_parts or {}
    metrics = {}
    failures = []

    # -- component overlap -------------------------------------------
    overlaps = 0
    for i, a in enumerate(parts):
        for b in parts[i + 1:]:
            if _overlap(a.bbox, b.bbox):
                overlaps += 1
                failures.append(f'{a.ref} overlaps {b.ref}')
    metrics['component_overlap'] = overlaps

    # -- label overlap (labels vs labels, vs bodies, vs wires) --------
    label_hits = 0
    for i, (ref_a, box_a) in enumerate(labels):
        for ref_b, box_b in labels[i + 1:]:
            if _overlap(box_a, box_b):
                label_hits += 1
                failures.append(f'label {ref_a} overlaps label {ref_b}')
        for part in parts:
            if _overlap(box_a, part.bbox):
                label_hits += 1
                failures.append(f'label {ref_a} overlaps {part.ref}')
        for net, net_paths in paths.items():
            for pts in net_paths:
                for seg in router.path_segments(pts):
                    if router.seg_penetrates(seg, box_a):
                        label_hits += 1
                        failures.append(f'label {ref_a} sits on net {net}')
                        break
    metrics['label_overlap'] = label_hits

    # -- wires through component bodies ------------------------------
    collisions = 0
    for net, net_paths in paths.items():
        for pts in net_paths:
            for seg in router.path_segments(pts):
                for part in parts:
                    if router.seg_penetrates(seg, part.bbox):
                        collisions += 1
                        failures.append(f'net {net} crosses body of {part.ref}')
    metrics['wire_component_collision'] = collisions

    # -- crossings between different nets ----------------------------
    flat = []
    for net, net_paths in paths.items():
        for pts in net_paths:
            flat += [(net, seg) for seg in router.path_segments(pts)]
    crossings = 0
    for i, (net_a, seg_a) in enumerate(flat):
        for net_b, seg_b in flat[i + 1:]:
            if net_a != net_b and router.segments_cross(seg_a, seg_b):
                crossings += 1
    metrics['wire_crossing'] = crossings

    # -- wire length and bends ---------------------------------------
    length = 0.0
    bends = 0
    for net_paths in paths.values():
        for pts in net_paths:
            length += router.path_length(pts)
            bends += router.bend_count(pts)
    metrics['wire_length'] = round(length, 3)
    metrics['extra_bend'] = bends

    # -- alignment: parts off the layout grid ------------------------
    off = 0
    for part in parts:
        for value in (part.x, part.y):
            if abs(value / grid - round(value / grid)) > 1e-3:
                off += 1
    metrics['alignment_error'] = off

    # -- symmetry / repeated structures ------------------------------
    sym = 0
    for group in (groups or []):
        members = [p for p in parts if p.ref in group]
        if len(members) < 2:
            continue
        ref = members[0]
        ref_size = (round(ref.bbox[2] - ref.bbox[0], 3),
                    round(ref.bbox[3] - ref.bbox[1], 3))
        for m in members[1:]:
            size = (round(m.bbox[2] - m.bbox[0], 3),
                    round(m.bbox[3] - m.bbox[1], 3))
            if size != ref_size or m.rot != ref.rot or m.mirror != ref.mirror:
                sym += 1
        # members of a group must share a row or a column exactly
        if len({round(m.y, 3) for m in members}) > 1 and \
           len({round(m.x, 3) for m in members}) > 1:
            sym += 1
        # and be evenly spaced along the axis they vary on
        varying = sorted({round(m.x, 3) for m in members}) \
            if len({round(m.y, 3) for m in members}) == 1 \
            else sorted({round(m.y, 3) for m in members})
        if len(varying) > 2:
            steps = {round(b - a, 3) for a, b in zip(varying, varying[1:])}
            if len(steps) > 1:
                sym += len(steps) - 1
    metrics['symmetry_error'] = sym

    # -- spacing consistency: wire-to-body clearance below 1G --------
    tight = 0
    for net, net_paths in paths.items():
        own = net_parts.get(net, set())
        for pts in net_paths:
            for seg in router.path_segments(pts):
                for part in parts:
                    if part.ref in own:
                        continue
                    if router.seg_penetrates(seg, part.clearance_bbox) and \
                       not router.seg_penetrates(seg, part.bbox):
                        tight += 1
    metrics['spacing_irregularity'] = tight

    return Report(metrics, failures)
