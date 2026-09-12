#!/usr/bin/env python3
"""Export individual symbol previews from the master sheet.

Generated artefacts, useful for debugging, documentation, inspection and
tests. They are NOT the canonical editable source and nothing in the
rendering path reads them: the master sheet stays authoritative and is always
parsed directly.

Each file records where it came from, so a stale preview is obvious:
source master file, source symbol id, semantic kind, and a source version
that is a digest of the master sheet rather than a wall-clock time -- which
keeps two runs over the same master byte-for-byte identical.

    python3 tools/export_symbols.py                 # every registered kind
    python3 tools/export_symbols.py nmos igbt cap   # a subset
    python3 tools/export_symbols.py --json          # registry metadata only
    python3 tools/export_symbols.py --report        # provenance audit
"""
import hashlib
import json
import os
import sys
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aipe_sketch import symlib
from aipe_sketch.parts import Registry
from aipe_sketch.pins import COARSE as G
from aipe_sketch.sketch import Sketch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
from aipe_sketch.paths import GENERATED as OUT, MASTER as SRC
OUT = os.path.join(ROOT, 'assets', 'generated_symbols')
AIPE_NS = 'https://github.com/AIPE-Sketch/symbol'
PAD = 2.0                      # millimetres of margin around the symbol
NS = symlib.NS


def source_version(path=SRC):
    """A digest of the master sheet: reproducible, unlike a timestamp."""
    with open(path, 'rb') as fh:
        return hashlib.blake2s(fh.read(), digest_size=8).hexdigest()


def _stamp(sketch, kind, spec, version):
    """Record provenance inside the generated file."""
    ET.register_namespace('aipe', AIPE_NS)
    meta = ET.Element('{%s}generated' % AIPE_NS, {
        'source-file': os.path.basename(SRC),
        'source-symbol': spec.symbol_id or '',
        'source-version': version,
        'kind': kind,
        'symbol-source': spec.source,
        'provenance': spec.provenance,
        'generator': 'tools/export_symbols.py',
    })
    note = ET.Comment(
        f' generated from {os.path.basename(SRC)} '
        f'[{version}] -- {spec.provenance}; regenerate, do not edit ')
    sketch.svg.insert(0, meta)
    sketch.svg.insert(0, note)


def export(kind, registry, out_dir, annotate=True, version=None):
    """Render one symbol on its own, optionally with its ports marked."""
    spec = registry[kind]
    version = version or source_version()
    x0, y0, x1, y1 = spec.bbox
    for _, (px, py) in spec.ports.items():
        x0, y0 = min(x0, px), min(y0, py)
        x1, y1 = max(x1, px), max(y1, py)
    w, h = (x1 - x0) + 2 * PAD, (y1 - y0) + 2 * PAD
    cx, cy = PAD - x0, PAD - y0

    sketch = Sketch(SRC, w, h, f'{kind} symbol')
    if spec.compound is None:
        sketch.place(kind, cx, cy)
    else:
        for sub, dx, dy, rot, mirror in spec.compound['symbols']:
            sketch.place(sub, cx + dx, cy + dy, rot=rot, mirror=mirror)
    for a, b in spec.decor.get('strokes', ()):
        sketch.wire((cx + a[0], cy + a[1]), (cx + b[0], cy + b[1]))
    for ox, oy, r in spec.decor.get('circles', ()):
        sketch.open_circle(cx + ox, cy + oy, r)
    for tx, ty, text, size in spec.decor.get('texts', ()):
        sketch.label(cx + tx, cy + ty, text, size=size, anchor='middle',
                     italic=False)

    if annotate:
        for name, (px, py) in sorted(spec.ports.items()):
            ET.SubElement(sketch.layer, NS + 'circle', {
                'cx': str(round(cx + px, 4)), 'cy': str(round(cy + py, 4)),
                'r': '0.45', 'style': 'fill:none;stroke:#e01b24;'
                                      'stroke-width:0.15'})
            sketch.label(cx + px + 0.9, cy + py - 0.6, name, size=1.6,
                         anchor='start', italic=False)
        bx0, by0, bx1, by1 = spec.margin_box()
        ET.SubElement(sketch.layer, NS + 'rect', {
            'x': str(round(cx + bx0, 4)), 'y': str(round(cy + by0, 4)),
            'width': str(round(bx1 - bx0, 4)),
            'height': str(round(by1 - by0, 4)),
            'style': 'fill:none;stroke:#3584e4;stroke-width:0.1;'
                     'stroke-dasharray:0.4,0.4'})

    _stamp(sketch, kind, spec, version)
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f'{kind}.svg')
    sketch.save(path)
    return path


def report(registry, stream=sys.stdout):
    """Provenance audit: which kinds come from the library, and which do not."""
    rows = registry.audit()
    width = max(len(r['kind']) for r in rows)
    print(f'{"kind".ljust(width)}  source           symbol      ports',
          file=stream)
    for r in rows:
        print(f'{r["kind"].ljust(width)}  {r["source"]:<15}  '
              f'{r["symbol_id"] or "-":<10}  {",".join(r["ports"])}',
              file=stream)
    tally = {}
    for r in rows:
        tally[r['source']] = tally.get(r['source'], 0) + 1
    print('\n' + ', '.join(f'{v} {k}' for k, v in sorted(tally.items())),
          file=stream)
    for r in rows:
        if r['reason']:
            print(f'  {r["kind"]}: {r["reason"]}', file=stream)
    return rows


def main(argv):
    registry = Registry(symlib.load(SRC)[1])
    if '--report' in argv:
        report(registry)
        return 0
    if '--json' in argv:
        os.makedirs(OUT, exist_ok=True)
        path = os.path.join(OUT, 'registry.json')
        with open(path, 'w') as fh:
            json.dump(registry.as_dict(), fh, indent=2, sort_keys=True)
        print(f'{path}  ({len(registry.as_dict())} kinds)')
        return 0
    kinds = [a for a in argv if not a.startswith('--')] or sorted(registry)
    annotate = '--plain' not in argv
    version = source_version()
    for kind in kinds:
        if kind not in registry:
            print(f'unknown kind {kind!r}', file=sys.stderr)
            continue
        path = export(kind, registry, OUT, annotate, version)
        print(os.path.relpath(path, ROOT))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
