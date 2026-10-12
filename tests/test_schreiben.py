"""Bestätigte Writes (v0.20.16, siehe schreiben.py).

Der Vorfall vom 08.10.2026: Heizstab-Write um 13:04:57 von der Proxon mit
Modbus-Exception 0x03 abgelehnt, Wattson bucht ihn trotzdem, um 13:30 gilt der
eigene verlorene Write als Hand-Eingriff — UC4b bis Mitternacht gesperrt.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from conftest import override as override_mod
from conftest import schreiben

schreiben_bestaetigt = schreiben.schreiben_bestaetigt
HEIZSTAB = "switch.proxon_t300_e_heizstab"


class Abgelehnt(Exception):
    """Steht für HomeAssistantError aus dem Service-Call."""


class Anlage:
    """Service, der die ersten `ablehnungen` Aufrufe ablehnt.

    `zeigt_an=False`: der Call kommt ohne Fehler zurück, der Zustand ändert
    sich aber nie (der UC4a-Fall vom Juli: falsche Domain, Erfolg gemeldet).
    """

    def __init__(self, ablehnungen: int = 0, *, zeigt_an: bool = True) -> None:
        self.ablehnungen = ablehnungen
        self.zeigt_an = zeigt_an
        self.aufrufe = 0
        self.zustand = "off"

    async def aufrufen(self) -> None:
        self.aufrufe += 1
        if self.aufrufe <= self.ablehnungen:
            raise Abgelehnt("Modbus Exception 0x03")
        if self.zeigt_an:
            self.zustand = "on"

    def lesen(self) -> str:
        return self.zustand


class Uhr:
    """Fake-Zeit: `schlafen` rückt die Uhr vor, statt zu warten."""

    def __init__(self) -> None:
        self.t = 0.0
        self.pausen: list[float] = []

    async def schlafen(self, s: float) -> None:
        self.pausen.append(s)
        self.t += s

    def jetzt(self) -> float:
        return self.t


def _schreiben(anlage: Anlage, uhr: Uhr) -> str | None:
    return asyncio.run(schreiben_bestaetigt(
        anlage.aufrufen, anlage.lesen, lambda ist: ist == "on",
        schlafen=uhr.schlafen, uhr=uhr.jetzt,
    ))


class TestSchreibenBestaetigt:
    def test_auf_anhieb(self):
        anlage, uhr = Anlage(), Uhr()
        assert _schreiben(anlage, uhr) is None
        assert anlage.aufrufe == 1
        assert uhr.pausen == []

    def test_zweiter_versuch(self):
        anlage, uhr = Anlage(ablehnungen=1), Uhr()
        assert _schreiben(anlage, uhr) is None
        assert anlage.aufrufe == 2
        assert uhr.pausen == [schreiben.PAUSE_ZWISCHEN_VERSUCHEN_S]

    def test_dreimal_abgelehnt_liefert_grund(self):
        anlage, uhr = Anlage(ablehnungen=99), Uhr()
        grund = _schreiben(anlage, uhr)
        assert grund is not None
        assert "3/3" in grund and "0x03" in grund
        assert anlage.aufrufe == schreiben.VERSUCHE == 3

    def test_stiller_fehlschlag_wird_beim_zuruecklesen_erkannt(self):
        anlage, uhr = Anlage(zeigt_an=False), Uhr()
        grund = _schreiben(anlage, uhr)
        assert grund is not None and "Ist 'off'" in grund
        assert anlage.aufrufe == 3

    def test_wartet_auf_spaete_anzeige(self):
        """evcc zeigt den neuen Wert erst nach dem eigenen Poll."""
        anlage, uhr = Anlage(zeigt_an=False), Uhr()
        grund = asyncio.run(schreiben_bestaetigt(
            anlage.aufrufen, lambda: "on" if uhr.t >= 10 else "off",
            lambda ist: ist == "on", schlafen=uhr.schlafen, uhr=uhr.jetzt,
        ))
        assert grund is None
        assert anlage.aufrufe == 1


# ── Der Vorfall vom 08.10.: kein Buchen, kein Phantom-Override ──────────────

BERLIN = timezone(timedelta(hours=2))


class FakeHass:
    def __init__(self, tmp_path):
        self.config = SimpleNamespace(path=lambda name: str(tmp_path / name))

    async def async_add_executor_job(self, func, *args):
        return func(*args)


@pytest.fixture
def mgr(tmp_path, monkeypatch):
    t = {"now": datetime(2026, 10, 8, 13, 4, 57, tzinfo=BERLIN)}
    monkeypatch.setattr(override_mod.dt_util, "now", lambda: t["now"])
    m = override_mod.OverrideManager(
        FakeHass(tmp_path), [override_mod.UCDefinition("uc4b", "Heizstab")],
    )
    m.uhr = t
    return m


def test_nicht_gebuchter_write_wird_nie_override(mgr):
    """Write scheiterte → `_try_act` bucht nichts → 25 min später kein Override."""
    mgr.uhr["now"] += timedelta(minutes=25)
    verdict = asyncio.run(mgr.async_check_action(HEIZSTAB, "off", uc_id="uc4b"))
    assert verdict == "ok"


def test_alter_weg_haette_override_gemeldet(mgr):
    """Negativprobe: so lief es bis v0.20.15 — unbestätigt gebucht, nie angekommen."""
    asyncio.run(mgr.async_record_action("uc4b", HEIZSTAB, "on", prev_value="off"))
    mgr.uhr["now"] += timedelta(minutes=25)
    verdict = asyncio.run(mgr.async_check_action(HEIZSTAB, "off", uc_id="uc4b"))
    assert verdict == "override"


def test_bestaetigt_gebucht(mgr):
    asyncio.run(mgr.async_record_action(
        "uc4b", HEIZSTAB, "on", prev_value="off", confirmed=True,
    ))
    assert mgr.get_last_action(HEIZSTAB).confirmed is True


def test_try_act_bucht_nur_bestaetigte_writes():
    """Quelltextprüfung: der Coordinator importiert Home Assistant."""
    quelle = (
        Path(__file__).resolve().parents[1]
        / "custom_components" / "wattson" / "coordinator.py"
    ).read_text(encoding="utf-8")
    try_act = quelle.split("async def _try_act(")[1].split("\n    async def ")[0]
    assert "blocking=False" not in try_act
    assert "schreiben_bestaetigt(" in try_act
    assert "confirmed=True" in try_act
    # Rückkehr ohne Buchung steht vor dem Buchen.
    assert try_act.index("return False, f\"Write nicht angekommen") < try_act.index(
        "async_record_action("
    )
