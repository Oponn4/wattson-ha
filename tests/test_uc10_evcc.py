"""UC10: evccs Batteriesteuerung ist kein Hand-Eingriff (v0.20.25).

Der 24.10.2026 aus der HA-Datenbank, `sensor.s10e_maximum_discharge` und
`sensor.evcc_battery_mode_value`:

    16:17:15  Auto lädt, evcc: "lock discharge"
    16:29:06  Wattson setzt 264 W (EMHASS-Plan) — hebt evccs Sperre auf
    16:30:15  evcc: "normal"
    16:30:17  maxDischargePower 1500 W (evcc setzt auf das Maximum zurück)
    16:34     Wattson wertet 1500 W als Hand-Eingriff, UC10 bis Mitternacht aus

Dieselbe Folge um 12:15 und 12:17. evcc hat batteryDischargeControl an, damit
der Hausspeicher das Auto nicht lädt.
"""
from __future__ import annotations

from conftest import const, forecast

einfluss = forecast.evcc_batterie_einfluss
fremd = forecast.uc10_fremdaenderung

FRIST = const.EVCC_BATTERY_GRACE_MIN
HALTEN = const.EVCC_BATTERY_MODES_HALTEN
MAX = const.E3DC_MAX_DISCHARGE_W


def evcc(modus, seit_min):
    return einfluss(modus, seit_min, FRIST, HALTEN)


class TestEinfluss:
    def test_lock_discharge_haelt(self):
        """16:29: Auto lädt, evcc sperrt — UC10 darf nicht schreiben."""
        assert evcc("lock discharge", 12.0) == "haelt"

    def test_haelt_auch_nach_langer_zeit(self):
        assert evcc("lock discharge", 300.0) == "haelt"

    def test_api_werte_halten(self):
        assert evcc("hold", 1.0) == "haelt"
        assert evcc("charge", 1.0) == "haelt"

    def test_normal_kurz_nach_wechsel(self):
        """16:34: "normal" seit 16:30:15."""
        assert evcc("normal", 3.75) == "kuerzlich"

    def test_neustart_unknown_ist_kuerzlich(self):
        """16:03:22: evcc-Neustart nach dem Paket-Update, Modus `unknown`."""
        assert evcc("unknown", 2.0) == "kuerzlich"

    def test_normal_lange_her(self):
        assert evcc("normal", 45.0) is None

    def test_grenze_frist_zaehlt_nicht_mehr(self):
        assert evcc("normal", float(FRIST)) is None

    def test_entity_fehlt(self):
        assert evcc(None, None) is None


class TestFremdaenderung:
    def test_16_34_evcc_reset_ist_kein_override(self):
        assert fremd(1500, 264, evcc("normal", 3.75), MAX) == "evcc"

    def test_negativprobe_ohne_evcc_wissen_override(self):
        """Das alte Verhalten: genau der Fehlalarm vom 24.10."""
        assert fremd(1500, 264, None, MAX) == "user"

    def test_reset_nach_der_frist_bleibt_override(self):
        assert fremd(1500, 264, evcc("normal", 30.0), MAX) == "user"

    def test_anderer_wert_in_der_frist_bleibt_override(self):
        """Christian setzt 800 W von Hand, kurz nachdem evcc gewechselt hat."""
        assert fremd(800, 0, evcc("normal", 2.0), MAX) == "user"

    def test_auf_null_in_der_frist_bleibt_override(self):
        assert fremd(0, 1500, evcc("normal", 2.0), MAX) == "user"

    def test_keine_abweichung(self):
        assert fremd(1500, 1500, None, MAX) is None
        assert fremd(1480, 1500, None, MAX) is None

    def test_nichts_gebucht(self):
        """Nach Neustart, Resume oder evcc-Pause ist das Gedächtnis leer."""
        assert fremd(1500, None, None, MAX) is None

    def test_toleranz_am_maximum(self):
        assert fremd(1460, 264, evcc("normal", 1.0), MAX) == "evcc"

    def test_evcc_sperrt_selbst_ist_kein_override(self):
        """Übergang, solange batteryDischargeControl noch an ist: evcc setzt 0 W."""
        assert fremd(0, 264, evcc("lock discharge", 0.5), MAX) == "evcc"


abgleich = forecast.uc10_evcc_abgleich


class TestAbgleich:
    """Wattson sperrt beim Laden selbst; evcc fasst die Batterie nicht mehr an."""

    def test_auto_laedt_sperrt_trotz_plan(self):
        """16:29 mit neuer Logik: EMHASS will 264 W, das Auto lädt."""
        ziel, grund = abgleich(264, True, None)
        assert ziel == 0 and "Auto lädt" in grund

    def test_auto_laedt_auch_wenn_evcc_noch_haelt(self):
        assert abgleich(1500, True, "haelt")[0] == 0

    def test_negativprobe_ohne_laden_folgt_dem_plan(self):
        assert abgleich(264, False, None) == (264, None)

    def test_evcc_haelt_und_plan_will_freigeben(self):
        ziel, grund = abgleich(264, False, "haelt")
        assert ziel is None and "pausiert" in grund

    def test_evcc_haelt_und_plan_sperrt_ohnehin(self):
        assert abgleich(0, False, "haelt") == (0, None)

    def test_nach_dem_laden_wieder_plan(self):
        """16:30:45 Laden aus, evcc-Modus seit 30 s "normal"."""
        assert abgleich(264, False, evcc("normal", 0.5)) == (264, None)
