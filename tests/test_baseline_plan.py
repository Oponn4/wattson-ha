"""Tests zum Grundplan-Gate (UC2, v0.20.5).

Der Grundplan kennt keinen Strompreis. Bis v0.20.4 zog er trotzdem jeden
Morgen auf BASELINE_SOC — am 15.08.2026 um 06:02 waren das 11 kW aus dem Netz
zu 37,5 ct, um von 48 auf 51 % zu kommen. Die einzige Fahrt des Tages
(Spieleabend, 13 km) brauchte 40 %, das Billigfenster lag mittags bei 18 ct.
Seither entfällt der Boden, wenn alle bekannten Fahrten gedeckt sind.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from conftest import const, forecast

baseline_plan_needed = forecast.baseline_plan_needed
TripCandidate = forecast.TripCandidate

BERLIN = timezone(timedelta(hours=2))

SOC = const.BASELINE_SOC        # 50
FLOOR = const.BASELINE_FLOOR_SOC  # 30


def trip(title: str, hour: int, distance_km: float, required_soc: int) -> TripCandidate:
    return TripCandidate(
        title=title, location=f"{title}-Ort", calendar="calendar.barchen",
        start=datetime(2026, 8, 15, hour, 0, tzinfo=BERLIN),
        distance_km=distance_km, required_soc=required_soc, uid=f"uid-{title}",
    )


def needed(car_soc: float, candidates: list[TripCandidate]) -> bool:
    return baseline_plan_needed(
        car_soc=car_soc, candidates=candidates,
        baseline_soc=SOC, floor_soc=FLOOR,
    )


# Der echte Fall vom 15.08.2026, mit den SOC-Werten von damals. Beide sind
# inzwischen niedriger: die Marge ist relativ (Spieleabend 20 %), und „Sonjas
# Eltern kommen" trägt die eigene Hausadresse — mit korrigierter home_address
# 0 km statt 4,1. Für das Gate ändert das nichts, gedeckt bleibt gedeckt.
SPIELEABEND = trip("Spieleabend", 18, 12.8, 40)
ELTERN = trip("Sonjas Eltern kommen", 12, 4.1, 35)


class TestVorfall20260815:
    def test_gedeckte_fahrten_brauchen_keinen_grundplan(self):
        """48 % deckt beide Fahrten → kein Laden zu 37,5 ct um 06:02."""
        assert needed(48.0, [SPIELEABEND, ELTERN]) is False

    def test_alte_logik_haette_geladen(self):
        """Gegenprobe: allein am SOC gemessen lag 48 % unter dem Boden."""
        assert 48.0 < SOC

    def test_ungedeckte_fahrt_laedt_weiterhin(self):
        """Der Boden darf nicht generell verschwinden."""
        assert needed(38.0, [SPIELEABEND, ELTERN]) is True

    def test_groessere_fahrt_am_folgetag_zaehlt_mit(self):
        gross = trip("Wolfgangs Geburtstag", 12, 100.6, 90)
        assert needed(45.0, [SPIELEABEND, gross]) is True


class TestReserve:
    def test_unter_reserve_immer_grundplan(self):
        """Kalender kennt nur Geplantes — unter der Reserve zählt er nicht."""
        assert needed(FLOOR - 1, [SPIELEABEND, ELTERN]) is True

    def test_exakt_auf_reserve_greift_die_reserve_nicht(self):
        """Grenze inklusiv: auf FLOOR entscheidet wieder die Deckung."""
        kurz = trip("Bäcker", 9, 1.0, 26)
        assert needed(FLOOR, [kurz]) is False

    def test_reserve_schlaegt_auch_bei_winziger_fahrt_zu(self):
        winzig = trip("Bäcker", 9, 1.0, 26)
        assert needed(20.0, [winzig]) is True


class TestOhneTermine:
    def test_leerer_kalender_behaelt_den_boden(self):
        """Ohne Termin sagt nichts, dass der SOC reicht — Verhalten wie bisher."""
        assert needed(48.0, []) is True

    def test_leerer_kalender_ueber_baseline_nichts_zu_tun(self):
        assert needed(SOC, []) is False


class TestBaselineSocGrenze:
    def test_ab_baseline_soc_nie_noetig(self):
        assert needed(SOC, [SPIELEABEND]) is False
        assert needed(SOC + 20, []) is False

    def test_knapp_unter_baseline_ohne_deckung_noetig(self):
        assert needed(SOC - 0.5, []) is True
