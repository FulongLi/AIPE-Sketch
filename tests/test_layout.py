"""Unit tests for the routing and junction primitives.

Whole-converter behaviour is covered by test_pipeline.py.

Most of these guard against a single class of bug: coordinates in the master
symbol sheet are rounded to three decimals, so a pin can sit a fraction of a
micron off an exact grid line.  Treating that as a real geometric difference
produced phantom junction dots, invisible dog-legs and false collisions.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aipe_sketch import router
from aipe_sketch.router import TOL

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
from aipe_sketch.paths import MASTER as SRC


class TestJunctions(unittest.TestCase):
    def test_tee_on_pin_is_a_node(self):
        paths = [[(0, 0), (10, 0)], [(0, 0), (0, 8)]]
        self.assertEqual(router.junction_points(paths, [(0, 0)]), [(0, 0)])

    def test_rail_ending_on_a_pin_is_not_a_node(self):
        self.assertEqual(router.junction_points([[(0, 0), (10, 0)]], [(10, 0)]), [])

    def test_corner_is_not_a_node(self):
        paths = [[(0, 0), (10, 0)], [(10, 0), (10, 8)]]
        self.assertEqual(router.junction_points(paths, [(0, 0), (10, 8)]), [])

    def test_device_tapping_mid_rail_is_a_node(self):
        """The tap is a terminal, not a wire end -- it must still be found."""
        self.assertEqual(
            router.junction_points([[(0, 0), (30, 0)]], [(0, 0), (15, 0), (30, 0)]),
            [(15, 0)])

    def test_crossing_is_never_a_node(self):
        """Two nets crossing are scored separately, so neither gets a dot."""
        self.assertEqual(router.junction_points([[(0, 5), (10, 5)]], []), [])
        self.assertEqual(router.junction_points([[(5, 0), (5, 10)]], []), [])

    def test_pin_off_grid_by_rounding_does_not_fake_a_node(self):
        """A terminal 3.3e-5 mm off the trunk must not create a stub."""
        trunk_x = 58.208333
        pin = (58.2083, 31.75)
        paths = router.route_trunk([pin, (trunk_x, 52.9167), (127.0, 37.04)],
                                   'v', trunk_x, [])
        self.assertEqual(len(paths), 2, 'no degenerate stub expected')
        dots = router.junction_points(paths, [pin, (trunk_x, 52.9167),
                                              (127.0, 37.04)])
        self.assertEqual(len(dots), 1, f'exactly one tap expected, got {dots}')


class TestRouting(unittest.TestCase):
    def test_near_aligned_route_is_straight(self):
        pts = router.route_pair((0, 29.1048), (-5, 29.1042), [], 2.6458)
        self.assertEqual(router.bend_count(pts), 0)
        self.assertEqual(len(router.path_segments(pts)), 1)

    def test_route_avoids_a_body(self):
        body = (2, -5, 8, 5)
        pts = router.route_pair((0, 0), (10, 0), [body], 2.6458)
        self.assertTrue(router.path_clear(pts, [body]))

    def test_degenerate_segment_is_dropped(self):
        self.assertEqual(router.path_segments([(0, 0), (0, TOL / 2)]), [])

    def test_wire_leaving_a_pin_is_not_a_collision(self):
        """A wire starting on a body edge must not read as penetrating it."""
        body = (0, 0, 10, 10)
        self.assertFalse(router.seg_penetrates(((5, 0), (5, -8)), body))
        self.assertTrue(router.seg_penetrates(((5, 2), (5, -8)), body))

    def test_edge_graze_within_tolerance_is_not_a_collision(self):
        body = (0, 0, 10, 10.000333)
        self.assertFalse(router.seg_penetrates(((0, 10), (20, 10)), body))


if __name__ == '__main__':
    unittest.main(verbosity=2)
