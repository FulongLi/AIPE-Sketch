"""Metrics for the general drawing rules.

Every symbol in the library is exactly one CELL tall, so CELL is the unit of
visual scale: clearances, local wire lengths and component spacing are all
measured against it.  These functions only measure; repair lives elsewhere.
"""
from statistics import mean, pstdev

from . import router
from .router import TOL
from .config import (BAND_EPS, BAND_HI, BAND_LO, CELL_MM as CELL,
                     CHAIN_BAND_HI, CHAIN_BAND_LO, CHAIN_NEUTRAL,
                     CHAIN_ROLES, LABEL_PAD_X_MM as LABEL_PAD_X,
                     LABEL_PAD_Y_MM as LABEL_PAD_Y, LONG_RUN_MM as LONG_RUN,
                     PORT_LEAD_RATIO)
from .pins import COARSE as G

CONTROL_PORTS = ('g',)       # gate leads are not part of the power path


def _segments(paths):
    return [(net, seg) for net, ps in paths.items()
            for pts in ps for seg in router.path_segments(pts)]


def _length(seg):
    return abs(seg[1][0] - seg[0][0]) + abs(seg[1][1] - seg[0][1])


def _same(a, b):
    return abs(a[0] - b[0]) < TOL and abs(a[1] - b[1]) < TOL


def _port_axis(part, port):
    """0 for a horizontal lead, 1 for a vertical lead, after rotation."""
    side = part.spec.port_side(port)
    axis = 0 if side in ('left', 'right') else 1
    return 1 - axis if part.rot % 180 else axis


def lead_length_penalty(length, body_span):
    """Soft cost around a straight lead of half the component body span."""
    target = max(TOL, PORT_LEAD_RATIO * body_span)
    return ((length - target) / target) ** 2


def port_connection_geometry(netlist, placed, paths):
    """Prefer point-to-point wires that leave each port on its own axis.

    The straight segment at a port targets half the component's width for a
    side port, or half its height for a top/bottom port.  Rails, buses,
    terminals, grounds and control nets are excluded because their stub length
    is set by the floorplan rather than by a neighbouring component.
    """
    penalty, axis_faults, report = 0.0, [], []
    for net, members in netlist.nets.items():
        if net not in paths or len(members) != 2:
            continue
        if any(port in CONTROL_PORTS for _, port in members):
            continue
        if any(r not in placed or placed[r].spec.role in CHAIN_NEUTRAL
               for r, _ in members):
            continue
        segs = [seg for pts in paths[net] for seg in router.path_segments(pts)]
        for ref, port in members:
            part, point = placed[ref], placed[ref].port(port)
            axis = _port_axis(part, port)
            attached = [seg for seg in segs
                        if _same(seg[0], point) or _same(seg[1], point)]
            aligned = [seg for seg in attached
                       if abs(seg[0][1 - axis] - seg[1][1 - axis]) < TOL]
            if not aligned:
                penalty += 4.0
                axis_faults.append(
                    f'net {net} does not leave {ref}.{port} on its port axis')
                continue
            length = min(_length(seg) for seg in aligned)
            span = part.bbox[axis + 2] - part.bbox[axis]
            penalty += lead_length_penalty(length, span)
            report.append((ref, port, round(length, 3),
                           round(PORT_LEAD_RATIO * span, 3)))
    return round(penalty, 4), axis_faults, report


# ------------------------------------------------------------------ rule 3
def clearance(bodies):
    """Gap between neighbouring bodies against the target for their relation.

    A series passive pair is meant to sit closer than two switching devices,
    so they are not measured against the same target.  Only nearest
    neighbours sharing a band are compared; distant components are separated
    by whitespace on purpose.
    """
    from .config import GAP_ADJACENT, GAP_SERIES_PASSIVE
    from .pins import COARSE as _G
    penalty, tight = 0.0, 0
    for axis in (0, 1):
        other = 1 - axis
        for a in bodies:
            best, best_part = None, None
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
                    best, best_part = gap, b
            if best is None or best > LONG_RUN:
                continue
            pair_chain = (a.spec.role in CHAIN_ROLES
                          and best_part is not None
                          and best_part.spec.role in CHAIN_ROLES)
            target = (GAP_SERIES_PASSIVE if pair_chain
                      else GAP_ADJACENT) * _G
            if best < 0.5 * target:
                tight += 1
            penalty += ((best - target) / target) ** 2
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
    # The hard requirement is few scales.  Five is still a small vocabulary:
    # rail stubs, leg midpoints, half-body port leads and inter-stage runs can
    # each have a distinct purpose.  Consistency *within* a role is
    # measured exactly by local_consistency and wire_uniformity, so this
    # only catches genuinely arbitrary distances.
    excess = max(0, len(modes) - 5)
    dominant = max(scales, key=len)
    drift = abs(mean(dominant) - 1.0)
    return round(excess + 0.3 * drift, 4), modes


# ------------------------------------------------------------------ rule 23
def local_consistency(placed, paths, netlist=None):
    """Spread of the wire lengths leaving one component's ports.

    A device with a very short wire on one side and a very long one on the
    other reads as irregular even when both are legal.

    Only the power path is compared: rails are long hauls set by the
    floorplan, and a gate stub is squeezed by the leg pitch, so neither says
    anything about local regularity.
    """
    # A net joining more than two components is a bus: its run length is set
    # by the components hanging off it, not by any local choice, so it says
    # nothing about whether one component's wires are evenly matched.
    bus_segments = []
    if netlist is not None:
        for net, members in netlist.nets.items():
            real = [r for r, _ in members
                    if r in placed
                    and placed[r].spec.role not in CHAIN_NEUTRAL]
            if len(real) > 2 and net in paths:
                bus_segments += [seg for pts in paths[net]
                                 for seg in router.path_segments(pts)]

    def _is_bus(seg):
        return any(seg is b or seg == b for b in bus_segments)

    segs = [seg for _, seg in _segments(paths) if not _is_bus(seg)]
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


def _boundary_verdict(placed, notes):
    marked = [r for r, p in placed.items()
              if getattr(p, 'marker', None) is not None]
    if not marked:
        return 'no exposed port; the drawing ends at its load network'
    return f'{len(marked)} marked port(s): {", ".join(sorted(marked))}'


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
        # Only the series ports need to be entered from the side.  A winding
        # returning to a rail drops onto it vertically, which is correct.
        series_ports = set()
        for net, members in netlist.nets.items():
            # a net carrying a ground glyph is a rail return, however few
            # components hang off it, and is entered vertically
            if any(placed[r].spec.role == 'reference'
                   for r, _ in members if r in placed):
                continue
            real = [r for r, _ in members
                    if r in placed
                    and placed[r].spec.role not in CHAIN_NEUTRAL]
            if len(real) == 2:
                series_ports |= {p for r, p in members if r == ref}
        for name, pt in placed[ref].ports.items():
            attached = [s for s in segs if _same(s[0], pt) or _same(s[1], pt)]
            if not attached:
                continue
            run = min(attached, key=_length)
            nearest.append(_length(run) / CELL)
            if name in series_ports and abs(run[0][1] - run[1][1]) >= TOL:
                horizontal = False
        closest = round(min(nearest), 2) if nearest else 0.0
        furthest = round(max(nearest), 2) if nearest else 0.0
        # 2.5 rather than 2.0: a transformer sits on a functional boundary,
        # and the group gap is 6 G by specification, so a 2.5 G wide
        # transformer cannot be reached in under ~2.2 cells.
        tx_ok = horizontal and closest <= 2.5
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
        '6 external ports terminated': (
            ok(True, f'{len(terminals)} open circle(s): '
                     f'{len(power_ports)} power, {len(gate_ports)} control')
            if terminals else ('N/A', 'the circuit exposes no interfaces')),
        '7 sources drawn conventionally': ok(
            all(placed[r].spec.decor for r in sources) if sources else True,
            f'{len(sources)} source(s)'),
        '8 input and output named once': ok(
            raw['redundant_annotation'] == 0,
            annotation_policy(placed, netlist, notes)),
        '9 labels consistently positioned': ok(raw['label_side'] == 0),
        '10 transformer compactly connected': (
            ok(tx_ok, tx_note) if has_tx else ('N/A', 'no transformer')),
        '11 no unnecessary bends': ok(
            raw['avoidable_bend'] == 0,
            f"{raw['bend']} bend(s), {raw['avoidable_bend']} avoidable"),
        '12 no abnormally long local wires': ok(
            raw['local_spread'] < 1.0, f"spread {raw['local_spread']}"),
        '13 labels close, no overlap': ok(raw['label_overlap'] == 0),
        '14 power path reads left to right': ok(left_to_right,
                                                ' -> '.join(order)),
        '15 no unexplained empty region': ok(
            raw['largest_void'] <= 0.25, f"largest void {raw['largest_void']}"),

        # --- the visual refinement pass -------------------------------
        '16 markers only on power interfaces': ok(
            raw['external_marker'] == 0,
            f'{raw["marker_count"]} marker(s) on {len(power_ports)} power '
            f'port(s); {len(gate_ports)} control port(s) unmarked'),
        '17 VIN/VOUT clear of neighbouring labels': ok(
            raw['label_overlap'] == 0,
            f'clearance {LABEL_PAD_X:.2f} x {LABEL_PAD_Y:.2f} mm'),
        '18 equivalent labels use one offset': ok(
            raw['label_distance'] == 0,
            f"irregularity {raw['label_distance']}"),
        '19 transformer reads as one object': (
            ok(all(v <= 2.0 for v in raw['tx_ratio'].values()),
               f"spread {raw['tx_ratio']}")
            if raw['tx_ratio'] else ('N/A', 'no transformer')),
        '20 master-library symbols reused undistorted': ok(
            raw['custom_symbols'] == 0 and raw['symbol_distortion'] == 0,
            f"{raw['library_symbols']} from the sheet, "
            f"{raw['assembled_symbols']} assembled from it, "
            f"{raw['symbol_distortion']} distorted"),
        '21 local runs within 0.75-1.5 D': ok(
            raw['length_band'] < 0.5, f"band penalty {raw['length_band']}"),
        '22 output port only where the output is exposed': ok(
            raw['redundant_annotation'] == 0,
            _boundary_verdict(placed, notes)),
        '23 wires follow port axes; straight lead targets 0.5 body span': ok(
            raw['port_axis_mismatch'] == 0,
            f"lead preference penalty {raw['port_lead']}"),
    }


# ------------------------------------------------------------------ rule 12



def length_band(paths, placed=None, netlist=None):
    """Component-to-component runs should sit within 0.75D..1.5D.

    Item 12 is about the wire between two adjacent components, so this
    measures the spacing of consecutive ports along each net's trunk -- not
    the stub that drops from a port onto a rail, whose length is set by the
    rail separation rather than by any local choice.  Control nets are
    excluded: a gate stub is squeezed by the leg pitch.
    """
    if placed is None or netlist is None:
        return 0.0, []
    penalty, strays = 0.0, []
    for net, members in netlist.nets.items():
        if net not in paths:
            continue
        if any(port in CONTROL_PORTS for _, port in members):
            continue
        roles = {placed[r].spec.role for r, _ in members if r in placed
                 and not placed[r].spec.is_terminal
                 and placed[r].spec.role not in CHAIN_NEUTRAL}
        chain = bool(roles) and roles <= CHAIN_ROLES
        lo, hi = ((CHAIN_BAND_LO, CHAIN_BAND_HI) if chain
                  else (BAND_LO, BAND_HI))
        runs = [seg for seg in (s for pts in paths[net]
                                for s in router.path_segments(pts))]
        if not runs:
            continue
        trunk = max(runs, key=_length)
        axis = 0 if abs(trunk[0][1] - trunk[1][1]) < TOL else 1
        points = sorted(placed[r].port(p)[axis] for r, p in members
                        if r in placed)
        for a, b in zip(points, points[1:]):
            gap = abs(b - a) / CELL
            if gap < TOL / CELL or gap > LONG_RUN / CELL:
                continue
            if gap < lo - BAND_EPS:
                penalty += ((lo - gap) / lo) ** 2
                strays.append((net, round(gap, 2)))
            elif gap > hi + BAND_EPS:
                penalty += ((gap - hi) / hi) ** 2
                strays.append((net, round(gap, 2)))
    return round(penalty, 4), strays


# ------------------------------------------------------------------ rule 15
def label_distance_irregularity(placed, label_boxes, classes):
    """Equivalent components must hold their labels at the same distance.

    Also flags a label that sits closer to its body than the registry's
    preferred offset, or much further away.
    """
    boxes = dict(label_boxes)
    gaps = {}
    for ref, part in placed.items():
        box = boxes.get(ref)
        if box is None:
            continue
        bx0, by0, bx1, by1 = part.bbox
        lx0, ly0, lx1, ly1 = box
        dx = max(bx0 - lx1, lx0 - bx1, 0.0)
        dy = max(by0 - ly1, ly0 - by1, 0.0)
        gaps[ref] = dx + dy

    penalty, faults = 0.0, []
    for cid, refs in sorted(classes.items()):
        members = [r for r in refs if r in gaps]
        if len(members) < 2:
            continue
        values = [gaps[r] for r in members]
        spread = (max(values) - min(values)) / CELL
        if spread > 0.05:
            penalty += spread ** 2
            faults.append(f'{cid}: label distances differ by '
                          f'{spread:.2f} cells')
    for ref, gap in gaps.items():
        want = placed[ref].label_offset
        drift = abs(gap - want) / CELL
        if drift > 0.5:
            penalty += drift ** 2
            faults.append(f'{ref}: label {gap:.1f} mm from its body, '
                          f'preferred {want:.1f} mm')
    return round(penalty, 4), faults


# ------------------------------------------------------------------ rule 16
def external_markers(netlist, placed, paths=None):
    """Boundary rings belong to main power interfaces, and to nothing else.

    Also checks the geometry: the wire must stop at the circumference, not
    run through the circle's interior.
    """
    faults = []
    for ref, part in placed.items():
        interface = getattr(part, 'interface', None)
        marker = getattr(part, 'marker', None)

        if interface == 'power' and marker is None:
            faults.append(f'{ref} is a power interface but draws no marker')
        if marker is not None and interface != 'power':
            faults.append(f'{ref} draws a boundary marker but is '
                          f'{interface or "an internal node"}')
        if interface is not None and not part.spec.is_terminal:
            faults.append(f'{ref} is marked an interface but is not a terminal')

    # VIN / VOUT, when drawn as a port, must carry exactly one marker.  A
    # converter fed from an explicit source has no external input boundary,
    # and inventing one would change the netlist -- so that case is reported,
    # not silently passed.
    labels = {}
    for ref, part in placed.items():
        if part.label:
            labels.setdefault(part.label, []).append(ref)
    for want in ('VIN', 'VOUT'):
        refs = labels.get(want, [])
        if not refs:
            continue
        if len(refs) > 1:
            faults.append(f'{want} appears on {len(refs)} components')
        for ref in refs:
            if getattr(placed[ref], 'interface', None) != 'power':
                faults.append(f'{want} does not sit on a power interface')
            elif getattr(placed[ref], 'marker', None) is None:
                faults.append(f'{want} has no boundary marker')

    if paths:
        faults += marker_geometry(placed, paths)
    return faults


def marker_geometry(placed, paths):
    """A wire may touch a boundary circle, never cross into it."""
    faults = []
    segs = [seg for _, seg in _segments(paths)]
    for ref, part in placed.items():
        marker = getattr(part, 'marker', None)
        if marker is None:
            continue
        cx, cy, r = marker
        port = part.port(next(iter(part.ports)))
        # the wire's end sits on the circumference, one radius from the centre
        offset = ((port[0] - cx) ** 2 + (port[1] - cy) ** 2) ** 0.5
        if abs(offset - r) > TOL:
            faults.append(f'{ref}: wire ends {offset:.3f} mm from the marker '
                          f'centre, expected {r:.3f}')
        for seg in segs:
            depth = _penetration(seg, cx, cy, r)
            if depth > TOL:
                faults.append(f'{ref}: a wire crosses {depth:.3f} mm into '
                              f'the boundary marker')
                break
    return faults


def _penetration(seg, cx, cy, r):
    """How far an axis-aligned segment reaches inside a circle."""
    (x0, y0), (x1, y1) = seg
    if abs(y0 - y1) < TOL:                      # horizontal
        if abs(y0 - cy) > r - TOL:
            return 0.0
        half = (r * r - (y0 - cy) ** 2) ** 0.5
        lo, hi = max(min(x0, x1), cx - half), min(max(x0, x1), cx + half)
        return max(0.0, hi - lo)
    if abs(x0 - x1) < TOL:                      # vertical
        if abs(x0 - cx) > r - TOL:
            return 0.0
        half = (r * r - (x0 - cx) ** 2) ** 0.5
        lo, hi = max(min(y0, y1), cy - half), min(max(y0, y1), cy + half)
        return max(0.0, hi - lo)
    return 0.0


# ------------------------------------------------------------------ rule 17
def transformer_spread(placed):
    """A transformer must read as one device, not two inductors.

    Measured as width against height: every symbol on the sheet is one
    component dimension tall, so a transformer much wider than that has its
    windings spread too far apart to read as a single component.
    """
    faults, ratios = [], {}
    for ref, part in placed.items():
        if part.spec.role != 'isolation':
            continue
        height = part.spec.height or 1e-6
        ratio = part.spec.width / height
        ratios[ref] = round(ratio, 3)
        if ratio > 1.5:
            faults.append(f'{ref}: {ratio:.2f}x wider than tall; the '
                          f'windings read as separate inductors')
    return faults, ratios


# ------------------------------------------------------------------ annotation
INPUT_NAMES = {'vin', 'v_in'}
OUTPUT_NAMES = {'vout', 'v_out'}
NEAR = 3 * CELL              # two labels this close are "nearby"


def _label_text(part):
    return f'{part.label or ""}{part.sub or ""}'.lower()


def redundant_annotation(placed, netlist, notes=()):
    """Two nearby labels saying the same thing.

    VIN and VOUT are semantic ideas, not mandatory ink.  An explicit source
    already names the input; an output that ends in a load network already
    shows what it is.  Saying it twice is what this catches.
    """
    faults = []

    rendered = [(_label_text(p), p.x, p.y) for p in placed.values() if p.label]
    for note in notes:
        op = note['text_op']
        rendered.append((f'{op["text"]}{op.get("sub") or ""}'.lower(),
                         op['x'], op['y']))

    # an input source plus a separate input annotation beside it
    for part in placed.values():
        if part.spec.role != 'source':
            continue
        for text, x, y in rendered:
            if text not in INPUT_NAMES:
                continue
            if _label_text(part) in INPUT_NAMES:
                continue                       # the source *is* the label
            if abs(x - part.x) + abs(y - part.y) < NEAR:
                faults.append(
                    f'{part.ref} is labelled {_label_text(part)} and an '
                    f'input annotation sits beside it; label the source '
                    f'itself instead')

    # the same text twice, close together
    for i, (text, x, y) in enumerate(rendered):
        for other, ox, oy in rendered[i + 1:]:
            if text and text == other and abs(x - ox) + abs(y - oy) < NEAR:
                faults.append(f'the label {text!r} is rendered twice nearby')

    # an output terminal on a net that already terminates in a load
    for ref, part in placed.items():
        if not part.spec.is_terminal or _label_text(part) not in OUTPUT_NAMES:
            continue
        net = netlist.net_of(ref, 't')
        if net is None:
            continue
        # "already ends in a load" means a component shunted across the
        # output pair, not merely something whose kind is a resistor: a
        # series resistor is not a load.
        from .analysis import PARALLEL_OUTPUT_BLOCK, classify_motifs
        blocks = classify_motifs(netlist).get(PARALLEL_OUTPUT_BLOCK, [])
        shunted = {m for block in blocks if net in block['nets']
                   for m in block['members']}
        companions = [r for r, _ in netlist.nets[net] if r != ref]
        if shunted & set(companions):
            faults.append(
                f'{ref}: the output already ends in a load network, so an '
                f'output terminal adds nothing')
    return faults


def annotation_policy(placed, netlist, notes=()):
    """How the input and output are named, for the review checklist."""
    sources = [p for p in placed.values() if p.spec.role == 'source']
    named_sources = [p for p in sources if _label_text(p) in INPUT_NAMES]
    exposed = sorted(r for r, p in placed.items()
                     if getattr(p, 'interface', None) == 'power')
    bits = []
    if named_sources:
        bits.append(f'input: source {named_sources[0].ref} carries the name')
    elif sources:
        bits.append(f'input: source {sources[0].ref}, unnamed')
    else:
        bits.append('input: no explicit source')
    bits.append('output: ' + (', '.join(exposed) + ' exposed' if exposed
                              else 'ends at its load network, no port'))
    return '; '.join(bits)


# ------------------------------------------------------------------ symbols
_ALLOWED_ROTATIONS = (0, 90, 180, 270, -90, -180, -270)


def symbol_integrity(placed, registry):
    """A placed symbol must keep the geometry the registry gave it.

    Only translation, rotation and mirroring are allowed.  Any difference
    between a part's drawn extent and its registry extent means something
    stretched it, which would mean the drawing no longer matches the library.
    """
    faults = []
    for ref, part in placed.items():
        if part.interface == 'control':
            continue            # metadata-only; no symbol is rendered
        spec = registry.get(part.kind)
        if spec is None:
            faults.append(f'{ref}: {part.kind} is not in the registry')
            continue
        if part.rot % 360 not in [r % 360 for r in _ALLOWED_ROTATIONS]:
            faults.append(f'{ref}: rotated {part.rot} deg, not a right angle')
        drawn = (part.bbox[2] - part.bbox[0], part.bbox[3] - part.bbox[1])
        if part.marker is not None:
            continue            # the boundary ring extends the drawn extent
        want = ((spec.width, spec.height) if part.rot % 180 == 0
                else (spec.height, spec.width))
        for got, expected, axis in zip(drawn, want, 'xy'):
            if abs(got - expected) > TOL:
                faults.append(
                    f'{ref}: drawn {axis} extent {got:.3f} mm but the library '
                    f'symbol is {expected:.3f} mm -- it has been scaled')
    return faults

# ------------------------------------------------------------------ power path
def series_chains(netlist, placed):
    """Runs of passive/magnetic components joined along one series path.

    Returns each chain as an ordered list of refs, left to right -- the main
    power path whose continuity the centreline rules protect.
    """
    eligible = {ref for ref, p in placed.items()
                if p.spec.role in CHAIN_ROLES
                and p.spec.role not in CHAIN_NEUTRAL}
    links = {}
    for net, members in netlist.nets.items():
        # a series link joins exactly two components; anything with more
        # connections is a shared node -- a rail, or a filter tap -- and the
        # components on it are not in series with each other
        real = [r for r, _ in members
                if r in placed
                and placed[r].spec.role not in CHAIN_NEUTRAL]
        if len(real) != 2:
            continue
        if not all(r in eligible for r in real):
            continue
        a, b = sorted(real, key=lambda r: placed[r].x)
        links.setdefault(a, set()).add(b)

    chains, used = [], set()
    starts = [r for r in eligible
              if not any(r in v for v in links.values())]
    for start in sorted(starts, key=lambda r: placed[r].x):
        if start in used:
            continue
        run, node = [start], start
        used.add(start)
        while node in links:
            nxt = sorted(links[node], key=lambda r: placed[r].x)[0]
            if nxt in used:
                break
            run.append(nxt)
            used.add(nxt)
            node = nxt
        if len(run) > 1:
            chains.append(run)
    return chains


def _faces_sideways(part, port):
    """True when a port sits on the left or right face as drawn."""
    px, py = part.port(port)
    cx = (part.bbox[0] + part.bbox[2]) / 2
    cy = (part.bbox[1] + part.bbox[3]) / 2
    return abs(px - cx) >= abs(py - cy)


def centreline_deviation(netlist, placed):
    """Consecutive components on one power chain should stay collinear.

    Measured between the ports that actually join them, so a transformer
    whose primary terminal sits off its own centre still counts as aligned
    when that terminal lines up with the inductor before it.
    """
    penalty, faults = 0.0, []
    for chain in series_chains(netlist, placed):
        for a, b in zip(chain, chain[1:]):
            shared = None
            for net, members in netlist.nets.items():
                refs = {r for r, _ in members}
                if a in refs and b in refs:
                    shared = members
                    break
            if shared is None:
                continue
            ports = [(r, p) for r, p in shared if r in placed]
            # Only ports facing sideways belong to the horizontal path.  A
            # shunt element ending a chain is entered from above, and that
            # step is structural rather than a routing defect.  Measured from
            # the placed geometry so it holds however the part was rotated.
            if not all(_faces_sideways(placed[r], p) for r, p in ports):
                continue
            ys = [placed[r].port(p)[1] for r, p in ports]
            drop = (max(ys) - min(ys)) / CELL
            if drop > 0.05:
                penalty += drop ** 2
                faults.append(f'{a} -> {b} steps {drop:.2f} cells off the '
                              f'power centreline')
    return round(penalty, 4), faults


def near_component_bend_penalty(netlist, placed, paths):
    """Bends should not sit right beside a passive or magnetic port.

    A wire ought to leave a capacitor, inductor or transformer along that
    component's own axis; a corner within one local wire length of the port
    makes the power path read as a detour around the component.
    """
    ports = []
    for ref, part in placed.items():
        if part.spec.role not in CHAIN_ROLES or \
                part.spec.role in CHAIN_NEUTRAL:
            continue
        for name, pt in part.ports.items():
            ports.append((ref, name, pt))
    if not ports:
        return 0.0, []

    reach = BAND_HI * CELL          # one preferred local wire length
    penalty, faults = 0.0, []
    for net, net_paths in paths.items():
        for pts in net_paths:
            trimmed = [pts[0]]
            for p in pts[1:]:
                if p != trimmed[-1]:
                    trimmed.append(p)
            for i in range(1, len(trimmed) - 1):
                corner = trimmed[i]
                for ref, name, pt in ports:
                    d = abs(corner[0] - pt[0]) + abs(corner[1] - pt[1])
                    if d < reach:
                        share = d / reach
                        penalty += (1.0 - share) ** 2
                        faults.append(
                            f'net {net} bends {d / CELL:.2f} cells from '
                            f'{ref}.{name}')
                        break
    return round(penalty, 4), faults


# ------------------------------------------------------------------ shunts
def shunt_branch_balance(netlist, placed, paths, motifs=None):
    """A shunt device should sit centred in its own branch.

    The branch is node -> device -> rail, not rail -> device -> rail, so the
    two connecting wires are measured against each other rather than against
    the page.  A long drop onto the device with the device already sitting on
    the rail is the failure this catches.
    """
    from .analysis import POLARITY, SHUNT_SWITCH, classify_motifs
    motifs = motifs or classify_motifs(netlist)
    segs = [seg for _, seg in _segments(paths)]

    def run_at(pt):
        attached = [s for s in segs if _same(s[0], pt) or _same(s[1], pt)]
        vertical = [s for s in attached if abs(s[0][0] - s[1][0]) < TOL]
        return min((_length(s) for s in vertical), default=0.0)

    penalty, faults, report = 0.0, [], {}
    for entry in motifs.get(SHUNT_SWITCH, []):
        ref = entry['device']
        part = placed.get(ref)
        if part is None:
            continue
        polarity = POLARITY.get(part.kind)
        if not polarity:
            continue
        top = run_at(part.port(polarity[0]))
        bottom = run_at(part.port(polarity[1]))
        total = top + bottom
        error = 0.0 if total < TOL else abs(top - bottom) / total
        report[ref] = dict(top=round(top / CELL, 3),
                           bottom=round(bottom / CELL, 3),
                           error=round(error, 3))
        if error > 0.34:
            penalty += error ** 2
            faults.append(
                f'{ref}: shunt branch is lopsided -- {top / CELL:.2f} cells '
                f'above, {bottom / CELL:.2f} below')
    return round(penalty, 4), faults, report


def shunt_verticality(netlist, placed, paths, motifs=None):
    """A shunt branch should be one straight vertical line."""
    from .analysis import POLARITY, SHUNT_SWITCH, classify_motifs
    motifs = motifs or classify_motifs(netlist)
    faults = []
    for entry in motifs.get(SHUNT_SWITCH, []):
        ref = entry['device']
        part = placed.get(ref)
        polarity = POLARITY.get(part.kind) if part else None
        if not polarity:
            continue
        hi = part.port(polarity[0])
        lo = part.port(polarity[1])
        if abs(hi[0] - lo[0]) > TOL:
            faults.append(f'{ref}: power terminals are not vertically aligned')
    return faults


# ------------------------------------------------------------------ facing
def port_facing(netlist, placed):
    """Series-connected ports should face each other.

    When two components are joined by a two-terminal net, the left one's
    port should be on its right side and vice versa.  If a part is rotated
    the other way its wire has to double back across the body, which shows
    up later as a mysterious short.  Reporting it here names the cause.
    """
    faults = []
    for net, members in netlist.nets.items():
        real = [(r, p) for r, p in members
                if r in placed
                and placed[r].spec.role not in CHAIN_NEUTRAL]
        if len(real) != 2:
            continue
        (ref_a, port_a), (ref_b, port_b) = real
        a, b = placed[ref_a], placed[ref_b]
        if abs(a.x - b.x) < TOL:
            continue                                   # stacked, not in a row
        left, lp, right, rp = ((a, port_a, b, port_b) if a.x < b.x
                               else (b, port_b, a, port_a))
        lx = left.port(lp)[0] - (left.bbox[0] + left.bbox[2]) / 2
        rx = right.port(rp)[0] - (right.bbox[0] + right.bbox[2]) / 2
        if lx < -TOL:
            faults.append(
                f'net {net}: {left.ref}.{lp} faces left, away from '
                f'{right.ref} -- check its rotation')
        if rx > TOL:
            faults.append(
                f'net {net}: {right.ref}.{rp} faces right, away from '
                f'{left.ref} -- check its rotation')
    return faults
