# AIPE-Sketch

Publication-quality power-electronics schematics generated from a netlist.

The netlist is the single source of truth. Layout and routing decide only
*where* things are drawn, never *what is connected to what* — and the finished
drawing is read back out of its own geometry and checked against the netlist
before anything is written to disk. A connectivity mismatch is fatal.

## Pipeline

```
netlist → topology analysis → functional grouping → symmetry detection
        → placement → routing → scoring → repair
        → connectivity check → render
```

Structure is *discovered* from the graph; geometry is *derived* deterministically
from a coordinate-free plan. The two never mix: `plan.py` contains no x or y,
and `placement.py` is the only module that invents a coordinate.

| stage | module | answers |
|---|---|---|
| netlist | `netlist.py` | what is connected to what |
| analysis | `analysis.py` | which legs, rails, groups and repeats exist |
| plan | `plan.py` | what belongs together, what sits left of what |
| placement | `placement.py` | exact coordinates, on grid |
| routing | `router.py` | Manhattan wires, rails, junction dots |
| scoring | `score.py` | cost and the 0–100 scorecard |
| drawing rules | `drawing_rules.py` | is it compact, regular and conventional |
| symbol registry | `parts.py` | geometry, ports, margins and label style |
| validation | `validate.py` | does the drawing match the netlist |
| orchestration | `pipeline.py` | run it, repair it, render it |

## Usage

```bash
python3 build.py                    # all six reference topologies
python3 build.py buck dab           # a subset
python3 build.py --plan buck        # structure and plan, no drawing
python3 -m unittest discover -s tests
```

## Reference topologies

All six are regression tests. Current scores:

| topology | conn | sym | rhythm | clearance | conventions | overall |
|---|---|---|---|---|---|---|
| buck | 100 | 100 | 93 | 100 | 100 | **99** |
| boost | 100 | 100 | 100 | 100 | 100 | **100** |
| half bridge | 100 | 100 | 100 | 100 | 100 | **100** |
| full bridge | 100 | 100 | 95 | 97 | 100 | **97** |
| three-phase 2-level | 100 | 100 | 94 | 97 | 100 | **98** |
| DAB | 100 | 100 | 98 | 98 | 100 | **99** |

Every drawing also answers the fifteen whole-drawing questions cleanly
(`python3 build.py --checks`).

The crossings in the last two are the topological minimum: three phase outputs
reaching a shared column must pass two legs, one leg and none; the DAB's two
bridges each reach across one leg to the transformer.

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
come out evenly spaced. Measured body-to-body gaps across all six topologies
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
* `interface='control'` — a gate drive or sensing port. Still a real
  component, so connectivity stays fully checkable, but drawn as an ordinary
  wire endpoint.
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
transformer  compound  -           p1,p2,s1,s2
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

Side and offset come from the registry per semantic role, so equivalent
components place their labels at identical distances — `label_distance`
irregularity is 0 across all six topologies. A component laid on its side (a
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

The transformer is the one compound. Every transformer `<symbol>` on the sheet
encloses geometry scattered across the whole drawing and cannot be
instantiated, so it is assembled from the library's **own coil**, using
proportions measured off the sheet's own transformer: two core bars 1.325 mm
apart spanning the full symbol height, windings hard against them, and an
equal straight entry segment at each of the four ports.

It is 3.5 G × 4.0 G — a spread ratio of 1.52 against its winding span. The
first version had the winding axes 10.6 mm apart and read as *inductor, core,
inductor*; `transformer_spread` now fails any ratio above 2.0, and a test
asserts the compound's width never changes with group pitch.

## Netlist as source of truth

```python
n = Netlist('Half Bridge')
n.add('Q1', 'nmos', label='S', sub='a+')
n.add('Q2', 'nmos', label='S', sub='a-')
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
  from a target length. A converter legitimately uses four — gate stubs, rail
  stubs, leg midpoints, inter-stage runs — each for a different purpose, so
  the threshold is four. Consistency *within* a role is measured exactly and
  separately by `local_consistency` and `wire_uniformity`, both zero
  everywhere.
* **Rule 23 (local consistency)** compares only the power path. A DC rail is a
  long haul set by the floorplan and a gate stub is squeezed by the leg pitch;
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

`Inkscape_Symbols_All.svg` is the
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

`python3 build.py --checks` answers 22 questions per drawing, all clean across
the catalogue. Checks report what is actually true rather than passing
vacuously — five topologies have no transformer, and four deliberately have no
output port at all.

## Known limits

* **The DAB's far-leg transformer run is unavoidably long** — 3.75 CELL
  against 1.75 for the near leg. A full bridge's outer leg has to reach past
  the inner one, so the two connections cannot be equal length. Reported by
  check 10 rather than hidden.
* **Placement is plan-driven, not automatic.** The placer is deterministic and
  enforces regularity, but a human still writes the plan — which groups exist
  and in what order. Auto-generating a plan from `analysis.analyse()` output is
  the obvious next step and is not done.
* **No search over layouts.** The cost function ranks a layout; nothing
  generates alternatives to rank. §15's "prefer the layout that minimises J"
  is not exercised because there is only ever one candidate.
* **The repair loop only moves labels.** It tries the four sides and keeps the
  first collision-free one. It cannot widen a rail, shift a column or reroute
  a net, so a layout that fails for any other reason is rejected rather than
  repaired.
* **Label boxes are estimated, not measured** — no font metrics available.
  Deliberately pessimistic (0.62 em/glyph, 1.15 em line height, 0.35 mm pad),
  but it is the weakest input to the collision checker.
* **Rule 19 (resonant tank) is untested.** Nothing in the catalogue has a
  series resonant path, so the "one horizontal centreline with comparable
  spacing" rule has no example behind it.
* **The scale threshold of four is a judgement call**, not a derived number.
* **The full bridge's load sits 0.5 D from each leg**, below the 0.75 D band.
  The load symbol is 4 G long and the legs are 8 G apart, so only 2 G remains
  on each side. Widening the legs to 12 G would fix the band at the cost of
  2 D leg clearance; the runs are symmetric and `local_spread` is 0, so the
  band penalty is reported rather than designed away. Item 19 forbids
  stretching the symbol itself.
* **The DAB's near-transformer run is 1.56 D**, just outside the band, and its
  far-leg run is 3.56 D — an outer leg has to reach past the inner one.
* **Gate stubs end bare and unlabelled.** Control ports carry no marker by
  design, but they also carry no label, so a gate lead is an anonymous short
  line. Labelling them (`VG1`, `G1`) would make them read as deliberate rather
  than unfinished.
* **Phase outputs are treated as exposed power interfaces.** A, B and C are
  what the inverter drives and nothing in the drawing terminates them, so they
  carry markers.
* **Input notation is set by `INPUT_LABEL` in `topologies.py`** — currently
  `('V', 'in')`, rendering as *V*<sub>in</sub> to match the drawing's other
  subscripted designators. Change it there for a different house style.
* **`pins.py` covers 14 part kinds of 196 symbols.** `tools/inspect_symbol.py`
  prints the measurements needed to add more; `KNOWN_DIRTY` lists symbol
  wrappers that need cleaning first.
* **NPC, ANPC, MMC and interleaved structures are not implemented.** The leg
  abstraction covers two-device legs only.
