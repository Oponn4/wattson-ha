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
from datetime import datetime, timezone
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


def _install_ha_stubs() -> None:
    """Minimal-Stubs für die HA-Imports von `override.py`.

    `override.py` braucht von Home Assistant nur den Typ `HomeAssistant` und
    `dt_util.now()`. Beides hier zu stubben ist billiger als eine echte
    HA-Installation im Test-Env — und hält die Suite bei <1 s Laufzeit.
    """
    if "homeassistant" in sys.modules:
        return

    ha = types.ModuleType("homeassistant")
    core = types.ModuleType("homeassistant.core")
    util = types.ModuleType("homeassistant.util")
    dt_mod = types.ModuleType("homeassistant.util.dt")

    class HomeAssistant:
        """Platzhalter für Type-Hints."""

    core.HomeAssistant = HomeAssistant
    dt_mod.now = lambda: datetime.now(timezone.utc).astimezone()
    dt_mod.utcnow = lambda: datetime.now(timezone.utc)
    util.dt = dt_mod
    ha.core = core
    ha.util = util

    sys.modules.update({
        "homeassistant": ha,
        "homeassistant.core": core,
        "homeassistant.util": util,
        "homeassistant.util.dt": dt_mod,
    })


if PKG not in sys.modules:
    _pkg = types.ModuleType(PKG)
    _pkg.__path__ = [str(COMPONENT_DIR)]
    sys.modules[PKG] = _pkg

_install_ha_stubs()

const = _load("const")
forecast = _load("forecast")
override = _load("override")
evcc_modes = _load("evcc_modes")
