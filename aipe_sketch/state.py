"""Explicit Engineering State -> Circuit IR mapping without topology inference.

Core owns validation of the complete state. This adapter validates the fields it
consumes and the explicit circuit; a converter name is insufficient connectivity.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .netlist import Netlist


def _digest(value):
    data = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
    return hashlib.sha256(data.encode('utf-8')).hexdigest()


def from_engineering_state(state):
    """Read `extensions['aipe.sketch'].circuit_ir`; never modify the source state."""
    if not isinstance(state, dict) or state.get('schema_version') != '0.1.0':
        raise ValueError('AIPE Engineering State schema_version 0.1.0 is required')
    if not isinstance(state.get('id'), str) or not state['id']:
        raise ValueError('state id is required')
    extension = state.get('extensions', {}).get('aipe.sketch', {})
    if not isinstance(extension, dict) or 'circuit_ir' not in extension:
        raise ValueError('explicit extensions.aipe.sketch.circuit_ir is required; topology labels do not define a circuit')
    if set(extension) != {'circuit_ir', 'evidence_refs'}:
        raise ValueError('aipe.sketch requires exactly circuit_ir and evidence_refs')
    references = extension['evidence_refs']
    if not isinstance(references, list) or not references or any(not isinstance(ref, str) for ref in references):
        raise ValueError('circuit evidence_refs must be a nonempty list of evidence IDs')
    evidence = {item['id']: item for item in state.get('evidence', [])}
    for reference in references:
        if reference not in evidence or evidence[reference].get('review_status') == 'rejected':
            raise ValueError(f'unknown or rejected circuit evidence: {reference}')
    circuit = Netlist.from_dict(extension['circuit_ir'])
    faults = circuit.validate()
    if faults:
        raise ValueError('invalid circuit: ' + '; '.join(faults))
    return circuit


def render_engineering_state(state, output):
    """Render SVG plus a hash-linked sidecar; no physical validation is inferred."""
    from .pipeline import Schematic
    circuit = from_engineering_state(state)
    output = Path(output)
    if output.suffix.lower() != '.svg':
        raise ValueError('schematic output must use the .svg extension')
    # Validate JSON values before producing an artifact.
    state_hash, circuit_hash = _digest(state), _digest(circuit.to_dict())
    schematic = Schematic.from_netlist(circuit)
    output.parent.mkdir(parents=True, exist_ok=True)
    schematic.render(str(output))
    provenance = {
        'schema_version': '0.1.0',
        'tool': {'id': 'aipe.sketch', 'adapter_version': '0.1.0'},
        'source_state': {'id': state['id'], 'sha256': state_hash},
        'circuit_ir_sha256': circuit_hash,
        'evidence_refs': list(state['extensions']['aipe.sketch']['evidence_refs']),
        'artifact': {'path': output.name, 'media_type': 'image/svg+xml',
                     'sha256': hashlib.sha256(output.read_bytes()).hexdigest()},
        'validation': {'connectivity': 'checked', 'physical': 'not_run'},
        'limitations': ['Circuit connectivity was explicitly supplied; component sizing and physical performance are not inferred.',
                        'The complete Engineering State must be validated against AIPE-Core separately.'],
    }
    sidecar = output.with_suffix('.provenance.json')
    sidecar.write_text(json.dumps(provenance, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    return provenance


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description='Render explicit Core state circuit IR to SVG and provenance JSON')
    parser.add_argument('state', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args(argv)
    try:
        state = json.loads(args.state.read_text(encoding='utf-8'))
        render_engineering_state(state, args.output)
    except (ValueError, KeyError, TypeError, OSError) as exc:
        parser.exit(1, f'{exc}\n')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
