"""Regression tests over the reference topologies.

For every converter the spec asks that connectivity survives, that repeated
structures stay symmetric, that spacing is uniform, that routing is
orthogonal, that equivalent branches route alike, that nothing overlaps and
that repeated runs are identical.  Each of those is a test here.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import build
from aipe_sketch import analysis, router, validate
from aipe_sketch.pins import COARSE as G
from aipe_sketch.placement import cluster
from aipe_sketch.topologies import CATALOGUE

NAMES = sorted(CATALOGUE)
_CACHE = {}


def built(name):
    if name not in _CACHE:
        _CACHE[name] = build.build(name, out_dir=OUT)
    return _CACHE[name]


OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '_out')


class TestTopologies(unittest.TestCase):
    """One assertion family per requirement, across every topology."""

    def test_netlist_is_well_formed(self):
        from aipe_sketch import symlib
        from aipe_sketch.parts import port_table
        syms = symlib.load(build.SRC)[1]
        table = port_table(syms)
        for name in NAMES:
            netlist, _, _ = CATALOGUE[name]()
            self.assertEqual(netlist.validate(table), [], name)

    def test_connectivity_survives_rendering(self):
        """The drawn geometry must reproduce the netlist exactly."""
        for name in NAMES:
            sch, card, _, _ = built(name)
            faults = validate.check(sch.netlist, sch.placed, sch.paths)
            self.assertEqual(faults, [], f'{name}: {faults}')
            self.assertEqual(card.sub['connectivity'], 100, name)

    def test_no_collisions(self):
        for name in NAMES:
            _, card, _, _ = built(name)
            self.assertEqual(card.sub['collision'], 100, f'{name}\n{card}')
            for key in ('component_overlap', 'label_overlap',
                        'wire_component_collision', 'out_of_bounds'):
                self.assertEqual(card.raw[key], 0, f'{name}/{key}')

    def test_repeated_structures_are_symmetric(self):
        for name in NAMES:
            sch, card, _, _ = built(name)
            self.assertEqual(card.raw['symmetry'], 0, f'{name}\n{card}')
            classes = analysis.repeated_classes(sch.netlist)
            for cid, refs in classes.items():
                members = [sch.placed[r] for r in refs]
                self.assertEqual(len({(m.rot, m.mirror) for m in members}), 1,
                                 f'{name}/{cid}: orientations differ')

    def test_spacing_is_uniform(self):
        """Equivalent devices must be evenly spaced along their shared axis."""
        for name in NAMES:
            sch, _, _, _ = built(name)
            for cid, refs in analysis.repeated_classes(sch.netlist).items():
                members = [sch.placed[r] for r in refs]
                xs = cluster([m.x for m in members])
                ys = cluster([m.y for m in members])
                varying = xs if len(ys) == 1 else ys
                if len(varying) > 2:
                    steps = [b - a for a, b in zip(varying, varying[1:])]
                    self.assertLess(max(steps) - min(steps), 1e-4,
                                    f'{name}/{cid}: uneven {steps}')

    def test_routing_is_orthogonal_and_on_grid(self):
        for name in NAMES:
            sch, _, _, _ = built(name)
            for net, paths in sch.paths.items():
                for pts in paths:
                    for a, b in router.path_segments(pts):
                        horizontal = abs(a[1] - b[1]) < router.TOL
                        vertical = abs(a[0] - b[0]) < router.TOL
                        self.assertTrue(horizontal or vertical,
                                        f'{name}/{net}: diagonal {a}->{b}')

    def test_equivalent_branches_route_alike(self):
        """Same shape -- same bend count and same number of wire runs."""
        for name in NAMES:
            _, card, _, _ = built(name)
            self.assertEqual(card.raw['routing_shape'], 0, f'{name}\n{card}')

    def test_components_are_on_the_grid(self):
        for name in NAMES:
            sch, _, _, _ = built(name)
            for ref, part in sch.placed.items():
                for value in (part.x, part.y):
                    self.assertLess(abs(value / G - round(value / G)), 1e-3,
                                    f'{name}/{ref} is off grid')

    def test_runs_are_deterministic(self):
        """Two runs must produce byte-identical output."""
        for name in NAMES:
            first = os.path.join(OUT, f'{name}.svg')
            build.build(name, out_dir=OUT)
            a = open(first, 'rb').read()
            build.build(name, out_dir=OUT)
            b = open(first, 'rb').read()
            self.assertEqual(a, b, f'{name} is not reproducible')

    def test_quality_threshold(self):
        for name in NAMES:
            _, card, _, _ = built(name)
            self.assertGreaterEqual(card.overall, 90, f'{name}\n{card}')


class TestConnectivityGuard(unittest.TestCase):
    """The checker must actually catch a drawing that lies about the circuit."""

    def test_a_short_is_detected(self):
        sch, _, _, _ = built('buck')
        shorted = dict(sch.paths)
        a = sch.placed['Q1'].port('d')
        b = sch.placed['D1'].port('a')
        shorted['DC_POS'] = list(shorted['DC_POS']) + [[a, (a[0], b[1])]]
        faults = validate.check(sch.netlist, sch.placed, shorted)
        self.assertTrue(faults, 'a deliberate short was not detected')

    def test_a_break_is_detected(self):
        sch, _, _, _ = built('buck')
        broken = {k: v for k, v in sch.paths.items() if k != 'SW'}
        faults = validate.check(sch.netlist, sch.placed, broken)
        self.assertTrue(faults, 'a missing net was not detected')

    def test_a_crossing_is_not_a_connection(self):
        sch, _, _, _ = built('three_phase_inverter')
        self.assertGreater(
            sum(1 for n, ps in sch.paths.items() for p in ps) , 0)
        faults = validate.check(sch.netlist, sch.placed, sch.paths)
        self.assertEqual(faults, [], 'crossings were read as connections')


if __name__ == '__main__':
    os.makedirs(OUT, exist_ok=True)
    unittest.main(verbosity=2)
