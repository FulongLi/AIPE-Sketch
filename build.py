#!/usr/bin/env python3
"""Run the pipeline over the reference topologies.

    python3 build.py                 # all of them
    python3 build.py buck dab        # a subset
    python3 build.py --plan buck     # show the plan and analysis, draw nothing
"""
import os
import sys

from aipe_sketch.pipeline import Schematic
from aipe_sketch.synthetic import SYNTHETIC
from aipe_sketch.topologies import CATALOGUE as CONVERTERS

# converters are regression cases; the synthetic circuits test the grammar
# on structure alone, with no converter semantics attached
CATALOGUE = dict(CONVERTERS, **SYNTHETIC)

ROOT = os.path.dirname(os.path.abspath(__file__))
from aipe_sketch.paths import MASTER as SRC


def build(name, out_dir=None):
    netlist, plan, opts = CATALOGUE[name]()
    sch = Schematic(SRC, netlist, plan, size=opts.get('size'))
    sch.trunks.update(opts.get('trunks', {}))
    sch.route()
    for ref, row, dx, dy, text, sub in opts.get('notes', ()):
        sch.note(ref, row, text, sub=sub, dx=dx, dy=dy,
                 anchor='start', italic=False)
    out = os.path.join(out_dir or os.path.join(ROOT, 'out'), f'{name}.svg')
    card, log = sch.render(out)
    return sch, card, log, out


def show_plan(name):
    """Print the stage the LLM reasons about: structure and relationships,
    with no coordinates anywhere in sight."""
    import json
    from aipe_sketch import analysis
    netlist, plan, _ = CATALOGUE[name]()
    print(f'\n=== {name}: topology analysis ===')
    print(json.dumps(analysis.analyse(netlist), indent=2, default=str))
    print(f'\n=== {name}: layout plan ===')
    print(json.dumps(plan.describe(), indent=2))


def main(argv):
    if argv and argv[0] == '--plan':
        for name in argv[1:] or list(CATALOGUE):
            show_plan(name)
        return 0
    names = [a for a in argv if not a.startswith('--')] or list(CATALOGUE)
    failures = []
    for name in names:
        try:
            sch, card, log, out = build(name)
        except Exception as exc:                     # noqa: BLE001
            failures.append(name)
            print(f'\n=== {name}: FAILED ===\n{exc}')
            continue
        print(f'\n=== {name} ===')
        print(card)
        if '--checks' in argv:
            print('  whole-drawing check:')
            for q, (verdict, detail) in card.checks.items():
                note = f'  -- {detail}' if detail else ''
                print(f'    {verdict:<5} {q}{note}')
        for line in log:
            print(f'  repair: {line}')
        print(f'  -> {os.path.relpath(out, ROOT)}')
    if failures:
        print(f'\nfailed: {", ".join(failures)}')
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
