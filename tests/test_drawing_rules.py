"""Regression tests for the general drawing rules.

Each test names the rule it guards, so a failure says which drawing
convention broke rather than just which number moved.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import build
from aipe_sketch import drawing_rules as dr
from aipe_sketch.drawing_rules import CELL
from aipe_sketch.topologies import CATALOGUE

NAMES = sorted(CATALOGUE)
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '_out')
_CACHE = {}


def built(name):
    if name not in _CACHE:
        _CACHE[name] = build.build(name, out_dir=OUT)
    return _CACHE[name]


class TestTerminals(unittest.TestCase):
    """Rules 1, 2, 25: exposed ports end in an open circle, never a bare line."""

    def test_every_external_port_draws_an_open_circle(self):
        for name in NAMES:
            sch, _, _, _ = built(name)
            for ref, part in sch.placed.items():
                if part.spec.is_terminal:
                    self.assertTrue(part.spec.decor.get('circles'),
                                    f'{name}/{ref} draws no terminal circle')

    def test_terminal_ring_differs_from_a_junction_dot(self):
        from aipe_sketch.parts import TERMINAL_R
        from aipe_sketch.sketch import DOT_R
        self.assertGreater(TERMINAL_R, DOT_R,
                           'an open port must not read as a junction dot')

    def test_no_wire_ends_in_mid_air(self):
        for name in NAMES:
            sch, _, _, _ = built(name)
            loose = dr.floating_ends(sch.placed, sch.paths)
            self.assertEqual(loose, [], f'{name}: {loose}')


class TestSourceSymbols(unittest.TestCase):
    """Rules 11, 12: sources carry polarity or a direction arrow."""

    def test_voltage_source_shows_polarity(self):
        sch, _, _, _ = built('buck')
        decor = sch.specs['vsource'].decor
        glyphs = {t[2] for t in decor.get('texts', ())}
        self.assertEqual(glyphs, {'+', '−'})

    def test_current_source_shows_an_arrow(self):
        sch, _, _, _ = built('buck')
        strokes = sch.specs['isource'].decor.get('strokes', ())
        self.assertGreaterEqual(len(strokes), 3, 'arrow needs a shaft and head')

    def test_polarity_sits_toward_the_matching_terminal(self):
        sch, _, _, _ = built('buck')
        texts = {t[2]: t[1] for t in sch.specs['vsource'].decor['texts']}
        ports = sch.specs['vsource'].ports
        self.assertLess(texts['+'], texts['−'])
        self.assertLess(ports['p'][1], ports['n'][1])


class TestLocalScale(unittest.TestCase):
    """Rules 3, 4, 5, 22, 23, 27: one consistent local visual scale."""

    def test_neighbouring_bodies_respect_their_spacing_role(self):
        """Spacing depends on the relationship, not one global scale."""
        from aipe_sketch.plan import CHAIN_ROLES
        for name in NAMES:
            sch, _, _, _ = built(name)
            parts = sorted((p for p in sch.placed.values()
                            if not p.spec.is_terminal), key=lambda p: p.x)
            for a, b in zip(parts, parts[1:]):
                overlap = (min(a.bbox[3], b.bbox[3]) -
                           max(a.bbox[1], b.bbox[1]))
                if overlap <= 0.05:
                    continue                       # not in the same band
                gap = (b.bbox[0] - a.bbox[2]) / CELL
                if gap <= 0 or gap > 3:
                    continue                       # touching or a long haul
                chain = (a.spec.role in CHAIN_ROLES
                         and b.spec.role in CHAIN_ROLES)
                floor = 0.4 if chain else 0.75
                self.assertGreaterEqual(gap, floor,
                                        f'{name}: {a.ref}->{b.ref} crowded')
                self.assertLessEqual(gap, 1.7,
                                     f'{name}: {a.ref}->{b.ref} too far')

    def test_series_passive_chains_are_tighter_than_group_boundaries(self):
        """The whole point of the hierarchy: a chain reads as one run."""
        from aipe_sketch.plan import (GAP_ADJACENT, GAP_BRIDGE_LEG,
                                      GAP_GROUP, GAP_SERIES_PASSIVE)
        self.assertLess(GAP_SERIES_PASSIVE, GAP_ADJACENT)
        self.assertLess(GAP_ADJACENT, GAP_BRIDGE_LEG)
        self.assertLessEqual(GAP_BRIDGE_LEG, GAP_GROUP)

    def test_local_gaps_follow_the_relationship(self):
        """Spacing comes from how a pair is connected, not from its group.

        L1 feeds a node that branches to both C2 and R1, so it is directly
        connected rather than in series -- the adjacent scale.  C2 and R1 are
        shunted across the same node pair, so they get the parallel scale.
        """
        from aipe_sketch.pins import COARSE as G
        from aipe_sketch.config import GAP_ADJACENT, GAP_PARALLEL_BLOCK
        sch, _, _, _ = built('buck')
        for left, right, ceiling in (('L1', 'C2', GAP_ADJACENT + 0.5),
                                     ('C2', 'R1', GAP_PARALLEL_BLOCK + 1.0)):
            gap = (sch.placed[right].bbox[0] -
                   sch.placed[left].bbox[2]) / G
            self.assertLessEqual(gap, ceiling,
                                 f'{left}->{right} is {gap:.1f}G')

    def test_a_component_has_no_wildly_uneven_local_wires(self):
        for name in NAMES:
            _, card, _, _ = built(name)
            self.assertLess(card.raw['local_spread'], 1.0,
                            f'{name}: {card.raw["local_spread"]}')

    def test_few_local_length_scales(self):
        for name in NAMES:
            _, card, _, _ = built(name)
            self.assertLessEqual(len(card.raw['scales']), 5,
                                 f'{name}: {card.raw["scales"]}')


class TestConventions(unittest.TestCase):
    """Rules 7, 8, 20, 24: bridge and rail drawing conventions."""

    def test_switching_node_leaves_straight(self):
        for name in NAMES:
            _, card, _, _ = built(name)
            self.assertEqual(card.raw['midpoint_detour'], 0, name)

    def test_dc_rails_are_straight(self):
        for name in NAMES:
            _, card, _, _ = built(name)
            self.assertEqual(card.raw['rail_step'], 0, name)

    def test_half_bridge_devices_share_a_column(self):
        for name in NAMES:
            sch, _, _, _ = built(name)
            for leg in sch.analysis['legs']:
                hi, lo = sch.placed[leg['high']], sch.placed[leg['low']]
                if abs(hi.x - lo.x) < 1e-6:
                    self.assertLess(hi.y, lo.y,
                                    f'{name}: {leg["high"]} is not above '
                                    f'{leg["low"]}')

    def test_switching_node_is_centred_between_its_devices(self):
        for name in NAMES:
            sch, _, _, _ = built(name)
            for leg in sch.analysis['legs']:
                hi, lo = sch.placed[leg['high']], sch.placed[leg['low']]
                if abs(hi.x - lo.x) > 1e-6:
                    continue                       # drawn side by side
                for pts in sch.paths[leg['mid']]:
                    if abs(pts[0][0] - hi.x) > 1e-6:
                        continue
                    lo_y, hi_y = sorted((pts[0][1], pts[-1][1]))
                    mid = (lo_y + hi_y) / 2
                    self.assertAlmostEqual(mid, (hi.bbox[3] + lo.bbox[1]) / 2,
                                           places=3, msg=name)

    def test_transformer_is_entered_horizontally(self):
        sch, card, _, _ = built('dab')
        verdict, detail = card.checks['10 transformer compactly connected']
        self.assertEqual(verdict, 'PASS', detail)
        self.assertIn('entries horizontal', detail)


class TestLabels(unittest.TestCase):
    """Rules 6, 14, 15, 16: designators and consistent label placement."""

    def test_reference_designators_are_conventional(self):
        prefix = {'vsource': 'V', 'isource': 'I', 'res': 'R', 'ind': 'L',
                  'cap': 'C', 'nmos': 'Q', 'igbt': 'Q', 'diode': 'D',
                  'transformer': 'T'}
        for name in NAMES:
            netlist, _, _ = CATALOGUE[name]()
            for ref, comp in netlist.components.items():
                want = prefix.get(comp.kind)
                if want and comp.label:
                    self.assertEqual(comp.label, want,
                                     f'{name}/{ref} labelled {comp.label}')

    def test_equivalent_components_label_on_the_same_side(self):
        for name in NAMES:
            _, card, _, _ = built(name)
            self.assertEqual(card.raw['label_side'], 0, name)

    def test_no_label_overlaps_anything(self):
        for name in NAMES:
            _, card, _, _ = built(name)
            self.assertEqual(card.raw['label_overlap'], 0, f'{name}\n{card}')

    def test_nothing_is_clipped_by_the_sheet(self):
        for name in NAMES:
            _, card, _, _ = built(name)
            self.assertEqual(card.raw['out_of_bounds'], 0, f'{name}\n{card}')


class TestWholeDrawing(unittest.TestCase):
    """Rule 26: the whole-drawing checklist must come back clean."""

    def test_checklist_has_no_open_questions(self):
        for name in NAMES:
            _, card, _, _ = built(name)
            flagged = {q: d for q, (v, d) in card.checks.items()
                       if v == 'CHECK'}
            self.assertEqual(flagged, {}, f'{name}: {flagged}')

    def test_drawings_are_compact(self):
        for name in NAMES:
            _, card, _, _ = built(name)
            self.assertGreaterEqual(card.raw['fill'], 0.4, name)
            self.assertLessEqual(card.raw['largest_void'], 0.25, name)


if __name__ == '__main__':
    os.makedirs(OUT, exist_ok=True)
    unittest.main(verbosity=2)
