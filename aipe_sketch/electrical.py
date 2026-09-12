"""Backend-independent electrical kinds and port semantics. No SVG dependencies."""
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

# Ports that are electrically interchangeable, so colour refinement does not
# treat two otherwise identical structures as different.
SYMMETRIC_PORTS = {
    'res': {'a': '*', 'b': '*'},
    'cap': {'a': '*', 'b': '*'},
    'ind': {'a': '*', 'b': '*'},
    'ind_core': {'a': '*', 'b': '*'},
    'transformer': {'p1': 'p*', 'p2': 'p*', 's1': 's*', 's2': 's*'},
}


def canonical_port(kind, port):
    return SYMMETRIC_PORTS.get(kind, {}).get(port, port)


ALIASES = {
    'capacitor': 'cap', 'polarised_capacitor': 'cap_pol',
    'resistor': 'res', 'inductor': 'ind', 'cored_inductor': 'ind_core',
    'voltage_source': 'vsource', 'current_source': 'isource',
    'mosfet': 'nmos', 'n_mosfet': 'nmos', 'ground': 'gnd',
    'switch': 'nmos', 'rectifier': 'diode',
}


PORTS = {
    **{k: ('a', 'b') for k in ('res', 'cap', 'cap_pol', 'ind', 'ind_core')},
    **{k: ('p', 'n') for k in ('vsource', 'isource', 'battery')},
    'nmos': ('d', 's', 'g'), 'nmos_don': ('d', 's', 'g'),
    'igbt': ('c', 'e', 'g'), 'diode': ('a', 'k'),
    'transformer': ('p1', 'p2', 's1', 's2'),
    'gnd': ('t',), 'terminal': ('t',),
}
CONTROL_PORTS = {'nmos': ('g',), 'nmos_don': ('g',), 'igbt': ('g',)}

def power_ports(component):
    return tuple(p for p in component.ports
                 if p not in CONTROL_PORTS.get(component.kind, ()))
