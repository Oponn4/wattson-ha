"""Tests der Ladepolitik (v0.19).

Christians Regel (25.07.2026, per Sprachnachricht):
  "very cheap ist natürlich very cheap, also saugünstig. Cheap sollte uns
   ausreichen." — und ausdrücklich: normal raus aus dem automatischen Laden.

Daraus:
  sau günstig                 → laden
  günstig UND Sonne           → laden
  Fahrplan, Zeit wird knapp   → sofort laden (überstimmt den Plan)
  sonst                       → nur PV-Überschuss
"""
from __future__ import annotations

from typing import ClassVar

from conftest import const, forecast

decide = forecast.decide_charge_mode

CHEAP = const.UC6_MINPV_PRICE_LEVELS
ALWAYS = const.UC6_ALWAYS_CHARGE_LEVELS
SUN_MIN = const.UC6_SUN_SURPLUS_MIN_W

BASE: ClassVar[dict] = {
    "car_connected": True,
    "plan_active": False,
    "plan_at_risk": False,
    "price_level": "normal",
    "pv_surplus_w": 0,
    "car_soc": 50.0,
    "limit_soc": 90,
    "cheap_levels": CHEAP,
    "always_charge_levels": ALWAYS,
    "pv_surplus_min_w": SUN_MIN,
}


def mode(**over) -> str:
    return decide(**{**BASE, **over}).mode


class TestPreisregel:
    def test_sau_guenstig_laedt_immer(self):
        """very_cheap braucht keine Sonne."""
        assert mode(price_level="very_cheap", pv_surplus_w=0) == "minpv"

    def test_guenstig_mit_sonne_laedt(self):
        assert mode(price_level="cheap", pv_surplus_w=SUN_MIN) == "minpv"

    def test_guenstig_ohne_sonne_laedt_nicht(self):
        assert mode(price_level="cheap", pv_surplus_w=0) == "pv"

    def test_guenstig_mit_zu_wenig_sonne_laedt_nicht(self):
        """Unter 3-phasigem Minimum zöge minpv die Differenz aus dem Netz."""
        assert mode(price_level="cheap", pv_surplus_w=SUN_MIN - 100) == "pv"

    def test_normal_laedt_nie(self):
        """Kern der Entscheidung: normal reicht bis ~115% des Mittels
        (Ende Juli 2026 rund 35 ct) — das ist keine Ladefreigabe."""
        assert mode(price_level="normal", pv_surplus_w=0) == "pv"
        assert mode(price_level="normal", pv_surplus_w=10000) == "pv"

    def test_teuer_laedt_nie(self):
        assert mode(price_level="expensive", pv_surplus_w=10000) == "pv"
        assert mode(price_level="very_expensive", pv_surplus_w=10000) == "pv"

    def test_normal_ist_nicht_in_der_freigabe(self):
        """Regression gegen die alte Konstante mit drei Leveln."""
        assert "normal" not in CHEAP


class TestFahrplan:
    def test_plan_laeuft_in_pv_nicht_minpv(self):
        """evcc kennt den Tarif und sucht die Slots selbst; minpv würde den
        Plan unterlaufen, weil es preisunabhängig dauernd Netzstrom zieht."""
        assert mode(plan_active=True, price_level="expensive") == "pv"

    def test_plan_in_gefahr_erzwingt_now(self):
        assert mode(plan_active=True, plan_at_risk=True,
                    price_level="very_expensive") == "now"

    def test_ohne_plan_kein_now(self):
        assert mode(plan_active=False, plan_at_risk=True) != "now"

    def test_guenstig_schlaegt_plan(self):
        """Billiger Strom lädt auch bei aktivem Plan — schadet dem Ziel nicht."""
        assert mode(plan_active=True, price_level="very_cheap") == "minpv"


class TestVorbedingungen:
    def test_abgesteckt_immer_pv(self):
        assert mode(car_connected=False, price_level="very_cheap") == "pv"

    def test_ueber_limit_nicht_laden(self):
        assert mode(price_level="very_cheap", car_soc=90.0, limit_soc=90) == "pv"

    def test_knapp_unter_limit_laedt(self):
        assert mode(price_level="very_cheap", car_soc=89.0, limit_soc=90) == "minpv"

    def test_limit_schlaegt_preis_aber_nicht_notfall(self):
        """Ein gefährdeter Fahrplan zieht auch über dem Limit."""
        assert mode(car_soc=95.0, plan_active=True, plan_at_risk=True) == "now"


class TestBegruendungLesbar:
    def test_jede_entscheidung_hat_klartext(self):
        for lvl in ("very_cheap", "cheap", "normal", "expensive"):
            d = decide(**{**BASE, "price_level": lvl})
            assert d.reason and len(d.reason) > 8, lvl
            assert d.mode in ("now", "minpv", "pv")


class TestRealeSituationen:
    """Szenarien aus dem echten Betrieb am 25.07.2026."""

    def test_heute_1520_billigfenster_ohne_sonne(self):
        """17,5 ct = very_cheap, PV-Überschuss nur 2,1 kW → trotzdem laden."""
        assert mode(price_level="very_cheap", pv_surplus_w=2100,
                    car_soc=53.0) == "minpv"

    def test_heute_nacht_teuer_mit_plan(self):
        """Plan aktiv, 35 ct, Zeit reicht → evcc entscheidet, kein now."""
        assert mode(plan_active=True, plan_at_risk=False,
                    price_level="expensive", car_soc=86.0) == "pv"

    def test_alte_regel_haette_nachts_geladen(self):
        """Gegenprobe: mit `normal` in der Freigabe hätte die Nacht geladen."""
        alt = decide(**{**BASE, "price_level": "normal",
                        "cheap_levels": ("very_cheap", "cheap", "normal"),
                        "always_charge_levels": ("very_cheap", "cheap", "normal")})
        assert alt.mode == "minpv"
        assert mode(price_level="normal") == "pv"
