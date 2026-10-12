"""UC12: keine Kühlung bei Heizbetrieb, keine Hitze aus Messausreißern (v0.20.17).

Am 11.10.2026 um 21:01 und am 12.10. um 09:12 wollte UC12 bei 3–5 °C draußen
kühlen. Die FWT heizte mit 50 °C Zuluft. Ein ~10-min-Zyklus der Wärmepumpe
(Kompressor 4000 → 5400 U/min, Zuluft 50 → 34 °C) trieb den Abluftfühler von
24,0 auf 26,2 °C, die Räume blieben bei 21–23,6 °C. Der Trend (+1,3 °C/h)
senkte die Hitze-Schwelle auf 25,0 °C, der Hitze-Zweig brach die
Expensive-Sperre und schaltete ein; beide Male wurde von Hand ausgeschaltet.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from conftest import const, forecast

cool_decision = forecast.cool_decision
anlage_heizt = forecast.anlage_heizt
hitze_uhr = forecast.hitze_uhr

BERLIN = timezone(timedelta(hours=2))
DELTA = const.COOL_HEIZBETRIEB_DELTA_K
DAUER = const.COOL_HEAT_MIN_DAUER_MIN


def entscheide(**over):
    """UC12-Entscheidung mit den Werten vom 12.10. 09:12 als Grundlage."""
    args = {
        "abluft_c": 26.1,
        "trigger_c": 24.0,
        "heat_c": 25.0,          # 25,5 minus Trend-Korrektur
        "off_c": 23.0,
        "hysteresis_c": const.COOL_ABLUFT_HYSTERESE_C,
        "pv_surplus_w": 0,
        "pv_min_w": const.PV_COOLING_MIN_W,
        "pv_band_w": const.COOL_PV_HYSTERESE_W,
        "pv_entry_delta_c": const.COOL_PV_ENTRY_DELTA_C,
        "spread_eur": 0.20,
        "spread_threshold_eur": const.SMART_SPREAD_THRESHOLD_EUR,
        "in_cheapest_4h": False,
        "expensive": True,
        "price_level": "very_expensive",
        "urlaub": False,
        "sleep": False,
        "cooling_on": False,
        "heat_forced": False,
        "pv_forced": False,
        "dwell_min": 999.0,
        "min_dwell_min": const.COOL_MIN_DWELL_MIN,
        "schwellen_info": "Trigger 24.0°C / Heat 25.0°C",
        "zuluft_c": 37.9,
        "frischluft_c": 5.1,
        "heizbetrieb_delta_k": DELTA,
        "hitze_dauer_min": 0.0,
        "hitze_min_dauer_min": DAUER,
    }
    args.update(over)
    return cool_decision(**args)


class TestAnlageHeizt:
    def test_normaler_heizbetrieb(self):
        assert anlage_heizt(zuluft_c=50.0, abluft_c=24.0, frischluft_c=3.9, delta_k=DELTA)

    def test_auch_mitten_im_waermepumpen_zyklus(self):
        """Tiefster Punkt am 12.10.: Zuluft 33,7 °C, Abluft 26,2 °C."""
        assert anlage_heizt(zuluft_c=33.7, abluft_c=26.2, frischluft_c=5.4, delta_k=DELTA)

    def test_heisser_sommertag_ist_kein_heizbetrieb(self):
        """Zuluft wärmer als Abluft, aber draußen heißer als drinnen."""
        assert not anlage_heizt(zuluft_c=33.0, abluft_c=26.0, frischluft_c=34.0, delta_k=DELTA)

    def test_kuehlbetrieb(self):
        assert not anlage_heizt(zuluft_c=16.0, abluft_c=25.0, frischluft_c=28.0, delta_k=DELTA)

    def test_fehlender_fuehler_sperrt_nicht(self):
        assert not anlage_heizt(zuluft_c=None, abluft_c=24.0, frischluft_c=4.0, delta_k=DELTA)
        assert not anlage_heizt(zuluft_c=50.0, abluft_c=24.0, frischluft_c=None, delta_k=DELTA)


class TestHeizbetriebSperrt:
    def test_der_vorfall_vom_12_10(self):
        e = entscheide()
        assert e.cool is False
        assert e.kind == "heizbetrieb"
        assert "Anlage heizt" in e.reason

    def test_sticht_auch_lange_hitze(self):
        """Selbst wenn die Abluft lange genug über der Schwelle läge."""
        e = entscheide(hitze_dauer_min=60.0)
        assert e.cool is False and e.kind == "heizbetrieb"

    def test_schaltet_laufende_kuehlung_ab(self):
        e = entscheide(cooling_on=True, heat_forced=True, dwell_min=1.0)
        assert e.cool is False and e.kind == "heizbetrieb"

    def test_negativprobe_ohne_neue_eingaben_kuehlt_es(self):
        """So entschied v0.20.16: Hitze, Kühlung trotz very_expensive."""
        e = entscheide(zuluft_c=None, frischluft_c=None, hitze_min_dauer_min=0.0)
        assert e.cool is True and e.kind == "hitze"


class TestHitzeBrauchtDauer:
    def test_kurzer_ausreisser_zaehlt_nicht(self):
        e = entscheide(zuluft_c=None, hitze_dauer_min=5.0)
        assert e.cool is False
        assert e.kind != "hitze"
        assert "zählt noch nicht" in e.reason

    def test_anhaltende_hitze_zaehlt(self):
        e = entscheide(zuluft_c=None, hitze_dauer_min=DAUER)
        assert e.cool is True and e.kind == "hitze"

    def test_laufende_hitze_kuehlung_haelt_ohne_neue_wartezeit(self):
        e = entscheide(
            zuluft_c=None, abluft_c=25.2, cooling_on=True, heat_forced=True,
            hitze_dauer_min=0.0,
        )
        assert e.cool is True and e.kind == "hitze"

    def test_im_schlafmodus_weiter_aus(self):
        e = entscheide(zuluft_c=None, sleep=True, hitze_dauer_min=5.0)
        assert e.cool is False and e.kind == "sleep"


class TestHitzeUhr:
    def test_der_morgen_des_12_10_im_tick_takt(self):
        """Abluft je Tick (5 min) wie am 12.10.: Spitze nur in einem Tick."""
        start = datetime(2026, 10, 12, 9, 2, tzinfo=BERLIN)
        verlauf = [24.3, 24.5, 26.1, 24.9, 24.6, 24.4]
        seit, dauern = None, []
        for i, abluft in enumerate(verlauf):
            seit, dauer = hitze_uhr(
                seit=seit, abluft_c=abluft, heat_c=25.0,
                now=start + timedelta(minutes=5 * i),
            )
            dauern.append(dauer)
        assert max(dauern) == 0.0
        assert seit is None

    def test_echte_hitze_erreicht_die_dauer(self):
        start = datetime(2026, 7, 27, 14, 0, tzinfo=BERLIN)
        seit, dauer = None, 0.0
        for i in range(5):
            seit, dauer = hitze_uhr(
                seit=seit, abluft_c=25.8, heat_c=25.5,
                now=start + timedelta(minutes=5 * i),
            )
        assert dauer == 20.0 >= DAUER

    def test_ein_tick_darunter_setzt_zurueck(self):
        t0 = datetime(2026, 7, 27, 14, 0, tzinfo=BERLIN)
        seit, _ = hitze_uhr(seit=None, abluft_c=26.0, heat_c=25.5, now=t0)
        seit, _ = hitze_uhr(seit=seit, abluft_c=25.0, heat_c=25.5,
                            now=t0 + timedelta(minutes=5))
        assert seit is None
