"""The netlist: the single source of truth for a schematic.

A circuit is a graph of components (nodes) joined by nets (hyperedges) at
named ports.  Nothing in the layout or routing stages may alter this
structure; they may only decide where things are drawn.
"""
from collections import defaultdict


class Component:
    __slots__ = ('ref', 'kind', 'role', 'label', 'sub', 'italic', 'attrs')

    def __init__(self, ref, kind, role=None, label=None, sub=None,
                 italic=True, **attrs):
        self.ref = ref
        self.kind = kind
        self.role = role
        self.label = label
        self.sub = sub
        self.italic = italic        # signal names are upright, quantities slant
        self.attrs = attrs

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
            **attrs):
        if ref in self.components:
            raise ValueError(f'duplicate component {ref}')
        c = Component(ref, kind, role, label, sub, italic, **attrs)
        self.components[ref] = c
        self.order.append(c)
        return c

    def connect(self, net, *terminals):
        """connect('SW_A', 'Q1.s', 'Q2.d') -- terminals are 'REF.port'."""
        for t in terminals:
            ref, port = t.split('.')
            if ref not in self.components:
                raise KeyError(f'net {net}: unknown component {ref}')
            entry = (ref, port)
            if entry in self._nets[net]:
                continue
            for other, members in self._nets.items():
                if other != net and entry in members:
                    raise ValueError(
                        f'{t} is already on net {other}; a port belongs to '
                        f'exactly one net')
            self._nets[net].append(entry)
        return net

    # ---------------------------------------------------------------- query
    @property
    def nets(self):
        return dict(self._nets)

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
    def validate(self, part_ports):
        """Structural checks against the component port metadata."""
        problems = []
        for ref, c in self.components.items():
            known = part_ports.get(c.kind)
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
        return problems

    def __repr__(self):
        return (f'<Netlist {self.name}: {len(self.components)} components, '
                f'{len(self._nets)} nets>')
