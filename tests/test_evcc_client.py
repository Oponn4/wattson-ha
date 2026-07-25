"""Tests für den evcc-REST-Client (UC2 Fahrplan).

Hintergrund: `evcc_intg.set_vehicle_plan` meldet in HA Erfolg, ohne dass in
evcc ein Plan entsteht (verifiziert 2026-07-25). Der Client darf deshalb NICHT
HTTP 200 allein als Erfolg werten, sondern muss die Quittung von evcc prüfen.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path

BERLIN = timezone(timedelta(hours=2))
DEPARTURE = datetime(2026, 7, 26, 11, 30, tzinfo=BERLIN)


def run(coro):
    """Coroutine synchron ausführen — spart die pytest-asyncio-Abhängigkeit."""
    return asyncio.run(coro)


def _load_client():
    """evcc_client isoliert laden (hängt nur an aiohttp, nicht an HA)."""
    import importlib.util

    root = Path(__file__).resolve().parents[1] / "custom_components" / "wattson"
    # Minimal-Stub, damit der HA-Import im Funktionsrumpf nicht greift
    spec = importlib.util.spec_from_file_location(
        "wattson_evcc_client", root / "evcc_client.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


evcc_client = _load_client()
EvccClient = evcc_client.EvccClient


class FakeClient(EvccClient):
    """Ersetzt nur den HTTP-Aufruf — die Auswertung bleibt echt."""

    def __init__(self, base_url: str, responses: list):
        super().__init__(hass=None, base_url=base_url)
        self._responses = list(responses)
        self.calls: list[tuple[str, str]] = []

    async def _request(self, method: str, path: str):
        self.calls.append((method, path))
        return self._responses.pop(0) if self._responses else None


class TestSetVehiclePlan:
    def test_erfolg_bei_bestaetigtem_plan(self):
        c = FakeClient("http://evcc:7070",
                       [{"soc": 90, "time": "2026-07-26T11:30:00+02:00"}])
        assert run(c.set_vehicle_plan("ora", 90, DEPARTURE)) is True

    def test_stiller_fehlschlag_wird_erkannt(self):
        """Kern: leere Antwort trotz HTTP 200 ist KEIN Erfolg.

        Genau dieser Fall lief über evcc_intg zehn Tage lang als „Plan aktiv".
        """
        c = FakeClient("http://evcc:7070", [{}])
        assert run(c.set_vehicle_plan("ora", 90, DEPARTURE)) is False

    def test_transportfehler_ist_kein_erfolg(self):
        c = FakeClient("http://evcc:7070", [None])
        assert run(c.set_vehicle_plan("ora", 90, DEPARTURE)) is False

    def test_ohne_url_kein_versuch(self):
        c = FakeClient("", [{"soc": 90}])
        assert run(c.set_vehicle_plan("ora", 90, DEPARTURE)) is False
        assert c.calls == []

    def test_pfad_und_zeitstempel(self):
        c = FakeClient("http://evcc:7070", [{"soc": 90, "time": "x"}])
        run(c.set_vehicle_plan("ora", 90, DEPARTURE))
        method, path = c.calls[0]
        assert method == "POST"
        assert path.startswith("/api/vehicles/ora/plan/soc/90/")
        # Zeitstempel URL-kodiert — das "+" des Offsets darf nicht als
        # Leerzeichen ankommen
        assert "%2B02%3A00" in path

    def test_soc_wird_ganzzahlig(self):
        c = FakeClient("http://evcc:7070", [{"soc": 90, "time": "x"}])
        run(c.set_vehicle_plan("ora", 90.0, DEPARTURE))
        assert "/plan/soc/90/" in c.calls[0][1]


class TestDeleteVehiclePlan:
    def test_loeschen_erfolgreich(self):
        c = FakeClient("http://evcc:7070", [{}])
        assert run(c.delete_vehicle_plan("ora")) is True
        assert c.calls == [("DELETE", "/api/vehicles/ora/plan/soc")]

    def test_loeschen_fehlgeschlagen(self):
        c = FakeClient("http://evcc:7070", [None])
        assert run(c.delete_vehicle_plan("ora")) is False
