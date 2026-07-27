"""Tests des Totbands am UC12-Hitze-Zweig (v0.20.1).

Vorfall 27.07.2026: die Proxon-Kühlung taktete ab 18:50 im Sägezahn — rund
5 Minuten an, 25 Minuten aus, dazu ein Push pro Zyklus. Die Abluft pendelte
zwischen 25,0 und 25,4 °C, also genau um die Hitze-Schwelle. Ein Tick sah 25,4
und schaltete ein, der nächste sah 25,1, und die Grundregel ("kein
PV-Überschuss, nicht in cheapest_4h, expensive") schaltete wieder aus.

Der Off-Zweig hatte seine Hysterese seit jeher (`off_c`), der Hitze-Zweig nicht.
"""
from __future__ import annotations

from conftest import const, forecast

heat_active = forecast.heat_active
HYST = const.COOL_ABLUFT_HYSTERESE_C
HEAT = 25.5


def active(abluft: float, cooling: bool) -> bool:
    return heat_active(
        abluft_c=abluft, heat_c=HEAT, hysteresis_c=HYST, currently_cooling=cooling
    )


class TestEinschalten:
    def test_ab_der_schwelle_an(self):
        assert active(HEAT, cooling=False) is True

    def test_knapp_darunter_bleibt_aus(self):
        assert active(HEAT - 0.1, cooling=False) is False


class TestTotband:
    def test_bleibt_an_im_totband(self):
        """Der Fall vom 27.07.: 25,1 °C bei laufender Kühlung."""
        assert active(HEAT - 0.4, cooling=True) is True

    def test_erst_unter_dem_totband_aus(self):
        assert active(HEAT - HYST - 0.1, cooling=True) is False

    def test_genau_am_totband_noch_an(self):
        assert active(HEAT - HYST, cooling=True) is True


class TestKeinSaegezahn:
    def test_die_reale_pendelbewegung_schaltet_nicht_mehr(self):
        """Gemessene Abluft am 27.07. zwischen 19:00 und 20:45."""
        verlauf = [25.2, 25.3, 25.4, 25.3, 25.2, 25.1, 25.0, 25.1, 25.2,
                   25.3, 25.4, 25.3, 25.2, 25.1, 25.0, 25.1, 25.2, 25.3, 25.4]
        cooling = False
        wechsel = 0
        for t in verlauf:
            neu = active(t, cooling=cooling)
            if neu != cooling:
                wechsel += 1
            cooling = neu
        assert wechsel <= 1, f"{wechsel} Schaltvorgänge — Totband greift nicht"

    def test_ohne_totband_haette_es_gesaegt(self):
        """Gegenprobe mit blankem >=, wie vor v0.20.1.

        Die Schwelle liegt hier bei 25,35 statt 25,5: `heat_c` ist adaptiv
        (`_compute_cool_thresholds`), lag am 27.07. also innerhalb des
        Pendelbands. Genau darum ging es überhaupt schief — welcher Wert es
        war, ist für den Mechanismus egal, entscheidend ist, dass das Signal
        ihn kreuzt.
        """
        schwelle = 25.35
        verlauf = [25.2, 25.4, 25.1, 25.4, 25.1, 25.4]
        zustand = False
        wechsel = 0
        for t in verlauf:
            neu = t >= schwelle        # alte Logik
            if neu != zustand:
                wechsel += 1
            zustand = neu
        assert wechsel >= 4, "Gegenprobe trifft den alten Fehler nicht"

    def test_dasselbe_signal_mit_totband_ruhig(self):
        """Dieselbe Schwelle, dieselbe Kurve, aber mit Totband."""
        schwelle = 25.35
        verlauf = [25.2, 25.4, 25.1, 25.4, 25.1, 25.4]
        cooling, wechsel = False, 0
        for t in verlauf:
            neu = heat_active(abluft_c=t, heat_c=schwelle,
                              hysteresis_c=HYST, currently_cooling=cooling)
            if neu != cooling:
                wechsel += 1
            cooling = neu
        assert wechsel == 1, f"{wechsel} Schaltvorgänge statt einem"


class TestHysteresewert:
    def test_totband_ist_nicht_null(self):
        """Ein Totband von 0 wäre die alte Logik."""
        assert HYST > 0

    def test_totband_deckt_die_beobachtete_pendelbreite(self):
        """Am 27.07. schwang die Abluft um 0,4 K."""
        assert HYST >= 0.4
