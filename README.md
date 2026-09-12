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

## Terminals, junctions and crossings

Three visually distinct things:

| meaning | drawn as |
|---|---|
| external port | open circle, r = 0.6 mm, page-coloured fill |
| electrical junction | filled dot, r = 0.4 mm |
| wires crossing, not connected | nothing |

Every exposed node — input, output, phase, gate drive — is a real `terminal`
component in the netlist, so it renders as an open circle and **no wire ever
ends in mid-air**. `drawing_rules.floating_ends` asserts this: a wire end must
be a port, a corner, or a tee onto another run.

A terminal's ring sits on the wire end by design, so terminals are excluded
from routing obstacles and wire-collision checks while still counting for
label and overlap purposes.

## Source symbols

The sheet's source circle carries no polarity and no direction, and
conventional practice requires both, so they are drawn as decoration over the
symbol: `+` and `\u2212` inside the circle with the plus toward the positive
terminal, and a current source gets a shaft-and-head arrow pointing from the
current-entry terminal to the current-exit one.

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
* **`pins.py` covers 14 part kinds of 196 symbols.** `tools/inspect_symbol.py`
  prints the measurements needed to add more; `KNOWN_DIRTY` lists symbol
  wrappers that need cleaning first.
* **NPC, ANPC, MMC and interleaved structures are not implemented.** The leg
  abstraction covers two-device legs only.
