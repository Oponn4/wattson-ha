"""UC11: Raumwert aus mehreren Sensoren, Kühlsperre (v0.20.29).

30.10.2026 10:42: Shelly H&T Office in der Sonne am Südfenster, 28,6 °C bei
40 % RH. Proxon-Panel 24,3 °C, Klimaanlage 24,5 °C, außen 10 °C. Wattson las
nur den Shelly und schaltete die Klima auf Kühlen.
"""
from __future__ import annotations

from conftest import const, forecast, klima

SHELLY_SONNE = 28.6
KLIMA = 24.5
PROXON = 24.3
RH = 40.0
AUSSEN = 10.0


def _sperre(aussen_c: float, tages_max_c: float | None) -> str | None:
    return klima.kuehlsperre(
        aussen_c=aussen_c,
        tages_max_c=tages_max_c,
        aussen_min_c=const.OUTDOOR_WARM_MIN_C,
        saison_max_c=const.COOL_SAISON_MAX_C,
    )


def test_sonne_auf_shelly_setzt_sich_nicht_durch():
    assert klima.raumtemperatur(SHELLY_SONNE, KLIMA, PROXON) == KLIMA


def test_fall_30_10_loest_nicht_mehr_aus():
    raum = klima.raumtemperatur(SHELLY_SONNE, KLIMA, PROXON)
    assert forecast.humidex(raum, RH) < const.HUMIDEX_WARM_THRESHOLD
    # Negativprobe: mit dem Shelly allein hätte es ausgelöst (so war es)
    assert forecast.humidex(SHELLY_SONNE, RH) >= const.HUMIDEX_WARM_THRESHOLD


def test_echte_hitze_bleibt_sichtbar():
    # Alle drei warm: der Median folgt, nichts wird kleingerechnet
    assert klima.raumtemperatur(29.0, 28.5, 28.0) == 28.5


def test_zwei_werte_nimmt_den_niedrigeren():
    assert klima.raumtemperatur(SHELLY_SONNE, None, PROXON) == PROXON


def test_ein_wert_und_keiner():
    assert klima.raumtemperatur(None, KLIMA, None) == KLIMA
    assert klima.raumtemperatur(None, None, None) is None


def test_kuehler_tag_sperrt():
    assert _sperre(aussen_c=25.0, tages_max_c=15.0) is not None


def test_kuehle_aussenluft_sperrt():
    grund = _sperre(aussen_c=AUSSEN, tages_max_c=None)
    assert grund is not None and "Lüften" in grund


def test_heisser_tag_erlaubt():
    assert _sperre(aussen_c=27.0, tages_max_c=31.0) is None


def test_grenze_aussen_genau_auf_schwelle_erlaubt():
    assert _sperre(aussen_c=const.OUTDOOR_WARM_MIN_C, tages_max_c=30.0) is None
