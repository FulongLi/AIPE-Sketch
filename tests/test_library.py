"""Extraction of the master sheet into a per-section component library.

Guards that geometry is copied rather than redrawn, that nested transforms
are honoured, that dirty wrappers are detected rather than discarded, and
that the registry and previews stay in step with the master.
"""
import json
import os
import subprocess
import sys
import unittest
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aipe_sketch import library, symlib
from aipe_sketch.paths import GENERATED, MASTER, REGISTRY_JSON, ROOT

NS = symlib.NS
_LOADED = None


def sheet():
    global _LOADED
    if _LOADED is None:
        _LOADED = symlib.load(MASTER)
    return _LOADED


class TestSectionDetection(unittest.TestCase):
    def test_sections_come_from_the_sheet(self):
        root, _ = sheet()
        names = {s[0] for s in library.detect_sections(root)}
        self.assertIn('Standard Elements', names)
        self.assertIn('Sources', names)
        self.assertGreaterEqual(len(names), 15)

    def test_in_drawing_text_is_not_mistaken_for_a_heading(self):
        root, _ = sheet()
        names = {s[0] for s in library.detect_sections(root)}
        for stray in ('+', '-', 'n:1', 'f(t)', 't', 'V1', 'Diac'):
            self.assertNotIn(stray, names)

    def test_symbols_are_placed_by_page_position(self):
        """A symbol's own frame is not where it is drawn."""
        root, _ = sheet()
        offsets = library.use_offsets(root)
        self.assertTrue(any(o != (0.0, 0.0) for o in offsets.values()))
        self.assertIn('g5754', offsets)


class TestClustering(unittest.TestCase):
    def test_nested_transforms_are_applied(self):
        """A child group carrying a translate puts geometry elsewhere."""
        _, syms = sheet()
        boxes = library.element_boxes(syms['g10556'])
        span = max(b[2] - b[0] for _, b in boxes)
        self.assertLess(span, 12.0,
                        'the nested diode was measured in the wrong frame')

    def test_a_capacitor_stays_one_cluster(self):
        _, syms = sheet()
        info = library.analyse(syms['g8210'])
        self.assertEqual(info['clusters'], 1)
        x0, y0, x1, y1 = info['clean_bbox']
        self.assertAlmostEqual(y1 - y0, 10.583, places=2)

    def test_neighbouring_components_do_not_merge(self):
        _, syms = sheet()
        info = library.analyse(syms['g7416'])          # Resistor_US
        x0, _, x1, _ = info['clean_bbox']
        self.assertLess(x1 - x0, 4.0, 'a neighbour merged into the resistor')

    def test_dirty_wrappers_are_flagged_not_discarded(self):
        _, syms = sheet()
        info = library.analyse(syms['g7138'])          # Transformer
        self.assertEqual(info['status'], 'needs_cleaning')
        self.assertTrue(info['flags'])
        self.assertTrue(info['main_elements'],
                        'a dirty symbol must still yield its device')

    def test_cleaning_shrinks_the_box_to_the_device(self):
        _, syms = sheet()
        info = library.analyse(syms['g7138'])
        raw = info['original_bbox']
        clean = info['clean_bbox']
        self.assertGreater(raw[2] - raw[0], 100)
        self.assertLess(clean[2] - clean[0], 12)


class TestExtraction(unittest.TestCase):
    """Geometry is copied out of the sheet, never redrawn."""

    @classmethod
    def setUpClass(cls):
        subprocess.run([sys.executable, 'tools/extract_library.py', '--all'],
                       cwd=ROOT, check=True, capture_output=True)
        with open(REGISTRY_JSON) as fh:
            cls.registry = json.load(fh)

    def test_registry_indexes_every_symbol(self):
        _, syms = sheet()
        self.assertGreaterEqual(len(self.registry['symbols']),
                                len(syms) - 10)
        self.assertIn('source_version', self.registry)

    def test_every_entry_records_its_provenance(self):
        for name, entry in self.registry['symbols'].items():
            for key in ('section', 'file', 'symbol_id', 'source_file',
                        'source_type', 'status', 'bbox', 'original_bbox',
                        'anchor', 'default_orientation'):
                self.assertIn(key, entry, name)
            self.assertEqual(entry['source_type'], 'extracted_library')

    def test_previews_exist_where_the_registry_says(self):
        for name, entry in self.registry['symbols'].items():
            path = os.path.join(ROOT, entry['file'])
            self.assertTrue(os.path.exists(path), f'{name}: {entry["file"]}')

    def test_files_are_grouped_by_section(self):
        for name, entry in self.registry['symbols'].items():
            self.assertIn(f'/{entry["section"]}/', entry['file'], name)

    def test_extracted_geometry_matches_the_master(self):
        """Element ids in a preview must exist in the master symbol."""
        _, syms = sheet()
        for name in ('capacitor__g8210', 'inductor_air_core',
                     'mosfet_n_enhancement'):
            entry = self.registry['symbols'][name]
            tree = ET.parse(os.path.join(ROOT, entry['file']))
            drawn = {e.get('id') for e in tree.getroot().iter()
                     if e.get('id') and e.tag.startswith(NS)}
            master = {e.get('id') for e in syms[entry['symbol_id']].el.iter()
                      if e.get('id')}
            self.assertTrue(drawn & master,
                            f'{name} shares no element with its source symbol')

    def test_variants_are_kept_distinct(self):
        names = set(self.registry['symbols'])
        for a, b in (('capacitor__g8210', 'capacitor_polarised'),
                     ('inductor_air_core', 'inductor_cored'),
                     ('mosfet_n_enhancement', 'mosfet_n_depletion')):
            self.assertIn(a, names)
            self.assertIn(b, names)
            self.assertNotEqual(self.registry['symbols'][a]['symbol_id'],
                                self.registry['symbols'][b]['symbol_id'])

    def test_dirty_symbols_are_kept_with_status(self):
        dirty = [n for n, e in self.registry['symbols'].items()
                 if e['status'] == 'needs_cleaning']
        self.assertTrue(dirty, 'nothing was flagged; detection is not running')
        for name in dirty:
            self.assertTrue(os.path.exists(
                os.path.join(ROOT, self.registry['symbols'][name]['file'])),
                f'{name} was discarded instead of flagged')

    def test_standard_elements_holds_the_expected_devices(self):
        section = {n for n, e in self.registry['symbols'].items()
                   if e['section'] == 'standard_elements'}
        for want in ('capacitor__g8210', 'inductor_air_core', 'resistor',
                     'diode', 'mosfet_n_enhancement', 'thyristor'):
            self.assertIn(want, section)

    def test_extraction_is_reproducible(self):
        path = os.path.join(GENERATED, 'standard_elements', 'resistor.svg')
        with open(path, 'rb') as fh:
            first = fh.read()
        subprocess.run([sys.executable, 'tools/extract_library.py',
                        '--section', 'standard_elements'],
                       cwd=ROOT, check=True, capture_output=True)
        with open(path, 'rb') as fh:
            self.assertEqual(fh.read(), first)

    def test_previews_are_normalised_to_a_local_origin(self):
        path = os.path.join(GENERATED, 'standard_elements', 'resistor.svg')
        root = ET.parse(path).getroot()
        self.assertTrue(root.get('viewBox').startswith('0 0'))
        stamp = root.find('{https://github.com/AIPE-Sketch/symbol}extracted')
        self.assertIsNotNone(stamp)
        self.assertEqual(stamp.get('anchor'), '0 0')


class TestMasterIsCanonical(unittest.TestCase):
    def test_master_lives_under_assets(self):
        self.assertTrue(MASTER.endswith(
            os.path.join('assets', 'master', 'Inkscape_Symbols_All.svg')))
        self.assertTrue(os.path.exists(MASTER))

    def test_rendering_does_not_read_generated_files(self):
        for module in ('pipeline', 'placement', 'parts', 'sketch'):
            with open(os.path.join(ROOT, 'aipe_sketch',
                                   f'{module}.py')) as fh:
                source = fh.read()
            self.assertNotIn('generated_symbols', source, module)
            self.assertNotIn('symbol_registry.json', source, module)


if __name__ == '__main__':
    unittest.main(verbosity=2)
