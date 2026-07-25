"""Tests für die preisgeankerte Anstecke-Deadline (UC2 Plug-in-Reminder).

Die Preiskurve stammt aus dem echten Tibber-Forecast vom 25.07.2026 — der Tag,
an dem eine „N Stunden vor Abfahrt"-Regel versagt hätte.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from conftest import forecast

PriceSlot = forecast.PriceSlot
plan_charge_window = forecast.plan_charge_window
pull_out_of_quiet_hours = forecast.pull_out_of_quiet_hours
cost_from = forecast.cost_from

BERLIN = timezone(timedelta(hours=2))

# Stündliche ct/kWh vom 25.07.2026, 15:00 → 26.07. 11:45 (Abfahrt 11:30)
HOURLY_CT = {
    (25, 15): 17.5, (25, 16): 17.8, (25, 17): 18.0, (25, 18): 20.6,
    (25, 19): 34.5, (25, 20): 37.4, (25, 21): 38.7, (25, 22): 38.6,
    (25, 23): 37.8,
    (26, 0): 35.6, (26, 1): 35.8, (26, 2): 35.3, (26, 3): 35.7,
    (26, 4): 36.3, (26, 5): 34.6, (26, 6): 34.0, (26, 7): 32.3,
    (26, 8): 31.2, (26, 9): 29.3, (26, 10): 20.7, (26, 11): 18.0,
}


def build_slots() -> list[PriceSlot]:
    slots = []
    for (day, hour), ct in sorted(HOURLY_CT.items()):
        for quarter in range(4):
            slots.append(PriceSlot(
                start=datetime(2026, 7, day, hour, quarter * 15, tzinfo=BERLIN),
                price=ct / 100.0,
            ))
    return slots


SLOTS = build_slots()
NOW = datetime(2026, 7, 25, 15, 20, tzinfo=BERLIN)
DEPARTURE = datetime(2026, 7, 26, 11, 30, tzinfo=BERLIN)
ENERGY_KWH = 27.4    # 53% → 90% bei 63 kWh, evccs eigene Zahl
POWER_KW = 11.04     # 3×16 A


class TestPlanChargeWindow:
    def test_deadline_liegt_am_abend_nicht_kurz_vor_abfahrt(self):
        """Kernaussage: Deadline ~18 Uhr, also 17,5 h vor Abfahrt."""
        got = plan_charge_window(
            SLOTS, NOW, DEPARTURE, ENERGY_KWH, POWER_KW, tolerance_eur_per_kwh=0.02
        )
        assert got is not None
        assert got.price_deadline is not None
        assert got.price_deadline.day == 25
        assert 15 <= got.price_deadline.hour <= 18, got.price_deadline
        # …und damit deutlich vor jeder "6 h vorher"-Regel (die wäre 05:30)
        stunden_vor_abfahrt = (DEPARTURE - got.price_deadline).total_seconds() / 3600
        assert stunden_vor_abfahrt > 15

    def test_sechs_stunden_regel_kostet_aufpreis(self):
        """Gegenprobe zur „6 h vorher"-Regel: 05:30 anstecken kostet mehr.

        Der Aufpreis (~1,61 EUR) ist kleiner als der reine Nachtpreis vermuten
        lässt, weil ein tarif-bewusstes evcc ab 05:30 noch das billige
        Morgenfenster 10:00–11:30 mitnimmt. Nicht dramatisch, aber vermeidbar —
        und die Deadline liegt trotzdem 17,5 h früher als die Regel behauptet.
        """
        got = plan_charge_window(
            SLOTS, NOW, DEPARTURE, ENERGY_KWH, POWER_KW, tolerance_eur_per_kwh=0.02
        )
        assert got is not None
        spaet = cost_from(
            SLOTS, datetime(2026, 7, 26, 5, 30, tzinfo=BERLIN), DEPARTURE,
            got.slots_needed, POWER_KW,
        )
        assert spaet is not None
        mehrkosten = got.extra_cost_eur(spaet)
        assert 1.4 < mehrkosten < 1.9, f"{mehrkosten:.2f} EUR Aufpreis"

    def test_blindes_nachtladen_ist_das_teure_szenario(self):
        """Ohne Tarif-Bewusstsein (mode=now abends) wird es richtig teuer."""
        got = plan_charge_window(
            SLOTS, NOW, DEPARTURE, ENERGY_KWH, POWER_KW, tolerance_eur_per_kwh=0.02
        )
        assert got is not None
        nacht_ct = [35.6, 35.8, 35.3, 35.7, 36.3, 34.6, 34.0, 32.3, 31.2, 29.3]
        kwh_pro_slot = POWER_KW * forecast.SLOT_HOURS
        blind = sum(ct / 100 * kwh_pro_slot for ct in nacht_ct)
        assert got.extra_cost_eur(blind) > 4.0

    def test_slots_needed_passt_zur_energie(self):
        got = plan_charge_window(
            SLOTS, NOW, DEPARTURE, ENERGY_KWH, POWER_KW, tolerance_eur_per_kwh=0.02
        )
        assert got is not None
        # 27,4 kWh / (11,04 kW × 0,25 h) = 9,9 → 10 Slots = 2,5 h
        assert got.slots_needed == 10

    def test_bester_preis_entspricht_billigfenster(self):
        got = plan_charge_window(
            SLOTS, NOW, DEPARTURE, ENERGY_KWH, POWER_KW, tolerance_eur_per_kwh=0.02
        )
        assert got is not None
        # 10 Slots × 2,76 kWh × ~0,178 EUR ≈ 4,9 EUR
        assert 4.5 < got.best_cost_eur < 5.3

    def test_latest_feasible_vor_abfahrt(self):
        got = plan_charge_window(
            SLOTS, NOW, DEPARTURE, ENERGY_KWH, POWER_KW, tolerance_eur_per_kwh=0.02
        )
        assert got is not None
        assert got.latest_feasible is not None
        # 10 Slots = 2,5 h → spätestens 09:00 anstecken
        assert got.latest_feasible <= DEPARTURE - timedelta(hours=2.5)

    def test_grosse_toleranz_schiebt_deadline_nach_hinten(self):
        eng = plan_charge_window(
            SLOTS, NOW, DEPARTURE, ENERGY_KWH, POWER_KW, tolerance_eur_per_kwh=0.0
        )
        weit = plan_charge_window(
            SLOTS, NOW, DEPARTURE, ENERGY_KWH, POWER_KW, tolerance_eur_per_kwh=0.20
        )
        assert eng is not None and weit is not None
        assert weit.price_deadline >= eng.price_deadline

    def test_kleine_energiemenge_ist_entspannt(self):
        """2 kWh gehen auch morgens früh noch günstig — späte Deadline."""
        got = plan_charge_window(
            SLOTS, NOW, DEPARTURE, 2.0, POWER_KW, tolerance_eur_per_kwh=0.02
        )
        assert got is not None
        assert got.price_deadline is not None
        assert got.price_deadline.day == 26

    def test_abfahrt_vergangen_gibt_none(self):
        assert plan_charge_window(
            SLOTS, NOW, NOW - timedelta(hours=1), ENERGY_KWH, POWER_KW, 0.02
        ) is None

    def test_ohne_preise_gibt_none(self):
        assert plan_charge_window([], NOW, DEPARTURE, ENERGY_KWH, POWER_KW, 0.02) is None

    def test_energie_passt_nicht_mehr(self):
        """Abfahrt in 1 h, 27 kWh nötig → nicht machbar, kein Absturz."""
        got = plan_charge_window(
            SLOTS, NOW, NOW + timedelta(hours=1), ENERGY_KWH, POWER_KW, 0.02
        )
        assert got is not None
        assert got.price_deadline is None
        assert got.latest_feasible is None

    def test_truncated_wird_gemeldet(self):
        """Forecast endet vor der Abfahrt (Tibber publiziert erst ~13:00)."""
        kurz = [s for s in SLOTS if s.start.day == 25]
        got = plan_charge_window(kurz, NOW, DEPARTURE, ENERGY_KWH, POWER_KW, 0.02)
        assert got is not None
        assert got.truncated is True


class TestQuietHours:
    def test_nachts_wird_auf_vorabend_gezogen(self):
        """03:30 → 21:59 am Vorabend. Nicht unterdrücken!"""
        got = pull_out_of_quiet_hours(
            datetime(2026, 7, 26, 3, 30, tzinfo=BERLIN), 22, 7
        )
        assert got == datetime(2026, 7, 25, 21, 59, tzinfo=BERLIN)

    def test_spaetabends_wird_vorgezogen(self):
        got = pull_out_of_quiet_hours(
            datetime(2026, 7, 25, 23, 15, tzinfo=BERLIN), 22, 7
        )
        assert got == datetime(2026, 7, 25, 21, 59, tzinfo=BERLIN)

    def test_tagsueber_unveraendert(self):
        when = datetime(2026, 7, 25, 16, 0, tzinfo=BERLIN)
        assert pull_out_of_quiet_hours(when, 22, 7) == when

    def test_genau_auf_der_grenze_wird_vorgezogen(self):
        got = pull_out_of_quiet_hours(
            datetime(2026, 7, 25, 22, 0, tzinfo=BERLIN), 22, 7
        )
        assert got == datetime(2026, 7, 25, 21, 59, tzinfo=BERLIN)

    def test_kurz_nach_nachtruhe_ende_unveraendert(self):
        when = datetime(2026, 7, 26, 7, 0, tzinfo=BERLIN)
        assert pull_out_of_quiet_hours(when, 22, 7) == when
