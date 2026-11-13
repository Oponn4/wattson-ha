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


# ── Zielzeit: feste Abfahrt vor 12:00 (v0.20.32) ────────────────────────────
# Am 13.11.2026 stand der Grundplan auf „50 % bis 12:00". evcc legte die Slots
# deshalb größtenteils auf den Vormittag, einer lag um 23:45 — Sonja fuhr um
# 07:12 mit 28 % los und das Vorheizen scheiterte.

baseline_ready_time = forecast.baseline_ready_time
BUFFER = const.EVCC_PLAN_BUFFER_MINUTES  # 30
WINTER = timezone(timedelta(hours=1))


def ready_for(now: datetime, departures: list[datetime]):
    return baseline_ready_time(
        now=now, ready_hour=const.BASELINE_READY_HOUR,
        fixed_departures=departures, buffer_minutes=BUFFER,
    )


def test_ohne_feste_abfahrt_bleibt_es_bei_12_uhr():
    now = datetime(2026, 11, 12, 15, 0, tzinfo=WINTER)
    ready, abfahrt = ready_for(now, [])
    assert ready == datetime(2026, 11, 13, 12, 0, tzinfo=WINTER)
    assert abfahrt is None


def test_schulabfahrt_vor_12_uhr_zieht_die_zielzeit_vor():
    # der Fall vom 13.11.2026: Grundplan um 15:00 am Vortag gesetzt
    now = datetime(2026, 11, 12, 15, 0, tzinfo=WINTER)
    schule = datetime(2026, 11, 13, 7, 5, tzinfo=WINTER)
    ready, abfahrt = ready_for(now, [schule])
    assert ready == datetime(2026, 11, 13, 6, 35, tzinfo=WINTER)
    assert abfahrt == schule


def test_abfahrt_nach_der_zielzeit_aendert_nichts():
    # Freitagnachmittag: nächste Schulabfahrt erst Montag, Zielzeit Samstag 12:00
    now = datetime(2026, 11, 13, 16, 0, tzinfo=WINTER)
    montag = datetime(2026, 11, 16, 7, 5, tzinfo=WINTER)
    ready, abfahrt = ready_for(now, [montag])
    assert ready == datetime(2026, 11, 14, 12, 0, tzinfo=WINTER)
    assert abfahrt is None


def test_angebrochener_puffer_zaehlt_nicht():
    # 06:50, Abfahrt 07:05: Puffer seit 06:35 angebrochen — keine Zielzeit in
    # der Vergangenheit, sondern die normale 12:00
    now = datetime(2026, 11, 13, 6, 50, tzinfo=WINTER)
    schule = datetime(2026, 11, 13, 7, 5, tzinfo=WINTER)
    ready, abfahrt = ready_for(now, [schule])
    assert ready == datetime(2026, 11, 13, 12, 0, tzinfo=WINTER)
    assert abfahrt is None


def test_frueheste_abfahrt_gewinnt():
    now = datetime(2026, 11, 12, 20, 0, tzinfo=WINTER)
    frueh = datetime(2026, 11, 13, 7, 5, tzinfo=WINTER)
    spaeter = datetime(2026, 11, 13, 9, 0, tzinfo=WINTER)
    ready, abfahrt = ready_for(now, [spaeter, frueh])
    assert abfahrt == frueh
    assert ready == datetime(2026, 11, 13, 6, 35, tzinfo=WINTER)
