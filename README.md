# AIPE-Sketch

Power-electronics schematics generated from a netlist and a curated symbol
library, output as clean, hand-editable Inkscape SVG.

You describe the circuit as components and nets. The engine places parts on a
grid, routes Manhattan wires, derives junction dots from connectivity, scores
the result, and **refuses to render a layout that fails the mandatory checks**.

## The symbol library

`Inkscape_Symbols_All.svg` is the
[UPB-LEA Inkscape electric symbols](https://github.com/upb-lea/Inkscape_electric_Symbols)
sheet. It is not a flat drawing: it carries **196 `<symbol>` definitions**
with `<title>` names — MOSFETs, IGBTs, GaN HEMTs/GITs, diodes, magnetics,
sources, logic, ladder symbols, plus whole reference topologies (LLC, DAB,
phase-shifted full bridge, B6, 3-level NPC/TNPC).

Two properties make it good to automate against:

* Everything is drawn on a **2.6458 mm (10 px) coarse grid**, fine grid
  1.3229 mm.
* Nearly every two-terminal symbol is exactly **10.583 mm (40 px) tall**,
  terminals on the bounding-box edges — one pitch fits all of them. Half a
  symbol height is exactly 2 G, so devices land on rails without fudging.

> **Licensing:** the symbol sheet is third-party work. Confirm the upstream
> licence and add the required attribution before publishing this repo.

## Layout

```
aipe_sketch/
  symlib.py   parse the master sheet, extract <symbol> geometry and endpoints
  pins.py     curated part table: symbol id, anchor point, named terminals
  sketch.py   low-level SVG writer (place / wire / dot / label / save)
  router.py   Manhattan routing, rail+stub bus routing, junction detection
  verify.py   layout metrics, aesthetic cost, mandatory-check gate
  engine.py   Schematic: netlist in, verified SVG out
examples/     buck_converter.py, three_phase_inverter.py
tools/        inspect_symbol.py, catalog.py
tests/        test_layout.py
out/          generated SVG/PNG
```

## Usage

```bash
python3 examples/buck_converter.py
python3 examples/three_phase_inverter.py
python3 -m unittest discover -s tests
```

Render to PNG with the Inkscape CLI:

```bash
/Applications/Inkscape.app/Contents/MacOS/inkscape \
  --export-type=png --export-area-drawing --export-margin=3 \
  --export-width=1700 --export-background=white out/buck_converter.svg
```

## Describing a circuit

Placement is on grid units; connectivity is declared over **named pins**, never
coordinates, so routing cannot silently alter the circuit:

```python
s = Schematic(SRC, 140, 80, 'Buck Converter')

s.add('Q1', 'nmos',  X_SW, Y_DCP + HALF, label='Q', sub='1')
s.add('D1', 'diode', X_SW, Y_DCN - HALF, label='D', sub='1')
s.add('L1', 'ind',   X_L,  Y_SW, rot=-90, label='L', sub='1', side='above')

s.net('DCP', 'V1.p', 'Cin.a', 'Q1.d',   trunk=('h', Y_DCP))
s.net('SW',  'Q1.s', 'D1.k',  'L1.a',   trunk=('h', Y_SW))

report = s.render('out/buck_converter.svg')   # raises if a check fails
```

A net with a `trunk` is drawn as a rail with perpendicular stubs, which is how
an engineer draws a bus and keeps parallel nets visually parallel. Without one,
two-terminal nets route point-to-point (straight → one bend → two bends,
discarding any candidate that crosses a body) and larger nets pick a trunk that
minimises stub length.

`s.repeated('Sap', 'Sbp', 'Scp')` declares a group that must stay
geometrically identical; the verifier checks orientation, size, shared axis and
even spacing.

## Junctions vs crossings

Dots are derived from the netlist, never from geometry. A point is a node when
its branch count reaches three, counting a device lead as one branch. Wires of
different nets are scored separately, so **a visual crossing can never become
an electrical node**. This matches the source library's own full-bridge figure,
which takes its midpoint crossings plainly with no dot.

A consequence worth knowing: where a rail *terminates* on a device pin there
are only two branches, so no dot is drawn, while a device tapping the middle of
the same rail gets one. In the three-phase example legs A and B are T-taps and
leg C is the rail's end, so leg C carries one dot fewer. That is the connection
genuinely differing, and electrical correctness outranks visual symmetry.

## Verification

`render()` computes the metrics below and aborts on any mandatory failure —
component overlap, label overlap, or a wire through a component body.

```
AestheticCost = 10000*ComponentOverlap + 5000*LabelOverlap
              + 1000*WireComponentCollision + 100*WireCrossing
              + 20*ExtraBend + 20*AlignmentError + 30*SymmetryError
              + 10*SpacingIrregularity + WireLength
```

Current scores:

| example | crossings | bends | symmetry | cost |
|---|---|---|---|---|
| buck converter | 0 | 0 | 0 | 313.5 |
| three-phase inverter | 3 | 0 | 0 | 764.6 |

The inverter's three crossings are the minimum for right-hand phase outputs:
phase A must pass legs B and C, phase B must pass leg C.

Label boxes are **estimated**, not measured — there is no font metric library
here. The estimate is deliberately pessimistic (0.62 em per glyph, 1.15 em
line height, 0.35 mm padding) so a tight label is reported rather than waved
through. It is the weakest part of the checker.

## Tolerance

Symbol coordinates in the master sheet are rounded to three decimals, so pins
land fractions of a micron off exact grid lines. Geometric predicates use a
0.05 mm tolerance — a fifth of a stroke width, a fiftieth of the grid. Treating
that rounding as real produced phantom junction dots, invisible dog-legs and
false collisions; `tests/test_layout.py` pins all three down.

## Status

Working: symbol extraction, the curated part table, grid placement with
rotation and mirroring, Manhattan and rail routing with body avoidance,
netlist-derived junction dots, the metric suite and render gate, defs pruning
(a buck converter is ~19 KB and stays editable in Inkscape).

Not done yet:

* **`pins.py` covers 13 parts of 196.** The rest need measuring;
  `tools/inspect_symbol.py` prints the numbers.
* **Some `<symbol>` wrappers are dirty** — they drag in geometry from
  neighbouring drawings, so their bounding box is far wider than the device
  (see `KNOWN_DIRTY` in `pins.py`). They need cleaning before use.
* **Placement is explicit, not automatic.** You choose the grid columns and
  rows; the engine enforces and scores them but will not invent a floorplan.
  Topology-aware auto-placement (half-bridge, full-bridge, three-phase
  templates) is the obvious next step.
* **No search over candidate layouts.** The cost function ranks a layout but
  nothing generates alternatives to rank.
* **Label boxes are estimated**, as described above.
* **Isolated topologies are untested** — no transformer-centred example yet,
  so primary/centre/secondary staging is unproven.
