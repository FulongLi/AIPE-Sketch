"""The master sheet is the authoritative graphical source.

These tests guard the lookup priority -- library symbol first, then a
compound of library primitives, and custom geometry only as a last resort --
and that a placed symbol keeps the geometry the library gave it.
"""
import os
import re
import subprocess
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import build
from aipe_sketch import drawing_rules as dr
from aipe_sketch import symlib
from aipe_sketch.parts import CUSTOM, LIBRARY, Registry
from aipe_sketch.topologies import CATALOGUE

NAMES = sorted(CATALOGUE)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '_out')
_CACHE = {}
_REGISTRY = None


def registry():
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = Registry(symlib.load(build.SRC)[1])
    return _REGISTRY


def built(name):
    if name not in _CACHE:
        _CACHE[name] = build.build(name, out_dir=OUT)
    return _CACHE[name]


class TestLookupPriority(unittest.TestCase):
    """Standard devices must come from the library, never be redrawn."""

    STANDARD = ('nmos', 'igbt', 'diode', 'cap', 'cap_pol', 'res', 'ind',
                'ind_core', 'vsource', 'isource', 'battery', 'gnd')

    def test_standard_devices_come_from_the_library(self):
        for kind in self.STANDARD:
            spec = registry()[kind]
            self.assertEqual(spec.source, LIBRARY, kind)
            self.assertTrue(spec.symbol_id, f'{kind} has no symbol id')

    def test_every_library_symbol_id_exists_in_the_master_sheet(self):
        symbols = symlib.load(build.SRC)[1]
        for kind, spec in registry().items():
            if spec.source != LIBRARY:
                continue
            self.assertIn(spec.symbol_id, symbols,
                          f'{kind} names a symbol the sheet does not have')

    def test_compounds_are_built_only_from_library_symbols(self):
        for kind, spec in registry().items():
            if spec.source != 'compound':
                continue
            self.assertTrue(spec.compound['symbols'],
                            f'{kind} claims to be a compound but assembles '
                            f'nothing')
            for sub, *_ in spec.compound['symbols']:
                self.assertEqual(registry()[sub].source, LIBRARY,
                                 f'{kind} assembles from non-library {sub}')

    def test_the_transformer_comes_from_the_library(self):
        """It was a hand-assembled compound until the sheet's own symbol
        was recovered by handling rotate/scale transforms."""
        spec = registry()['transformer']
        self.assertEqual(spec.source, LIBRARY)
        self.assertEqual(spec.symbol_id, 'g7138')

    def test_custom_geometry_is_a_last_resort_and_justified(self):
        custom = [k for k, s in registry().items() if s.source == CUSTOM]
        self.assertEqual(custom, ['terminal'],
                         f'unexpected custom geometry: {custom}')
        for kind in custom:
            self.assertTrue(registry()[kind].reason,
                            f'{kind} is custom with no recorded reason')

    def test_no_drawing_uses_unjustified_custom_geometry(self):
        for name in NAMES:
            _, card, _, _ = built(name)
            self.assertEqual(card.raw['custom_symbols'], 0, name)


class TestRegistryAccess(unittest.TestCase):
    """Components are requested by semantic name, not built as paths."""

    def test_plain_engineering_names_resolve(self):
        for alias, kind in (('capacitor', 'cap'), ('resistor', 'res'),
                            ('inductor', 'ind'), ('voltage_source', 'vsource'),
                            ('current_source', 'isource'), ('mosfet', 'nmos'),
                            ('ground', 'gnd')):
            self.assertEqual(registry().get(alias).kind, kind, alias)
            self.assertIn(alias, registry())

    def test_metadata_matches_the_documented_schema(self):
        for kind, spec in registry().items():
            data = spec.as_dict()
            for key in ('symbol_id', 'ports', 'bbox', 'default_rotation',
                        'semantic_role', 'symbol_source', 'provenance'):
                self.assertIn(key, data, kind)

    def test_unknown_kind_returns_none_rather_than_raising(self):
        self.assertIsNone(registry().get('flux_capacitor'))


class TestGeometryPreserved(unittest.TestCase):
    """Translate, rotate and mirror only -- never stretch."""

    def test_no_placed_symbol_is_distorted(self):
        for name in NAMES:
            sch, card, _, _ = built(name)
            self.assertEqual(dr.symbol_integrity(sch.placed, sch.specs), [],
                             name)
            self.assertEqual(card.raw['symbol_distortion'], 0, name)

    def test_a_stretched_symbol_is_detected(self):
        sch, _, _, _ = built('buck')
        part = sch.placed['Q1']
        original = part.bbox
        try:
            x0, y0, x1, y1 = original
            part.bbox = (x0, y0, x0 + (x1 - x0) * 1.4, y1)
            faults = dr.symbol_integrity(sch.placed, sch.specs)
            self.assertTrue(any('scaled' in f for f in faults), faults)
        finally:
            part.bbox = original

    def test_a_non_right_angle_rotation_is_detected(self):
        sch, _, _, _ = built('buck')
        part = sch.placed['Q1']
        original = part.rot
        try:
            part.rot = 37
            faults = dr.symbol_integrity(sch.placed, sch.specs)
            self.assertTrue(any('right angle' in f for f in faults), faults)
        finally:
            part.rot = original

    def test_only_right_angle_rotations_are_used(self):
        for name in NAMES:
            sch, _, _, _ = built(name)
            for ref, part in sch.placed.items():
                self.assertEqual(part.rot % 90, 0, f'{name}/{ref}')


class TestExportedPreviews(unittest.TestCase):
    """Generated artefacts: stamped, reproducible, and never required."""

    @classmethod
    def setUpClass(cls):
        cls.dir = os.path.join(ROOT, 'assets', 'generated_symbols')
        subprocess.run([sys.executable, 'tools/export_symbols.py'],
                       cwd=ROOT, check=True, capture_output=True)

    def test_a_preview_exists_for_every_kind(self):
        for kind in registry():
            self.assertTrue(
                os.path.exists(os.path.join(self.dir, f'{kind}.svg')), kind)

    def test_every_preview_records_its_provenance(self):
        for kind, spec in registry().items():
            with open(os.path.join(self.dir, f'{kind}.svg')) as fh:
                text = fh.read()
            self.assertIn('Inkscape_Symbols_All.svg', text, kind)
            self.assertIn(f'kind="{kind}"', text)
            self.assertIn('source-version=', text, kind)
            self.assertIn(f'symbol-source="{spec.source}"', text)
            if spec.symbol_id:
                self.assertIn(f'source-symbol="{spec.symbol_id}"', text)

    def test_the_source_version_is_a_digest_not_a_clock(self):
        """Two runs over the same master must be byte-identical."""
        with open(os.path.join(self.dir, 'nmos.svg'), 'rb') as fh:
            first = fh.read()
        subprocess.run([sys.executable, 'tools/export_symbols.py', 'nmos'],
                       cwd=ROOT, check=True, capture_output=True)
        with open(os.path.join(self.dir, 'nmos.svg'), 'rb') as fh:
            second = fh.read()
        self.assertEqual(first, second, 'export is not reproducible')

    def test_the_version_tracks_the_master_sheet(self):
        sys.path.insert(0, os.path.join(ROOT, 'tools'))
        import export_symbols
        self.assertRegex(export_symbols.source_version(), r'^[0-9a-f]{16}$')

    def test_rendering_never_reads_the_previews(self):
        for module in ('pipeline', 'placement', 'sketch', 'parts', 'score'):
            path = os.path.join(ROOT, 'aipe_sketch', f'{module}.py')
            with open(path) as fh:
                source = fh.read()
            self.assertNotIn('generated_symbols', source, module)

    def test_a_drawing_builds_with_the_previews_deleted(self):
        import shutil
        backup = self.dir + '.bak'
        shutil.move(self.dir, backup)
        try:
            _, card, _, _ = build.build('buck', out_dir=OUT)
            self.assertEqual(card.sub['connectivity'], 100)
        finally:
            shutil.move(backup, self.dir)


class TestAudit(unittest.TestCase):
    """The provenance report must name every kind and its source."""

    def test_report_lists_every_kind(self):
        import io
        sys.path.insert(0, os.path.join(ROOT, 'tools'))
        import export_symbols
        stream = io.StringIO()
        rows = export_symbols.report(registry(), stream)
        text = stream.getvalue()
        self.assertEqual(len(rows), len(list(registry())))
        for kind, spec in registry().items():
            self.assertIn(kind, text)
        self.assertIn('library', text)
        self.assertIn('custom', text)
        self.assertIn('from the library', text)

    def test_report_matches_the_registry(self):
        for row in registry().audit():
            spec = registry()[row['kind']]
            self.assertEqual(row['source'], spec.source)
            self.assertEqual(row['symbol_id'], spec.symbol_id or '')


if __name__ == '__main__':
    os.makedirs(OUT, exist_ok=True)
    unittest.main(verbosity=2)
