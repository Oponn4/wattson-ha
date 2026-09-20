"""Tests der UC12-Entscheidung als Ganzes (v0.20.9).

Vorfall 19.09.2026, drei Befunde an einem Tag:

* **Sägezahn am PV-Zweig.** Der PV-Überschuss pendelte an einem Wolkentag um
  die 1500-W-Schwelle, die Freigabe kippte zwischen 10:46 und 14:02 zehnmal im
  5-min-Tick-Takt. Der Kompressor kam bei keinem dieser Fenster zum Laufen.
* **Erbschleichendes Force-Recht.** `heat_active` bekam den *Schalter* als
  Totband-Gedächtnis. Damit wurde jede aus PV- oder Preisgründen laufende
  Kühlung ab `heat_c − 1 K` zur „Hitze"-Kühlung — und Hitze bricht die
  Expensive-Sperre. Um 19:17 loggte Wattson „Hitze 24.8°C ≥ 25.5°C": verglichen
  wurde gegen 24,5. Echte Hitze gab es an dem Tag nie (Tagesmax 25,1 °C).
* **Einfrieren im Schlafmodus.** Das Gate im Coordinator kehrt vor allen
  Handlern zurück. Eine um 22:49 offene Freigabe stand deshalb bis 09:16 des
  Folgetags — die Entscheidung „Schlafmodus → aus" wurde nie ausgeführt.
"""
from __future__ import annotations

from pathlib import Path
from typing import ClassVar

import pytest
from conftest import const, forecast

cool_decision = forecast.cool_decision

TRIGGER = 24.0          # Schwellen des 19.09.: Außen-Forecast max 20 °C
HEAT = 25.5
OFF = TRIGGER - const.COOL_ABLUFT_HYSTERESE_C
PV_MIN = const.PV_COOLING_MIN_W
PV_BAND = const.COOL_PV_HYSTERESE_W
DWELL = const.COOL_MIN_DWELL_MIN


def entscheide(**over):
    """UC12-Entscheidung mit den Werten des 19.09. als Grundlage."""
    args = {
        "abluft_c": 24.0,
        "trigger_c": TRIGGER,
        "heat_c": HEAT,
        "off_c": OFF,
        "hysteresis_c": const.COOL_ABLUFT_HYSTERESE_C,
        "pv_surplus_w": 0,
        "pv_min_w": PV_MIN,
        "pv_band_w": PV_BAND,
        "spread_eur": 0.20,
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
        "min_dwell_min": DWELL,
        "schwellen_info": "Trigger 24.0°C / Heat 25.5°C",
    }
    args.update(over)
    return cool_decision(**args)


class TestHitzeHaengtAmGrundNichtAmSchalter:
    """Der Kern des 19.09.: wer läuft, ist nicht automatisch heiß."""

    def test_pv_kuehlung_erbt_kein_force_recht(self):
        """14:02 aus PV an, 19:17 teuer, Abluft 24,8 — muss aus."""
        d = entscheide(
            abluft_c=24.8, cooling_on=True, heat_forced=False,
            expensive=True, price_level="expensive", pv_surplus_w=0,
        )
        assert d.cool is False
        assert d.kind == "hysterese_gebrochen"

    def test_echte_hitze_rastet_ein(self):
        d = entscheide(abluft_c=HEAT, cooling_on=False, heat_forced=False)
        assert d.cool is True
        assert d.kind == "hitze"
        assert d.heat_forced is True

    def test_eingerastete_hitze_haelt_im_totband(self):
        """Der Fall, für den das Totband 27.07. gebaut wurde — bleibt erhalten."""
        d = entscheide(
            abluft_c=24.8, cooling_on=True, heat_forced=True,
            expensive=True, price_level="expensive",
        )
        assert d.cool is True
        assert d.kind == "hitze"
        assert d.heat_forced is True

    def test_unter_dem_totband_faellt_das_force_recht(self):
        d = entscheide(
            abluft_c=HEAT - const.COOL_ABLUFT_HYSTERESE_C - 0.1,
            cooling_on=True, heat_forced=True,
            expensive=True, price_level="expensive",
        )
        assert d.kind != "hitze"
        assert d.heat_forced is False

    def test_tagesmaximum_des_19_09_war_keine_hitze(self):
        """25,1 °C bei geschlossenem Merker — die Schwelle lag bei 25,5."""
        d = entscheide(abluft_c=25.1, cooling_on=True, heat_forced=False)
        assert d.kind != "hitze"

    def test_band_rutscht_nie_unter_den_kuehl_trigger(self):
        """Review-Fund zu v0.20.9: `heat_c` ist adaptiv.

        Trend-Korrektur (C) drückt Heat auf 25,0. Mit vollem 1-K-Band läge die
        verglichene Schwelle bei 24,0 — auf dem Trigger, also würde der Zweig,
        der die Expensive-Sperre bricht, schon bei normalem Kühlbedarf losgehen.
        """
        d = entscheide(abluft_c=24.2, heat_c=25.0, cooling_on=True,
                       heat_forced=True, expensive=True,
                       price_level="very_expensive")
        assert d.heat_limit_c == pytest.approx(24.5)
        assert d.heat_limit_c > TRIGGER
        assert d.kind == "hysterese_gebrochen"

    def test_trend_korrektur_bleibt_wirksam(self):
        """Gegenprobe zur naheliegenden Kappe an `heat_c` statt am Band.

        `max(heat, trigger + 0.5 + Hysterese)` hätte Heat wieder auf 25,5
        gehoben — Korrektur C wäre bei Trigger 24,0 toter Code gewesen.
        """
        d = entscheide(abluft_c=25.0, heat_c=25.0, cooling_on=False,
                       heat_forced=False)
        assert d.kind == "hitze"
        assert d.heat_limit_c == pytest.approx(25.0)

    def test_kein_band_wenn_heat_dicht_am_trigger_liegt(self):
        d = entscheide(abluft_c=24.9, heat_c=25.0, trigger_c=24.5,
                       cooling_on=True, heat_forced=True)
        assert d.heat_limit_c == pytest.approx(25.0)
        assert d.kind != "hitze"

    def test_nach_neustart_kein_force_recht(self):
        """`heat_forced` kommt aus dem RAM; nach Restart False.

        Am 19.09. startete HA um 19:17 neu und meldete im ersten Tick sofort
        wieder „Hitze" — weil der Schalter, nicht der Grund, das Gedächtnis war.
        """
        d = entscheide(
            abluft_c=24.8, cooling_on=True, heat_forced=False,
            expensive=True, price_level="expensive",
        )
        assert d.kind == "hysterese_gebrochen"


class TestMeldungNenntDieVerglicheneSchwelle:
    def test_im_totband_steht_die_effektive_schwelle(self):
        d = entscheide(abluft_c=24.8, cooling_on=True, heat_forced=True)
        assert "≥ 24.5°C" in d.reason
        assert "Totband" in d.reason

    def test_die_alte_falschaussage_kommt_nicht_mehr_vor(self):
        """„Hitze 24.8°C ≥ 25.5°C" war arithmetisch falsch."""
        d = entscheide(abluft_c=24.8, cooling_on=True, heat_forced=True)
        assert "24.8°C ≥ 25.5°C" not in d.reason

    def test_ohne_totband_steht_die_nackte_schwelle(self):
        d = entscheide(abluft_c=25.6, cooling_on=False, heat_forced=False)
        assert "≥ 25.5°C" in d.reason
        assert "Totband" not in d.reason

    def test_pv_totband_steht_in_der_begruendung(self):
        d = entscheide(abluft_c=24.2, cooling_on=True, pv_forced=True,
                       pv_surplus_w=PV_MIN - 100)
        assert d.kind == "pv"
        assert f"{PV_MIN - PV_BAND}W" in d.reason
        assert "Totband" in d.reason


class TestPvTotband:
    def test_einstieg_bleibt_an_der_nackten_schwelle(self):
        assert entscheide(abluft_c=24.2, pv_surplus_w=PV_MIN).kind == "pv"
        assert entscheide(abluft_c=24.2, pv_surplus_w=PV_MIN - 1).kind != "pv"

    def test_pv_zweig_setzt_seinen_merker(self):
        assert entscheide(abluft_c=24.2, pv_surplus_w=PV_MIN).pv_forced is True

    def test_ausstieg_erst_unter_dem_band(self):
        laeuft = {"abluft_c": 23.5, "cooling_on": True, "pv_forced": True,
                  "dwell_min": 999.0}
        assert entscheide(pv_surplus_w=PV_MIN - PV_BAND, **laeuft).kind == "pv"
        assert entscheide(pv_surplus_w=PV_MIN - PV_BAND - 1, **laeuft).kind != "pv"

    def test_band_gilt_nur_bei_laufendem_pv_zweig(self):
        """Sonst würde die Freigabe schon unter der Schwelle aufgehen."""
        d = entscheide(abluft_c=23.5, cooling_on=False, pv_forced=False,
                       pv_surplus_w=PV_MIN - PV_BAND)
        assert d.kind != "pv"

    def test_preis_kuehlung_erbt_das_pv_band_nicht(self):
        """Review-Fund zu v0.20.9: dasselbe Erbe wie beim Hitze-Zweig.

        Die Freigabe läuft aus `cheapest_4h`/Hysterese, der Überschuss hat die
        1500 W nie erreicht. Mit `active=cooling_on` hätte der gesenkte
        Einstieg (1250 W) gegriffen und die Kühlung durch das teure Fenster
        gehalten — genau die Sperre, die `heat_forced` schützen soll.
        """
        d = entscheide(
            abluft_c=24.2, cooling_on=True, pv_forced=False,
            pv_surplus_w=PV_MIN - PV_BAND, expensive=True,
            price_level="very_expensive",
        )
        assert d.kind == "hysterese_gebrochen"
        assert d.cool is False

    def test_merker_ueberlebt_den_preis_zweig_nicht(self):
        """Wer nicht wegen PV läuft, trägt den PV-Merker auch nicht weiter."""
        d = entscheide(abluft_c=24.2, cooling_on=True, in_cheapest_4h=True,
                       spread_eur=0.05)
        assert d.kind == "cheapest"
        assert d.pv_forced is False


class TestMindestVerweildauer:
    def test_weicher_wechsel_wird_gehalten(self):
        d = entscheide(abluft_c=23.5, cooling_on=True, dwell_min=5.0)
        assert d.cool is True
        assert d.kind == "dwell"
        assert "erst 5 von 20 min" in d.reason

    def test_nach_ablauf_wird_geschaltet(self):
        d = entscheide(abluft_c=23.5, cooling_on=True, dwell_min=DWELL)
        assert d.cool is False
        assert d.kind == "aus"

    def test_unbekanntes_alter_haelt_nichts_auf(self):
        """Nach Restart ist `last_changed` die Restore-Zeit — lieber schalten."""
        d = entscheide(abluft_c=23.5, cooling_on=True, dwell_min=None)
        assert d.cool is False

    @pytest.mark.parametrize("over,erwartet", [
        ({"urlaub": True}, "urlaub"),
        ({"sleep": True}, "sleep"),
        ({"abluft_c": OFF}, "unter_off"),
    ])
    def test_harte_aus_zweige_ignorieren_die_verweildauer(self, over, erwartet):
        d = entscheide(cooling_on=True, dwell_min=1.0, **over)
        assert d.cool is False, f"{erwartet} muss sofort greifen"
        assert d.kind == erwartet

    def test_hitze_schaltet_sofort_ein(self):
        """Komfort wartet nicht 20 Minuten."""
        d = entscheide(abluft_c=HEAT, cooling_on=False, dwell_min=1.0)
        assert d.cool is True
        assert d.kind == "hitze"

    def test_gehaltener_zustand_erbt_kein_force_recht(self):
        """23,5 °C: Totband gerissen, Zweig „aus" — gehalten, aber ohne Merker.

        Der gehaltene Zustand darf den Hitze-Merker nicht konservieren, sonst
        lebt das Force-Recht über die Haltezeit hinaus weiter.
        """
        d = entscheide(abluft_c=23.5, cooling_on=True, heat_forced=True,
                       dwell_min=1.0)
        assert d.kind == "dwell"
        assert d.cool is True          # gehalten, aber …
        assert d.heat_forced is False  # … nicht mehr als Hitze

    def test_expensive_sperre_wird_nicht_gehalten(self):
        """Review-Fund zu v0.20.9: Schutz ist keine Optimierung.

        Unter der Kappe hätte die Sperre bis zu vier Ticks Verzug — 20 Minuten
        Import zum Tageshöchstpreis, um einen Schaltvorgang zu sparen.
        """
        d = entscheide(abluft_c=24.4, cooling_on=True, expensive=True,
                       price_level="very_expensive", dwell_min=1.0)
        assert d.kind == "hysterese_gebrochen"
        assert d.cool is False

    def test_expensive_sperre_ist_kein_weicher_zweig(self):
        assert "hysterese_gebrochen" not in forecast.SOFT_COOL_KINDS

    def test_gehaltener_zustand_erbt_auch_kein_pv_band(self):
        """Gehalten-aus, während PV im Band liegt: kein Merker, kein Einstieg.

        Sonst rastet der gesenkte PV-Einstieg ein, obwohl nichts läuft.
        """
        d = entscheide(abluft_c=24.2, cooling_on=False, pv_forced=True,
                       pv_surplus_w=PV_MIN - PV_BAND, dwell_min=1.0)
        assert d.kind == "dwell"
        assert d.cool is False
        assert d.pv_forced is False


class TestSchlafmodus:
    def test_schlaf_schlaegt_hitze(self):
        d = entscheide(abluft_c=26.0, sleep=True, cooling_on=True)
        assert d.cool is False
        assert d.kind == "hitze_sleep"
        assert d.heat_forced is False

    def test_schlaf_schlaegt_pv(self):
        d = entscheide(abluft_c=24.5, sleep=True, cooling_on=True,
                       pv_surplus_w=3000)
        assert d.cool is False

    @pytest.mark.parametrize("abluft", [22.0, 23.5, 24.0, 24.8, 25.1, 27.0])
    @pytest.mark.parametrize("cooling_on", [False, True])
    @pytest.mark.parametrize("heat_forced", [False, True])
    def test_im_schlaf_geht_nie_etwas_an(self, abluft, cooling_on, heat_forced):
        """Invariante, auf die sich `sleep_only_off` im Coordinator stützt.

        Der Riegel dort ist trotzdem drin: er hält, wenn diese Invariante
        später durch einen neuen Zweig verletzt wird.
        """
        d = entscheide(
            abluft_c=abluft, sleep=True, cooling_on=cooling_on,
            heat_forced=heat_forced, pv_surplus_w=3000, in_cheapest_4h=True,
            spread_eur=0.05,
        )
        assert d.cool is False


class TestUnveraenderteZweige:
    """Was vor v0.20.9 richtig war, muss richtig bleiben."""

    def test_urlaub_schlaegt_alles(self):
        d = entscheide(abluft_c=27.0, urlaub=True, cooling_on=True,
                       heat_forced=True)
        assert d.cool is False
        assert d.kind == "urlaub"

    def test_unter_off_schwelle_aus(self):
        d = entscheide(abluft_c=OFF - 0.1, cooling_on=True)
        assert d.cool is False
        assert d.kind == "unter_off"

    def test_cheapest_mit_kleinem_spread_kuehlt(self):
        d = entscheide(abluft_c=24.2, in_cheapest_4h=True, spread_eur=0.05)
        assert d.cool is True
        assert d.kind == "cheapest"

    def test_cheapest_mit_grossem_spread_ueberlaesst_uc10(self):
        d = entscheide(abluft_c=24.2, in_cheapest_4h=True, spread_eur=0.20)
        assert d.cool is False
        assert d.kind == "cheapest_uc10"

    def test_hysterese_haelt_bei_normalem_preis(self):
        d = entscheide(abluft_c=24.2, cooling_on=True)
        assert d.cool is True
        assert d.kind == "hysterese"

    def test_hysterese_bricht_bei_teuer(self):
        d = entscheide(abluft_c=24.2, cooling_on=True, expensive=True,
                       price_level="very_expensive")
        assert d.cool is False
        assert d.kind == "hysterese_gebrochen"


# ── Nachgestellter Verlauf 19.09.2026, 10:40–14:05 ────────────────────────────
# PV-Überschuss: 5-min-Mittel aus den Recorder-Statistiken von
# `sensor.pv_uberschuss_der_letzen_15_minuten`. Abluft: gemessene Werte von
# `sensor.proxon_fwt_temperatur_t07_abluft`, aufs 5-min-Raster gelegt.
# Preis-Level war den ganzen Zeitraum `very_cheap`, die cheapest_4h-Zweige
# feuerten nicht — sonst hätte die Freigabe nicht zwischendurch geschlossen.
PV_VERLAUF = [
    1159, 1775, 1477, 1428, 1327, 2025, 2159, 2271, 2648, 2498, 2110, 721,
    840, 2090, 2475, 2586, 3074, 2276, 1701, 910, 971, 1260, 1732, 2154,
    1557, 1607, 1809, 1920, 1620, 1511, 1167, 130, 347, 448, 1489, 1016,
    33, 154, 652, 1161, 3117, 3156,
]
ABLUFT_VERLAUF = [
    23.8, 23.8, 23.8, 23.7, 23.7, 23.6, 23.6, 23.6, 23.6, 23.7, 23.7, 23.7,
    23.8, 23.8, 23.8, 23.9, 23.9, 23.9, 23.9, 23.9, 23.9, 23.9, 23.9, 23.9,
    23.9, 23.9, 23.9, 24.0, 24.0, 24.0, 24.0, 24.0, 24.1, 24.2, 24.2, 24.2,
    24.3, 24.3, 24.3, 24.3, 24.4, 24.5,
]
TICK_MIN = 5.0


def _replay(*, pv_band_w: int, min_dwell_min: float) -> tuple[int, list[float]]:
    """Verlauf durchspielen. Returns (Schaltvorgänge, Haltezeiten in min).

    Die erste Haltezeit zählt nicht mit — vor dem ersten Tick gibt es keine.
    """
    assert len(PV_VERLAUF) == len(ABLUFT_VERLAUF)
    cooling, heat_forced, pv_forced = False, False, False
    dwell, wechsel = 999.0, 0
    haltezeiten: list[float] = []
    for pv, abluft in zip(PV_VERLAUF, ABLUFT_VERLAUF):
        d = entscheide(
            abluft_c=abluft, pv_surplus_w=pv, pv_band_w=pv_band_w,
            cooling_on=cooling, heat_forced=heat_forced, pv_forced=pv_forced,
            dwell_min=dwell, min_dwell_min=min_dwell_min,
            price_level="very_cheap",
        )
        if d.cool != cooling:
            wechsel += 1
            if dwell < 900:
                haltezeiten.append(dwell)
            dwell = TICK_MIN
        else:
            dwell += TICK_MIN
        # Wie im Coordinator: ein Merker gilt nur, solange die Freigabe offen ist
        cooling = d.cool
        heat_forced = d.heat_forced and cooling
        pv_forced = d.pv_forced and cooling
    return wechsel, haltezeiten


class TestVerlauf1909:
    """Was der Fix am gemessenen Tag ausrichtet — und was nicht.

    Er beseitigt die Schaltvorgänge nicht, er begrenzt ihre Rate. Der
    PV-Überschuss war an dem Tag über 20 Minuten lang weg (721/840 W um 11:35,
    unter 500 W ab 13:15) — dann ist Ausschalten die richtige Entscheidung und
    kein Sägezahn. Was weg muss, ist der 5-Minuten-Takt.
    """

    def test_alte_logik_saegt(self):
        """Gegenprobe ohne Band und ohne Kappe — der gemessene Tag.

        Real waren es zehn Schaltvorgänge zwischen 10:46 und 14:02; der Nachbau
        rechnet mit 5-min-Mitteln statt Momentanwerten und kommt auf neun.
        """
        wechsel, haltezeiten = _replay(pv_band_w=0, min_dwell_min=0.0)
        assert wechsel >= 8
        assert min(haltezeiten) == TICK_MIN, "ohne Kappe fehlt der Sägezahn"

    def test_kein_wechsel_schneller_als_die_kappe(self):
        _, haltezeiten = _replay(pv_band_w=PV_BAND, min_dwell_min=DWELL)
        assert min(haltezeiten) >= DWELL

    def test_weniger_wechsel_als_vorher(self):
        neu, _ = _replay(pv_band_w=PV_BAND, min_dwell_min=DWELL)
        alt, _ = _replay(pv_band_w=0, min_dwell_min=0.0)
        assert neu < alt

    def test_band_allein_laesst_10_minuten_takte_zu(self):
        """Die Wolkenlöcher am 19.09. waren tiefer als 250 W — daher die Kappe."""
        _, haltezeiten = _replay(pv_band_w=PV_BAND, min_dwell_min=0.0)
        assert min(haltezeiten) < DWELL


# ── Abendverlauf 19.09.2026, 19:00–20:55 ──────────────────────────────────────
# Gemessene Abluft, PV war weg. Die Freigabe lief seit 14:02 (PV-Zweig) und
# stand bis 20:56, als Christian sie von Hand schloss.
ABEND_ABLUFT = [
    24.9, 24.8, 24.8, 24.9, 24.8, 24.8, 24.8, 24.8, 24.8, 24.8, 24.9, 24.9,
    25.0, 25.1, 25.1, 24.9, 24.9, 24.7, 24.7, 24.6, 24.6, 24.5, 24.5, 24.4,
]


def _replay_abend(*, merker_ist_der_schalter: bool, price_level: str) -> int:
    """Abend durchspielen, Ticks mit offener Freigabe zählen.

    `merker_ist_der_schalter=True` stellt die Bindung vor v0.20.9 nach
    (`heat_forced` bekam `s.cool_enable_on`) — genau die Zeile, die den Fehler
    trug. Alles andere bleibt gleich.
    """
    cooling, heat_forced, gekuehlt = True, False, 0
    for abluft in ABEND_ABLUFT:
        d = entscheide(
            abluft_c=abluft, pv_surplus_w=0, cooling_on=cooling,
            heat_forced=cooling if merker_ist_der_schalter else heat_forced,
            expensive=price_level in const.UC12_EXPENSIVE_LEVELS,
            price_level=price_level, dwell_min=999.0,
        )
        cooling = d.cool
        heat_forced = d.heat_forced and cooling
        gekuehlt += 1 if cooling else 0
    return gekuehlt


class TestAbend1909:
    """Die eigentliche Rechnung: kühlt UC12 ins teure Fenster hinein?

    Das Preis-Level stand an dem Abend auf `normal`, obwohl die Stunde um 19:45
    **33,94 ct** kostete — die Expensive-Sperre hätte also ohnehin nicht
    gegriffen. Deshalb hier beide Läufe: mit dem gemessenen Level und
    kontrafaktisch mit `expensive`, um die Sperre selbst zu prüfen.
    """

    def test_alte_bindung_kuehlt_den_ganzen_abend_durch(self):
        """Gegenprobe. Abluft ≥ 24,5 → Totband → „Hitze" → Sperre gebrochen."""
        assert _replay_abend(
            merker_ist_der_schalter=True, price_level="very_expensive",
        ) >= 20

    def test_neue_bindung_schaltet_sofort_ab(self):
        assert _replay_abend(
            merker_ist_der_schalter=False, price_level="very_expensive",
        ) == 0

    def test_mit_dem_gemessenen_level_laeuft_sie_weiter(self):
        """Nicht der Fix ist hier die Lücke, sondern die Teuer-Definition.

        Bei `normal` hält die Hysterese die Kühlung — korrekt nach der
        aktuellen Regel. Dass 33,94 ct als `normal` gelten, ist ein eigener
        offener Punkt (absolute Grenze / Tages-Perzentil).
        """
        assert _replay_abend(
            merker_ist_der_schalter=False, price_level="normal",
        ) == len(ABEND_ABLUFT)


class TestBindungImCoordinator:
    """Wächter auf die Aufrufstelle — dort saß der Fehler von v0.20.8.

    `coordinator.py` importiert Home Assistant und ist in dieser Suite nicht
    ladbar (siehe `conftest.py`). Eine reine Logikprüfung kann den Fehler aber
    nicht finden: die Funktion war korrekt, das Argument war falsch. Also wird
    die Bindung im Quelltext geprüft — grob, aber genau an der Stelle, die
    zweimal stillschweigend kippen konnte.
    """

    QUELLE: ClassVar[str] = (
        Path(__file__).resolve().parents[1]
        / "custom_components" / "wattson" / "coordinator.py"
    ).read_text(encoding="utf-8")

    def test_merker_kommt_aus_dem_vortick_und_dem_gelesenen_schalter(self):
        assert "heat_forced=self._prev.cool_heat_forced and s.cool_enable_on" \
            in self.QUELLE
        assert "pv_forced=self._prev.cool_pv_forced and s.cool_enable_on" \
            in self.QUELLE

    def test_der_schalter_ist_nicht_mehr_das_gedaechtnis(self):
        """Die Form des alten Fehlers darf nicht zurückkommen."""
        assert "heat_forced=s.cool_enable_on" not in self.QUELLE
        assert "pv_forced=s.cool_enable_on" not in self.QUELLE
        assert "currently_cooling" not in self.QUELLE

    def test_verweildauer_zaehlt_den_eigenen_write(self):
        """Nicht `last_changed`: das setzt jeder `unavailable`-Blip zurück."""
        assert "dwell_min=self._uc12_dwell_minutes(now)" in self.QUELLE

    def test_schlafmodus_ruft_uc12_nur_zum_ausschalten(self):
        assert "sleep_only_off=True" in self.QUELLE
