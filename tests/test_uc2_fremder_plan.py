"""Tests gegen das Überschreiben fremder evcc-Fahrpläne (v0.20.10).

Vorfall 19./20.09.2026:

* 18:54:27 trägt Christian in evcc „100 % bis 20.09 10:45" ein.
* ~18:57 erkennt Wattson den Eingriff korrekt — `sensor.wattson_eauto_fahrplan`
  zeigt ab da `user-override (…min Rest)`, der Countdown läuft auf Mitternacht.
* 23:56:07 steht dort „user-override (3min Rest)".
* **00:01:08** schreibt UC2 den Grundplan „50 % bis 20.09 12:00" darüber —
  68 Sekunden nach Ablauf des Cooldowns.

Zwei Lücken, zwei Fixes: der Cooldown kannte die Zielzeit des Plans nicht
(`cooldown_until_next_midnight` endete stur um Mitternacht), und es gab keine
Prüfung, wem der Plan in evcc überhaupt gehört.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import ClassVar

import pytest
from conftest import forecast, override

foreign_plan_note = forecast.foreign_plan_note
cooldown_until_next_midnight = override.cooldown_until_next_midnight

TZ = timezone(timedelta(hours=2))

# Der Abend des 19.09.2026
CHRISTIANS_PLAN_ZEIT = datetime(2026, 9, 20, 10, 45, tzinfo=TZ)
GRUNDPLAN_ZEIT = datetime(2026, 9, 20, 12, 0, tzinfo=TZ)
EINGRIFF = datetime(2026, 9, 19, 18, 57, tzinfo=TZ)


def grundplan_gespeichert(zeit: datetime = GRUNDPLAN_ZEIT, soc: int = 50) -> dict:
    """Was Wattson nach einem eigenen Write in `misc.uc2_plan` hinterlegt."""
    return {
        "key": f"baseline:{soc}:{zeit.date().isoformat()}",
        "uid": "wattson-baseline",
        "titel": "Grundplan",
        "soc": soc,
        "abfahrt": zeit.isoformat(),
    }


class TestFremderPlan:
    def test_der_vorfall(self):
        """evcc hält Christians Plan, hinterlegt ist Wattsons Grundplan."""
        note = foreign_plan_note(
            plan_soc=100, plan_time=CHRISTIANS_PLAN_ZEIT,
            stored=grundplan_gespeichert(),
        )
        assert note == "100% bis 20.09 10:45"

    def test_eigener_plan_ist_nicht_fremd(self):
        note = foreign_plan_note(
            plan_soc=50, plan_time=GRUNDPLAN_ZEIT, stored=grundplan_gespeichert(),
        )
        assert note is None

    def test_kein_plan_in_evcc_blockiert_nichts(self):
        assert foreign_plan_note(
            plan_soc=0, plan_time=None, stored=grundplan_gespeichert(),
        ) is None
        assert foreign_plan_note(
            plan_soc=None, plan_time=None, stored=None,
        ) is None

    def test_gleicher_soc_andere_zeit_ist_fremd(self):
        """Zwei Pläne mit 50 % zu verschiedenen Zeiten sind verschiedene Pläne."""
        note = foreign_plan_note(
            plan_soc=50, plan_time=GRUNDPLAN_ZEIT + timedelta(hours=3),
            stored=grundplan_gespeichert(),
        )
        assert note == "50% bis 20.09 15:00"

    def test_gleiche_zeit_anderer_soc_ist_fremd(self):
        note = foreign_plan_note(
            plan_soc=80, plan_time=GRUNDPLAN_ZEIT, stored=grundplan_gespeichert(),
        )
        assert note is not None

    def test_ohne_eigenen_plan_gilt_alles_als_fremd(self):
        """Nach einem Reset kennt Wattson keinen eigenen Plan — dann Finger weg."""
        note = foreign_plan_note(
            plan_soc=60, plan_time=GRUNDPLAN_ZEIT, stored=None,
        )
        assert note is not None

    def test_rundung_auf_volle_minuten_ist_kein_fremder_plan(self):
        note = foreign_plan_note(
            plan_soc=50, plan_time=GRUNDPLAN_ZEIT + timedelta(seconds=30),
            stored=grundplan_gespeichert(),
        )
        assert note is None

    def test_knapp_daneben_ist_fremd(self):
        note = foreign_plan_note(
            plan_soc=50, plan_time=GRUNDPLAN_ZEIT + timedelta(minutes=5),
            stored=grundplan_gespeichert(),
        )
        assert note is not None

    def test_plan_ohne_zeit_gilt_als_fremd(self):
        """Sichere Richtung: ohne vergleichbare Zeit kein Freibrief."""
        note = foreign_plan_note(
            plan_soc=50, plan_time=None, stored=grundplan_gespeichert(),
        )
        assert note == "50% ohne Zielzeit"

    def test_kaputter_speicherstand_sperrt_statt_zu_schreiben(self):
        for kaputt in ({}, {"soc": "fuffzig"}, {"soc": 50}, {"abfahrt": "gestern"}):
            assert foreign_plan_note(
                plan_soc=50, plan_time=GRUNDPLAN_ZEIT, stored=kaputt,
            ) is not None


class TestCooldownMitZielzeit:
    def test_der_vorfall_cooldown_haelt_bis_zur_zielzeit(self):
        bis = cooldown_until_next_midnight(EINGRIFF, CHRISTIANS_PLAN_ZEIT)
        assert bis == CHRISTIANS_PLAN_ZEIT

    def test_gegenprobe_ohne_zielzeit_endet_um_mitternacht(self):
        """Das alte Verhalten — und der Grund, warum 00:01:08 möglich war."""
        bis = cooldown_until_next_midnight(EINGRIFF)
        assert bis == datetime(2026, 9, 20, 0, 0, tzinfo=TZ)
        assert bis < CHRISTIANS_PLAN_ZEIT

    def test_zielzeit_vor_mitternacht_verkuerzt_nicht(self):
        früh = datetime(2026, 9, 19, 20, 0, tzinfo=TZ)
        assert cooldown_until_next_midnight(EINGRIFF, früh) == datetime(
            2026, 9, 20, 0, 0, tzinfo=TZ
        )

    def test_mindestcooldown_bleibt(self):
        """Eingriff um 23:30: zwei Stunden, nicht 30 Minuten."""
        spaet = datetime(2026, 9, 19, 23, 30, tzinfo=TZ)
        assert cooldown_until_next_midnight(spaet) == spaet + timedelta(hours=2)

    @pytest.mark.parametrize("hold", [None])
    def test_signatur_bleibt_rueckwaertskompatibel(self, hold):
        assert cooldown_until_next_midnight(EINGRIFF, hold) > EINGRIFF


class TestBindungImCoordinator:
    """Wächter auf die Aufrufstelle — `coordinator.py` ist hier nicht ladbar."""

    QUELLE: ClassVar[str] = (
        Path(__file__).resolve().parents[1]
        / "custom_components" / "wattson" / "coordinator.py"
    ).read_text(encoding="utf-8")

    def test_fremder_plan_wird_vor_dem_schreiben_geprueft(self):
        assert "if (fremd := self._foreign_plan()) is not None:" in self.QUELLE

    def test_die_pruefung_steht_vor_dem_cooldown(self):
        """Sonst entscheidet wieder eine Frist statt des Zustands."""
        quelle = self.QUELLE
        assert quelle.index("self._foreign_plan()") < quelle.index(
            'self._override.in_cooldown("uc2")'
        )

    def test_override_haelt_die_zielzeit(self):
        assert "hold_until=plan_time" in self.QUELLE

    def test_fremdpruefung_liest_den_hinterlegten_plan(self):
        """Nicht den *effektiven*: der steht auf 0, sobald evcc pausiert."""
        assert "ENTITY_EVCC_VEHICLE_PLAN_SOC" in self.QUELLE
        assert "ENTITY_EVCC_VEHICLE_PLAN_TIME" in self.QUELLE
