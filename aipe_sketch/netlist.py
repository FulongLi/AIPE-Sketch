"""Circuit IR: backend-independent electrical source of truth.

A circuit is a graph of components (nodes) joined by nets (hyperedges) at
named ports.  Nothing in the layout or routing stages may alter this
structure; they may only decide where things are drawn.
"""
from collections import defaultdict


class Component:
    """Electrical meaning only; port declarations do not depend on a symbol."""
    __slots__ = ('ref', 'kind', 'role', 'interface', 'attrs', 'ports', '__weakref__')

    def __init__(self, ref, kind, role=None, interface=None, ports=None, **attrs):
        from .electrical import ALIASES, PORTS
        self.ref = ref
        self.kind = ALIASES.get(kind, kind)
        self.role = role
        self.interface = interface
        self.ports = tuple(ports if ports is not None else PORTS.get(self.kind, ()))
        if not self.ports or len(set(self.ports)) != len(self.ports):
            raise ValueError(f'{ref}: declare unique electrical ports for {kind}')
        forbidden = {'x', 'y', 'rot', 'rotation', 'mirror', 'svg_symbol',
                     'symbol_id', 'label_side', 'spacing', 'routing', 'dx', 'dy',
                     'bbox', 'visual_bbox', 'label_position', 'coordinates', 'svg_symbol_id'}
        if forbidden.intersection(attrs):
            raise ValueError('drawing attributes belong in schematic metadata')
        self.attrs = attrs

    @property
    def external(self):
        return self.interface is not None

    # Read-only compatibility accessors; these values live outside Circuit IR.
    @property
    def label(self):
        from .presentation import text_for
        return text_for(self).label

    @property
    def sub(self):
        from .presentation import text_for
        return text_for(self).sub

    @property
    def italic(self):
        from .presentation import text_for
        return text_for(self).italic

    def __repr__(self):
        return f'Component({self.ref!r}, {self.kind!r})'


class Netlist:
    """Components plus the nets that join their ports."""

    def __init__(self, name='circuit'):
        self.name = name
        self.components = {}
        self._nets = defaultdict(list)      # net -> [(ref, port), ...]
        self.order = []

    # ---------------------------------------------------------------- build
    def add(self, ref, kind, role=None, label=None, sub=None, italic=True,
            interface=None, ports=None, **attrs):
        if ref in self.components:
            raise ValueError(f'duplicate component {ref}')
        if interface not in (None, 'power', 'control'):
            raise ValueError(f'{ref}: interface must be power, control or None')
        c = Component(ref, kind, role, interface, ports, **attrs)
        if label is not None or sub is not None or not italic:
            from .presentation import set_legacy
            set_legacy(c, label, sub, italic)
        self.components[ref] = c
        self.order.append(c)
        return c

    def connect(self, net, *terminals):
        """connect('SW_A', 'Q1.s', 'Q2.d') -- terminals are 'REF.port'."""
        pending = []
        for t in terminals:
            ref, port = t.rsplit('.', 1)
            if ref not in self.components:
                raise KeyError(f'net {net}: unknown component {ref}')
            entry = (ref, port)
            if entry in self._nets.get(net, ()) or entry in pending:
                continue
            for other, members in self._nets.items():
                if other != net and entry in members:
                    raise ValueError(
                        f'{t} is already on net {other}; a port belongs to '
                        f'exactly one net')
            pending.append(entry)
        if pending:
            self._nets[net].extend(pending)
        return net

    # ---------------------------------------------------------------- query
    @property
    def nets(self):
        return {n: list(members) for n, members in self._nets.items()}

    def net_of(self, ref, port):
        for net, members in self._nets.items():
            if (ref, port) in members:
                return net
        return None

    def ports_of(self, ref):
        return [(net, port) for net, members in self._nets.items()
                for r, port in members if r == ref]

    def neighbours(self, ref):
        out = set()
        for net, members in self._nets.items():
            if any(r == ref for r, _ in members):
                out.update(r for r, _ in members if r != ref)
        return out

    def signature(self):
        """Canonical connectivity: {net: sorted [(ref, port)]}.

        Two schematics of the same circuit must produce the same signature.
        """
        return {net: sorted(members) for net, members in self._nets.items()}

    def partition(self):
        """Connectivity as a set of frozensets of terminals, net names aside.

        This is what a rendered drawing can be checked against: the drawing
        need not know net *names*, only which terminals are joined.
        """
        return {frozenset(members) for members in self._nets.values()}

    # ---------------------------------------------------------------- checks
    def validate(self, part_ports=None):
        """Structural checks against the component port metadata."""
        from .electrical import PORTS
        problems = []
        for ref, c in self.components.items():
            if c.kind in PORTS and set(c.ports) != set(PORTS[c.kind]):
                problems.append(f'{ref}: declared ports disagree with electrical kind {c.kind}')
            known = (part_ports.get(c.kind) if part_ports is not None else c.ports)
            if known is None:
                problems.append(f'{ref}: unknown component kind {c.kind!r}')
                continue
            wired = {port for _, port in self.ports_of(ref)}
            unknown = wired - set(known)
            if unknown:
                problems.append(
                    f'{ref} ({c.kind}): no such port(s) {sorted(unknown)}; '
                    f'has {sorted(known)}')
            floating = set(known) - wired
            if floating:
                problems.append(
                    f'{ref} ({c.kind}): unconnected port(s) {sorted(floating)}')
        for net, members in self._nets.items():
            if len(members) < 2:
                problems.append(f'net {net}: only {len(members)} terminal')
        for ref, c in self.components.items():
            if c.kind == 'terminal' and not c.external:
                problems.append(
                    f'{ref}: a terminal must declare interface="power" or '
                    f'"control"; an internal node should connect straight to '
                    f'a component')
            if c.external and c.kind != 'terminal':
                problems.append(
                    f'{ref}: only a terminal may be an external interface')
        return problems

    def to_dict(self):
        """Versioned, JSON-compatible electrical interchange; no view metadata."""
        from copy import deepcopy
        return {'version': 1, 'name': self.name,
                'components': [dict(ref=c.ref, kind=c.kind, ports=list(c.ports),
                                    role=c.role, interface=c.interface,
                                    attrs=deepcopy(c.attrs))
                               for c in sorted(self.order, key=lambda c: c.ref)],
                'nets': {n: [f'{r}.{p}' for r, p in sorted(m)]
                         for n, m in sorted(self._nets.items())}}

    @classmethod
    def from_dict(cls, data):
        if data.get('version') != 1:
            raise ValueError('unsupported Circuit IR version')
        from copy import deepcopy
        n = cls(data.get('name', 'circuit'))
        for c in data['components']:
            n.add(c['ref'], c['kind'], role=c.get('role'),
                  ports=c['ports'], interface=c.get('interface'),
                  **deepcopy(c.get('attrs', {})))
        for net, members in data['nets'].items():
            n.connect(net, *members)
        faults = n.validate()
        if faults:
            raise ValueError('invalid Circuit IR: ' + '; '.join(faults))
        return n

    def __repr__(self):
        return (f'<Netlist {self.name}: {len(self.components)} components, '
                f'{len(self._nets)} nets>')
