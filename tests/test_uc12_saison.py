"""UC12: Saisonsperre und Tagesvorhersage (v0.20.23).

Am 15.10.2026 um 15:24 hörte die FWT auf zu heizen (Zuluft 42,2 → 28,0 °C in
einer Minute). Die Sonne hatte das Haus auf 24,8 °C Abluft gebracht. Um 15:25:45
lag die Zuluft nur noch 2,3 K über der Abluft, die Heizsperre war offen, und
bei 1822 W Überschuss schaltete der PV-Zweig die Kühlung ein — bei 17 °C
draußen. Danach hielt die Hysterese sie, bis sie um 17:06 von Hand ausging.

Dazu kam: der Außen-Forecast war seit Monaten tot (`weather.forecast_home`
existiert nicht, das `forecast`-Attribut gibt es seit HA 2024.3 nicht mehr),
Wattson rechnete stumm mit dem Default 20,0 °C.
"""
from __future__ import annotations

from datetime import date, timedelta, timezone

from conftest import const, forecast

cool_decision = forecast.cool_decision
tages_max = forecast.tages_max_aus_forecast
merken = forecast.tages_max_merken

BERLIN = timezone(timedelta(hours=2))
HEUTE = date(2026, 10, 15)
WETTER = "weather.gerdihome"


def entscheide(**over):
    """UC12-Entscheidung mit den Werten vom 15.10. 15:25:45 als Grundlage."""
    args = {
        "abluft_c": 24.8,
        "trigger_c": 24.0,
        "heat_c": 25.5,
        "off_c": 23.0,
        "hysteresis_c": const.COOL_ABLUFT_HYSTERESE_C,
        "pv_surplus_w": 1822,
        "pv_min_w": const.PV_COOLING_MIN_W,
        "pv_band_w": const.COOL_PV_HYSTERESE_W,
        "pv_entry_delta_c": const.COOL_PV_ENTRY_DELTA_C,
        "spread_eur": 0.05,
        "spread_threshold_eur": const.SMART_SPREAD_THRESHOLD_EUR,
        "in_cheapest_4h": False,
        "expensive": False,
        "price_level": "normal",
        "urlaub": False,
        "sleep": False,
        "cooling_on": False,
        "heat_forced": False,
        "pv_forced": False,
        "dwell_min": 999.0,
        "min_dwell_min": const.COOL_MIN_DWELL_MIN,
        "schwellen_info": "Trigger 24.0°C / Heat 25.5°C",
        "zuluft_c": 27.1,
        "frischluft_c": 17.1,
        "heizbetrieb_delta_k": const.COOL_HEIZBETRIEB_DELTA_K,
        "hitze_dauer_min": 0.0,
        "hitze_min_dauer_min": const.COOL_HEAT_MIN_DAUER_MIN,
        "aussen_max_c": 20.0,
        "saison_max_c": const.COOL_SAISON_MAX_C,
    }
    args.update(over)
    return cool_decision(**args)


class TestSaisonsperre:
    def test_15_10_pv_zweig_bleibt_zu(self):
        e = entscheide()
        assert not e.cool
        assert e.kind == "saison"
        assert not e.pv_forced
        assert "kühler Tag" in e.reason

    def test_negativprobe_ohne_sperre_haette_pv_gekuehlt(self):
        """Ohne Vorhersage: genau das Einschalten vom 15.10."""
        e = entscheide(aussen_max_c=None)
        assert e.cool and e.kind == "pv"

    def test_warmer_tag_pv_kuehlt_wie_bisher(self):
        e = entscheide(aussen_max_c=26.0)
        assert e.cool and e.kind == "pv"

    def test_grenze_genau_auf_der_schwelle_sperrt_nicht(self):
        e = entscheide(aussen_max_c=const.COOL_SAISON_MAX_C)
        assert e.cool and e.kind == "pv"

    def test_laufende_hysterese_wird_beendet(self):
        """15:30–17:06: Kühlung lief per Hysterese weiter."""
        e = entscheide(cooling_on=True, pv_surplus_w=0, abluft_c=24.5, zuluft_c=22.7)
        assert not e.cool and e.kind == "saison"

    def test_laufende_pv_kuehlung_wird_beendet(self):
        e = entscheide(cooling_on=True, pv_forced=True, pv_surplus_w=2400, zuluft_c=22.7)
        assert not e.cool and e.kind == "saison"

    def test_cheapest_fenster_bleibt_zu(self):
        e = entscheide(pv_surplus_w=0, in_cheapest_4h=True, spread_eur=0.0)
        assert not e.cool and e.kind == "saison"

    def test_verweildauer_haelt_frisch_eingeschaltete_kuehlung(self):
        """Saison ist ein weicher Grund: frisch geschaltet wird nicht sofort umgeschaltet."""
        e = entscheide(cooling_on=True, pv_forced=True, dwell_min=5.0)
        assert e.cool and e.kind == "dwell"

    def test_hitze_kuehlt_auch_an_kuehlen_tagen(self):
        e = entscheide(abluft_c=25.8, hitze_dauer_min=25.0)
        assert e.cool and e.kind == "hitze"

    def test_hitze_noch_zu_kurz_bleibt_gesperrt(self):
        e = entscheide(abluft_c=25.8, hitze_dauer_min=5.0)
        assert not e.cool and e.kind == "saison"

    def test_heizbetrieb_hat_vorrang(self):
        e = entscheide(zuluft_c=42.2)
        assert not e.cool and e.kind == "heizbetrieb"


def antwort(*tage):
    return {WETTER: {"forecast": [
        {"datetime": dt, "temperature": t, "templow": 8.0} for dt, t in tage
    ]}}


class TestTagesMax:
    def test_heutiger_eintrag(self):
        r = antwort(("2026-10-15T10:00:00+00:00", 20.0), ("2026-10-16T10:00:00+00:00", 14.0))
        assert tages_max(r, WETTER, HEUTE, BERLIN) == 20.0

    def test_vortag_am_anfang_wird_uebersprungen(self):
        r = antwort(("2026-10-14T10:00:00+00:00", 23.0), ("2026-10-15T10:00:00+00:00", 19.5))
        assert tages_max(r, WETTER, HEUTE, BERLIN) == 19.5

    def test_datum_in_lokaler_zeit(self):
        """22:30 UTC am 14. ist in Berlin schon der 15."""
        r = antwort(("2026-10-14T22:30:00+00:00", 18.0))
        assert tages_max(r, WETTER, HEUTE, BERLIN) == 18.0

    def test_kein_heutiger_eintrag(self):
        r = antwort(("2026-10-16T10:00:00+00:00", 14.0))
        assert tages_max(r, WETTER, HEUTE, BERLIN) is None

    def test_falsche_entity(self):
        r = antwort(("2026-10-15T10:00:00+00:00", 20.0))
        assert tages_max(r, "weather.forecast_home", HEUTE, BERLIN) is None

    def test_leere_und_kaputte_antworten(self):
        assert tages_max(None, WETTER, HEUTE, BERLIN) is None
        assert tages_max({}, WETTER, HEUTE, BERLIN) is None
        assert tages_max({WETTER: {"forecast": None}}, WETTER, HEUTE, BERLIN) is None
        kaputt = {WETTER: {"forecast": [{"datetime": "2026-10-15T10:00:00+00:00"}]}}
        assert tages_max(kaputt, WETTER, HEUTE, BERLIN) is None
        nan = antwort(("2026-10-15T10:00:00+00:00", float("nan")))
        assert tages_max(nan, WETTER, HEUTE, BERLIN) is None



class TestTagesMaxMerken:
    GESTERN = HEUTE - timedelta(days=1)

    def test_spaeterer_abruf_senkt_nicht(self):
        """15.10.: morgens 20,0 °C, um 17 Uhr meldet met.no nur noch 12,1 °C."""
        assert merken(tag=HEUTE, max_c=20.0, heute=HEUTE, wert=12.1) == (HEUTE, 20.0)

    def test_hoeherer_wert_zaehlt(self):
        assert merken(tag=HEUTE, max_c=20.0, heute=HEUTE, wert=22.5) == (HEUTE, 22.5)

    def test_neuer_tag_faengt_neu_an(self):
        assert merken(tag=self.GESTERN, max_c=28.0, heute=HEUTE, wert=14.0) == (HEUTE, 14.0)

    def test_fehlschlag_behaelt_heutigen_wert(self):
        assert merken(tag=HEUTE, max_c=20.0, heute=HEUTE, wert=None) == (HEUTE, 20.0)

    def test_fehlschlag_loescht_vortag(self):
        assert merken(tag=self.GESTERN, max_c=28.0, heute=HEUTE, wert=None) == (None, None)

    def test_erster_abruf(self):
        assert merken(tag=None, max_c=None, heute=HEUTE, wert=19.0) == (HEUTE, 19.0)
