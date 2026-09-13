# AIPE-Sketch

Generate a schematic from an electrical circuit graph, the master symbol library,
and a general drawing grammar. The schematic is a view of the circuit.

## Pipeline

```
Circuit IR → graph analysis → coordinate-free AutoPlan
           → drawing grammar → placement → Manhattan routing → global labels
           → score geometry candidates → connectivity validation → SVG
```

`Schematic.from_netlist()` is the primary API. Converter names are never inputs
to the planner or scorer. Reference converters and synthetic networks are test
inputs. The master `assets/master/Inkscape_Symbols_All.svg` remains authoritative.

| Layer | Modules | Responsibility |
| --- | --- | --- |
| Electrical IR | `netlist.py`, `electrical.py` | Components, named ports, nets, interfaces, roles and electrical attributes |
| Graph planning | `analysis.py`, `planner.py` | Recognise motifs, infer power flow, describe relationships without coordinates |
| Drawing grammar | `grammar.py`, `plan.py`, `config.py` | Translate relationships into rows, slots, orientations and spacing |
| Symbol library | `parts.py`, `pins.py`, master SVG | Kind-to-symbol mapping, port geometry, margins and provenance |
| Geometry | `placement.py`, `router.py`, `labels.py` | Visual cells, coordinates, paths and collision-free labels |
| Selection and validation | `candidates.py`, `score.py`, `validate.py` | Rank 12 deterministic geometry candidates; reject electrical mismatches |
| Presentation | `presentation.py`, `pipeline.py` | Optional text styling and rendering |

`AutoPlan` contains no coordinates or spacing. The older `LayoutPlan` is a
geometric constraint language retained for expert overrides and baseline tests.
See [the audit and migration notes](docs/architecture.md).

Ground domains are explicit electrical kinds. Use `power_ground` for the IEC
earth-bar symbol and `digital_ground` (aliases `digital_gnd`, `dgnd`, or
`signal_ground`) for the open inverted-triangle symbol. Legacy `gnd` and
`ground` inputs resolve to `power_ground`; separate ground components remain on
separate nets unless the circuit IR deliberately connects those nets.

## Usage

```python
from aipe_sketch import Netlist, Schematic

circuit = Netlist('Inductive branch')
circuit.add('V1', 'voltage_source')
circuit.add('L1', 'inductor', inductance=0.001)
circuit.add('R1', 'resistor', resistance=10)
circuit.connect('input', 'V1.p', 'L1.a')
circuit.connect('output', 'L1.b', 'R1.a')
circuit.connect('return', 'V1.n', 'R1.b')

schematic = Schematic.from_netlist(circuit)
schematic.render('out/branch.svg')
```

```bash
python3 build.py                         # automatic planning for every example
python3 build.py buck dab                # a subset
python3 build.py --plan buck             # electrical analysis and relational plan
python3 build.py --manual buck           # preserved manual baseline
python3 build.py --checks
python3 -m unittest discover -s tests
```

`topologies.CIRCUITS` and `synthetic.CIRCUITS` contain Netlist-only builders.
The old `CATALOGUE` / `SYNTHETIC` tuple-returning maps remain compatibility
aliases to `manual_topologies.py` / `manual_synthetic.py`.

For an explicit override use `Schematic.from_netlist(circuit, plan=manual_plan)`.
For a single deterministic plan use `candidates=1`. The default searches 12
small spacing and shunt-position variants. Every variant is rerouted, relabelled,
scored and validated; valid candidates always outrank invalid ones. Inspect
`candidate_report` and `selected_candidate` to see the decision.

Electrical validation requires no SVG: `circuit.validate()` checks the declared
ports. `Netlist.from_dict(circuit.to_dict())` round-trips versioned electrical
JSON without drawing metadata. Unknown electrical kinds can declare `ports=`;
a schematic additionally requires a matching symbol registry entry.

Optional notation belongs to the backend:

```python
from aipe_sketch import SchematicText
schematic = Schematic.from_netlist(
    circuit, text={'V1': SchematicText('V', 'supply')})
```

Legacy `add(label=..., sub=..., italic=...)` arguments are accepted through a
weak presentation sidecar, never stored or serialized as electrical attributes.
New regression builders do not use them.

## Regression coverage

Seven reference converters and seven synthetic circuits exercise the default
path. Tests also rename every component and net, reverse insertion order,
verify isolated net partitions, compare manual connectivity, and inject shorts.
[Regression results](docs/auto-planning-results.md) record automatic/manual
scores and validity. A passing score is not a proof that every arbitrary graph
will have an acceptable layout; the renderer rejects invalid candidates.

## Spacing comes from relationships, not groups

Gap is decided for each **adjacent pair** from how the two are connected,
because a group may hold a series element feeding a parallel block and
classifying the whole group gives neither the right spacing:

| relationship | gap |
|---|---|
| joined by a two-terminal net (series) | 2 G |
| shunted across the same node pair (parallel) | 2 G |
| sharing a node (directly connected) | 4 G |
| unrelated, across a functional boundary | 6 G |
| legs of one bridge | 6 G, uniform pitch |

An electrical relationship crossing a functional boundary overrides the
boundary. Only a bridge keeps a uniform pitch, because its legs must stay
evenly spaced.

## Topology motifs

A switching device is not automatically half of a bridge.
`planner.graph_analysis` discovers source/DC-link blocks, series paths, shunts,
bridge families, parallel blocks, isolation, rectifiers, loads and interfaces.
`analysis.classify_motifs` remains a legacy local diagnostic. Core rules include:

| motif | how it is recognised | placement |
|---|---|---|
| `bridge_leg` | the high device hangs from the positive supply | stacked, midpoint between |
| `shunt_switch` | low port on the reference, high port on a main-path node | centred in its own branch |
| `series_power_path` | passives joined two-at-a-time in series | one horizontal line |
| `parallel_output_block` | two or more shunt parts sharing the same net pair | one compact block |

```
boost          shunts=['Q1']            bridge_legs=[]
buck           shunts=[]                bridge_legs=['Q1/D1']
half_bridge    shunts=[]                bridge_legs=['Q1/Q2']
```

A boost is **not** a half bridge. Its main path stays horizontal and Q1 hangs
from the switching node down to the return rail:

```
Vin ─── L1 ─── ● ─── D1 ─── output
               │
               Q1
               │
              GND
```

`shunt_branch_balance` scores `|L_top - L_bottom| / (L_top + L_bottom)` for
every shunt, and `shunt_verticality` fails any shunt whose power terminals are
not vertically aligned. Before this, the boost scored a **perfect 1.0
imbalance** -- 2.00 cells above the switch and 0.00 below, because bridge-leg
geometry dropped it onto the rail. It is now 1.0 / 1.0, error 0.

> The buck's freewheel diode stays a **bridge-leg member, not a shunt**: a buck
> *is* a half bridge with the low-side switch replaced by a diode, and its
> anode belongs on the rail. Rebalancing it would lift it off the rail, which
> is not how a buck is drawn.

## Main power path

A resonant converter's primary side -- switching node, Cr, Lr, transformer --
should read as one continuous horizontal line. Two metrics enforce that:

* **`centreline_deviation`** finds runs of passives joined in series and
  penalises any vertical step between consecutive members, measured at the
  ports that actually join them.
* **`near_component_bend_penalty`** penalises a corner within one local wire
  length of a passive or magnetic port -- a wire should leave a capacitor,
  inductor or transformer along that component's own axis.
* **`port_connection_geometry`** applies the same convention to every direct
  point-to-point power connection. The first/last segment follows the declared
  port face, and its soft length target is one half of that component's body
  width (side port) or height (top/bottom port). Rails, buses, grounds,
  terminals and control nets are exempt because the floorplan sets their stub
  length.

A *series link* is a net joining exactly two components. A rail or a filter
tap has more, and the parts on it are not in series -- without that
distinction the DC- rail looked like a Cr-to-T1 chain.

The LLC places its transformer half a symbol below the switching-node row, so
`T1.p1` lands exactly on that row and the whole tank stays collinear:

```
Q1/Q2 midpoint ──── Cr ──── Lr ──── T1 ┃ ──── D1 ──── C2 ──── R1
```

### Spacing by relationship

| relation | target | LLC measured |
|---|---|---|
| series passive chain | 2 G | Cr→Lr **2.0**, D1→C2 **2.0** |
| chain across a boundary | 2 G | Lr→T1 **2.8**, T1→D1 **2.8** |
| functional group | 6 G | Q1→Cr **6.5** |

Chain detection crosses functional boundaries -- a tank running into a
transformer is one chain even though they are different blocks -- and
rectifiers count, so a transformer never sits far from the rectifier after
it. A ground glyph sharing a slot is neutral and does not break a chain.

Chain members carry a reduced keep-out (0.5 G) on the facing sides only.

## Visual scale

Every symbol in the library is exactly **4 G tall**, so 4 G is the unit of
visual scale — one component dimension, called `CELL`. Every spacing derives
from it:

| quantity | value |
|---|---|
| clearance between neighbouring bodies | 1 CELL |
| leg midpoint gap | 1 CELL (1.5 where take-off corridors need room) |
| slot pitch inside a group | widest body + 1 CELL |
| functional-group pitch | 10 G |
| around a transformer | 9 G — more clearance than a passive gets |

Slot pitch is derived from the group's own widest body, so narrow passives sit
close together while switching devices keep a full cell apart. Because every
slot of a repeated structure holds the same devices, repeated structures still
come out evenly spaced. Measured body-to-body gaps across the catalogue
are 1.00–1.12 CELL.

The sheet is fitted to its content and the whole drawing is shifted into the
margin by a whole number of grid steps, so nothing is ever clipped and
placement stays on grid.

## Terminals, junctions and boundaries

Four visually distinct things:

| meaning | drawn as |
|---|---|
| exposed power boundary (an output port, a phase terminal) | open circle, r = 0.6 mm |
| electrical junction | filled dot, r = 0.4 mm |
| control port, ordinary connection, crossing | nothing |

**A boundary marker is reserved for main power-side interfaces.** Gate drives,
control ports, switching nodes, transformer connections and every other
internal node carry none — a wire ending somewhere is never reason enough.

Interface status is explicit metadata on the component, one of:

* `interface='power'` — a main power boundary; carries the marker.
* `interface='control'` — a gate drive or sensing port. A switch-gate
  interface stays in Circuit IR for connectivity, but is co-located with the
  gate in the schematic: the library symbol's own gate lead is retained and no
  additional line segment or boundary marker is drawn.
* `None` — not an interface. The netlist refuses a terminal without one, and
  refuses an interface on anything that is not a terminal.

### Marker geometry

The wire stops **at the circumference**, never running to the centre:

```
wire ─────○          not   wire ──────⊕────
```

The circle is placed one radius beyond the wire's end, along the wire's own
axis. The outward direction is taken from the segment that actually arrives,
so nothing has to be declared by hand and the circle is automatically centred
on the wire axis whichever way the connection approaches.

`marker_geometry` checks both halves: the port must sit exactly one radius
from the centre, and no wire may reach into the circle's interior. A test
pushes a wire through a marker to confirm the check can fail.

## VIN and VOUT are semantic, not mandatory ink

A net may be *called* `VOUT` for analysis without that implying any rendered
text. Semantic net name and drawn label are separate concerns, and nothing
creates a label merely because a circuit has an input and an output.

**Input.** When a circuit has an explicit source, the source carries the name
itself — labelled `V_in`, not `V1` with a second `VIN` annotation beside it.

**Output.** No output port is appended just to say "this is the output". A
converter that ends in `Cout + RL` simply ends there. A port appears only
where the output is genuinely exposed:

| topology | output |
|---|---|
| buck, boost, DAB, full bridge | ends at its load network — no port |
| half bridge | `VOUT` exposed: it has no load of its own |
| three-phase inverter | `PHA`, `PHB`, `PHC` exposed |

`redundant_annotation` enforces this rather than trusting the topology
definitions. It catches both anti-patterns by name:

* a source labelled `V1` with a separate `VIN` annotation nearby →
  *"label the source itself instead"*
* an output port on a net that already contains a load →
  *"the output already ends in a load network, so an output terminal adds
  nothing"*

Tests inject both to confirm the check can fail.

## Extracted component library

The master sheet is split into a clean, per-section library:

```
assets/master/Inkscape_Symbols_All.svg      canonical, never generated
assets/generated_symbols/<section>/*.svg    derived, regenerate freely
assets/symbol_registry.json                 the index
out/catalog_<section>.svg                   review catalogues
out/library_report.{txt,json}               inspection report
```

```bash
python3 tools/extract_library.py --report
python3 tools/extract_library.py --section standard_elements --catalog
python3 tools/extract_library.py --all --catalog
```

**191 symbols across 14 sections; 158 clean, 33 need cleaning.** Sections are
detected from the sheet's own headings, not assumed — heading-sized text is
matched against the real section titles so an in-drawing `+`, `n:1` or `f(t)`
is never mistaken for one.

### Clustering is what makes this work

Many `<symbol>` wrappers enclose geometry from neighbouring drawings, so their
bounding boxes are meaningless — `g7138` claims 144 mm for a 10 mm device.
Grouping each wrapper's children by proximity separates the device from the
strays. The largest cluster is the device; the rest are flagged, never
discarded.

Two bugs had to be fixed before this was trustworthy, both found by looking at
the rendered catalogue rather than the numbers:

* **Transforms were only half handled.** First `translate` was ignored
  entirely — `g10556` wraps a diode in a group carrying `translate(19.84)` and
  extracted as a doubled symbol. Then `rotate` and `scale` were still ignored,
  which is what hid the transformer's secondary winding. Geometry is now
  walked with a full affine matrix stack (translate, scale, rotate about a
  centre, matrix, skew).
* **A symbol is placed by its `<use>`, not its own frame.** Section assignment
  read symbol-local coordinates, putting the battery under *Designators*.
  Using the page position fixed the inventory.

The cluster gap is 2 mm: above ~1.6 mm a capacitor's plates stay together,
and much above 2 mm neighbouring components on the sheet start merging — which
is what made `Resistor_US` extract with a MOSFET on top of it.

### Provenance

Every extracted file and registry entry records `semantic_name`,
`original_symbol_id`, `source_section`, `source_file`, `original_bbox`,
`clean_bbox`, `anchor`, `default_orientation`, `status` and
`source_type: extracted_library`. Variants are kept distinct rather than
overwritten (`capacitor` / `capacitor_polarised`, `inductor_air_core` /
`inductor_cored`, `mosfet_n_enhancement` / `mosfet_n_depletion`); where the
`<title>` alone is ambiguous the symbol id is appended.

`source_version` is a digest of the master, so extraction is reproducible — a
test re-runs it and compares bytes.

### Transformers

All ten candidates were extracted, cleaned and rendered. The first pass
concluded no wrapper held a complete two-winding device — that conclusion was
wrong, and the catalogue is what exposed it.

`g7138` draws its **secondary winding as a `rotate(180)` copy** of the primary,
and `path5746` carries `scale(-1)`. The extractor only parsed `translate`, so
the secondary was measured 10 mm away from where it draws and fell outside the
device cluster. With full affine transforms the wrapper yields the complete
symbol:

| | before | after |
|---|---|---|
| `g7138` cleaned | 5.7 × 10.6, primary + core only | **6.6 × 10.6, both windings, core, polarity dots** |
| `g5846`, `g5868` | empty housing boxes | boxes with their windings drawn |
| `g8072`, `g8142`, `g8123`, `g6295`, `g21122`, `g33442` | outlines | complete vector-group symbols |

`g7138` is now the transformer the schematics use, and the hand-assembled
compound is gone. The registry reports it as `library g7138 (cleaned)`:

```
14 from the library, 0 assembled, 1 custom
  terminal: the sheet has no open-circle interface marker
  transformer: wrapper also encloses neighbouring geometry, so only the
               device's own children are kept
```

`pins.py` names the six child ids to keep. The coupling arrow and the `n:1`
text are left out — they are annotations, and dropping them keeps the symbol
at the library's 4 G height. Nothing is redrawn.

## Symbol registry

`Inkscape_Symbols_All.svg` → `symlib` parser → `parts.Registry` → renderer,
placement metadata, pin geometry. The master sheet is the authoritative
graphical source and is always parsed directly; **no part of the pipeline
reads an exported file**, and a test builds a drawing with the previews
deleted to prove it.

Components are requested by semantic name, never built as paths:

```python
registry.get('capacitor')       # aliases resolve: cap
registry.get('voltage_source')  # vsource
registry['nmos'].symbol_id      # 'g4046'
```

Each kind exposes `symbol_id`, `bbox`, `ports` with preferred sides,
`default_rotation`, `preferred_orientation`, `semantic_role`, `visual_margin`,
`preferred_label_side`, `preferred_label_offset`, and its provenance.

### Lookup priority

1. **library** — instantiate a `<symbol>` from the master sheet.
2. **compound** — assemble from library primitives.
3. **custom** — only when neither is possible, and the reason is recorded.

`python3 tools/export_symbols.py --report` audits this:

```
kind         source    symbol      ports
nmos         library   g4046       d,g,s
igbt         library   g13197      c,e,g
cap          library   g8210       a,b
transformer  cleaned_library  g7138  p1,p2,s1,s2
terminal     custom    -           t

13 from the library, 1 assembled, 1 custom
  terminal: the sheet has no open-circle interface marker; its only lone
            circles are filled GND glyphs
  transformer: every transformer <symbol> on the sheet encloses geometry
            scattered across the whole drawing and cannot be instantiated;
            assembled from the library coil instead
```

Both non-library cases were verified against the sheet rather than assumed.
The sheet does carry IEC source forms (`voltage_source`, a bar parallel to the
terminals; `g6663`, perpendicular) — but none shows `+`/`−` polarity or a
current arrow, so the library circle `g11181` supplies the body and only the
missing marks are added over it. That shows in the audit as `library g11181 +
marks`.

### Geometry is preserved

Placement may translate, rotate by a right angle, and mirror. Nothing else.
`symbol_integrity` compares each placed part's drawn extent against its
registry extent and fails on any difference:

```
Q1: drawn x extent 14.817 mm but the library symbol is 10.583 mm -- it has been scaled
Q1: rotated 37 deg, not a right angle
```

Tests inject both to confirm the check can fail.

### Generated previews

`python3 tools/export_symbols.py` writes `assets/generated_symbols/<kind>.svg`
with ports and margin boxes marked, plus `registry.json`. These are generated
artefacts for debugging, documentation, inspection and tests — not the
canonical source, and gitignored.

Each file carries its provenance so a stale preview is obvious:

```xml
<!-- generated from Inkscape_Symbols_All.svg [61f2f1a5919bcf8c] -- library g4046; regenerate, do not edit -->
<aipe:generated source-file="Inkscape_Symbols_All.svg" source-symbol="g4046"
                source-version="61f2f1a5919bcf8c" kind="nmos"
                symbol-source="library" .../>
```

`source-version` is a digest of the master sheet, not a wall-clock time, so
two runs over the same master are byte-identical — a test asserts it.

## Label placement

All label placement goes through one engine (`labels.py`). Topology
definitions describe the circuit; they never choose a label position -- a test
asserts `topologies.py` contains no `label_side=` or `label_offset=`.

For each component the engine takes the registry's preferred side, generates
candidates in a fixed order (preferred, opposite, above, below, left, right),
rejects any that collide with a body, another label, a wire, a junction dot or
a terminal marker, and keeps the cheapest survivor. Cost weighs departure from
the preferred side, distance from the body and its port, and remaining
clearance. **It never returns an overlapping position** -- if every candidate
fails it returns nothing, and the drawing is rejected.

Preference is per orientation, not per rotation alone:

```python
'filter': dict(side='left', flat='above', offset=1.3)
```

Rotating the upright preference cannot express the convention: a capacitor
prefers `left` standing up, which rotates to `below`, but a horizontal
capacitor should be labelled `above` like every other flat passive. The
registry therefore holds both, and the engine picks by orientation.



Side and offset come from the registry per semantic role, so equivalent
components place their labels at identical distances — `label_distance`
irregularity is 0 across the catalogue. A component laid on its side (a
horizontal L/C/R/D) is labelled above, per convention.

Every label carries a **clearance margin**, not merely a non-overlap
requirement: 0.5 G horizontal and 0.35 G vertical. Nothing — body, other
label, or wire — may enter that box.

An `above` label is anchored by its baseline, so its box still reaches below
that by the descent plus the pad. `MIN_STACK_OFFSET` clamps stacked offsets so
a label can never sit inside its own body; that was a real bug, found when the
transformer's label dipped 0.14 mm into it.

When the repair loop moves a label, it moves **every member of that
equivalence class together** — a repeated structure with one label on a
different side reads worse than the collision did.

## Source and transformer symbols

The sheet's source circle carries no polarity and no direction, and
conventional practice requires both, so they are drawn as decoration over the
library symbol: `+` and `\u2212` inside the circle with the plus toward the
positive terminal, and a current source gets a shaft-and-head arrow pointing
from the current-entry terminal to the current-exit one.

The transformer comes from the sheet as well — `g7138`, cleaned to its own six
child elements. It is 2.5 G × 4.0 G, a width-to-height ratio of 0.63;
`transformer_spread` fails anything wider than tall, since a spread-out
transformer reads as two separate inductors.

## Netlist as source of truth

```python
n = Netlist('Half Bridge')
n.add('Q1', 'nmos')
n.add('Q2', 'nmos')
n.connect('DC_POS', 'V1.p', 'Cdc.a', 'Q1.d')
n.connect('SW_A',   'Q1.s', 'Q2.d', 'OUT.t')
n.connect('DC_NEG', 'V1.n', 'Cdc.b', 'Q2.s', 'GND1.t')
```

A port belongs to exactly one net and the netlist refuses to let it join a
second. `Netlist.validate()` rejects unknown ports, floating ports and
one-terminal nets before any geometry exists.

### Checking the drawing against it

`validate.py` rebuilds the connectivity from the drawn geometry alone —
ignoring net names and the router's intentions — by unioning wire segments that
share an endpoint or meet at a tee, attaching component ports that land on a
segment, and **refusing to union two segments that merely cross**. The
resulting partition must equal `Netlist.partition()` exactly.

This is what proves a visual crossing never became an electrical node. Two
tests deliberately inject a short and a break to confirm the checker catches
them.

## Structure discovery

Repetition is found by colour refinement over the component/net bipartite
graph — no naming conventions, no hints:

```
full bridge   → [San, Sbn], [Sap, Sbp]
three-phase   → [San, Sbn, Scn], [Sap, Sbp, Scp]
DAB           → [Q1, Q3], [Q2, Q4], [Q5, Q7], [Q6, Q8]
```

DAB correctly keeps primary and secondary apart: they face different rails.
Electrically interchangeable ports (both ends of a resistor, the two primary
windings of a transformer) are canonicalised first, or two otherwise identical
legs stop looking identical.

## Symmetry by construction

Items in a slot share one x; slots in a group share one pitch. Alignment,
spacing uniformity and symmetry are therefore exact by construction rather
than repaired afterwards — the scorer verifies them instead of fixing them.
`placement.check_regularity()` raises before rendering if a plan would break a
detected repeated structure.

## Drawing-rule metrics

`drawing_rules.py` measures the general rules. Three of them needed care to
avoid measuring the wrong thing:

* **Rule 22 (rhythm)** counts *distinct local length scales*, not deviation
  from a target length. A converter legitimately uses several — rail stubs,
  leg midpoints and inter-stage runs — each for a different purpose, so
  the threshold is five. Consistency *within* a role is measured exactly and
  separately by `local_consistency` and `wire_uniformity`, both zero
  everywhere.
* **Rule 23 (local consistency)** compares only the power path. A DC rail is a
  long haul set by the floorplan and control nets have no added gate stub;
  neither says anything about local regularity. Including them made every
  switching device look defective.
* **Rule 17 (transformer)** measures the wire runs actually attached to the
  transformer's ports. The first version measured the distance from the
  transformer's centre to its own ports, which is a constant — a check that
  could not fail.
* **Item 12 (length band)** measures the spacing of consecutive ports along a
  net's trunk — the wire between two adjacent components. Measuring individual
  segments instead counted rail stubs, whose length is set by the rail
  separation rather than any local choice. The band edges are inclusive: a run
  at exactly 1.5 D was being flagged by floating-point noise.
* **Item 23 (port leads)** checks direct component-to-component nets. Port-axis
  alignment is required; the half-body lead length is a preference in the
  candidate cost, so obstacle clearance and connectivity still take priority.

## Cost and quality

```
J = 10⁹·connectivity + 10⁵·overlap + 5·10⁴·(wire collision, label overlap)
  + 4000·symmetry + 3000·spacing_variance + 3000·alignment
  + 2000·routing_shape + 1500·wire_uniformity + 300·crossing
  + 120·spacing_target + 60·bend + 1·length
```

Dispersion terms are **scale-free** (relative standard deviation, grid units)
rather than raw variance in mm² — otherwise they are dimensionally
incomparable with a length term in mm, and they punish equivalent branches for
length differences that the topology makes unavoidable. Routing *shape* (bend
count, number of runs) is compared exactly; routing *length* only in relative
terms.

Rendering aborts unless connectivity is 100 and nothing collides.

## Geometric tolerance

Symbol coordinates in the master sheet are rounded to three decimals, so pins
land fractions of a micron off exact grid lines. Every geometric predicate uses
a 0.05 mm tolerance — a fifth of a stroke width. Treating that rounding as real
produced phantom junction dots, invisible dog-legs and false collisions, and
comparing *rounded* coordinates turned exactly equal spacings into unequal
ones. `tests/test_layout.py` pins all of it down.

## Symbol library

`assets/master/Inkscape_Symbols_All.svg` is the
[UPB-LEA Inkscape electric symbols](https://github.com/upb-lea/Inkscape_electric_Symbols)
sheet: 196 `<symbol>` definitions with `<title>` names, everything on a
2.6458 mm grid, and nearly every two-terminal symbol exactly 10.583 mm tall —
so half a symbol is exactly 2 G and devices land on rails without fudging.

> **Licensing:** third-party work. Confirm the upstream licence and add the
> required attribution before publishing this repo.

Compound parts (`parts.py`) assemble several symbols plus primitive strokes.
The transformer is built this way because every transformer `<symbol>` on the
sheet encloses geometry scattered across the whole drawing and is unusable as a
unit.

## Whole-drawing checklist

`python3 build.py --checks` reports the whole-drawing checklist. Structural
checks and soft aesthetic penalties remain visible; a high overall score does
not erase a long-wire or spacing warning. Electrical mismatch is always fatal.

## Known limits

* Power-path inference is structural, not an operating-point or energy-flow
  simulation. Multi-source, cyclic and disconnected graphs may have ambiguous
  ordering; deterministic tie-breaking is reported in plan diagnostics.
* The current bridge grammar recognises two-device legs. Arbitrary multilevel
  stacks and overlapping motifs need additional general grammar rules.
* Twelve candidates explore small adjacent/bridge spacing and shunt-position
  changes. They do not exhaust group permutations, routing corridors or every
  symmetric orientation. Some candidates may be identical for a simple graph.
* Label bounds use conservative font estimates. Unsupported symbols and layouts
  with no valid candidate fail explicitly; `force=True` never bypasses electrical
  connectivity validation.
* Recognised repeated bridge legs get equal geometry. Graph equivalence alone
  does not solve all arrangements of repeated multi-component modules.
* The registry uses curated port geometry from the master sheet. Most symbols
  in the full sheet still lack an engineering port map and cannot yet render.
* Simulation, SPICE and other exporters are future backends. This version adds
  their electrical validation and serialization boundary, not those backends.
