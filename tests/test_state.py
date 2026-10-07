"""Engineering State boundary tests; physical performance is deliberately absent."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from aipe_sketch.state import from_engineering_state, render_engineering_state
from aipe_sketch.topologies import buck, dab


def state(circuit=None):
    # A consumed-field fixture, not a replacement for full Core schema validation.
    return {'id': 'aipe.example.dab-10kw', 'schema_version': '0.1.0',
            'converter': {'topology': 'dual-active-bridge'},
            'evidence': [{'id': 'evidence.explicit-circuit', 'kind': 'assumption', 'review_status': 'unreviewed'}],
            'extensions': {'aipe.sketch': {'circuit_ir': (circuit or dab()).to_dict(),
                                           'evidence_refs': ['evidence.explicit-circuit']}}}


class TestStateMapping(unittest.TestCase):
    def test_preserves_explicit_connectivity_and_input(self):
        source = state()
        original = copy.deepcopy(source)
        self.assertEqual(from_engineering_state(source).signature(), dab().signature())
        self.assertEqual(source, original)

    def test_topology_label_does_not_invent_connectivity(self):
        source = state()
        del source['extensions']
        with self.assertRaisesRegex(ValueError, 'explicit'):
            from_engineering_state(source)

    def test_unknown_version_and_rejected_evidence_fail(self):
        source = state()
        source['schema_version'] = '1.0.0'
        with self.assertRaises(ValueError):
            from_engineering_state(source)
        source = state()
        source['evidence'][0]['review_status'] = 'rejected'
        with self.assertRaises(ValueError):
            from_engineering_state(source)

    def test_invalid_circuit_rejected(self):
        source = state()
        source['extensions']['aipe.sketch']['circuit_ir']['nets']['DCP1'].append('Q1.missing')
        with self.assertRaises((ValueError, KeyError)):
            from_engineering_state(source)

    def test_rendered_artifact_has_matching_hashes_and_no_physical_claim(self):
        source = state(buck())
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'buck.svg'
            report = render_engineering_state(source, output)
            self.assertEqual(report['artifact']['sha256'], hashlib.sha256(output.read_bytes()).hexdigest())
            self.assertEqual(report['validation']['physical'], 'not_run')
            self.assertEqual(report, json.loads(output.with_suffix('.provenance.json').read_text()))
            self.assertEqual(report, render_engineering_state(source, output))


if __name__ == '__main__':
    unittest.main()
