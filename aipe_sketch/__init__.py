"""Circuit IR plus optional schematic backend.

Importing Netlist does not import the SVG, placement or routing backend.
"""
from importlib import import_module
from .netlist import Component, Netlist

_EXPORTS = {
    'Schematic': 'pipeline', 'SchematicText': 'presentation',
    'AutoPlan': 'planner', 'auto_plan': 'planner', 'graph_analysis': 'planner',
    'Group': 'plan', 'Item': 'plan', 'Slot': 'plan', 'LayoutPlan': 'plan',
    'ROWS': 'plan', 'bridge_group': 'plan', 'Sketch': 'sketch',
    'COARSE': 'pins', 'GRID': 'pins',
}
__all__ = ['Netlist', 'Component', *_EXPORTS]


def __getattr__(name):
    module = _EXPORTS.get(name)
    if module is None:
        raise AttributeError(name)
    value = getattr(import_module('.' + module, __name__), name)
    globals()[name] = value
    return value
