"""Tests für die UC6-Sofortlade-Entscheidung (v0.18.13).

Der Sofort-Modus (`now`) überstimmt den evcc-Fahrplan und lädt preisblind.
Er darf deshalb erst greifen, wenn der Plan zeitlich nicht mehr durchkommt —
nicht schon, weil die Abfahrt näher als N Stunden ist.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from conftest import const, forecast

needs_forced_charging = forecast.needs_forced_charging
FALLBACK_H = const.UC6_NOW_TRIP_URGENT_HOURS

BERLIN = timezone(timedelta(hours=2))
# Der reale Fall vom 25.07.2026
TRIP_START = datetime(2026, 7, 26, 12, 0, tzinfo=BERLIN)
LATEST_FEASIBLE = datetime(2026, 7, 26, 9, 0, tzinfo=BERLIN)


class TestRegressionNachtladen:
    def test_mitternacht_erzwingt_nicht_mehr(self):
        """Kern: um 00:00 wäre die alte 12h-Regel gekippt und hätte zu
        35,6 ct geladen, obwohl der Plan bis 11:30 locker reicht."""
        mitternacht = datetime(2026, 7, 26, 0, 0, tzinfo=BERLIN)
        assert needs_forced_charging(
            True, TRIP_START, LATEST_FEASIBLE, mitternacht, FALLBACK_H
        ) is False

    def test_alte_regel_haette_gegriffen(self):
        """Gegenprobe: ohne Machbarkeitsgrenze feuert die Zeitregel."""
        mitternacht = datetime(2026, 7, 26, 0, 0, tzinfo=BERLIN)
        assert needs_forced_charging(
            True, TRIP_START, None, mitternacht, FALLBACK_H
        ) is True

    def test_ab_machbarkeitsgrenze_wird_erzwungen(self):
        assert needs_forced_charging(
            True, TRIP_START, LATEST_FEASIBLE,
            datetime(2026, 7, 26, 9, 0, tzinfo=BERLIN), FALLBACK_H,
        ) is True

    def test_kurz_davor_noch_nicht(self):
        assert needs_forced_charging(
            True, TRIP_START, LATEST_FEASIBLE,
            datetime(2026, 7, 26, 8, 45, tzinfo=BERLIN), FALLBACK_H,
        ) is False

    def test_nach_der_grenze_weiterhin(self):
        assert needs_forced_charging(
            True, TRIP_START, LATEST_FEASIBLE,
            datetime(2026, 7, 26, 10, 30, tzinfo=BERLIN), FALLBACK_H,
        ) is True


class TestVorbedingungen:
    NOW = datetime(2026, 7, 26, 11, 0, tzinfo=BERLIN)  # nach latest_feasible

    def test_ohne_plan_nie(self):
        assert needs_forced_charging(
            False, TRIP_START, LATEST_FEASIBLE, self.NOW, FALLBACK_H
        ) is False

    def test_ohne_trip_start_nie(self):
        assert needs_forced_charging(
            True, None, LATEST_FEASIBLE, self.NOW, FALLBACK_H
        ) is False

    def test_fallback_weit_vor_abfahrt_nein(self):
        """Ohne Grenze, aber Abfahrt noch weit weg → kein Zwang."""
        assert needs_forced_charging(
            True, TRIP_START, None,
            datetime(2026, 7, 25, 12, 0, tzinfo=BERLIN), FALLBACK_H,
        ) is False
