"""Generalisation and backend-boundary tests; circuits are electrical inputs."""
import ast
import json
from pathlib import Path
import tempfile
import unittest

from aipe_sketch import Netlist, Schematic, auto_plan, graph_analysis, validate
from aipe_sketch.topologies import CIRCUITS, CATALOGUE
from aipe_sketch.synthetic import CIRCUITS as SYNTHETIC
from aipe_sketch.planner import AutoPlan


def anonymous(circuit, reverse=False):
    """Rename all nets/refs, and optionally reverse insertion order."""
    data = circuit.to_dict()
    names = {c['ref']: f'X{i}' for i, c in enumerate(data['components'])}
    nodes = {n: f'node{i}' for i, n in enumerate(data['nets'])}
    data['name'] = 'unclassified graph'
    for c in data['components']:
        c['ref'] = names[c['ref']]
    data['nets'] = {nodes[n]: [names[t.rsplit('.', 1)[0]] + '.' + t.rsplit('.', 1)[1]
                             for t in members] for n, members in data['nets'].items()}
    if reverse:
        data['components'].reverse()
        data['nets'] = {net: list(reversed(members))
                        for net, members in reversed(list(data['nets'].items()))}
    return Netlist.from_dict(data)


class CircuitIRTests(unittest.TestCase):
    def test_electrical_round_trip_without_drawing_library(self):
        from unittest.mock import patch
        with patch('aipe_sketch.symlib.load', side_effect=AssertionError('SVG accessed')):
            for factory in CIRCUITS.values():
                n = factory()
                data = json.loads(json.dumps(n.to_dict()))
                copy = Netlist.from_dict(data)
                self.assertEqual(n.to_dict(), copy.to_dict())
                self.assertEqual(copy.validate(), [])
                self.assertIsInstance(graph_analysis(copy), AutoPlan)

    def test_custom_electrical_component_needs_no_symbol(self):
        n = Netlist()
        n.add('U', 'simulation_only', ports=('in', 'out'), model='custom')
        n.add('A', 'terminal', interface='power')
        n.add('B', 'terminal', interface='power')
        n.connect('a', 'U.in', 'A.t')
        n.connect('b', 'U.out', 'B.t')
        self.assertEqual(n.validate(), [])
        self.assertEqual(n.to_dict(), Netlist.from_dict(n.to_dict()).to_dict())

    def test_view_data_does_not_enter_serialized_ir(self):
        n, _, _ = CATALOGUE['buck']()
        self.assertNotIn('label', json.dumps(n.to_dict()))
        for c in n.components.values():
            for field in ('x', 'y', 'label', 'sub', 'italic', 'symbol_id'):
                self.assertNotIn(field, c.__slots__)
        with self.assertRaises(ValueError):
            n.add('bad', 'res', svg_symbol='arbitrary')

    def test_nets_query_cannot_modify_ir(self):
        n = CIRCUITS['buck']()
        before = n.signature()
        n.nets[next(iter(n.nets))].clear()
        self.assertEqual(n.signature(), before)

    def test_rejected_connect_is_atomic(self):
        n = CIRCUITS['buck']()
        n.add('EXTRA', 'res')
        before = n.signature()
        with self.assertRaises(ValueError):
            n.connect('new', 'EXTRA.a', 'Q1.d')
        self.assertEqual(n.signature(), before)

    def test_known_kind_ports_follow_electrical_schema(self):
        n = Netlist()
        n.add('R', 'res', ports=('in', 'out'))
        self.assertTrue(any('electrical kind' in p for p in n.validate()))

    def test_aliases_are_electrical_kinds(self):
        n = Netlist()
        n.add('R', 'resistor')
        n.add('V', 'voltage_source')
        n.connect('a', 'V.p', 'R.a')
        n.connect('b', 'V.n', 'R.b')
        self.assertEqual(n.validate(), [])
        self.assertEqual(n.components['R'].kind, 'res')


class PlannerTests(unittest.TestCase):
    def test_all_builders_end_at_ir(self):
        for factory in {**CIRCUITS, **SYNTHETIC}.values():
            self.assertIsInstance(factory(), Netlist)

    def test_plan_is_coordinate_free_and_covers_components_once(self):
        forbidden = {'x', 'y', 'dx', 'dy', 'rows', 'rot', 'spacing', 'svg_symbol'}
        def check(value):
            if isinstance(value, dict):
                self.assertFalse(forbidden & set(value))
                for v in value.values(): check(v)
            elif isinstance(value, (tuple, list)):
                for v in value: check(v)
        for factory in {**CIRCUITS, **SYNTHETIC}.values():
            n = factory()
            plan = auto_plan(n)
            check(plan.describe())
            refs = [r for b in plan.blocks for r in b.members]
            refs += [r for r, *rest in plan.control_interfaces + plan.power_interfaces + plan.references]
            self.assertCountEqual(refs, n.components)

    def test_bridge_and_shunt_are_distinguished(self):
        plan = auto_plan(CIRCUITS['boost']())
        self.assertFalse(any(b.legs for b in plan.blocks))
        self.assertIn(('Q1',), [b.members for b in plan.blocks if b.motif == 'shunt_branch'])
        for name, count in [('buck', 1), ('three_phase_inverter', 3), ('dab', 4)]:
            self.assertEqual(sum(len(b.legs) for b in auto_plan(CIRCUITS[name]()).blocks), count)

    def test_series_order_crosses_isolation_without_shorting_nets(self):
        n = CIRCUITS['llc_resonant']()
        plan = auto_plan(n)
        order = [r for b in plan.blocks for r in b.members]
        self.assertEqual(sorted(['Cr', 'Lr', 'T1', 'D1'], key=order.index),
                         ['Cr', 'Lr', 'T1', 'D1'])
        self.assertNotEqual(n.net_of('T1', 'p1'), n.net_of('T1', 's1'))

    def test_planner_has_no_converter_or_drawing_dependency(self):
        import aipe_sketch.planner as module
        tree = ast.parse(Path(module.__file__).read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                self.assertNotIn(node.module, ('topologies', 'manual_topologies', 'pins', 'parts', 'symlib'))
            if isinstance(node, ast.Attribute):
                self.assertNotEqual(node.attr, 'name')

    def test_reordered_netlist_has_identical_plan(self):
        for factory in CIRCUITS.values():
            n = anonymous(factory())
            reordered = Netlist.from_dict(dict(n.to_dict(),
                components=list(reversed(n.to_dict()['components'])),
                nets=dict(reversed(list(n.to_dict()['nets'].items())))))
            self.assertEqual(auto_plan(n), auto_plan(reordered))


class AutomaticRenderingTests(unittest.TestCase):
    def test_reference_and_synthetic_graphs_validate_without_manual_plans(self):
        with tempfile.TemporaryDirectory() as tmp:
            for name, factory in {**CIRCUITS, **SYNTHETIC}.items():
                n = factory()
                before = n.to_dict()
                s = Schematic.from_netlist(n)
                card, _ = s.render(str(Path(tmp) / (name + '.svg')))
                self.assertEqual(n.to_dict(), before)
                self.assertTrue(card.acceptable, (name, card.faults))
                self.assertEqual(validate.check(n, s.placed, s.paths), [], name)
                self.assertGreaterEqual(card.overall, 90, name)
                self.assertEqual(len(s.candidate_report), 12)
                for p in s.placed.values():
                    b, v = p.body_bbox, p.visual_bbox
                    self.assertLessEqual(v[0], b[0])
                    self.assertGreaterEqual(v[2], b[2])
                    if p.label: self.assertIsNotNone(p.label_keepout)

    def test_renamed_graphs_render(self):
        with tempfile.TemporaryDirectory() as tmp:
            for name, factory in {**CIRCUITS, **SYNTHETIC}.items():
                s = Schematic.from_netlist(anonymous(factory(), reverse=True), candidates=1)
                card, _ = s.render(str(Path(tmp) / (name + '.svg')))
                self.assertTrue(card.acceptable, (name, card.faults))

    def test_manual_baselines_remain_available(self):
        with tempfile.TemporaryDirectory() as tmp:
            for name in ('buck', 'boost', 'llc_resonant'):
                n, plan, opts = CATALOGUE[name]()
                s = Schematic.from_netlist(n, plan=plan)
                s.trunks.update(opts.get('trunks', {}))
                card, _ = s.render(str(Path(tmp) / (name + '.svg')))
                self.assertTrue(card.acceptable)
                self.assertEqual(n.signature(), CIRCUITS[name]().signature())
                self.assertEqual(s.candidate_report, [])

    def test_render_and_selection_are_deterministic(self):
        with tempfile.TemporaryDirectory() as tmp:
            n = CIRCUITS['boost']()
            outputs = []
            for _ in range(2):
                s = Schematic.from_netlist(n)
                path = Path(tmp) / 'drawing.svg'
                s.render(str(path))
                outputs.append((path.read_bytes(), s.selected_candidate, s.candidate_report))
            self.assertEqual(outputs[0], outputs[1])

    def test_long_horizontal_label_reserves_visual_cell(self):
        from aipe_sketch import SchematicText
        n = SYNTHETIC['series_rlc']()
        normal = Schematic.from_netlist(n, candidates=1)
        longer = Schematic.from_netlist(n, candidates=1,
                                       text={'L1': SchematicText('long_inductance_description')})
        self.assertGreater(longer.placed['C1'].x - longer.placed['R1'].x,
                           normal.placed['C1'].x - normal.placed['R1'].x)
        with tempfile.TemporaryDirectory() as tmp:
            card, _ = longer.render(str(Path(tmp) / 'long-label.svg'))
            self.assertTrue(card.acceptable)

    def test_source_free_parallel_block(self):
        n = Netlist('Passive two-port')
        n.add('R', 'res')
        n.add('C', 'cap')
        n.add('A', 'terminal', interface='power', direction='input')
        n.add('B', 'terminal', interface='power', direction='output')
        n.connect('left', 'A.t', 'R.a', 'C.a')
        n.connect('right', 'B.t', 'R.b', 'C.b')
        s = Schematic.from_netlist(n)
        with tempfile.TemporaryDirectory() as tmp:
            card, _ = s.render(str(Path(tmp) / 'passive.svg'))
            self.assertTrue(card.acceptable)
            self.assertLess(s.placed['A'].x, s.placed['R'].x)
            self.assertGreater(s.placed['B'].x, s.placed['R'].x)

    def test_rerouting_after_sheet_translation_preserves_connectivity(self):
        s = Schematic.from_netlist(SYNTHETIC['source_l_r'](), candidates=1)
        with tempfile.TemporaryDirectory() as tmp:
            s.render(str(Path(tmp) / 'translated.svg'))
            s.route()
            self.assertEqual(validate.check(s.netlist, s.placed, s.paths), [])

    def test_a_short_is_never_repaired_by_editing_ir(self):
        s = Schematic.from_netlist(CIRCUITS['buck'](), candidates=1)
        s.route()
        before = s.netlist.to_dict()
        a, b = s.placed['Q1'].port('d'), s.placed['D1'].port('a')
        s.paths['DC_POS'].append([a, (a[0], b[1])])
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(RuntimeError):
                s.render(str(Path(tmp) / 'bad.svg'), force=True)
        self.assertEqual(s.netlist.to_dict(), before)


if __name__ == '__main__':
    unittest.main()
