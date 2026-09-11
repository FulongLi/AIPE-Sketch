"""AIPE-Sketch: publication-quality power-electronics schematics generated
from a netlist.

The netlist is the single source of truth.  Layout and routing may only
decide where things are drawn, never what is connected to what, and the
finished drawing is read back and checked against the netlist before it is
written out.

    netlist -> analysis -> plan -> placement -> routing
            -> scoring -> repair -> connectivity check -> render
"""
from .netlist import Component, Netlist
from .pins import COARSE, GRID
from .pipeline import Schematic
from .plan import Group, Item, LayoutPlan, ROWS, Slot, bridge_group
from .sketch import Sketch

__all__ = ['Netlist', 'Component', 'Schematic', 'LayoutPlan', 'Group', 'Slot',
           'Item', 'bridge_group', 'ROWS', 'Sketch', 'GRID', 'COARSE']
