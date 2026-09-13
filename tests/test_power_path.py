"""Half-bridge primary-side power paths and passive chain spacing.

The LLC resonant converter is the case these rules exist for: a switching
node feeding Cr, Lr and a transformer in series.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import build
from aipe_sketch import drawing_rules as dr
from aipe_sketch.drawing_rules import CELL
from aipe_sketch.pins import COARSE as G
from aipe_sketch.plan import (CHAIN_ROLES, GAP_GROUP, GAP_SERIES_PASSIVE)
from aipe_sketch.topologies import CATALOGUE

NAMES = sorted(CATALOGUE)
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '_out')
_CACHE = {}


def built(name):
    if name not in _CACHE:
        _CACHE[name] = build.build(name, out_dir=OUT)
    return _CACHE[name]


class TestPowerPathContinuity(unittest.TestCase):
    """Rules 1, 3, 6, 9: the main power path is one straight line."""

    def test_the_resonant_chain_is_detected(self):
        sch, _, _, _ = built('llc_resonant')
        chains = dr.series_chains(sch.netlist, sch.placed)
        self.assertEqual(chains, [['Cr', 'Lr', 'T1', 'D1']])

    def test_a_rail_is_not_mistaken_for_a_series_chain(self):
        """C1 and T1 share the DC- rail; that is a node, not a series link."""
        sch, _, _, _ = built('llc_resonant')
        for chain in dr.series_chains(sch.netlist, sch.placed):
            self.assertNotIn('C1', chain)

    def test_no_centreline_deviation_anywhere(self):
        for name in NAMES:
            _, card, _, _ = built(name)
            self.assertEqual(card.raw['centreline_deviation'], 0,
                             f'{name}\n{card}')

    def test_the_chain_shares_one_horizontal_line(self):
        sch, _, _, _ = built('llc_resonant')
        ys = {round(sch.placed[r].port(p)[1], 3)
              for r, p in (('Cr', 'a'), ('Cr', 'b'), ('Lr', 'a'),
                           ('Lr', 'b'), ('T1', 'p1'), ('T1', 's1'),
                           ('D1', 'a'), ('D1', 'k'))}
        self.assertEqual(len(ys), 1,
                         f'the power path sits on {len(ys)} levels: {ys}')

    def test_switching_node_leaves_horizontally_from_its_midpoint(self):
        """The node is the vertical run between the devices; the tank taps
        its centre and leaves on the flat."""
        sch, _, _, _ = built('llc_resonant')
        high = sch.placed['Q1'].port('s')[1]
        low = sch.placed['Q2'].port('d')[1]
        tap = sch.placed['Cr'].port('a')
        self.assertAlmostEqual(tap[1], (high + low) / 2, places=3)
        runs = [seg for _, seg in dr._segments(sch.paths)
                if dr._same(seg[0], tap) or dr._same(seg[1], tap)]
        self.assertTrue(runs)
        for seg in runs:
            self.assertLess(abs(seg[0][1] - seg[1][1]), 1e-6,
                            'the switching node does not leave horizontally')

    def test_a_step_off_the_centreline_is_detected(self):
        sch, _, _, _ = built('llc_resonant')
        part = sch.placed['Lr']
        saved = (part.y, part.ports, part.bbox)
        try:
            part.y += 2 * G
            part.ports = {k: (x, y + 2 * G)
                          for k, (x, y) in part.ports.items()}
            x0, y0, x1, y1 = part.bbox
            part.bbox = (x0, y0 + 2 * G, x1, y1 + 2 * G)
            penalty, faults = dr.centreline_deviation(sch.netlist, sch.placed)
            self.assertGreater(penalty, 0)
            self.assertTrue(any('centreline' in f for f in faults), faults)
        finally:
            part.y, part.ports, part.bbox = saved


class TestBendsNearPassives(unittest.TestCase):
    """Rules 2, 8: no corner right beside a passive port."""

    def test_no_bend_sits_beside_a_passive(self):
        for name in NAMES:
            _, card, _, _ = built(name)
            self.assertEqual(card.raw['near_component_bend'], 0,
                             f'{name}\n{card}')

    def test_a_bend_beside_a_passive_is_detected(self):
        sch, _, _, _ = built('llc_resonant')
        port = sch.placed['Lr'].port('a')
        bad = {k: [list(p) for p in v] for k, v in sch.paths.items()}
        bad['RES'] = [[(port[0] - 3 * G, port[1] - 3 * G),
                       (port[0] - 3 * G, port[1]), port]]
        penalty, faults = dr.near_component_bend_penalty(
            sch.netlist, sch.placed, bad)
        self.assertGreater(penalty, 0)
        self.assertTrue(any('bends' in f for f in faults), faults)

    def test_inductor_wires_are_collinear_with_its_axis(self):
        """Rule 6: horizontal in, horizontal out, no vertical stub."""
        sch, _, _, _ = built('llc_resonant')
        lr = sch.placed['Lr']
        for port in ('a', 'b'):
            pt = lr.port(port)
            runs = [seg for _, seg in dr._segments(sch.paths)
                    if dr._same(seg[0], pt) or dr._same(seg[1], pt)]
            self.assertTrue(runs, f'Lr.{port} has no wire')
            for seg in runs:
                self.assertLess(abs(seg[0][1] - seg[1][1]), 1e-6,
                                f'Lr.{port} leaves vertically')


class TestPortConnectionRule(unittest.TestCase):
    """Point-to-point connections follow the port axis and half-span lead."""

    def test_all_outputs_leave_point_to_point_ports_on_axis(self):
        for name in NAMES:
            _, card, _, _ = built(name)
            self.assertEqual(card.raw['port_axis_mismatch'], 0,
                             f'{name}: {card.faults}')

    def test_half_a_body_span_is_the_preferred_lead_length(self):
        self.assertEqual(dr.lead_length_penalty(5, 10), 0)
        self.assertGreater(dr.lead_length_penalty(10, 10), 0)

    def test_a_wire_leaving_across_the_port_axis_is_detected(self):
        sch, _, _, _ = built('llc_resonant')
        port = sch.placed['Lr'].port('a')
        bad = dict(sch.paths)
        bad['RES'] = [[port, (port[0], port[1] - G),
                       sch.placed['Cr'].port('b')]]
        _, faults, _ = dr.port_connection_geometry(
            sch.netlist, sch.placed, bad)
        self.assertTrue(any('Lr.a' in fault for fault in faults), faults)


class TestChainSpacing(unittest.TestCase):
    """Rules 4, 5, 7: a chain is tighter than a functional boundary."""

    def test_chain_spacing_is_tighter_than_group_spacing(self):
        self.assertLess(GAP_SERIES_PASSIVE, GAP_GROUP)

    def test_measured_chain_gaps_are_compact(self):
        sch, _, _, _ = built('llc_resonant')
        for left, right, ceiling in (('Cr', 'Lr', 3), ('Lr', 'T1', 4),
                                     ('T1', 'D1', 4), ('D1', 'C2', 4)):
            gap = (sch.placed[right].bbox[0] -
                   sch.placed[left].bbox[2]) / G
            self.assertGreaterEqual(gap, 1.5, f'{left}->{right} crowded')
            self.assertLessEqual(gap, ceiling,
                                 f'{left}->{right} is {gap:.1f}G')

    def test_the_group_boundary_stays_wider(self):
        """Half bridge to tank is a functional boundary, not a chain."""
        sch, _, _, _ = built('llc_resonant')
        boundary = (sch.placed['Cr'].bbox[0] -
                    sch.placed['Q1'].bbox[2]) / G
        chain = (sch.placed['Lr'].bbox[0] - sch.placed['Cr'].bbox[2]) / G
        self.assertGreater(boundary, chain)

    def test_facing_margins_are_relaxed_only_on_facing_sides(self):
        sch, _, _, _ = built('llc_resonant')
        lr = sch.placed['Lr']
        self.assertTrue(lr.margin_override, 'Lr sits in a chain')
        self.assertEqual(set(lr.margin_override) - {'left', 'right'}, set(),
                         'only the facing sides may be relaxed')
        for side in ('top', 'bottom'):
            self.assertEqual(lr.clearance_bbox[1] if side == 'top' else None,
                             lr.spec.margin_box(lr.bbox)[1]
                             if side == 'top' else None)

    def test_chain_roles_include_the_rectifier(self):
        """Rule 7: a transformer must not sit far from its rectifier."""
        self.assertIn('rectifier', CHAIN_ROLES)
        self.assertIn('isolation', CHAIN_ROLES)


class TestAcceptance(unittest.TestCase):
    """Rule 10: the whole-drawing checklist stays clean."""

    def test_no_open_questions(self):
        for name in NAMES:
            _, card, _, _ = built(name)
            flagged = {q: d for q, (v, d) in card.checks.items()
                       if v == 'CHECK'}
            self.assertEqual(flagged, {}, f'{name}: {flagged}')

    def test_connectivity_unchanged_by_the_spacing_work(self):
        for name in NAMES:
            _, card, _, _ = built(name)
            self.assertEqual(card.sub['connectivity'], 100, name)
            self.assertEqual(card.sub['collision'], 100, name)


if __name__ == '__main__':
    os.makedirs(OUT, exist_ok=True)
    unittest.main(verbosity=2)
