"""Tests der Anstecken-Erinnerung (v0.19).

Eine Sorte Meldung statt gestaffelter Preis-Eskalation: das Einzige, was ein
Mensch beisteuern muss, ist das Kabel. Gemeldet wird beim Heimkommen — da
steht man neben dem Auto — oder wenn eine Fahrt zeitlich zu kippen droht.
"""
from __future__ import annotations

from typing import ClassVar

from conftest import const, forecast

due = forecast.plugin_reminder_due
COMFORT = const.PLUGIN_COMFORT_SOC
WINDOW = const.PLUGIN_ARRIVAL_WINDOW_MIN

BASE: ClassVar[dict] = {
    "car_home": True,
    "car_plugged": False,
    "car_soc": 80.0,
    "comfort_soc": COMFORT,
    "trip_required_soc": None,
    "trip_title": "Fahrt",
    "trip_at_risk": False,
    "minutes_since_arrival": 5.0,
    "arrival_window_min": WINDOW,
}


def r(**over):
    return due(**{**BASE, **over})


class TestAlltag:
    def test_heimgekommen_mit_leerem_akku_erinnert(self):
        got = r(car_soc=30.0)
        assert got is not None
        assert got.kind == "ankunft"
        assert "30" in got.message
        assert got.urgent is False

    def test_heimgekommen_mit_vollem_akku_schweigt(self):
        """Seltenheit ist Teil der Funktion — sonst wird sie ignoriert."""
        assert r(car_soc=80.0) is None

    def test_genau_auf_der_komfortschwelle_schweigt(self):
        assert r(car_soc=float(COMFORT)) is None

    def test_knapp_darunter_erinnert(self):
        assert r(car_soc=COMFORT - 1.0) is not None

    def test_ausserhalb_des_ankunftsfensters_schweigt(self):
        """Dieselbe Meldung abends auf dem Sofa wird weggewischt."""
        assert r(car_soc=20.0, minutes_since_arrival=WINDOW + 1) is None

    def test_am_fensterrand_erinnert_noch(self):
        assert r(car_soc=20.0, minutes_since_arrival=float(WINDOW)) is not None


class TestVorbedingungen:
    def test_angesteckt_schweigt_immer(self):
        """Löst sich von selbst auf — deshalb braucht es keinen Quittungsknopf."""
        assert r(car_plugged=True, car_soc=5.0, trip_at_risk=True) is None

    def test_nicht_zuhause_schweigt(self):
        assert r(car_home=False, car_soc=5.0) is None

    def test_nie_angekommen_schweigt(self):
        assert r(car_soc=10.0, minutes_since_arrival=None) is None


class TestFahrt:
    TRIP: ClassVar[dict] = {
        "trip_required_soc": 90,
        "trip_title": "Wolfgangs Geburtstag",
    }

    def test_gefaehrdete_fahrt_meldet_ohne_ankunft(self):
        """Sonst verpasst man sie, wenn das Auto schon länger dasteht."""
        got = r(**self.TRIP, car_soc=60.0, trip_at_risk=True,
                minutes_since_arrival=None)
        assert got is not None
        assert got.kind == "fahrt"
        assert got.urgent is True
        assert "Wolfgangs Geburtstag" in got.message

    def test_fahrt_bei_ankunft_ist_nicht_dringend(self):
        got = r(**self.TRIP, car_soc=60.0, trip_at_risk=False)
        assert got is not None
        assert got.kind == "ankunft"
        assert got.urgent is False

    def test_fahrt_gedeckt_meldet_nicht(self):
        """SOC über Bedarf und über Komfort → nichts zu tun."""
        assert r(**self.TRIP, car_soc=95.0, trip_at_risk=True) is None

    def test_fahrt_zieht_ueber_komfortschwelle(self):
        """70% wären im Alltag genug, für die Fahrt aber nicht."""
        assert r(car_soc=70.0) is None
        assert r(**self.TRIP, car_soc=70.0) is not None


class TestTextIstAlltagstauglich:
    def test_kein_preis_und_kein_euro_im_text(self):
        """WAF: die Bitte lautet 'steck an' — Preise gehören ins Dashboard."""
        for over in ({"car_soc": 20.0},
                     {"car_soc": 60.0, "trip_required_soc": 90,
                      "trip_title": "Geburtstag", "trip_at_risk": True}):
            got = r(**over)
            assert got is not None
            low = got.message.lower()
            assert "€" not in got.message and "ct" not in low
            assert "cheap" not in low and "tibber" not in low
            assert "anstecken" in low

    def test_text_bleibt_kurz(self):
        got = r(car_soc=20.0)
        assert got is not None and len(got.message) < 120


class TestSituationHeuteNacht:
    """26.07.2026, 00:15 — Auto zuhause, 88%, Fahrt braucht 90%."""

    def test_kein_alarm_mitten_in_der_nacht(self):
        """Zeit reicht bis 10:19 locker → kein Wecken."""
        assert r(trip_required_soc=90, trip_title="Wolfgangs Geburtstag",
                 car_soc=88.0, trip_at_risk=False,
                 minutes_since_arrival=None) is None

    def test_morgens_wenn_es_knapp_wird_meldet_es(self):
        got = r(trip_required_soc=90, trip_title="Wolfgangs Geburtstag",
                car_soc=88.0, trip_at_risk=True, minutes_since_arrival=None)
        assert got is not None and got.urgent is True
