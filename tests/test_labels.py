"""Global label placement, applied identically to every topology.

A fix is not complete if it solves one converter while breaking another, so
every check here runs across the whole catalogue.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import build
from aipe_sketch import config, labels
from aipe_sketch.labels import LabelPlacer, overlaps, preferred_side
from aipe_sketch.topologies import CATALOGUE

NAMES = sorted(CATALOGUE)
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '_out')
_CACHE = {}


def built(name):
    if name not in _CACHE:
        _CACHE[name] = build.build(name, out_dir=OUT)
    return _CACHE[name]


class TestNoCollisions(unittest.TestCase):
    """Rule 7: fatal conditions, checked on every drawing."""

    def test_no_label_overlaps_a_component_body(self):
        for name in NAMES:
            sch, _, _, _ = built(name)
            bodies = [p for p in sch.placed.values()
                      if p.spec.width > 0 or p.spec.height > 0]
            for ref, box in sch.labels:
                for part in bodies:
                    if part.ref == ref:
                        continue
                    self.assertFalse(overlaps(box, part.bbox),
                                     f'{name}: label {ref} over {part.ref}')

    def test_no_label_overlaps_another_label(self):
        for name in NAMES:
            sch, _, _, _ = built(name)
            for i, (ref_a, box_a) in enumerate(sch.labels):
                for ref_b, box_b in sch.labels[i + 1:]:
                    self.assertFalse(overlaps(box_a, box_b),
                                     f'{name}: {ref_a} over {ref_b}')

    def test_no_label_sits_on_a_wire(self):
        for name in NAMES:
            _, card, _, _ = built(name)
            self.assertEqual(card.raw['label_overlap'], 0, f'{name}\n{card}')

    def test_no_label_covers_a_junction_or_terminal_marker(self):
        from aipe_sketch import router
        for name in NAMES:
            sch, _, _, _ = built(name)
            dots = []
            for net, net_paths in sch.paths.items():
                terms = [sch.placed[r].port(p)
                         for r, p in sch.netlist.nets.get(net, [])
                         if r in sch.placed]
                dots += router.junction_points(net_paths, terms)
            markers = [(p.marker[0], p.marker[1], p.marker[2])
                       for p in sch.placed.values() if p.marker]
            for ref, box in sch.labels:
                for x, y in dots:
                    r = config.JUNCTION_R_MM
                    self.assertFalse(overlaps(box, (x - r, y - r,
                                                    x + r, y + r)),
                                     f'{name}: {ref} covers a junction')
                for x, y, r in markers:
                    self.assertFalse(overlaps(box, (x - r, y - r,
                                                    x + r, y + r)),
                                     f'{name}: {ref} covers a terminal')

    def test_every_label_found_a_home(self):
        for name in NAMES:
            sch, _, _, _ = built(name)
            self.assertEqual(sch.homeless_labels, [], name)


class TestClearanceMargin(unittest.TestCase):
    """Rule 2: clearance, not merely non-overlap."""

    def test_padding_matches_the_specified_range(self):
        from aipe_sketch.pins import COARSE as G
        self.assertGreaterEqual(config.LABEL_PAD_X_MM, 0.4 * G)
        self.assertLessEqual(config.LABEL_PAD_X_MM, 0.6 * G)
        self.assertGreaterEqual(config.LABEL_PAD_Y_MM, 0.3 * G)
        self.assertLessEqual(config.LABEL_PAD_Y_MM, 0.5 * G)

    def test_the_keepout_box_is_larger_than_the_ink(self):
        ink = labels.ink_bbox(0, 0, 'C', '1')
        keep = labels.text_bbox(0, 0, 'C', '1')
        self.assertLess(keep[0], ink[0])
        self.assertGreater(keep[2], ink[2])
        self.assertLess(keep[1], ink[1])
        self.assertGreater(keep[3], ink[3])


class TestPreferredSides(unittest.TestCase):
    """Rules 3, 6: registry preferences, rotation-aware."""

    def test_horizontal_passives_are_labelled_above(self):
        for name in NAMES:
            sch, _, _, _ = built(name)
            for ref, part in sch.placed.items():
                if part.rot % 180 and part.label and \
                        part.spec.role in ('magnetic', 'filter', 'load',
                                           'rectifier'):
                    self.assertEqual(part.label_side, 'above',
                                     f'{name}/{ref}')

    def test_switches_are_labelled_beside_the_body(self):
        for name in NAMES:
            sch, _, _, _ = built(name)
            for ref, part in sch.placed.items():
                if part.spec.role == 'power_switch' and part.label:
                    self.assertIn(part.label_side, ('left', 'right'),
                                  f'{name}/{ref}')

    def test_rotation_maps_sides_consistently(self):
        for side, expected in (('right', 'above'), ('left', 'below'),
                               ('above', 'left'), ('below', 'right')):
            self.assertEqual(labels.rotated_side(side, -90), expected)

    def test_most_labels_land_on_their_preferred_side(self):
        """Fallbacks exist, but should stay rare."""
        total = moved = 0
        for name in NAMES:
            sch, _, _, _ = built(name)
            for part in sch.placed.values():
                if not part.label:
                    continue
                total += 1
                if part.label_side != preferred_side(part):
                    moved += 1
        self.assertLess(moved / max(1, total), 0.15,
                        f'{moved} of {total} labels needed a fallback')


class TestConsistency(unittest.TestCase):
    """Rule 4: equivalent components share an offset."""

    def test_label_offsets_are_consistent(self):
        for name in NAMES:
            _, card, _, _ = built(name)
            self.assertEqual(card.raw['label_distance'], 0, f'{name}\n{card}')

    def test_equivalent_components_share_a_side(self):
        for name in NAMES:
            _, card, _, _ = built(name)
            self.assertEqual(card.raw['label_side'], 0, f'{name}\n{card}')


class TestEngineIsGlobal(unittest.TestCase):
    """Rules 1, 9: one engine, no per-topology label choices."""

    def test_topologies_do_not_choose_label_positions(self):
        import aipe_sketch.topologies as topo
        with open(topo.__file__) as fh:
            source = fh.read()
        for hack in ('label_side=', 'label_offset='):
            self.assertNotIn(hack, source,
                             f'topology code still sets {hack}')

    def test_the_engine_rejects_an_overlapping_position(self):
        """Blocking every side must yield no placement, never a bad one."""
        sch, _, _, _ = built('buck')
        placer = LabelPlacer(sch.placed, sch.paths)
        part = sch.placed['Q1']
        huge = (part.bbox[0] - 500, part.bbox[1] - 500,
                part.bbox[2] + 500, part.bbox[3] + 500)
        placer.reserve('wall', huge)
        self.assertIsNone(placer.place(part))

    def test_placement_is_deterministic(self):
        first = {r: (p.label_side, round(p.x, 4))
                 for r, p in built('dab')[0].placed.items()}
        _CACHE.pop('dab')
        second = {r: (p.label_side, round(p.x, 4))
                  for r, p in built('dab')[0].placed.items()}
        self.assertEqual(first, second)


class TestConstantsCentralised(unittest.TestCase):
    """Rules 11, 14: one authoritative definition per value."""

    def test_modules_read_config_rather_than_redefining(self):
        import aipe_sketch.drawing_rules as dr
        import aipe_sketch.pipeline as pipeline
        from aipe_sketch import parts, plan, sketch
        self.assertEqual(dr.LABEL_PAD_X, config.LABEL_PAD_X_MM)
        self.assertEqual(pipeline.LABEL_PAD_X, config.LABEL_PAD_X_MM)
        self.assertEqual(dr.CELL, config.CELL_MM)
        self.assertEqual(plan.CELL, config.CELL_G)
        self.assertEqual(plan.GAP_SERIES_PASSIVE, config.GAP_SERIES_PASSIVE)
        self.assertEqual(parts.TERMINAL_R, config.TERMINAL_R_MM)
        self.assertEqual(sketch.DOT_R, config.JUNCTION_R_MM)

    def test_no_module_redefines_a_visual_constant(self):
        import re
        names = ('LABEL_PAD_X', 'LABEL_PAD_Y', 'GAP_SERIES_PASSIVE',
                 'GAP_ADJACENT', 'GAP_GROUP', 'TERMINAL_R_MM',
                 'JUNCTION_R_MM', 'BAND_LO', 'BAND_HI')
        folder = os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), 'aipe_sketch')
        for fname in sorted(os.listdir(folder)):
            if not fname.endswith('.py') or fname == 'config.py':
                continue
            with open(os.path.join(folder, fname)) as fh:
                source = fh.read()
            for name in names:
                literal = re.search(rf'^{name}\s*=\s*[\d.]', source,
                                    re.MULTILINE)
                self.assertIsNone(literal,
                                  f'{fname} redefines {name} as a literal')


if __name__ == '__main__':
    os.makedirs(OUT, exist_ok=True)
    unittest.main(verbosity=2)
