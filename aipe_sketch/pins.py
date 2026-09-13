"""Curated pin maps for symbols in ``Inkscape_Symbols_All.svg``.

Each entry maps a friendly part name to:

``sym``     the ``<symbol>`` id in the master sheet
``anchor``  the reference point in the symbol's own coordinates; for
            two-terminal parts this is the midpoint of the two terminals
``pins``    terminal offsets relative to that anchor

All values below were measured from the master sheet (see
``tools/inspect_symbol.py``), not estimated.  Most two-terminal symbols
are exactly 10.583 mm (40 px @96 dpi) tall, so their terminals sit at
y = -/+ ``H``; the battery is a compact 5.292 mm exception.
"""

H = 5.29165          # half the standard symbol height, mm
GRID = 1.3229167     # fine grid, mm  (5 px)
COARSE = 2.6458333   # coarse grid, mm (10 px)

# gate/base lead offset shared by the MOSFET and IGBT symbols
_GATE = (-6.615, 2.6465)

PARTS = {
    # --- sources -----------------------------------------------------
    'vsource':  dict(sym='g11181', anchor=(60.854, 78.7185),
                     pins={'p': (0, -H), 'n': (0, H)}),
    # the plain source circle; direction comes from the arrow in parts.DECOR
    'isource':  dict(sym='g11181', anchor=(60.854, 78.7185),
                     pins={'p': (0, -H), 'n': (0, H)}),
    'battery':  dict(sym='g5754',  anchor=(144.198, 61.521),
                     pins={'p': (0, -2.646), 'n': (0, 2.646)}),

    # --- passives ----------------------------------------------------
    'res':      dict(sym='use3315', anchor=(30.427, -95.9065),
                     pins={'a': (0, -H), 'b': (0, H)}),
    'cap':      dict(sym='g8210',  anchor=(30.427, -18.5205),
                     pins={'a': (0, -H), 'b': (0, H)}),
    'cap_pol':  dict(sym='g8838',  anchor=(44.979, -18.5205),
                     pins={'a': (0, -H), 'b': (0, H)}),   # 'a' is the + plate
    'ind':      dict(sym='g6472',  anchor=(76.729, 58.875),
                     pins={'a': (0, -H), 'b': (0, H)}),
    'ind_core': dict(sym='g16215', anchor=(42.333, -61.5105),
                     pins={'a': (0, -H), 'b': (0, H)}),

    # --- diodes ------------------------------------------------------
    # cathode ('k') is the top terminal as drawn
    'diode':    dict(sym='g13419', anchor=(80.698, 70.7815),
                     pins={'k': (0, -H), 'a': (0, H)}),

    # --- switches ----------------------------------------------------
    # drain/collector top, source/emitter bottom, gate on the left
    'nmos':     dict(sym='g4046',  anchor=(33.073, 15.875),
                     pins={'d': (0, -H), 's': (0, H), 'g': _GATE}),
    'nmos_don': dict(sym='g3996',  anchor=(33.073, 1.323),
                     pins={'d': (0, -H), 's': (0, H), 'g': _GATE}),
    'igbt':     dict(sym='g13197', anchor=(31.750, 148.1665),
                     pins={'c': (0, -H), 'e': (0, H), 'g': _GATE}),

    # --- magnetics ---------------------------------------------------
    # The sheet's own two-winding transformer.  Its wrapper also encloses
    # geometry from neighbouring drawings, so only the device's own children
    # are kept; the coupling arrow above it is an annotation, like the 'n:1'
    # text, and is left out so the symbol keeps the library's 4 G height.
    'transformer': dict(sym='g7138', anchor=(57.392, 20.159),
                        keep=('path5742', 'path5744', 'use6557-2',
                              'use6557-0', 'g6472-8', 'g6472-7'),
                        pins={'p1': (-3.307, -H), 'p2': (-3.307, H),
                              's1': (3.307, -H), 's2': (3.307, H)},
                        sides={'p1': 'left', 'p2': 'left',
                               's1': 'right', 's2': 'right'}),

    # --- misc --------------------------------------------------------
    # Ground anchors are their connection points, not bbox centres.  Power
    # ground uses the IEC earth bars; digital/signal ground uses the open
    # inverted triangle so the two reference domains remain visible.
    'power_ground': dict(sym='g9386', anchor=(37.175, 96.578),
                         pins={'t': (0, 0)}),
    'digital_ground': dict(sym='g9380', anchor=(31.884, 96.578),
                           pins={'t': (0, 0)}),
}

# Symbols in the master sheet whose <symbol> wrapper drags in geometry from
# neighbouring drawings (their bbox is far wider than the device).  They need
# cleaning before they can be added to PARTS.
KNOWN_DIRTY = ['g10556', 'g10606', 'g6049', 'g12339', 'g12347', 'g3650']
