#!/usr/bin/env python3
"""Run the pipeline over the reference topologies.

    python3 build.py                 # all of them
    python3 build.py buck dab        # a subset
    python3 build.py --plan buck     # show the plan and analysis, draw nothing
"""
import os
import sys

from aipe_sketch.pipeline import Schematic
from aipe_sketch.synthetic import CIRCUITS as SYNTHETIC
from aipe_sketch.topologies import CIRCUITS as CONVERTERS

# converters are regression cases; the synthetic circuits test the grammar
# on structure alone, with no converter semantics attached
CATALOGUE = dict(CONVERTERS, **SYNTHETIC)

ROOT = os.path.dirname(os.path.abspath(__file__))
from aipe_sketch.paths import MASTER as SRC


def build(name, out_dir=None, manual=False):
    if manual:
        from aipe_sketch.manual_topologies import CATALOGUE as converters
        from aipe_sketch.manual_synthetic import SYNTHETIC as synthetic
        netlist, plan, opts = dict(converters, **synthetic)[name]()
        sch = Schematic(SRC, netlist, plan, size=opts.get('size'))
        sch.trunks.update(opts.get('trunks', {}))
    else:
        sch = Schematic.from_netlist(CATALOGUE[name]())
    out = os.path.join(out_dir or os.path.join(ROOT, 'out'), f'{name}.svg')
    card, log = sch.render(out)
    return sch, card, log, out


def show_plan(name, manual=False):
    """Print the stage the LLM reasons about: structure and relationships,
    with no coordinates anywhere in sight."""
    import json
    from aipe_sketch import analysis
    netlist = CATALOGUE[name]()
    from aipe_sketch.planner import auto_plan
    plan = auto_plan(netlist)
    if manual:
        from aipe_sketch.manual_topologies import CATALOGUE as converters
        from aipe_sketch.manual_synthetic import SYNTHETIC as synthetic
        netlist, plan, _ = dict(converters, **synthetic)[name]()
    print(f'\n=== {name}: topology analysis ===')
    print(json.dumps(analysis.analyse(netlist), indent=2, default=str))
    print(f'\n=== {name}: layout plan ===')
    print(json.dumps(plan.describe(), indent=2))


def main(argv):
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('names', nargs='*')
    parser.add_argument('--plan', action='store_true')
    parser.add_argument('--manual', action='store_true', help='use saved regression plans')
    parser.add_argument('--checks', action='store_true')
    args = parser.parse_args(argv)
    available = CATALOGUE
    if args.manual:
        from aipe_sketch.manual_topologies import CATALOGUE as converters
        from aipe_sketch.manual_synthetic import SYNTHETIC as synthetic
        available = dict(converters, **synthetic)
    names = args.names or list(available)
    for name in names:
        if name not in available:
            parser.error(f'unknown circuit {name!r}; choose from {", ".join(available)}')
    if args.plan:
        for name in names:
            show_plan(name, manual=args.manual)
        return 0
    failures = []
    for name in names:
        try:
            sch, card, log, out = build(name, manual=args.manual)
        except Exception as exc:                     # noqa: BLE001
            failures.append(name)
            print(f'\n=== {name}: FAILED ===\n{exc}')
            continue
        print(f'\n=== {name} ===')
        print(card)
        if args.checks:
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
