"""Bounded geometry-only search over one graph-derived semantic plan.

Every candidate is independently placed, rerouted, relabelled, scored and
validated. Connectivity is never repaired. Stable iteration order breaks ties.
"""
from .grammar import lower


def candidate_plans(semantic, circuit, limit=12):
    if not 1 <= limit <= 12:
        raise ValueError('candidate count must be between 1 and 12')
    # Compact global scales, with small local branch displacement alternatives.
    profiles = [(gap, bridge, shunt) for gap in (0, -1)
                for bridge in (0, -1) for shunt in (0, -1, 1)]
    for gap, bridge, shunt in profiles[:limit]:
        plan = lower(semantic, circuit)
        plan.opts['gap_adjacent'] += gap
        plan.opts['gap_bridge'] += bridge
        # Series and parallel scales are invariants, not optimisation slack.
        shunts = {r for b in semantic.blocks if b.motif == 'shunt_branch'
                  for r in b.members}
        controls = {r for r, target, port in semantic.control_interfaces if target in shunts}
        for _, _, item in plan.items():
            if item.ref in shunts | controls:
                item.dy += shunt
        yield plan, dict(gap_delta=gap, bridge_delta=bridge, shunt_delta=shunt)


def select(schematic, count=12, text=None):
    from .pipeline import Schematic
    circuit = schematic.netlist
    signature = circuit.to_dict()
    best, best_key = None, None
    reports = []
    for i, (plan, profile) in enumerate(candidate_plans(schematic.semantic_plan, circuit, count)):
        try:
            trial = Schematic(schematic.source, circuit, plan, size=schematic.fixed_size,
                              title=schematic.title, text=text)
            trial.route()
            trial.build_labels()
            trial.resolve_markers()
            trial.build_labels()
            card = trial.evaluate()
            # Valid drawings always outrank invalid ones, regardless of score.
            key = (not card.acceptable, -card.overall, card.cost, i)
            reports.append(dict(index=i, profile=profile, acceptable=card.acceptable,
                                score=card.overall, cost=card.cost, faults=list(card.faults)))
            if best_key is None or key < best_key:
                best, best_key = trial, key
        except ValueError as exc:
            reports.append(dict(index=i, profile=profile, acceptable=False, error=str(exc)))
    if circuit.to_dict() != signature:
        raise RuntimeError('geometry search changed Circuit IR')
    if best is None:
        raise ValueError('no placeable candidate: ' + str(reports))
    best.auto = True
    best.candidate_report = reports
    best.selected_candidate = best_key[-1]
    return best
