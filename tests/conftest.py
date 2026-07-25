"""Test-Setup ohne Home-Assistant-Installation.

`custom_components/wattson/__init__.py` importiert Home Assistant. Die reinen
Logik-Module (`const`, `forecast`) brauchen es nicht — sie benutzen aber
relative Imports (`from .const import ...`), die einen Package-Kontext
verlangen. Darum wird hier ein synthetisches Package registriert, dessen
`__path__` auf das Komponentenverzeichnis zeigt: relative Imports lösen sich
auf, das echte `__init__.py` wird nie ausgeführt.
"""
from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

PKG = "wattson_pure"
COMPONENT_DIR = Path(__file__).resolve().parents[1] / "custom_components" / "wattson"


def _load(module_name: str) -> types.ModuleType:
    full_name = f"{PKG}.{module_name}"
    if full_name in sys.modules:
        return sys.modules[full_name]
    spec = importlib.util.spec_from_file_location(
        full_name, COMPONENT_DIR / f"{module_name}.py"
    )
    if spec is None or spec.loader is None:
        raise ImportError(f"Kann {module_name} nicht laden")
    module = importlib.util.module_from_spec(spec)
    sys.modules[full_name] = module
    spec.loader.exec_module(module)
    return module


if PKG not in sys.modules:
    _pkg = types.ModuleType(PKG)
    _pkg.__path__ = [str(COMPONENT_DIR)]
    sys.modules[PKG] = _pkg

const = _load("const")
forecast = _load("forecast")
