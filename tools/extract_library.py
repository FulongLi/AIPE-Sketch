#!/usr/bin/env python3
"""Extract the master sheet into a clean, per-section component library.

    python3 tools/extract_library.py --report
    python3 tools/extract_library.py --section standard_elements --catalog
    python3 tools/extract_library.py --all --catalog

The master SVG stays canonical.  Everything written under
assets/generated_symbols/ is derived and may be regenerated at any time.
Nothing here redraws a component: geometry is copied out of the sheet,
unrelated neighbouring geometry is dropped, and the result is normalised
around a local origin.
"""
import argparse
import copy
import hashlib
import json
import os
import sys
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aipe_sketch import config, library, symlib, typography
from aipe_sketch.paths import EXTRACTED, MASTER, MASTER_NAME, OUT, REGISTRY_JSON
from aipe_sketch.pins import PARTS as CURATED

NS = symlib.NS
AIPE_NS = 'https://github.com/AIPE-Sketch/symbol'
PAD = 1.5                       # millimetres of margin in a preview
ET.register_namespace('', 'http://www.w3.org/2000/svg')
ET.register_namespace('aipe', AIPE_NS)

CURATED_BY_ID = {entry['sym']: kind for kind, entry in CURATED.items()}


def master_version():
    with open(MASTER, 'rb') as fh:
        return hashlib.blake2s(fh.read(), digest_size=8).hexdigest()


# ------------------------------------------------------------------ inventory
def inventory():
    """Every symbol, cleaned, named and assigned to the section it came from."""
    root, symbols = symlib.load(MASTER)
    sections = library.detect_sections(root)
    offsets = library.use_offsets(root)
    defs = list(root.iter(NS + 'defs'))[0]

    taken, entries = set(), []
    for sym in sorted(symbols.values(), key=lambda s: s.id):
        info = library.analyse(sym)
        if info.get('empty'):
            continue
        offset = offsets.get(sym.id, (0.0, 0.0))
        section = library.slug(library.assign_section(info['clean_bbox'],
                                                      sections, offset))
        name = library.semantic_name(sym, taken)
        taken.add(name)
        entries.append(dict(
            semantic_name=name,
            original_symbol_id=sym.id,
            title=sym.name,
            source_section=section,
            source_file=MASTER_NAME,
            original_bbox=info['original_bbox'],
            clean_bbox=info['clean_bbox'],
            status=info['status'],
            flags=info['flags'],
            clusters=info['clusters'],
            default_orientation='vertical',
            source_type='extracted_library',
            curated_as=CURATED_BY_ID.get(sym.id),
            page_offset=[round(v, 4) for v in offset],
            port_candidates=[list(p) for p in
                             library.free_endpoints(info['main_elements'])],
            _main=info['main_elements'],
        ))
    return entries, sections, defs


# ------------------------------------------------------------------ export
def write_symbol(entry, defs, version, out_root=EXTRACTED):
    """One standalone preview, normalised to a local origin."""
    x0, y0, x1, y1 = entry['clean_bbox']
    w, h = (x1 - x0) + 2 * PAD, (y1 - y0) + 2 * PAD
    svg = ET.Element(NS + 'svg', {
        'width': f'{w:.4f}mm', 'height': f'{h:.4f}mm',
        'viewBox': f'0 0 {w:.4f} {h:.4f}', 'version': '1.1'})
    svg.append(ET.Comment(
        f' extracted from {MASTER_NAME} [{version}] symbol '
        f'{entry["original_symbol_id"]}; generated, do not edit '))
    ET.SubElement(svg, '{%s}extracted' % AIPE_NS, {
        'semantic-name': entry['semantic_name'],
        'original-symbol-id': entry['original_symbol_id'],
        'source-section': entry['source_section'],
        'source-file': entry['source_file'],
        'source-version': version,
        'source-type': entry['source_type'],
        'status': entry['status'],
        'original-bbox': ' '.join(f'{v:g}' for v in entry['original_bbox']),
        'clean-bbox': ' '.join(f'{v:g}' for v in entry['clean_bbox']),
        'anchor': '0 0',
        'default-orientation': entry['default_orientation'],
    })
    ET.SubElement(svg, NS + 'title').text = entry['semantic_name']
    kept = ET.SubElement(svg, NS + 'defs')
    for child in defs:
        kept.append(copy.deepcopy(child))
    # normalise: the tight box's top-left lands at (PAD, PAD)
    group = ET.SubElement(svg, NS + 'g', {
        'transform': f'translate({PAD - x0:.4f},{PAD - y0:.4f})'})
    for element in entry['_main']:
        group.append(copy.deepcopy(element))

    folder = os.path.join(out_root, entry['source_section'])
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, f'{entry["semantic_name"]}.svg')
    ET.ElementTree(svg).write(path, xml_declaration=True, encoding='utf-8')
    return path


def write_registry(entries, version, path=REGISTRY_JSON):
    index = {}
    for e in entries:
        x0, y0, x1, y1 = e['clean_bbox']
        index[e['semantic_name']] = {
            'section': e['source_section'],
            'file': os.path.relpath(
                os.path.join(EXTRACTED, e['source_section'],
                             f'{e["semantic_name"]}.svg'),
                os.path.dirname(os.path.dirname(EXTRACTED))),
            'symbol_id': e['original_symbol_id'],
            'title': e['title'],
            'source_file': e['source_file'],
            'source_type': e['source_type'],
            'status': e['status'],
            'flags': e['flags'],
            'bbox': {'x': round(x0, 4), 'y': round(y0, 4),
                     'width': round(x1 - x0, 4), 'height': round(y1 - y0, 4)},
            'original_bbox': e['original_bbox'],
            'anchor': [0.0, 0.0],
            'default_orientation': e['default_orientation'],
            'ports': (sorted(CURATED[e['curated_as']]['pins'])
                      if e['curated_as'] else None),
            'port_candidates': e['port_candidates'],
            'curated_as': e['curated_as'],
        }
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as fh:
        json.dump({'source_file': MASTER_NAME, 'source_version': version,
                   'symbols': index}, fh, indent=2, sort_keys=True)
    return path


# ------------------------------------------------------------------ catalogue
def write_catalogue(entries, section, defs, out_dir=OUT):
    members = [e for e in entries if e['source_section'] == section]
    if not members:
        return None
    cols = 6
    cw, ch = 30.0, 34.0
    rows = (len(members) + cols - 1) // cols
    svg = ET.Element(NS + 'svg', {
        'width': f'{cols * cw}mm', 'height': f'{rows * ch}mm',
        'viewBox': f'0 0 {cols * cw} {rows * ch}', 'version': '1.1'})
    ET.SubElement(svg, NS + 'rect', {
        'x': '0', 'y': '0', 'width': str(cols * cw), 'height': str(rows * ch),
        'fill': '#ffffff'})
    kept = ET.SubElement(svg, NS + 'defs')
    for child in defs:
        kept.append(copy.deepcopy(child))

    for i, e in enumerate(sorted(members, key=lambda m: m['semantic_name'])):
        x0, y0, x1, y1 = e['clean_bbox']
        cx = (i % cols) * cw + cw / 2
        cy = (i // cols) * ch + ch / 2 - 3
        scale = min(1.0, 20.0 / max(1e-6, max(x1 - x0, y1 - y0)))
        g = ET.SubElement(svg, NS + 'g', {
            'transform': f'translate({cx},{cy}) scale({scale:.4f}) '
                         f'translate({-(x0 + x1) / 2},{-(y0 + y1) / 2})'})
        for element in e['_main']:
            g.append(copy.deepcopy(element))
        for text, dy, size, fill in (
                (e['semantic_name'], ch - 7.0, 2.0, '#000000'),
                (f'{e["original_symbol_id"]}  '
                 f'{x1 - x0:.1f}x{y1 - y0:.1f}', ch - 4.6, 1.5, '#777777'),
                (e['status'], ch - 2.2, 1.5,
                 '#c01c28' if e['status'] != 'clean' else '#2ec27e')):
            t = ET.SubElement(svg, NS + 'text', {
                'x': str(cx), 'y': str((i // cols) * ch + dy),
                'text-anchor': 'middle',
                'style': (f'font-size:{size}px;'
                          f'font-family:{config.FONT_FAMILY_CSS};'
                          f'font-weight:{config.FONT_WEIGHT};fill:{fill}')})
            t.text = text
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f'catalog_{section}.svg')
    typography.apply_svg_font(svg)
    ET.ElementTree(svg).write(path, xml_declaration=True, encoding='utf-8')
    return path


# ------------------------------------------------------------------ report
def report(entries, sections, stream=sys.stdout):
    by_section = {}
    for e in entries:
        by_section.setdefault(e['source_section'], []).append(e)
    print(f'{len(entries)} symbols across {len(by_section)} sections '
          f'({len(sections)} headings detected on the sheet)\n', file=stream)
    summary = {}
    for section in sorted(by_section, key=lambda s: -len(by_section[s])):
        members = by_section[section]
        clean = [m for m in members if m['status'] == 'clean']
        dirty = [m for m in members if m['status'] != 'clean']
        summary[section] = dict(total=len(members), clean=len(clean),
                                needs_cleaning=len(dirty))
        print(f'{section}', file=stream)
        print(f'  {len(members)} detected, {len(clean)} clean, '
              f'{len(dirty)} need cleaning', file=stream)
        print(f'  extracted: '
              f'{", ".join(sorted(m["semantic_name"] for m in members)[:10])}'
              f'{" ..." if len(members) > 10 else ""}', file=stream)
        for m in dirty[:4]:
            print(f'    {m["semantic_name"]} ({m["original_symbol_id"]}): '
                  f'{"; ".join(m["flags"])}', file=stream)
        print(file=stream)
    return summary


# ------------------------------------------------------------------ cli
def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--section', action='append', default=[],
                    help='section slug to extract (repeatable)')
    ap.add_argument('--all', action='store_true', help='every section')
    ap.add_argument('--catalog', action='store_true',
                    help='also write a review catalogue per section')
    ap.add_argument('--report', action='store_true',
                    help='print the inventory and exit')
    ap.add_argument('--json', help='write the report summary here')
    ap.add_argument('--report-file', help='write the human report here')
    args = ap.parse_args(argv)

    entries, sections, defs = inventory()
    version = master_version()

    if args.report and not (args.section or args.all):
        summary = report(entries, sections)
        _write_reports(entries, sections, summary, args)
        return 0

    wanted = set(args.section)
    if args.all or not wanted:
        wanted = {e['source_section'] for e in entries}
    chosen = [e for e in entries if e['source_section'] in wanted]
    if not chosen:
        print(f'no symbols in {sorted(wanted)}; known sections: '
              f'{sorted({e["source_section"] for e in entries})}',
              file=sys.stderr)
        return 1

    for e in chosen:
        write_symbol(e, defs, version)
    print(f'{len(chosen)} symbols written to '
          f'{os.path.relpath(EXTRACTED, os.getcwd())}')
    print(f'registry: {os.path.relpath(write_registry(entries, version))}')

    if args.catalog:
        for section in sorted(wanted):
            path = write_catalogue(entries, section, defs)
            if path:
                print(f'catalogue: {os.path.relpath(path)}')
    if args.report:
        print()
        summary = report(entries, sections)
        _write_reports(entries, sections, summary, args)
    return 0


def _write_reports(entries, sections, summary, args):
    if args.json:
        with open(args.json, 'w') as fh:
            json.dump({'sections': summary,
                       'symbols': [{k: v for k, v in e.items()
                                    if not k.startswith('_')}
                                   for e in entries]},
                      fh, indent=2, sort_keys=True)
        print(f'report json: {os.path.relpath(args.json)}')
    if args.report_file:
        os.makedirs(os.path.dirname(os.path.abspath(args.report_file)),
                    exist_ok=True)
        with open(args.report_file, 'w') as fh:
            report(entries, sections, fh)
        print(f'report: {os.path.relpath(args.report_file)}')


if __name__ == '__main__':
    sys.exit(main())
