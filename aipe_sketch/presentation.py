"""Optional schematic text, deliberately outside the electrical IR.

The weak sidecar supports the historic Netlist.add(label=..., sub=...) API.
New callers can supply a SchematicText mapping to Schematic.from_netlist.
Serialization of a circuit never includes this backend-specific data.
"""
from __future__ import annotations
from dataclasses import dataclass
from weakref import WeakKeyDictionary


@dataclass(frozen=True)
class SchematicText:
    label: str | None = None
    sub: str | None = None
    italic: bool = True


_legacy = WeakKeyDictionary()


def set_legacy(component, label, sub, italic):
    _legacy[component] = SchematicText(label, sub, italic)


def text_for(component):
    if component in _legacy:
        return _legacy[component]
    from .electrical import is_reference
    if is_reference(component) or component.interface == 'control':
        return SchematicText()
    if component.interface == 'power':
        return SchematicText(component.attrs.get('name', component.ref), italic=False)
    if component.kind in ('vsource', 'isource', 'battery'):
        return SchematicText('I' if component.kind == 'isource' else 'V', 'in')
    # Standard designator notation is global and independent of circuit name.
    ref = component.ref
    return SchematicText(ref[0], ref[1:] or None)
