"""Component metadata: geometry, ports and semantic role.

Simple parts wrap one <symbol> from the master sheet (see pins.py).
Compound parts are assembled from several symbols plus primitive strokes,
which is how reusable structures like a transformer are built.
"""
from .pins import PARTS as SYMBOL_PARTS, H, COARSE as G

# ------------------------------------------------------------------ compounds
# A transformer is not usable from the sheet: its <symbol> wrappers enclose
# geometry scattered across the whole drawing.  It is composed here from the
# library's own coil so the strokes still match the house style.
_COIL_BULGE = 1.058          # the coil symbol bulges this far off its axis
_WIND_X = 2 * G              # winding axis offset from the device centre
_CORE_X = 0.25 * G           # core bar offset from the device centre
_CORE_Y = 1.5 * G

COMPOUND = {
    # A named connection point.  It draws nothing but a label, and exists so
    # that every net ends on a real component port -- which is what lets the
    # rendered drawing be checked against the netlist in full.
    'terminal': dict(role='terminal', symbols=[], strokes=[],
                     ports={'t': (0.0, 0.0)}, bbox=(0.0, 0.0, 0.0, 0.0)),

    'transformer': dict(
        role='isolation',
        # (symbol kind, dx, dy, rot, mirror) in millimetres from the centre
        symbols=[('ind', -_WIND_X, 0, 0, False),
                 ('ind', _WIND_X, 0, 0, True)],
        strokes=[((-_CORE_X, -_CORE_Y), (-_CORE_X, _CORE_Y)),
                 ((_CORE_X, -_CORE_Y), (_CORE_X, _CORE_Y))],
        ports={'p1': (-_WIND_X, -H), 'p2': (-_WIND_X, H),
               's1': (_WIND_X, -H), 's2': (_WIND_X, H)},
        bbox=(-_WIND_X - _COIL_BULGE, -H, _WIND_X + _COIL_BULGE, H),
    ),
}

# ------------------------------------------------------------------ sides
_SIDE_ORDER = ('top', 'bottom', 'left', 'right')


def _side_of(offset):
    dx, dy = offset
    if abs(dy) >= abs(dx):
        return 'top' if dy < 0 else 'bottom'
    return 'left' if dx < 0 else 'right'


# semantic roles, used for functional grouping and layout conventions
ROLES = {
    'nmos': 'power_switch', 'nmos_don': 'power_switch', 'igbt': 'power_switch',
    'diode': 'rectifier',
    'ind': 'magnetic', 'ind_core': 'magnetic', 'transformer': 'isolation',
    'cap': 'filter', 'cap_pol': 'filter',
    'res': 'load',
    'vsource': 'source', 'isource': 'source', 'battery': 'source',
    'gnd': 'reference',
    'terminal': 'terminal',
}

# Ports that are electrically interchangeable.  Colour refinement must not
# treat the two ends of a resistor as different, or two otherwise identical
# bridge legs stop looking identical.
SYMMETRIC_PORTS = {
    'res': {'a': '*', 'b': '*'},
    'cap': {'a': '*', 'b': '*'},
    'ind': {'a': '*', 'b': '*'},
    'ind_core': {'a': '*', 'b': '*'},
    'transformer': {'p1': 'p*', 'p2': 'p*', 's1': 's*', 's2': 's*'},
}


def canonical_port(kind, port):
    return SYMMETRIC_PORTS.get(kind, {}).get(port, port)


ORIENTATION = {k: 'vertical' for k in ROLES}
ORIENTATION['transformer'] = 'vertical'


class PartSpec:
    """Everything the placer and router need to know about a component kind."""

    def __init__(self, kind, ports, bbox, role, compound=None):
        self.kind = kind
        self.ports = ports                      # {name: (dx, dy)} from anchor
        self.bbox = bbox                        # (x0, y0, x1, y1) from anchor
        self.role = role
        self.compound = compound
        self.sides = {p: _side_of(o) for p, o in ports.items()}

    @property
    def width(self):
        return self.bbox[2] - self.bbox[0]

    @property
    def height(self):
        return self.bbox[3] - self.bbox[1]

    @property
    def orientation(self):
        return ORIENTATION.get(self.kind, 'vertical')

    def port_side(self, port):
        return self.sides[port]

    def as_dict(self):
        return {
            'id': self.kind,
            'type': self.kind,
            'width': round(self.width, 3),
            'height': round(self.height, 3),
            'ports': {p: {'preferred_side': s} for p, s in self.sides.items()},
            'preferred_orientation': self.orientation,
            'semantic_role': self.role,
        }


def build_specs(symbols):
    """Build the part table.  `symbols` is the loaded symbol library."""
    specs = {}
    for kind, entry in SYMBOL_PARTS.items():
        sym = symbols[entry['sym']]
        ax, ay = entry['anchor']
        x0, y0, x1, y1 = sym.bbox
        specs[kind] = PartSpec(
            kind, dict(entry['pins']),
            (x0 - ax, y0 - ay, x1 - ax, y1 - ay),
            ROLES.get(kind, 'generic'))
    for kind, entry in COMPOUND.items():
        specs[kind] = PartSpec(kind, dict(entry['ports']), entry['bbox'],
                               entry.get('role', 'generic'), compound=entry)
    return specs


def port_table(symbols):
    """{kind: [port names]} -- used by Netlist.validate."""
    return {k: sorted(s.ports) for k, s in build_specs(symbols).items()}
