"""Tests der Ladepolitik (v0.20).

Die Freigabe hängt nicht mehr an Tibber-Leveln, sondern an einer gerechneten
Schwelle. Grund (Christian, 27.07.2026): eine feste Cent-Grenze altert — 20 ct
sind im Sommer günstig und werden im Winter nie erreicht, da bräuchte es 60 —
und Tibbers Level hängen am gleitenden Mittel statt am eigenen Bedarf.

Vier Regime:
  Fahrplan kippt zeitlich          → now
  Preis ≤ Einspeisevergütung       → now  (Netz billiger als eigene Sonne)
  Preis ≤ Bedarfsschwelle          → minpv
  sonst                            → pv
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import ClassVar

from conftest import const, forecast

decide = forecast.decide_charge_mode
threshold = forecast.charge_threshold_ct
PriceSlot = forecast.PriceSlot

EEG = const.EEG_VERGUETUNG_CT
SUN_MIN = const.UC6_SUN_SURPLUS_MIN_W
POWER = const.WALLBOX_POWER_KW

BASE: ClassVar[dict] = {
    "car_connected": True,
    "plan_active": False,
    "plan_at_risk": False,
    "price_ct": 30.0,
    "threshold_ct": 20.0,
    "eeg_ct": EEG,
    "pv_surplus_w": 0,
    "car_soc": 50.0,
    "limit_soc": 80,
    "pv_surplus_min_w": SUN_MIN,
}


def mode(**over) -> str:
    return decide(**{**BASE, **over}).mode


class TestSchwelle:
    def test_unter_der_schwelle_laedt(self):
        assert mode(price_ct=18.0, threshold_ct=20.0) == "minpv"

    def test_genau_auf_der_schwelle_laedt(self):
        assert mode(price_ct=20.0, threshold_ct=20.0) == "minpv"

    def test_darueber_nur_pv(self):
        assert mode(price_ct=20.1, threshold_ct=20.0) == "pv"

    def test_die_schwelle_wandert_mit(self):
        """Kern der Entscheidung: dieselben 30 ct sind mal günstig, mal nicht."""
        assert mode(price_ct=30.0, threshold_ct=20.0) == "pv"
        assert mode(price_ct=30.0, threshold_ct=55.0) == "minpv"

    def test_ohne_schwelle_nur_pv(self):
        """Ohne Preisforecast bleibt nur der Fahrplan."""
        assert mode(threshold_ct=None) == "pv"

    def test_ohne_preis_nur_pv(self):
        assert mode(price_ct=None) == "pv"


class TestEinspeiseverguetung:
    def test_unter_eeg_volle_leistung(self):
        """Netzstrom ist dort billiger als die eigene Sonne — Sonne egal."""
        assert mode(price_ct=EEG - 0.1, pv_surplus_w=0) == "now"

    def test_negativpreis_volle_leistung(self):
        """April/Mai 2026 real: −39 und −41 ct."""
        assert mode(price_ct=-40.0) == "now"

    def test_knapp_darueber_nur_minpv(self):
        assert mode(price_ct=EEG + 0.1, threshold_ct=20.0) == "minpv"


class TestFahrplan:
    def test_plan_in_gefahr_erzwingt_now(self):
        assert mode(plan_active=True, plan_at_risk=True, price_ct=60.0,
                    threshold_ct=20.0) == "now"

    def test_ohne_plan_kein_now(self):
        assert mode(plan_active=False, plan_at_risk=True, price_ct=60.0) != "now"

    def test_teurer_plan_laeuft_in_pv(self):
        """evcc kennt den Tarif und sucht die Slots selbst; minpv würde ihn
        preisunabhängig unterlaufen."""
        assert mode(plan_active=True, price_ct=40.0, threshold_ct=20.0) == "pv"

    def test_guenstig_schlaegt_plan(self):
        assert mode(plan_active=True, price_ct=15.0, threshold_ct=20.0) == "minpv"


class TestVorbedingungen:
    def test_abgesteckt_immer_pv(self):
        assert mode(car_connected=False, price_ct=-40.0) == "pv"

    def test_ueber_limit_nicht_laden(self):
        assert mode(car_soc=80.0, limit_soc=80, price_ct=5.0) == "pv"

    def test_limit_schlaegt_preis_aber_nicht_notfall(self):
        assert mode(car_soc=95.0, plan_active=True, plan_at_risk=True) == "now"


class TestBegruendungLesbar:
    def test_jede_entscheidung_hat_klartext(self):
        for price in (-40.0, 5.0, 18.0, 30.0, 60.0):
            d = decide(**{**BASE, "price_ct": price})
            assert d.reason and len(d.reason) > 8, price
            assert d.mode in ("now", "minpv", "pv")


def slots_from(prices_ct: list[float], start: datetime) -> list[PriceSlot]:
    return [
        PriceSlot(start=start + timedelta(minutes=15 * i), price=p / 100.0)
        for i, p in enumerate(prices_ct)
    ]


class TestBedarfsschwelle:
    """`charge_threshold_ct` — Schwelle aus Bedarf und Kurve statt Geschmack."""

    NOW: ClassVar[datetime] = datetime(2026, 7, 27, 10, 0, tzinfo=timezone.utc)

    def test_nimmt_den_teuersten_noetigen_slot(self):
        # 4 Slots à 15 min; bei 11 kW liefert einer 2,75 kWh
        s = slots_from([10, 20, 30, 40], self.NOW)
        assert threshold(s, needed_kwh=2.75, power_kw=POWER, now=self.NOW) == 10.0
        assert threshold(s, needed_kwh=5.5, power_kw=POWER, now=self.NOW) == 20.0

    def test_mehr_bedarf_weitet_die_schwelle(self):
        s = slots_from([10, 20, 30, 40], self.NOW)
        eng = threshold(s, needed_kwh=2.75, power_kw=POWER, now=self.NOW)
        weit = threshold(s, needed_kwh=8.25, power_kw=POWER, now=self.NOW)
        assert weit > eng

    def test_reihenfolge_egal_nur_der_preis_zaehlt(self):
        """Die günstigsten Slots werden gewählt, nicht die frühesten."""
        s = slots_from([40, 30, 20, 10], self.NOW)
        assert threshold(s, needed_kwh=2.75, power_kw=POWER, now=self.NOW) == 10.0

    def test_fenster_begrenzt_die_auswahl(self):
        s = slots_from([40, 40, 10, 10], self.NOW)
        bis = self.NOW + timedelta(minutes=30)   # nur die ersten beiden
        assert threshold(s, needed_kwh=2.75, power_kw=POWER,
                         now=self.NOW, until=bis) == 40.0

    def test_vergangene_slots_zaehlen_nicht(self):
        s = slots_from([5, 5, 30, 30], self.NOW - timedelta(minutes=30))
        assert threshold(s, needed_kwh=2.75, power_kw=POWER, now=self.NOW) == 30.0

    def test_fenster_zu_klein_nimmt_den_teuersten(self):
        """Reicht das Fenster nicht, ist jeder Slot nötig — nicht None."""
        s = slots_from([10, 20], self.NOW)
        assert threshold(s, needed_kwh=100.0, power_kw=POWER, now=self.NOW) == 20.0

    def test_ohne_slots_keine_schwelle(self):
        assert threshold([], needed_kwh=5.0, power_kw=POWER, now=self.NOW) is None

    def test_kein_bedarf_keine_schwelle(self):
        s = slots_from([10, 20], self.NOW)
        assert threshold(s, needed_kwh=0.0, power_kw=POWER, now=self.NOW) is None

    def test_untergrenze_wird_respektiert(self):
        s = slots_from([2, 3, 4], self.NOW)
        got = threshold(s, needed_kwh=2.75, power_kw=POWER, now=self.NOW,
                        floor_ct=EEG)
        assert got == EEG


class TestRealeKurve:
    """27.07.2026: flacher Mittagsboden bei 17,9 ct, Tagesmittel 27,1."""

    KURVE: ClassVar[list[float]] = (
        [32] * 16 + [27] * 8 + [18] * 24 + [20] * 8 + [30] * 16
    )
    NOW: ClassVar[datetime] = datetime(2026, 7, 27, 6, 0, tzinfo=timezone.utc)

    def test_kleiner_bedarf_landet_im_billigen_block(self):
        s = slots_from(self.KURVE, self.NOW)
        # 26 → 35 % bei 63 kWh ≈ 5,7 kWh
        got = threshold(s, needed_kwh=5.7, power_kw=POWER, now=self.NOW)
        assert got == 18.0, f"erwartet den billigen Block, war {got}"

    def test_grosser_bedarf_bleibt_im_block_wenn_er_reicht(self):
        """20 → 80 % sind 37,8 kWh = 14 Slots. Der Mittagsblock hat 24 Slots
        (66 kWh) — die Schwelle muss also NICHT höher greifen. Erst geprüft,
        als die umgekehrte Erwartung im Test scheiterte."""
        s = slots_from(self.KURVE, self.NOW)
        assert threshold(s, needed_kwh=37.8, power_kw=POWER, now=self.NOW) == 18.0

    def test_schmaler_billigblock_weitet_die_schwelle(self):
        kurve = [32] * 16 + [18] * 4 + [24] * 12 + [30] * 16
        s = slots_from(kurve, self.NOW)
        # 4 billige Slots = 11 kWh; für 20 kWh muss der 24-ct-Bereich mit rein
        assert threshold(s, needed_kwh=11.0, power_kw=POWER, now=self.NOW) == 18.0
        assert threshold(s, needed_kwh=20.0, power_kw=POWER, now=self.NOW) == 24.0


class TestGrundplan:
    def test_grundplan_ist_gesetzt_und_moderat(self):
        """Christian, 27.07.2026: Grundplan ja, aber nur 50 %."""
        assert const.BASELINE_SOC == 50
        assert 0 <= const.BASELINE_READY_HOUR <= 23

    def test_grundplan_unter_dem_ladelimit(self):
        """Sonst würde er den Termin-Fahrplan dauerhaft überschreiben."""
        assert const.BASELINE_SOC < const.SOC_TARGET
