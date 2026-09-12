"""Extract the master sheet into a clean, searchable component library.

The master SVG stays canonical.  Nothing here redraws a component: geometry is
copied out of the sheet, unrelated neighbouring geometry is dropped, and the
result is normalised around a local origin.

Many of the sheet's ``<symbol>`` wrappers enclose geometry from neighbouring
drawings, so their bounding boxes are meaningless.  Clustering the child
elements separates the device from the strays, which is what makes both the
section inventory and the cleaning possible.
"""
import re
import unicodedata

from . import symlib

NS = symlib.NS
HEADING_SIZE = 10.58         # section headings on the sheet
# Millimetres.  Above ~1.6 a capacitor's two plates stay together; much above
# this and neighbouring components on the sheet start merging into one symbol.
CLUSTER_GAP = 2.0

# The sheet's section headings.  Detected by matching text drawn at heading
# size against this list, so an in-drawing annotation at the same size -- a
# '+', a 'n:1', a 'f(t)' -- is never mistaken for a section.
SECTION_TITLES = (
    'Standard Elements', 'Lines', 'Designators', 'Drawing Elements',
    'Sources', 'Magnetic', 'Earth symbols', 'Measurement', 'Switches',
    'Miscellaneous', 'Connectors', 'Logical Operations', 'Signals',
    'Optoelectronics', 'Ladder logic symbols', 'Standard B6-Topologies',
    'Diode Rectifiers', 'Standard 3-Level-Topologies', 'Test circuits',
)

# Names verified by eye against the sheet, where the <title> alone is ambiguous.
VARIANT_NAMES = {
    'g6472': 'inductor_air_core',
    'g16215': 'inductor_cored',
    'g5826': 'inductor_tapped',
    'g4046': 'mosfet_n_enhancement',
    'g3996': 'mosfet_n_depletion',
    'g11181': 'voltage_source_plain',
    'voltage_source': 'voltage_source_iec',
    'g7309': 'voltage_source_square',
    'g6663': 'current_source_iec',
    'g8210': 'capacitor',
    'g8838': 'capacitor_polarised',
    'g8469': 'capacitor_adjustable',
}


def slug(text):
    text = unicodedata.normalize('NFKD', text or '')
    text = ''.join(c for c in text if not unicodedata.combining(c))
    text = re.sub(r'[^0-9A-Za-z]+', '_', text).strip('_').lower()
    return text or 'unnamed'


def _font_size(el):
    m = re.search(r'font-size:([\d.]+)', el.get('style') or '')
    return float(m.group(1)) if m else None


def detect_sections(root):
    """Section headings actually present on the sheet, with their anchors."""
    found = {}
    for el in root.iter(NS + 'text'):
        text = ''.join(el.itertext()).strip()
        size = _font_size(el)
        x, y = el.get('x'), el.get('y')
        span = el.find(NS + 'tspan')
        if span is not None:
            size = size or _font_size(span)
            x = x or span.get('x')
            y = y or span.get('y')
        if not text or x is None or size is None:
            continue
        if abs(size - HEADING_SIZE) > 0.2 or text not in SECTION_TITLES:
            continue
        found.setdefault(text, (text, float(x), float(y)))
    return sorted(found.values(), key=lambda s: (s[2], s[1]))


# --- affine transforms -------------------------------------------------
# The sheet uses translate, scale, rotate and matrix.  Reading only translate
# put rotated and mirrored geometry -- a transformer's secondary winding, for
# one -- tens of millimetres away from where it actually draws.
_XFORM = re.compile(r'(matrix|translate|scale|rotate|skewX|skewY)\s*\(([^)]*)\)')
IDENTITY = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)


def _nums(text):
    return [float(v) for v in re.findall(r'[-+]?[\d.]+(?:[eE][-+]?\d+)?', text)]


def _multiply(m, n):
    """Compose two 2x3 affine matrices (m applied after n)."""
    a1, b1, c1, d1, e1, f1 = m
    a2, b2, c2, d2, e2, f2 = n
    return (a1 * a2 + c1 * b2, b1 * a2 + d1 * b2,
            a1 * c2 + c1 * d2, b1 * c2 + d1 * d2,
            a1 * e2 + c1 * f2 + e1, b1 * e2 + d1 * f2 + f1)


def parse_transform(text):
    """An SVG transform attribute as a 2x3 affine matrix."""
    result = IDENTITY
    for kind, body in _XFORM.findall(text or ''):
        v = _nums(body)
        if kind == 'matrix' and len(v) == 6:
            m = tuple(v)
        elif kind == 'translate':
            m = (1.0, 0.0, 0.0, 1.0, v[0] if v else 0.0,
                 v[1] if len(v) > 1 else 0.0)
        elif kind == 'scale':
            sx = v[0] if v else 1.0
            sy = v[1] if len(v) > 1 else sx
            m = (sx, 0.0, 0.0, sy, 0.0, 0.0)
        elif kind == 'rotate':
            import math
            ang = math.radians(v[0] if v else 0.0)
            cos, sin = math.cos(ang), math.sin(ang)
            m = (cos, sin, -sin, cos, 0.0, 0.0)
            if len(v) >= 3:                     # rotation about a centre
                cx, cy = v[1], v[2]
                m = _multiply((1.0, 0.0, 0.0, 1.0, cx, cy),
                              _multiply(m, (1.0, 0.0, 0.0, 1.0, -cx, -cy)))
        elif kind in ('skewX', 'skewY'):
            import math
            t = math.tan(math.radians(v[0] if v else 0.0))
            m = (1.0, 0.0, t, 1.0, 0.0, 0.0) if kind == 'skewX' \
                else (1.0, t, 0.0, 1.0, 0.0, 0.0)
        else:
            continue
        result = _multiply(result, m)
    return result


def apply(matrix, x, y):
    a, b, c, d, e, f = matrix
    return (a * x + c * y + e, b * x + d * y + f)


def _walk(el, matrix, xs, ys):
    matrix = _multiply(matrix, parse_transform(el.get('transform')))
    tag = el.tag.replace(NS, '')
    corners = []
    if tag == 'path' and el.get('d'):
        corners = symlib.path_points(el.get('d'))
    elif tag in ('circle', 'ellipse'):
        cx, cy = float(el.get('cx', 0)), float(el.get('cy', 0))
        rx = float(el.get('r') or el.get('rx') or 0)
        ry = float(el.get('r') or el.get('ry') or 0)
        corners = [(cx - rx, cy - ry), (cx + rx, cy - ry),
                   (cx - rx, cy + ry), (cx + rx, cy + ry)]
    elif tag == 'rect':
        x, y = float(el.get('x', 0)), float(el.get('y', 0))
        w, h = float(el.get('width', 0)), float(el.get('height', 0))
        corners = [(x, y), (x + w, y), (x, y + h), (x + w, y + h)]
    for px, py in corners:
        tx, ty = apply(matrix, px, py)
        xs.append(tx)
        ys.append(ty)
    for child in el:
        _walk(child, matrix, xs, ys)


def element_boxes(sym):
    """One bounding box per drawable child, each an indivisible unit.

    Nested transforms are applied: a child group carrying a translate places
    its geometry somewhere else entirely, and ignoring that put symbols in
    the wrong place and split them into phantom clusters.
    """
    boxes = []
    for child in sym.el:
        if child.tag == NS + 'title':
            continue
        xs, ys = [], []
        _walk(child, IDENTITY, xs, ys)
        if xs:
            boxes.append((child, (min(xs), min(ys), max(xs), max(ys))))
    return boxes


def cluster(boxes, gap=CLUSTER_GAP):
    """Group elements whose boxes lie within `gap` of each other."""
    parent = list(range(len(boxes)))

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    def near(b1, b2):
        dx = max(b1[0] - b2[2], b2[0] - b1[2], 0.0)
        dy = max(b1[1] - b2[3], b2[1] - b1[3], 0.0)
        return (dx * dx + dy * dy) ** 0.5 <= gap

    for i in range(len(boxes)):
        for j in range(i + 1, len(boxes)):
            if near(boxes[i][1], boxes[j][1]):
                a, b = find(i), find(j)
                if a != b:
                    parent[a] = b
    groups = {}
    for i in range(len(boxes)):
        groups.setdefault(find(i), []).append(i)
    return sorted(groups.values(), key=len, reverse=True)


def _union(boxes, idx):
    xs = [boxes[i][1][0] for i in idx] + [boxes[i][1][2] for i in idx]
    ys = [boxes[i][1][1] for i in idx] + [boxes[i][1][3] for i in idx]
    return (min(xs), min(ys), max(xs), max(ys))


def analyse(sym):
    """Split a symbol into its real device and any stray neighbouring geometry."""
    boxes = element_boxes(sym)
    if not boxes:
        return dict(symbol_id=sym.id, name=sym.name, empty=True,
                    status='empty', clusters=0)
    groups = cluster(boxes)
    main = groups[0]
    clean = _union(boxes, main)
    raw = sym.bbox
    raw_span = max(raw[2] - raw[0], raw[3] - raw[1])
    clean_span = max(clean[2] - clean[0], clean[3] - clean[1])

    reasons = []
    if len(groups) > 1:
        reasons.append(f'{len(groups)} disconnected geometry clusters')
    if clean_span > 1e-6 and raw_span > clean_span * 1.5 + 2:
        reasons.append(f'wrapper bbox {raw_span:.1f} mm vs device '
                       f'{clean_span:.1f} mm')
    if clean_span > 40:
        reasons.append(f'device itself spans {clean_span:.1f} mm')

    return dict(
        symbol_id=sym.id,
        name=sym.name,
        empty=False,
        clusters=len(groups),
        main_elements=[boxes[i][0] for i in main],
        stray_elements=[boxes[i][0] for g in groups[1:] for i in g],
        original_bbox=[round(v, 4) for v in raw],
        clean_bbox=[round(v, 4) for v in clean],
        status='needs_cleaning' if reasons else 'clean',
        flags=reasons,
    )


def _path_ends(el, matrix, ends):
    matrix = _multiply(matrix, parse_transform(el.get('transform')))
    if el.tag == NS + 'path' and el.get('d'):
        pts = symlib.path_points(el.get('d'))
        if pts:
            for pt in (pts[0], pts[-1]):
                tx, ty = apply(matrix, *pt)
                key = (round(tx, 3), round(ty, 3))
                ends[key] = ends.get(key, 0) + 1
    for child in el:
        _path_ends(child, matrix, ends)


def free_endpoints(elements):
    """Path ends that no other path shares -- candidate terminals."""
    ends = {}
    for child in elements:
        _path_ends(child, IDENTITY, ends)
    return sorted(k for k, v in ends.items() if v == 1)


def use_offsets(root):
    """Where each symbol is actually placed on the page.

    A <symbol>'s own coordinates are not where it is drawn: the sheet
    instantiates it through <use> with a translation.  Section assignment has
    to use the page position, or a symbol lands under the wrong heading.
    """
    xlink = '{http://www.w3.org/1999/xlink}href'
    layers = [g for g in root.iter(NS + 'g')
              if g.get('{http://www.inkscape.org/namespaces/inkscape}'
                       'groupmode') == 'layer']
    offsets = {}
    for layer in layers:
        for use in layer.iter(NS + 'use'):
            href = (use.get(xlink) or use.get('href') or '').lstrip('#')
            if not href:
                continue
            m = re.match(r'translate\(\s*([-\d.eE]+)[,\s]+([-\d.eE]+)\s*\)',
                         use.get('transform') or '')
            offsets.setdefault(href, (float(m.group(1)), float(m.group(2)))
                               if m else (0.0, 0.0))
    return offsets


def assign_section(clean_bbox, sections, offset=(0.0, 0.0)):
    """Nearest heading above the device, biased toward its own column."""
    x0, y0, x1, y1 = clean_bbox
    cx = (x0 + x1) / 2 + offset[0]
    cy = (y0 + y1) / 2 + offset[1]
    y1 = y1 + offset[1]
    best, score = None, None
    for name, hx, hy in sections:
        if hy > y1 + 6:
            continue
        value = (cy - hy) + abs(cx - hx) * 1.6
        if score is None or value < score:
            best, score = name, value
    return best or 'misc'


def semantic_name(sym, taken):
    """A stable, distinct name.  Variants are kept, never overwritten."""
    name = VARIANT_NAMES.get(sym.id) or slug(sym.name)
    if name not in taken:
        return name
    return f'{name}__{sym.id}'
