"""Every visual constant, defined once.

Layout, labelling, routing and scoring all read their numbers from here, so
a spacing or clearance value has one authoritative definition rather than a
copy per module.  Modules re-export the names they are historically known by,
but this file is where they are set.

Two units appear throughout and are kept distinct by name:

``*_G``   grid units -- what the placer works in
``*_MM``  millimetres -- what the geometry predicates work in
"""
from .pins import COARSE as G, H

# ------------------------------------------------------------------ scale
# Every symbol on the sheet is exactly this tall, which makes it the natural
# unit of visual scale: one component dimension.
CELL_G = 4
CELL_MM = CELL_G * G
HALF_SYMBOL_MM = H

# ------------------------------------------------------------------ spacing
# Gaps between bodies, edge to edge, in grid units.  They depend on how two
# neighbours are related rather than on one global scale.
GAP_SERIES_PASSIVE = 2       # C -> L -> C along one series path
GAP_PARALLEL_BLOCK = 2       # Cout || Rload and any other shunt block
GAP_ADJACENT = 4             # ordinary neighbouring components
GAP_BRIDGE_LEG = 6           # between the legs of one bridge, and wide
                             # enough that a load slung between two legs
                             # lands exactly half way, on the grid
GAP_GROUP = 6                # across a functional boundary
GAP_ANCHOR = 6               # around a visually dense anchor

START_COL = 6                # first column, in grid units

# Roles that may form a compact series chain.  A rectifier counts: a
# transformer should not sit far from the rectifier that follows it.
# A source starts a series path -- 'source -> L -> C -> transformer' is the
# canonical example -- so it is chain-eligible too.  Where a source feeds a
# rail instead, that net has more than two members and no chain is detected.
CHAIN_ROLES = frozenset({'filter', 'load', 'magnetic', 'isolation',
                         'rectifier', 'source'})
# Neutral riders -- a ground glyph or an interface marker attached to a node
# is not part of the power path and must not disqualify a chain.
CHAIN_NEUTRAL = frozenset({'reference', 'terminal'})
CHAIN_FACING_MARGIN_G = 0.5  # keep-out on a side facing a chain neighbour

# ------------------------------------------------------------------ labels
FONT_FAMILY = 'Times New Roman'
FONT_FAMILY_CSS = f"'{FONT_FAMILY}',Times,serif"
FONT_WEIGHT = 400              # optically balanced with the 1 px circuit line
LABEL_SIZE = 2.82222         # px, matching the sheet's own designator text
NOTE_SIZE = 2.5              # free annotations
GLYPH_W = 0.62               # conservative em width for collision estimates
LINE_H = 1.15                # em, cap height plus descender
SUBSCRIPT = 0.72             # subscript size relative to its parent

# Clearance demanded around every label.  Nothing -- body, other label, wire,
# junction dot or terminal marker -- may enter this box.  It is a margin, not
# merely non-overlap.
LABEL_PAD_X_MM = 0.5 * G
LABEL_PAD_Y_MM = 0.35 * G

# A label must keep visible daylight from its own component -- touching is
# not enough.  This is enforced by the engine, not by trusting each offset.
LABEL_OWN_CLEARANCE_MM = 0.35 * G

# An 'above' or 'below' label is anchored by its baseline, so its box still
# reaches past that by the descent plus the pad.  Any smaller offset would
# put a label's keep-out inside its own body.
MIN_STACK_OFFSET_MM = (0.25 * LINE_H * LABEL_SIZE + LABEL_PAD_Y_MM
                       + LABEL_OWN_CLEARANCE_MM)

# Preferred label side and offset per semantic role.
#
# ``side``  the preference while the symbol stands upright, expressed in its
#           own frame and rotated with it.
# ``flat``  the preference once it is laid on its side.  A two-terminal
#           passive laid flat is labelled above whichever way it was rotated,
#           which rotating the upright preference cannot express: a capacitor
#           prefers 'left' standing up, and that rotates to 'below'.
LABEL_STYLE = {
    'power_switch': dict(side='right', flat='above', offset=1.3),
    'rectifier':    dict(side='right', flat='above', offset=1.3),
    'magnetic':     dict(side='right', flat='above', offset=1.3),
    'isolation':    dict(side='above', flat='above', offset=2.0),
    'filter':       dict(side='left',  flat='above', offset=1.3),
    'load':         dict(side='right', flat='above', offset=1.3),
    'source':       dict(side='left',  flat='left',  offset=1.6),
    'reference':    dict(side='below', flat='below', offset=1.0),
    'terminal':     dict(side='right', flat='right', offset=1.4),
    'generic':      dict(side='right', flat='above', offset=1.3),
}

# Deterministic fallback order when the preferred side will not fit.
LABEL_FALLBACK = ('preferred', 'opposite', 'above', 'below', 'left', 'right')

# ------------------------------------------------------------------ markers
TERMINAL_R_MM = 0.6          # open circle marking an external power boundary
JUNCTION_R_MM = 0.4          # filled dot, matching the library's own nodes

# ------------------------------------------------------------------ keep-out
# Beyond the drawn body, per role, in grid units.  A raw bounding box is not
# always the right spacing boundary.
VISUAL_MARGIN = {
    'isolation':    dict(top=1.0, bottom=1.0, left=1.25, right=1.25),
    'power_switch': dict(top=1.0, bottom=1.0, left=1.25, right=1.0),
    'source':       dict(top=1.0, bottom=1.0, left=1.25, right=1.0),
    'terminal':     dict(top=0.25, bottom=0.25, left=0.25, right=0.25),
    'reference':    dict(top=0.25, bottom=0.5, left=0.5, right=0.5),
    'generic':      dict(top=1.0, bottom=1.0, left=1.0, right=1.0),
}

# ------------------------------------------------------------------ routing
TOL_MM = 0.05                # a fifth of a stroke width; below this is noise
LONG_RUN_MM = 2 * CELL_MM    # beyond this a wire is a deliberate long haul
WIRE_WIDTH_MM = 0.264583     # 1 px at 96 dpi, the sheet's own stroke

# Acceptable run length between adjacent components, in cells.
BAND_LO, BAND_HI = 0.75, 1.5
CHAIN_BAND_LO, CHAIN_BAND_HI = 0.4, 1.0   # a chain is packed tighter
BAND_EPS = 1e-4                            # band edges are inclusive
PORT_LEAD_RATIO = 0.5       # straight lead target vs body span on that axis

SHEET_MARGIN_MM = 2 * G      # breathing room around the drawn content
