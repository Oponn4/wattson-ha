"""UC2: evcc-Fahrpläne erst buchen, wenn HA sie zeigt (v0.20.21).

Bis v0.20.20 buchte UC2 den Plan sofort nach der API-Antwort, unbestätigt.
Der Override-Abgleich liest aber den HA-Sensor, und der zieht erst beim
nächsten Poll von evcc_intg nach — dieselbe Grace-Falle, die am 08.10.2026
den Heizstab bis Mitternacht gesperrt hat (siehe test_schreiben.py).
"""
from __future__ import annotations

from pathlib import Path

QUELLE = (
    Path(__file__).resolve().parents[1]
    / "custom_components" / "wattson" / "coordinator.py"
).read_text(encoding="utf-8")


def _funktion(name: str) -> str:
    return QUELLE.split(f"async def {name}(")[1].split("\n    async def ")[0]


def test_beide_plan_wege_laufen_ueber_die_bestaetigung():
    """Termin-Plan und Grundplan — kein direkter API-Aufruf mehr im UC2-Pfad."""
    assert QUELLE.count("await self._set_plan_bestaetigt(") == 2
    assert QUELLE.count("self._evcc.set_vehicle_plan(") == 1   # nur im Helfer


def test_gebucht_wird_nur_bestaetigt_und_erst_danach():
    for name in ("_handle_trip_planning", "_run_baseline_plan"):
        body = _funktion(name)
        assert "_set_plan_bestaetigt(" in body, name
        assert body.index("_set_plan_bestaetigt(") < body.index("async_record_action(")
        record = body.split("async_record_action(")[1].split(")")[0]
        assert "confirmed=True" in record, name


def test_helfer_aktualisiert_den_sensor_und_liest_zurueck():
    helfer = _funktion("_set_plan_bestaetigt")
    assert '"homeassistant", "update_entity"' in helfer
    assert "schreiben_bestaetigt(" in helfer
    assert "ENTITY_EVCC_PLAN_SOC" in helfer


def test_kein_unbestaetigter_uc2_record_mehr():
    """Jeder UC2-Record trägt `confirmed=True`."""
    teile = QUELLE.split('async_record_action(\n                "uc2"')[1:]
    assert teile, "UC2-Records nicht gefunden"
    for teil in teile:
        assert "confirmed=True" in teil.split(")")[0]


def test_aufwaerm_tick_fragt_tibber_nicht():
    """Im Aufwärm-Tick fehlte `tibber.get_prices` regelmäßig — nur Log-Rauschen."""
    assert (
        "await self._fetch_tibber_forecast()\n"
        "            if self.hass.state is CoreState.running else []"
    ) in QUELLE
