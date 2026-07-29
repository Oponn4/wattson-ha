"""Tests des gemeinsamen Totband-Musters (v0.20.3).

Drei Vorfälle im Juli 2026 sahen gleich aus: ein blankes `>=`/`<=` gegen eine
Schwelle, alle 5 Minuten neu ausgewertet, und ein Signal, das genau darum
herum pendelt.

    UC12 (27.07.)  Abluft pendelte um die Hitze-Schwelle    → Kühlung sägte
    UC6  (28.07.)  die *Schwelle* wanderte um den Preis     → Lademodus kippte
    UC14 (29.07.)  EMHASS p_batt fiel kurz auf 0 und zurück → E3DC-Schreibsalve

`deadband_hold` ist das Primitiv dahinter. UC14 braucht zusätzlich eine Kappe:
sein Sperrwert (0.00) ist ein Wert, auf dem das Signal stehen bleiben kann —
ein reines Band würde dort ewig halten.
"""
from __future__ import annotations

from typing import ClassVar

from conftest import const, forecast

hold = forecast.deadband_hold
grid_holds = forecast.grid_charge_holds


class TestPrimitivNachOben:
    """UC12-Richtung: aktiv ab der Schwelle, aus erst unter Schwelle − Band."""

    def test_einstieg_an_der_schwelle(self):
        assert hold(value=25.5, threshold=25.5, band=1.0, active=False) is True

    def test_knapp_darunter_bleibt_aus(self):
        assert hold(value=25.4, threshold=25.5, band=1.0, active=False) is False

    def test_im_band_bleibt_an(self):
        assert hold(value=25.1, threshold=25.5, band=1.0, active=True) is True

    def test_unter_dem_band_geht_aus(self):
        assert hold(value=24.4, threshold=25.5, band=1.0, active=True) is False

    def test_genau_am_bandrand_noch_an(self):
        assert hold(value=24.5, threshold=25.5, band=1.0, active=True) is True


class TestPrimitivNachUnten:
    """UC6-Richtung: aktiv bis zur Schwelle, aus erst über Schwelle + Band."""

    def test_einstieg_an_der_schwelle(self):
        assert hold(value=18.0, threshold=18.0, band=0.5, active=False,
                    direction="below") is True

    def test_knapp_darueber_bleibt_aus(self):
        assert hold(value=18.1, threshold=18.0, band=0.5, active=False,
                    direction="below") is False

    def test_im_band_bleibt_an(self):
        assert hold(value=18.4, threshold=18.0, band=0.5, active=True,
                    direction="below") is True

    def test_ueber_dem_band_geht_aus(self):
        assert hold(value=18.6, threshold=18.0, band=0.5, active=True,
                    direction="below") is False


class TestStrikt:
    """UC14 braucht `<` statt `<=`: p_batt == 0 heißt ausdrücklich "nicht laden"."""

    def test_null_ist_ohne_strict_noch_aktiv(self):
        assert hold(value=0.0, threshold=0.0, band=0.0, active=False,
                    direction="below") is True

    def test_null_ist_mit_strict_inaktiv(self):
        assert hold(value=0.0, threshold=0.0, band=0.0, active=False,
                    direction="below", strict=True) is False


class TestHeatActiveUnveraendert:
    """Die UC12-Semantik darf sich durch das Refactoring nicht verschieben."""

    HEAT: ClassVar[float] = 25.5
    HYST: ClassVar[float] = const.COOL_ABLUFT_HYSTERESE_C

    def test_gleiche_antwort_wie_das_primitiv(self):
        for abluft in (24.0, 24.5, 25.0, 25.4, 25.5, 26.0):
            for cooling in (False, True):
                assert forecast.heat_active(
                    abluft_c=abluft, heat_c=self.HEAT,
                    hysteresis_c=self.HYST, currently_cooling=cooling,
                ) is hold(
                    value=abluft, threshold=self.HEAT,
                    band=self.HYST, active=cooling, direction="above",
                ), (abluft, cooling)


class TestUC14Netzladen:
    """Realer p_batt-Verlauf vom 29.07.2026, 09:30–11:40 (5-min-Ticks).

    Die 0.00-Werte um 10:35 und 11:00 sind Plan-Zacken; ab 11:00 blieb der
    Sensor 30 Minuten auf 0.00 stehen, das ist ein echtes Ende.
    """

    BAND: ClassVar[float] = const.UC14_P_BATT_DEADBAND_W
    KAPPE: ClassVar[int] = const.UC14_P_BATT_HOLD_CYCLES

    # Ein Eintrag = ein Tick. 0.00-Plateaus ausgeschrieben, wie der Sensor sie
    # über mehrere Ticks gehalten hat.
    VERLAUF: ClassVar[list[float]] = [
        -1275.0, -1273.0, -1347.0, -1378.0, -814.61, -1462.0, -1454.0,
        -415.63, -1500.0, -1500.0, -185.05, -938.67, -868.04,
        0.0, 0.0,                      # Zacke 10:35–10:40
        -414.0, -189.0, -36.0,
        0.0, 0.0, 0.0, 0.0, 0.0, 0.0,  # echtes Ende ab 11:00 (30 min)
        -11.89, -109.5, -29.53,
    ]

    def _enden(self, band: float, kappe: int) -> int:
        """Wie oft würde UC14 in diesem Verlauf beendet?"""
        active = True
        nonneg = 0
        enden = 0
        for p in self.VERLAUF:
            nonneg = nonneg + 1 if p >= 0 else 0
            haelt = grid_holds(
                p_batt_w=p, band_w=band, active=active,
                nonneg_ticks=nonneg, max_nonneg_ticks=kappe,
            )
            if active and not haelt:
                enden += 1
            active = haelt
        return enden

    def test_zacken_beenden_nicht_mehr(self):
        """Vorher: jeder Nulldurchgang ein Ende plus Neustart."""
        assert self._enden(self.BAND, self.KAPPE) == 1

    def test_ohne_band_haette_es_mehrfach_beendet(self):
        assert self._enden(0.0, 999) > 1

    def test_das_echte_ende_wird_erkannt(self):
        """Die 30-Minuten-Null muss beenden — sonst hinge UC14 an 1500 W."""
        active = True
        for tick in range(1, self.KAPPE + 1):
            active = grid_holds(
                p_batt_w=0.0, band_w=self.BAND, active=active,
                nonneg_ticks=tick, max_nonneg_ticks=self.KAPPE,
            )
        assert active is False

    def test_kappe_greift_auch_bei_positivem_plan(self):
        assert grid_holds(p_batt_w=50.0, band_w=self.BAND, active=True,
                          nonneg_ticks=self.KAPPE, max_nonneg_ticks=self.KAPPE) is False

    def test_klarer_ladewunsch_haelt(self):
        assert grid_holds(p_batt_w=-1500.0, band_w=self.BAND, active=True,
                          nonneg_ticks=0, max_nonneg_ticks=self.KAPPE) is True

    def test_einstieg_braucht_echten_ladewunsch(self):
        """Ohne laufendes Netzladen zählt das Band nicht — 0 startet nichts."""
        assert grid_holds(p_batt_w=0.0, band_w=self.BAND, active=False,
                          nonneg_ticks=1, max_nonneg_ticks=self.KAPPE) is False
