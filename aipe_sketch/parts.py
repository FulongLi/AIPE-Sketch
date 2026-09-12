"""Symbol registry: the single programmatic view of the master symbol sheet.

    Inkscape_Symbols_All.svg  ->  symlib parser  ->  Registry
                                                      |
                                +---------------------+---------------------+
                                |                     |                     |
                            renderer        placement metadata        pin geometry

The master SVG stays authoritative.  Nothing here redraws a symbol that the
sheet already provides; custom geometry appears only where the sheet's own
symbol is unusable, and then it is assembled from other library symbols.
"""
from . import config
from .config import LABEL_STYLE, VISUAL_MARGIN
from .pins import PARTS as SYMBOL_PARTS, H, COARSE as G

TERMINAL_R = config.TERMINAL_R_MM

# Where a symbol's geometry comes from.  Lookup priority is library first,
# then a compound assembled from library primitives, and only then custom
# geometry -- so nothing standard is ever redrawn by hand.
LIBRARY = 'library'          # one <symbol> instantiated straight from the sheet
CLEANED_LIBRARY = 'cleaned_library'   # sheet geometry, minus unrelated strays
COMPOUND_SRC = 'compound'    # assembled from library symbols plus primitives
CUSTOM = 'custom'            # drawn here because the sheet offers nothing
FROM_SHEET = (LIBRARY, CLEANED_LIBRARY)

# ------------------------------------------------------------------ compounds

COMPOUND = {
    # An external interface point.  It draws nothing but an open circle, and
    # exists so a net that leaves the schematic ends somewhere explicit.
    'terminal': dict(role='terminal', symbols=[], strokes=[],
                     circles=[(0.0, 0.0, TERMINAL_R)],
                     ports={'t': (0.0, 0.0)},
                     bbox=(-TERMINAL_R, -TERMINAL_R, TERMINAL_R, TERMINAL_R),
                     source=CUSTOM,
                     reason='the sheet has no open-circle interface marker; '
                            'its only lone circles are filled GND glyphs'),

}

# ------------------------------------------------------------------ decoration
# Marks drawn over a library symbol.  The sheet's plain source circle carries
# neither polarity nor direction, and conventional practice requires both.
_ARROW_H = 0.55

DECOR = {
    'vsource': dict(texts=[(0.0, -0.55, '+', 2.5),
                           (0.0, 2.15, '−', 2.5)]),
    'isource': dict(strokes=[((0.0, 1.6), (0.0, -1.6)),
                             ((-_ARROW_H, -0.85), (0.0, -1.6)),
                             ((_ARROW_H, -0.85), (0.0, -1.6))]),
}

# ------------------------------------------------------------------ roles
from .electrical import ROLES, SYMMETRIC_PORTS, canonical_port

ORIENTATION = {k: "vertical" for k in ROLES}

# Label style and keep-out live in config; they are visual policy, not
# symbol geometry, and several modules need the same numbers.

# Callers may request a component by its plain engineering name.
from .electrical import ALIASES

_SIDE_ORDER = ('top', 'bottom', 'left', 'right')


def _side_of(offset):
    dx, dy = offset
    if abs(dy) >= abs(dx):
        return 'top' if dy < 0 else 'bottom'
    return 'left' if dx < 0 else 'right'


class SymbolSpec:
    """Everything the placer, router and renderer need about one kind."""

    def __init__(self, kind, symbol_id, ports, bbox, role, compound=None,
                 default_rotation=0, cleaned=None):
        self.kind = kind
        self.symbol_id = symbol_id
        self.default_rotation = default_rotation
        self.ports = ports                  # {name: (dx, dy)} from the anchor
        self.bbox = bbox                    # (x0, y0, x1, y1) from the anchor
        self.role = role
        self.compound = compound
        self.sides = {p: _side_of(o) for p, o in ports.items()}
        decor = dict(DECOR.get(kind, {}))
        if compound:
            for key in ('strokes', 'texts', 'circles'):
                if compound.get(key):
                    decor.setdefault(key, []).extend(compound[key])
        self.decor = decor
        if compound:
            self.source = compound.get('source', COMPOUND_SRC)
            self.reason = compound.get('reason', '')
        else:
            self.source = CLEANED_LIBRARY if cleaned else LIBRARY
            self.reason = DECOR.get(kind, {}).get('reason', '')
            if cleaned:
                self.reason = (self.reason + '; ' if self.reason else '') + \
                    'wrapper also encloses neighbouring geometry, so only ' \
                    'the device\'s own children are kept'
        self.cleaned = bool(cleaned)
        style = LABEL_STYLE.get(role, LABEL_STYLE['generic'])
        self.label_side = style['side']
        self.label_side_flat = style.get('flat', style['side'])
        self.label_offset = style['offset']
        self.visual_margin = VISUAL_MARGIN.get(role, VISUAL_MARGIN['generic'])

    # -- geometry ----------------------------------------------------
    @property
    def width(self):
        return self.bbox[2] - self.bbox[0]

    @property
    def height(self):
        return self.bbox[3] - self.bbox[1]

    @property
    def orientation(self):
        return ORIENTATION.get(self.kind, 'vertical')

    @property
    def is_terminal(self):
        return self.role == 'terminal'

    def port_side(self, port):
        """Which face of the symbol a port sits on, in its own frame."""
        return self.sides[port]

    @property
    def from_sheet(self):
        """True when the geometry came out of the master library."""
        return self.source in FROM_SHEET

    @property
    def decorated(self):
        """True when marks are added over a library symbol."""
        return bool(DECOR.get(self.kind))

    @property
    def provenance(self):
        """One line naming where this symbol's geometry comes from."""
        if self.source in FROM_SHEET:
            text = f'{self.source} {self.symbol_id}'
            if self.decorated:
                text += ' + marks'
            return text
        if self.source == COMPOUND_SRC:
            parts = ', '.join(sub for sub, *_ in self.compound['symbols'])
            return f'{COMPOUND_SRC} of {parts}'
        return CUSTOM

    def margin_box(self, bbox=None):
        """The body box grown by this symbol's own keep-out."""
        x0, y0, x1, y1 = bbox or self.bbox
        m = self.visual_margin
        return (x0 - m['left'] * G, y0 - m['top'] * G,
                x1 + m['right'] * G, y1 + m['bottom'] * G)

    def as_dict(self):
        return {
            'kind': self.kind,
            'symbol_id': self.symbol_id,
            'bbox': [round(v, 3) for v in self.bbox],
            'anchor': [0.0, 0.0],
            'ports': {p: {'offset': [round(v, 3) for v in o],
                          'preferred_side': self.sides[p]}
                      for p, o in self.ports.items()},
            'preferred_orientation': self.orientation,
            'semantic_role': self.role,
            'visual_margin': self.visual_margin,
            'preferred_label_side': self.label_side,
            'preferred_label_offset': self.label_offset,
            'default_rotation': self.default_rotation,
            'symbol_source': self.source,
            'provenance': self.provenance,
            'reason': self.reason,
        }


class Registry:
    """The programmatic view of the symbol sheet."""

    def __init__(self, symbols):
        self.symbols = symbols
        self._specs = {}
        for kind, entry in SYMBOL_PARTS.items():
            sym = symbols[entry['sym']]
            ax, ay = entry['anchor']
            x0, y0, x1, y1 = sym.bbox
            keep = entry.get('keep')
            if keep:                      # measure only the kept children
                xs, ys = [], []
                for child in sym.el:
                    if child.get('id') not in keep:
                        continue
                    from . import library as _lib
                    px, py = [], []
                    _lib._walk(child, _lib.IDENTITY, px, py)
                    xs += px
                    ys += py
                if xs:
                    x0, y0, x1, y1 = min(xs), min(ys), max(xs), max(ys)
            self._specs[kind] = SymbolSpec(
                kind, entry['sym'], dict(entry['pins']),
                (x0 - ax, y0 - ay, x1 - ax, y1 - ay),
                ROLES.get(kind, 'generic'), cleaned=keep)
        for kind, entry in COMPOUND.items():
            self._specs[kind] = SymbolSpec(
                kind, None, dict(entry['ports']), entry['bbox'],
                entry.get('role', 'generic'), compound=entry)

    def __getitem__(self, kind):
        return self._specs[ALIASES.get(kind, kind)]

    def get(self, kind, default=None):
        """Fetch by semantic name; plain engineering names are accepted."""
        return self._specs.get(ALIASES.get(kind, kind), default)

    def __contains__(self, kind):
        return ALIASES.get(kind, kind) in self._specs

    def __iter__(self):
        return iter(self._specs)

    def items(self):
        return self._specs.items()

    def port_table(self):
        return {k: sorted(s.ports) for k, s in self._specs.items()}

    def as_dict(self):
        return {k: s.as_dict() for k, s in sorted(self._specs.items())}

    def audit(self):
        """One row per kind: where its geometry comes from."""
        rows = []
        for kind, spec in sorted(self._specs.items()):
            rows.append(dict(kind=kind, source=spec.source,
                             symbol_id=spec.symbol_id or '',
                             provenance=spec.provenance,
                             ports=sorted(spec.ports),
                             bbox=[round(v, 3) for v in spec.bbox],
                             reason=spec.reason))
        return rows


def build_specs(symbols):
    """Backwards-compatible accessor returning the registry."""
    return Registry(symbols)


def port_table(symbols):
    return Registry(symbols).port_table()
