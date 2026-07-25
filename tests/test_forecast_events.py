"""Tests für die Kalender-Event-Auswertung (UC2 Trip-Planning).

forecast.py ist absichtlich HA-frei (nur stdlib + const), darum laufen diese
Tests ohne Home-Assistant-Installation: `pytest tests/`.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from conftest import const, forecast

SKIP_LOCATION_KEYWORDS = const.SKIP_LOCATION_KEYWORDS
next_relevant_event = forecast.next_relevant_event
parse_event_start = forecast.parse_event_start
relevant_events = forecast.relevant_events

BERLIN = timezone(timedelta(hours=2))  # CEST, wie HA es im Sommer liefert
NOW = datetime(2026, 7, 25, 16, 0, tzinfo=BERLIN)

TENNIS = {
    "start": "2026-07-25T18:00:00+02:00",
    "end": "2026-07-25T19:30:00+02:00",
    "summary": "Tennis",
    "location": "ESV Blau-Weiß Limburg e.V.\nStephanshügel 26\n65549 Diez\nDeutschland",
}
GEBURTSTAG = {
    "start": "2026-07-26T12:00:00+02:00",
    "end": "2026-07-26T15:00:00+02:00",
    "summary": "Wolfgangs Geburtstag",
    "location": "Kuralpe Kreuzhof\nKuralpe 2\n64686 Lautertal (Odenwald)\nDeutschland",
}
# Ganztags-Event MIT Location — genau die Kombination, die den Tick riss
GANZTAGS_MIT_ORT = {
    "start": "2026-07-26",
    "end": "2026-07-27",
    "summary": "Wolfgangs Geburtstag (ganztags)",
    "location": "Kuralpe 2, 64686 Lautertal (Odenwald)",
}
TEAMS = {
    "start": "2026-07-25T17:00:00+02:00",
    "end": "2026-07-25T18:00:00+02:00",
    "summary": "Go-Live b7",
    "location": "Microsoft Teams-Besprechung",
}


class TestParseEventStart:
    def test_getimtes_event_behaelt_offset(self):
        got = parse_event_start("2026-07-26T12:00:00+02:00", BERLIN)
        assert got == datetime(2026, 7, 26, 12, 0, tzinfo=BERLIN)

    def test_ganztags_wird_tz_aware(self):
        """Kernregression: früher naiv → TypeError beim Vergleich mit now."""
        got = parse_event_start("2026-07-26", BERLIN)
        assert got is not None
        assert got.tzinfo is not None
        assert got == datetime(2026, 7, 26, 8, 0, tzinfo=BERLIN)
        assert got > NOW  # der Vergleich, der vorher geworfen hat

    def test_ganztags_hour_konfigurierbar(self):
        got = parse_event_start("2026-07-26", BERLIN, all_day_hour=6)
        assert got == datetime(2026, 7, 26, 6, 0, tzinfo=BERLIN)

    def test_zulu_suffix(self):
        got = parse_event_start("2026-07-26T10:00:00Z", BERLIN)
        assert got == datetime(2026, 7, 26, 10, 0, tzinfo=timezone.utc)

    @pytest.mark.parametrize("bad", ["", "morgen", None, 12345, {}])
    def test_muell_gibt_none_statt_exception(self, bad):
        assert parse_event_start(bad, BERLIN) is None


class TestRelevantEvents:
    def test_ganztags_mit_ort_reisst_nichts(self):
        """Vorher: TypeError → kompletter Coordinator-Tick failed."""
        got = relevant_events([GANZTAGS_MIT_ORT], NOW, SKIP_LOCATION_KEYWORDS)
        assert len(got) == 1
        assert got[0]["_start_dt"] == datetime(2026, 7, 26, 8, 0, tzinfo=BERLIN)

    def test_kaputtes_event_verdraengt_gute_nicht(self):
        events = [{"start": "kaputt", "location": "Irgendwo"}, GEBURTSTAG]
        got = relevant_events(events, NOW, SKIP_LOCATION_KEYWORDS)
        assert [e["summary"] for e in got] == ["Wolfgangs Geburtstag"]

    def test_liefert_alle_kommenden_sortiert(self):
        got = relevant_events([GEBURTSTAG, TENNIS], NOW, SKIP_LOCATION_KEYWORDS)
        assert [e["summary"] for e in got] == ["Tennis", "Wolfgangs Geburtstag"]

    def test_ohne_location_ignoriert(self):
        ferien = {"start": "2026-06-29", "end": "2026-08-08", "summary": "Sommerferien"}
        assert relevant_events([ferien], NOW, SKIP_LOCATION_KEYWORDS) == []

    def test_teams_ignoriert(self):
        assert relevant_events([TEAMS], NOW, SKIP_LOCATION_KEYWORDS) == []

    def test_vergangenes_ignoriert(self):
        past = {**TENNIS, "start": "2026-07-25T09:00:00+02:00"}
        assert relevant_events([past], NOW, SKIP_LOCATION_KEYWORDS) == []


class TestNextRelevantEvent:
    def test_liefert_naechstes(self):
        got = next_relevant_event([GEBURTSTAG, TENNIS], NOW, SKIP_LOCATION_KEYWORDS)
        assert got is not None
        assert got["summary"] == "Tennis"

    def test_leer_gibt_none(self):
        assert next_relevant_event([], NOW, SKIP_LOCATION_KEYWORDS) is None
