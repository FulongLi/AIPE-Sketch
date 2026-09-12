# Circuit IR architecture audit

## Phase 1: baseline (before implementation)

The baseline passes 177 unittest checks. `Netlist` owns components and named
hyperedges and enforces single-net port membership, but its components also
store label text, subscripts and italic styling. Port validation and graph
colour refinement depend on the symbol registry. There is no independent
electrical component schema or serialization contract.

`parts.Registry`, `pins`, and the canonical master SVG already own symbol
geometry, port offsets, provenance, labels and visual margins. These remain
authoritative for drawing; electrical port names and equivalence belong in
an independent electrical schema.

`analysis` discovers legs, rail candidates and graph equivalence classes.
`LayoutPlan` is a manual geometric constraint language: despite its docstring,
rows, offsets and spacing are geometric. Every reference and synthetic builder
constructs one, and some provide routing trunks. No automatic planner exists.

`placement` handles relationship-aware spacing; `router` handles Manhattan
paths; `labels` searches collision-free candidates; `score` measures general
properties; `validate` reconstructs connectivity. `repair` only reports missing
labels. These are schematic backend concerns, not Circuit IR concerns.

## Ownership contract

| Layer | Owns | Must not own |
| --- | --- | --- |
| Circuit IR | kinds, named ports, nets, roles, external interfaces, electrical attributes | symbols, coordinates, labels, spacing |
| Electrical schema | port names, control/power semantics, interchangeable ports | SVG or port offsets |
| Symbol registry | master symbol mapping, body/port geometry, margins, typography, provenance | circuit connectivity |
| Analysis / automatic plan | graph motifs, energy-transfer ordering, branch and interface relationships | coordinates, SVG, converter-name dispatch |
| Drawing grammar / manual plan | symbolic relationships translated into rows, slots, orientations, corridors | electrical changes |
| Placement / routing / labels | visual cells, coordinates, wire paths, collision-free labels | electrical changes |
| Scoring / candidate search | deterministic geometry alternatives, validation and ranking | electrical changes |

Manual plans remain expert overrides and regression baselines. The new default
must derive its schematic entirely from the electrical graph and the global
grammar. Simulation execution is outside this refactor; independent validation
and versioned electrical serialization establish the future backend boundary.

## Implemented migration

1. The baseline audit above was recorded before changing behavior.
2. `planner.graph_analysis` contracts electrical bridge and parallel motifs,
   removes return/control shortcuts, and derives an ordered transfer graph.
   `AutoPlan` records block ordering, incoming nets, local branch relationships,
   references, interfaces, equivalent classes and a dominant source-to-sink path.
3. `grammar.lower` applies global series, shunt, bridge, transverse-branch,
   parallel and interface rules. No converter name or builder is consulted.
   All seven reference converters now use this path by default.
4. The grammar covers isolated passive networks, primary/secondary bridges,
   rectifying devices and repeated leg families. Transformer alignment uses the
   registry's actual port offset. Each isolation-domain return remains separate.
5. `Schematic.from_netlist` searches up to 12 candidates (12 by default), ranks
   valid drawings first, and keeps manual `LayoutPlan` support. Candidate repairs
   change adjacent spacing, repeated bridge spacing and local shunt displacement;
   every trial is placed, rerouted, relabelled and electrically validated.
   Series and parallel gap scales stay fixed. Rendering revalidates the winner.
6. Electrical kinds, port declarations and port equivalence live in
   `electrical.py`. `Netlist.validate()` and version-1 JSON interchange do not
   depend on SVGs. Importing `Netlist` does not load schematic modules. Custom
   kinds can declare ports and electrical attributes for other backends.

Placed components expose `body_bbox`, `visual_bbox`, `label_keepout` and `ports`.
Placement reserves provisional visual margins and horizontal label projections;
relationship gaps absorb those margins instead of accumulating arbitrary padding.
The global label solver computes the final label keepouts after routing.

## Compatibility and limitations

The public functions in `topologies.py` and `synthetic.py` now return Netlist.
Their `CIRCUITS` mappings drive the default build. The historic tuple-returning
`CATALOGUE` / `SYNTHETIC` mappings point at preserved `manual_*` fixtures so old
comparison tests and expert callers can migrate independently. `--manual` only
lists fixtures with a saved baseline.

Legacy label keywords and read-only component label accessors delegate to a weak
presentation sidecar. They are absent from component slots, electrical attributes
and JSON. New code should pass `SchematicText` to the schematic backend.
Electrical interface `name` and `direction` are optional semantic attributes;
marker geometry and typography are backend decisions.

Power flow is a deterministic structural inference, not proof of operating-point
energy transfer. Equal-cost choices may depend on stable reference ordering.
Recognised bridge families get identical geometry; general graph equivalence does
not yet synthesize every possible repeated multi-component module. The bounded
search does not exhaust permutations or routing corridors. Unsupported graphs
remain explicit validation failures rather than silently altered circuits.
No simulation execution or SPICE/PLECS/Simulink exporter is implemented here.
