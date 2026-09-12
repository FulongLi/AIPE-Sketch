"""Regression tests for the visual refinement pass.

Each test names the rule it guards.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import build
from aipe_sketch import symlib
from aipe_sketch.drawing_rules import BAND_HI, BAND_LO, CELL
from aipe_sketch.netlist import Netlist
from aipe_sketch.parts import Registry
from aipe_sketch.pins import COARSE as G
from aipe_sketch.topologies import CATALOGUE

NAMES = sorted(CATALOGUE)
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '_out')
_CACHE = {}


def built(name):
    if name not in _CACHE:
        _CACHE[name] = build.build(name, out_dir=OUT)
    return _CACHE[name]


class TestExternalInterfaces(unittest.TestCase):
    """Markers mark main power boundaries and nothing else."""

    def test_markers_match_declared_interfaces(self):
        for name in NAMES:
            _, card, _, _ = built(name)
            self.assertEqual(card.raw['external_marker'], 0, f'{name}\n{card}')

    def test_internal_nodes_carry_no_ring(self):
        """A switching node or bridge midpoint must never get an open circle."""
        for name in NAMES:
            sch, _, _, _ = built(name)
            externals = {r for r, p in sch.placed.items() if p.external}
            for leg in sch.analysis['legs']:
                members = {r for r, _ in sch.netlist.nets[leg['mid']]}
                internal = members - externals
                self.assertTrue(internal, f'{name}: {leg["mid"]}')
                for ref in internal:
                    self.assertFalse(sch.placed[ref].external,
                                     f'{name}/{ref} is an internal node')

    def test_a_terminal_must_declare_its_interface(self):
        n = Netlist('t')
        n.add('R1', 'res')
        n.add('X1', 'terminal')          # no interface declared
        n.connect('N', 'R1.a', 'X1.t')
        registry = Registry(symlib.load(build.SRC)[1])
        problems = n.validate(registry.port_table())
        self.assertTrue(any('interface=' in p for p in problems), problems)

    def test_interface_flag_requires_a_terminal(self):
        n = Netlist('t')
        n.add('R1', 'res', interface='power')
        registry = Registry(symlib.load(build.SRC)[1])
        problems = n.validate(registry.port_table())
        self.assertTrue(any('only a terminal' in p for p in problems), problems)

    def test_an_unknown_interface_is_rejected(self):
        n = Netlist('t')
        with self.assertRaises(ValueError):
            n.add('X1', 'terminal', interface='sensing')

    def test_gate_ports_carry_no_marker(self):
        """A gate drive is control, not a power boundary."""
        for name in NAMES:
            sch, _, _, _ = built(name)
            gates = set()
            for net, members in sch.netlist.nets.items():
                if any(port == 'g' for _, port in members):
                    gates |= {r for r, _ in members
                              if sch.placed[r].spec.is_terminal}
            self.assertTrue(gates, f'{name} has no gate ports')
            for ref in gates:
                part = sch.placed[ref]
                self.assertEqual(part.interface, 'control', f'{name}/{ref}')
                self.assertIsNone(part.marker,
                                  f'{name}/{ref} draws a boundary marker')

    def test_only_power_interfaces_are_marked(self):
        for name in NAMES:
            sch, _, _, _ = built(name)
            for ref, part in sch.placed.items():
                if part.marker is not None:
                    self.assertEqual(part.interface, 'power',
                                     f'{name}/{ref}')

    def test_switching_nodes_are_unmarked_unless_exposed(self):
        """A midpoint gets a marker only where it is the declared output.

        A buck's switching node is purely internal and must stay unmarked; a
        half bridge's midpoint *is* VOUT, so the marker belongs there.
        """
        for name in NAMES:
            sch, _, _, _ = built(name)
            for leg in sch.analysis['legs']:
                for ref, _ in sch.netlist.nets[leg['mid']]:
                    part = sch.placed[ref]
                    if part.marker is None:
                        continue
                    self.assertEqual(part.interface, 'power',
                                     f'{name}/{ref} is an internal node')
                    self.assertTrue(part.spec.is_terminal, f'{name}/{ref}')

    def test_a_purely_internal_switching_node_has_no_marker(self):
        sch, _, _, _ = built('buck')
        for ref, _ in sch.netlist.nets['SW']:
            self.assertIsNone(sch.placed[ref].marker, ref)


class TestMarkerGeometry(unittest.TestCase):
    """The wire stops at the circumference, never crossing the interior."""

    def test_wire_ends_one_radius_from_the_centre(self):
        for name in NAMES:
            sch, _, _, _ = built(name)
            for ref, part in sch.placed.items():
                if part.marker is None:
                    continue
                cx, cy, r = part.marker
                px, py = part.port('t')
                offset = ((px - cx) ** 2 + (py - cy) ** 2) ** 0.5
                self.assertAlmostEqual(offset, r, places=3,
                                       msg=f'{name}/{ref}')

    def test_marker_sits_on_the_wire_axis(self):
        """For a horizontal approach the circle is level with the wire."""
        for name in NAMES:
            sch, _, _, _ = built(name)
            for ref, part in sch.placed.items():
                if part.marker is None:
                    continue
                cx, cy, _ = part.marker
                px, py = part.port('t')
                on_axis = (abs(cy - py) < 1e-6) or (abs(cx - px) < 1e-6)
                self.assertTrue(on_axis, f'{name}/{ref} marker is off axis')

    def test_no_wire_crosses_a_marker_interior(self):
        from aipe_sketch import drawing_rules as dr
        for name in NAMES:
            sch, _, _, _ = built(name)
            self.assertEqual(dr.marker_geometry(sch.placed, sch.paths), [],
                             name)

    def test_a_wire_through_a_marker_is_detected(self):
        """The geometry check must be able to fail."""
        from aipe_sketch import drawing_rules as dr
        sch, _, _, _ = built('half_bridge')
        part = sch.placed['VOUT']
        cx, cy, _ = part.marker
        port = part.port('t')
        beyond = (cx + (cx - port[0]), cy + (cy - port[1]))

        bad = {k: [list(pts) for pts in v] for k, v in sch.paths.items()}
        pushed = False
        for pts in bad.values():
            for path in pts:
                for i, point in enumerate(path):
                    if (abs(point[0] - port[0]) < 1e-6
                            and abs(point[1] - port[1]) < 1e-6):
                        path[i] = beyond      # run the wire past the centre
                        pushed = True
        self.assertTrue(pushed, 'no wire reaches the VOUT port')
        faults = dr.marker_geometry(sch.placed, bad)
        self.assertTrue(any('crosses' in f for f in faults), faults)


class TestNaming(unittest.TestCase):
    """VIN and VOUT are semantic ideas, not mandatory ink."""

    def test_the_source_carries_the_input_name(self):
        for name in NAMES:
            sch, _, _, _ = built(name)
            sources = [p for p in sch.placed.values()
                       if p.spec.role == 'source']
            self.assertTrue(sources, name)
            for src in sources:
                self.assertEqual((src.label, src.sub), ('V', 'in'),
                                 f'{name}/{src.ref}')

    def test_no_separate_input_annotation(self):
        """An explicit source names the input; nothing else should."""
        for name in NAMES:
            sch, _, _, _ = built(name)
            texts = {n['text_op']['text'].lower() for n in sch._notes}
            self.assertFalse(texts & {'vin', 'v_in'},
                             f'{name} annotates the input twice')

    def test_no_output_port_where_a_load_terminates_the_circuit(self):
        for name in NAMES:
            sch, _, _, _ = built(name)
            for ref, part in sch.placed.items():
                if not part.spec.is_terminal:
                    continue
                if f'{part.label or ""}'.upper() != 'VOUT':
                    continue
                net = sch.netlist.net_of(ref, 't')
                roles = {sch.placed[r].spec.role
                         for r, _ in sch.netlist.nets[net] if r != ref}
                self.assertNotIn('load', roles,
                                 f'{name}: {ref} follows a load network')

    def test_an_exposed_output_keeps_its_port(self):
        """A half bridge has no load of its own, so its midpoint stays a port."""
        sch, _, _, _ = built('half_bridge')
        self.assertIn('VOUT', sch.placed)
        self.assertEqual(sch.placed['VOUT'].interface, 'power')

    def test_semantic_net_names_do_not_imply_labels(self):
        """A net called VOUT must not force a VOUT label into the drawing."""
        sch, _, _, _ = built('buck')
        self.assertIn('VOUT_N', sch.netlist.nets)
        rendered = {f"{t['text']}{t['sub'] or ''}".upper() for t in sch.texts}
        self.assertNotIn('VOUT', rendered)
        self.assertNotIn('VOUTN', rendered)


class TestRedundancy(unittest.TestCase):
    """Rule 6: never say the same thing twice."""

    def test_no_redundant_annotation(self):
        for name in NAMES:
            _, card, _, _ = built(name)
            self.assertEqual(card.raw['redundant_annotation'], 0,
                             f'{name}\n{card}')

    def test_source_plus_input_annotation_is_detected(self):
        from aipe_sketch import drawing_rules as dr
        sch, _, _, _ = built('buck')
        src = sch.placed['V1']
        original = (src.label, src.sub)
        try:
            src.label, src.sub = 'V', '1'
            sch.note('V1', 'dc_pos', 'VIN', dx=0.4, dy=-1.3, anchor='start',
                     italic=False)
            faults = dr.redundant_annotation(sch.placed, sch.netlist,
                                             sch._notes)
            self.assertTrue(any('label the source itself' in f
                                for f in faults), faults)
        finally:
            src.label, src.sub = original
            sch._notes.clear()
            sch.build_labels()


class TestLabelClearance(unittest.TestCase):
    """Rules 3, 4, 5, 15: labels keep a margin and a consistent offset."""

    def test_clearance_margin_is_applied(self):
        from aipe_sketch.pipeline import LABEL_PAD_X, LABEL_PAD_Y
        self.assertAlmostEqual(LABEL_PAD_X, 0.5 * G, places=6)
        self.assertAlmostEqual(LABEL_PAD_Y, 0.35 * G, places=6)

    def test_nothing_enters_a_label_clearance_box(self):
        for name in NAMES:
            _, card, _, _ = built(name)
            self.assertEqual(card.raw['label_overlap'], 0, f'{name}\n{card}')

    def test_equivalent_labels_share_one_offset(self):
        for name in NAMES:
            _, card, _, _ = built(name)
            self.assertEqual(card.raw['label_distance'], 0, f'{name}\n{card}')

    def test_stacked_label_clears_its_own_body(self):
        """An 'above' label is baselined, so its box must not dip into the body."""
        for name in NAMES:
            sch, _, _, _ = built(name)
            boxes = dict(sch.labels)
            for ref, part in sch.placed.items():
                if part.label_side not in ('above', 'below'):
                    continue
                box = boxes.get(ref)
                if box is None:
                    continue
                bx0, by0, bx1, by1 = part.bbox
                self.assertFalse(box[3] > by0 + 1e-6 and box[1] < by1 - 1e-6
                                 and box[2] > bx0 and box[0] < bx1,
                                 f'{name}/{ref} label overlaps its own body')

    def test_horizontal_passives_are_labelled_above(self):
        for name in NAMES:
            sch, _, _, _ = built(name)
            for ref, part in sch.placed.items():
                if part.rot % 180 and part.spec.orientation == 'vertical':
                    self.assertEqual(part.label_side, 'above',
                                     f'{name}/{ref}')


class TestTransformer(unittest.TestCase):
    """Rules 6, 7, 17, 19: one compact device with fixed internal geometry."""

    def test_symbol_is_compact(self):
        for name in NAMES:
            _, card, _, _ = built(name)
            for ref, ratio in card.raw['tx_ratio'].items():
                self.assertLessEqual(ratio, 2.0, f'{name}/{ref}: {ratio}')

    def test_internal_geometry_is_fixed(self):
        """Placement must not stretch the compound, whatever the group pitch."""
        registry = Registry(symlib.load(build.SRC)[1])
        want = registry['transformer'].width
        for name in NAMES:
            sch, _, _, _ = built(name)
            for ref, part in sch.placed.items():
                if part.kind == 'transformer':
                    self.assertAlmostEqual(part.bbox[2] - part.bbox[0], want,
                                           places=6, msg=f'{name}/{ref}')

    def test_it_comes_from_the_library_not_a_hand_built_compound(self):
        registry = Registry(symlib.load(build.SRC)[1])
        spec = registry['transformer']
        self.assertEqual(spec.source, 'library')
        self.assertEqual(spec.symbol_id, 'g7138')
        self.assertTrue(spec.cleaned,
                        'the wrapper also encloses neighbouring geometry')

    def test_it_reads_as_one_device(self):
        registry = Registry(symlib.load(build.SRC)[1])
        spec = registry['transformer']
        self.assertLessEqual(spec.width / spec.height, 1.5,
                             'wider than tall reads as two inductors')
        self.assertAlmostEqual(spec.height, 4 * G, places=2,
                               msg='must keep the library 4 G height')

    def test_both_windings_are_present(self):
        """The secondary is a rotate(180) copy; losing it was the old bug."""
        from aipe_sketch.pins import PARTS
        keep = PARTS['transformer']['keep']
        coils = [k for k in keep if k.startswith('g6472')]
        self.assertEqual(len(coils), 2, f'expected two windings, got {coils}')

    def test_ports_are_symmetric_about_the_core(self):
        registry = Registry(symlib.load(build.SRC)[1])
        ports = registry['transformer'].ports
        self.assertAlmostEqual(ports['p1'][0], -ports['s1'][0], places=3)
        self.assertAlmostEqual(ports['p2'][0], -ports['s2'][0], places=3)
        for a, b in (('p1', 's1'), ('p2', 's2')):
            self.assertAlmostEqual(ports[a][1], ports[b][1], places=3)


class TestLocalScale(unittest.TestCase):
    """Rule 12: adjacent components sit 0.75D..1.5D apart."""

    def test_band_is_respected_or_explained(self):
        for name in NAMES:
            _, card, _, _ = built(name)
            self.assertLess(card.raw['length_band'], 0.5,
                            f'{name}: {card.raw["length_band"]}')

    def test_band_constants(self):
        self.assertEqual((BAND_LO, BAND_HI), (0.75, 1.5))


class TestRegistry(unittest.TestCase):
    """Rules 8, 9, 11, 20: the master sheet stays authoritative."""

    def test_every_kind_exposes_its_metadata(self):
        registry = Registry(symlib.load(build.SRC)[1])
        for kind, spec in registry.items():
            data = spec.as_dict()
            for key in ('kind', 'symbol_id', 'bbox', 'ports',
                        'preferred_orientation', 'semantic_role',
                        'visual_margin', 'preferred_label_side',
                        'preferred_label_offset'):
                self.assertIn(key, data, kind)

    def test_no_kind_redraws_a_library_symbol(self):
        for name in NAMES:
            _, card, _, _ = built(name)
            self.assertEqual(card.raw['custom_symbols'], 0, name)

    def test_any_compound_is_assembled_from_library_symbols(self):
        registry = Registry(symlib.load(build.SRC)[1])
        for kind, spec in registry.items():
            if spec.source != 'compound':
                continue
            for sub, *_ in spec.compound['symbols']:
                self.assertEqual(registry[sub].source, 'library',
                                 f'{kind} assembles from non-library {sub}')

    def test_visual_margin_is_symbol_specific(self):
        registry = Registry(symlib.load(build.SRC)[1])
        self.assertGreater(registry['transformer'].visual_margin['left'],
                           registry['cap'].visual_margin['left'])
        self.assertLess(registry['terminal'].visual_margin['left'],
                        registry['cap'].visual_margin['left'])

    def test_rendering_does_not_need_exported_files(self):
        """The export tool is optional: nothing in the pipeline reads it."""
        import aipe_sketch.pipeline as pipeline
        with open(pipeline.__file__) as fh:
            source = fh.read()
        self.assertNotIn('assets/generated', source)


class TestChecklist(unittest.TestCase):
    """Rule 18: the review checklist must come back clean."""

    def test_no_open_questions(self):
        for name in NAMES:
            _, card, _, _ = built(name)
            flagged = {q: d for q, (v, d) in card.checks.items()
                       if v == 'CHECK'}
            self.assertEqual(flagged, {}, f'{name}: {flagged}')

    def test_checklist_covers_the_refinement_rules(self):
        _, card, _, _ = built('dab')
        for key in ('16 markers only on power interfaces',
                    '17 VIN/VOUT clear of neighbouring labels',
                    '18 equivalent labels use one offset',
                    '19 transformer reads as one object',
                    '20 master-library symbols reused undistorted',
                    '21 local runs within 0.75-1.5 D',
                    '22 output port only where the output is exposed'):
            self.assertIn(key, card.checks)


if __name__ == '__main__':
    os.makedirs(OUT, exist_ok=True)
    unittest.main(verbosity=2)
