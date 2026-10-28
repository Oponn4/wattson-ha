"""Kalender-Abruf: ein Fehler kostet den Termin, nicht den Tick (v0.20.28).

28.10.2026 21:45: iCloud-CalDAV meldete `RateLimitError ... Retry after: 1862`.
Die CalDAV-Integration reicht das roh durch, `_fetch_calendar_events` fing nur
`HomeAssistantError` — Wattson war einen Tick `unavailable`. Fünf Mal seit dem
26.10.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from conftest import const, kalender

BERLIN = timezone(timedelta(hours=1))
NOW = datetime(2026, 10, 28, 21, 45, tzinfo=BERLIN)
NORMAL = const.SAUNA_KALENDER_INTERVALL_MIN
ABEND = const.SAUNA_KALENDER_INTERVALL_ABEND_MIN
ABEND_H = const.SAUNA_KALENDER_ABEND_H


def intervall(t: datetime) -> int:
    return kalender.abruf_intervall_min(
        t, normal_min=NORMAL, abend_min=ABEND, abend_h=ABEND_H,
    )

class RateLimitError(Exception):
    """Steht für `caldav.lib.error.RateLimitError` — kein HomeAssistantError."""


def run(coro):
    return asyncio.run(coro)


def _abruf(antwort=None, fehler=None):
    aufrufe = []

    async def abruf(ids, hours):
        aufrufe.append((ids, hours))
        if fehler is not None:
            raise fehler
        return antwort

    return abruf, aufrufe


def test_der_vorfall_fremder_fehler_heisst_nicht_abrufbar():
    abruf, _ = _abruf(fehler=RateLimitError("Retry after: 1862"))
    assert run(kalender.termine_holen(abruf, ["calendar.barchen"], 24)) is None


def test_termine_werden_zusammengefuehrt_mit_quelle():
    abruf, aufrufe = _abruf(antwort={
        "calendar.barchen": {"events": [{"summary": "Sauna"}]},
        "calendar.arbeit": {"events": [{"summary": "Termin"}, {"summary": "X"}]},
    })
    events = run(kalender.termine_holen(
        abruf, ["calendar.barchen", "calendar.arbeit"], 24,
    ))
    assert [e["_calendar"] for e in events] == [
        "calendar.barchen", "calendar.arbeit", "calendar.arbeit",
    ]
    assert aufrufe == [(["calendar.barchen", "calendar.arbeit"], 24)]


def test_ohne_kalender_leer_und_kein_abruf():
    abruf, aufrufe = _abruf(fehler=AssertionError("darf nicht laufen"))
    assert run(kalender.termine_holen(abruf, [], 24)) == []
    assert aufrufe == []


def test_leere_antwort_ist_nicht_abrufbar_statt_keine_termine():
    abruf, _ = _abruf(antwort={})
    assert run(kalender.termine_holen(abruf, ["calendar.barchen"], 24)) is None


def test_kalender_ohne_termine_ist_leer():
    abruf, _ = _abruf(antwort={"calendar.barchen": {"events": []}})
    assert run(kalender.termine_holen(abruf, ["calendar.barchen"], 24)) == []


class TestDrossel:
    def test_erster_abruf_sofort(self):
        assert kalender.abruf_faellig(None, NOW, NORMAL) is True

    def test_innerhalb_des_intervalls_nicht(self):
        letzter = NOW - timedelta(minutes=NORMAL - 1)
        assert kalender.abruf_faellig(letzter, NOW, NORMAL) is False

    def test_ab_intervall_wieder(self):
        letzter = NOW - timedelta(minutes=NORMAL)
        assert kalender.abruf_faellig(letzter, NOW, NORMAL) is True


class TestIntervall:
    def test_werte_wie_vereinbart(self):
        """Christian, 28.10.: stündlich reicht, 15–20 Uhr alle 20 min."""
        assert (NORMAL, ABEND, ABEND_H) == (60, 20, (15, 20))

    def test_grenzen(self):
        tag = NOW.replace(minute=0)
        assert intervall(tag.replace(hour=14, minute=59)) == NORMAL
        assert intervall(tag.replace(hour=15)) == ABEND
        assert intervall(tag.replace(hour=19, minute=59)) == ABEND
        assert intervall(tag.replace(hour=20)) == NORMAL

    def test_ein_tag_mit_5_minuten_ticks(self):
        """Statt 288 Abrufe (jeder Tick) nur noch 34: 19 stündlich + 15 abends."""
        start = NOW.replace(hour=0, minute=0)
        letzter = None
        abrufe = 0
        for i in range(24 * 12):
            t = start + timedelta(minutes=5 * i)
            if kalender.abruf_faellig(letzter, t, intervall(t)):
                letzter = t
                abrufe += 1
        assert abrufe == 34
