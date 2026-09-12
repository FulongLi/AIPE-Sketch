"""Topology-class-aware placement.

A switching device is not automatically half of a bridge.  These tests guard
the distinction between a bridge leg and a shunt device hanging from a main
path down to the return rail, and the balance rules that follow from it.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import build
from aipe_sketch import analysis
from aipe_sketch import drawing_rules as dr
from aipe_sketch.analysis import (BRIDGE_LEG, PARALLEL_OUTPUT_BLOCK,
                                  SHUNT_SWITCH)
from aipe_sketch.pins import COARSE as G
from aipe_sketch.topologies import CATALOGUE

NAMES = sorted(CATALOGUE)
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '_out')
_CACHE = {}


def built(name):
    if name not in _CACHE:
        _CACHE[name] = build.build(name, out_dir=OUT)
    return _CACHE[name]


class TestMotifClassification(unittest.TestCase):
    """Rule 8: placement depends on the local electrical motif."""

    def test_boost_switch_is_a_shunt_not_a_bridge_leg(self):
        netlist, _, _ = CATALOGUE['boost']()
        motifs = analysis.classify_motifs(netlist)
        self.assertEqual([m['device'] for m in motifs[SHUNT_SWITCH]], ['Q1'])
        self.assertEqual(motifs[BRIDGE_LEG], [],
                         'a boost has no bridge leg')

    def test_buck_and_half_bridge_are_bridge_legs(self):
        for name, pair in (('buck', ('Q1', 'D1')),
                           ('half_bridge', ('Q1', 'Q2'))):
            netlist, _, _ = CATALOGUE[name]()
            motifs = analysis.classify_motifs(netlist)
            legs = [(m['high'], m['low']) for m in motifs[BRIDGE_LEG]]
            self.assertIn(pair, legs, name)
            self.assertEqual(motifs[SHUNT_SWITCH], [],
                             f'{name}: leg members are not shunts')

    def test_a_bridge_leg_hangs_from_the_positive_supply(self):
        """What separates the two motifs, stated as a property."""
        for name in NAMES:
            netlist, _, _ = CATALOGUE[name]()
            positive, _ = analysis.supply_nets(netlist)
            for leg in analysis.classify_motifs(netlist)[BRIDGE_LEG]:
                kind = netlist.components[leg['high']].kind
                high_port = analysis.POLARITY[kind][0]
                self.assertEqual(netlist.net_of(leg['high'], high_port),
                                 positive, f'{name}/{leg["high"]}')

    def test_parallel_output_blocks_are_found(self):
        for name in ('boost', 'buck', 'llc_resonant'):
            netlist, _, _ = CATALOGUE[name]()
            blocks = analysis.classify_motifs(netlist)[PARALLEL_OUTPUT_BLOCK]
            self.assertTrue(blocks, f'{name} has a Cout/Rload pair')
            for block in blocks:
                self.assertGreaterEqual(len(block['members']), 2)


class TestShuntBranch(unittest.TestCase):
    """Rules 3, 4, 9, 11: the shunt sits centred in its own branch."""

    def test_boost_shunt_is_balanced(self):
        _, card, _, _ = built('boost')
        branch = card.raw['shunt_branches']['Q1']
        self.assertAlmostEqual(branch['top'], branch['bottom'], places=2,
                               msg=f'lopsided: {branch}')
        self.assertLess(branch['error'], 0.1)

    def test_no_topology_has_a_lopsided_shunt(self):
        for name in NAMES:
            _, card, _, _ = built(name)
            self.assertEqual(card.raw['shunt_balance'], 0, f'{name}\n{card}')

    def test_the_shunt_sits_under_its_node(self):
        """Rule 9: power terminals vertically aligned, no detour."""
        for name in NAMES:
            _, card, _, _ = built(name)
            self.assertEqual(card.raw['shunt_detour'], 0, name)

    def test_boost_switch_is_below_the_switching_node(self):
        sch, _, _, _ = built('boost')
        q1, l1, d1 = (sch.placed[r] for r in ('Q1', 'L1', 'D1'))
        self.assertGreater(q1.y, l1.y, 'Q1 must hang below the main path')
        self.assertAlmostEqual(l1.port('b')[1], d1.port('a')[1], places=3,
                               msg='the main path is not horizontal')

    def test_an_imbalanced_shunt_is_detected(self):
        """Drop the switch onto the rail, as the bridge rule used to."""
        sch, _, _, _ = built('boost')
        q1 = sch.placed['Q1']
        saved = (q1.y, q1.ports, q1.bbox)
        try:
            shift = 4 * G
            q1.y += shift
            q1.ports = {k: (x, y + shift) for k, (x, y) in q1.ports.items()}
            x0, y0, x1, y1 = q1.bbox
            q1.bbox = (x0, y0 + shift, x1, y1 + shift)
            sch.route()
            penalty, faults, _ = dr.shunt_branch_balance(
                sch.netlist, sch.placed, sch.paths)
            self.assertGreater(penalty, 0)
            self.assertTrue(any('lopsided' in f for f in faults), faults)
        finally:
            q1.y, q1.ports, q1.bbox = saved
            sch.route()


class TestBoostAcceptance(unittest.TestCase):
    """Rule 13: the boost acceptance criteria, item by item."""

    def setUp(self):
        self.sch, self.card, _, _ = built('boost')

    def test_main_path_is_horizontal(self):
        """Vin -> L1 -> switching node -> D1 -> output on one line.

        Q1.d is deliberately *not* on it: the shunt hangs below the node.
        """
        ys = {round(self.sch.placed[r].port(p)[1], 3)
              for r, p in (('L1', 'a'), ('L1', 'b'), ('D1', 'a'), ('D1', 'k'))}
        self.assertEqual(len(ys), 1, f'main path sits on {len(ys)} levels')
        self.assertGreater(self.sch.placed['Q1'].port('d')[1], max(ys),
                           'the shunt switch should hang below the path')

    def test_the_shunt_meets_the_path_on_one_vertical(self):
        q1 = self.sch.placed['Q1']
        self.assertAlmostEqual(q1.port('d')[0], q1.port('s')[0], places=3)

    def test_output_block_is_compact(self):
        gap = (self.sch.placed['R1'].bbox[0] -
               self.sch.placed['C1'].bbox[2]) / G
        self.assertLessEqual(gap, 4.0, f'Cout->Rload is {gap:.1f}G')

    def test_output_block_shares_both_rails(self):
        nets = {r: {n for n, _ in self.sch.netlist.ports_of(r)}
                for r in ('C1', 'R1')}
        self.assertEqual(nets['C1'], nets['R1'])

    def test_local_spacing_is_not_wildly_uneven(self):
        order = ['V1', 'L1', 'Q1', 'D1', 'C1', 'R1']
        gaps = []
        prev = None
        for ref in order:
            part = self.sch.placed[ref]
            if prev is not None:
                gaps.append((part.bbox[0] - prev.bbox[2]) / G)
            prev = part
        self.assertLessEqual(max(gaps) / min(gaps), 3.5,
                             f'gaps vary too much: '
                             f'{[round(g, 1) for g in gaps]}')

    def test_no_unnecessary_long_vertical_segment(self):
        self.assertEqual(self.card.raw['shunt_balance'], 0)
        self.assertEqual(self.card.raw['near_component_bend'], 0)

    def test_drawing_is_compact(self):
        self.assertGreaterEqual(self.card.raw['fill'], 0.4)
        self.assertLessEqual(self.card.raw['largest_void'], 0.25)


if __name__ == '__main__':
    os.makedirs(OUT, exist_ok=True)
    unittest.main(verbosity=2)
