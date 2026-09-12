"""Canonical file locations.

The master sheet is the one authoritative graphical source.  Everything under
``assets/generated_symbols`` is derived from it and may be regenerated at any
time; nothing there is edited by hand as the primary workflow.
"""
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MASTER_DIR = os.path.join(ROOT, 'assets', 'master')
MASTER = os.path.join(MASTER_DIR, 'Inkscape_Symbols_All.svg')
GENERATED = os.path.join(ROOT, 'assets', 'generated_symbols')
REGISTRY_JSON = os.path.join(ROOT, 'assets', 'symbol_registry.json')
OUT = os.path.join(ROOT, 'out')

MASTER_NAME = os.path.basename(MASTER)
