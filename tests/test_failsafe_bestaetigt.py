"""Heizstab-Failsafe: Abschalten erst buchen, wenn es zurückgelesen ist (v0.20.22).

Der Failsafe war die letzte Stelle, die mit `blocking=False` schrieb und
unbestätigt buchte. Scheitert das Abschalten, darf er nichts buchen: sonst
gälte der weiterlaufende Stab beim nächsten Tick als Hand-Eingriff.
"""
from __future__ import annotations

from pathlib import Path

QUELLE = (
    Path(__file__).resolve().parents[1]
    / "custom_components" / "wattson" / "coordinator.py"
).read_text(encoding="utf-8")
FAILSAFE = QUELLE.split("async def _heizstab_failsafe_off(")[1].split("\n    async def ")[0]


def test_failsafe_schreibt_bestaetigt():
    assert "blocking=False" not in FAILSAFE
    assert "schreiben_bestaetigt(" in FAILSAFE


def test_failsafe_bucht_erst_nach_der_bestaetigung():
    fehlschlag = FAILSAFE.index("if fehler is not None:")
    rueckkehr = FAILSAFE.index("return", fehlschlag)
    assert rueckkehr < FAILSAFE.index("async_record_action(")


def test_kein_unbestaetigter_write_mehr_im_coordinator():
    """Nach v0.20.22 schreibt kein UC mehr ungeprüft auf ein getracktes Ziel."""
    assert "failed_write" not in QUELLE
    assert "_observe_tracked_entities" not in QUELLE
