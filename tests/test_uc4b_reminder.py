"""UC4b Safety-Reminder: teuer heißt auch teuer für den Tag (v0.20.27).

Am 28.10.2026 schaltete Wattson den Heizstab um 12:06 im EMHASS-Block ein und
warnte um 12:11 selbst: „Heizstab läuft bei teurem Strom". Tibbers Stufe stand
ab 06:00 durchgehend auf expensive/very_expensive, weil sie mit den Vortagen
vergleicht. Der Slot kostete 41,3 ct bei einer Tagesspanne von 38,1–59,2 ct
und Schnitt 47,6 ct, Rang 0,125. Billiger ging es an dem Tag nicht.
"""
from __future__ import annotations

import pytest
from conftest import const, forecast

faellig = forecast.heizstab_reminder_faellig
TEUER = const.UC12_EXPENSIVE_LEVELS
SCHWELLE = const.UC4B_REMINDER_MIN_RANKING


def _f(level: str, rang: float) -> bool:
    return faellig(
        price_level=level, price_ranking=rang,
        expensive_levels=TEUER, min_ranking=SCHWELLE,
    )


def test_der_vorfall_billigster_slot_eines_teuren_tages():
    assert _f("expensive", 0.125) is False


@pytest.mark.parametrize("level", ["expensive", "very_expensive"])
def test_teure_stunde_eines_teuren_tages_warnt(level):
    assert _f(level, 0.8) is True


def test_mittleres_drittel_warnt_weiter():
    assert _f("expensive", 0.5) is True


def test_schwelle_selbst_gilt_als_guenstig():
    assert _f("expensive", SCHWELLE) is False
    assert _f("expensive", SCHWELLE + 0.01) is True


@pytest.mark.parametrize("level", ["normal", "cheap", "very_cheap"])
def test_ohne_teure_stufe_nie(level):
    assert _f(level, 1.0) is False
