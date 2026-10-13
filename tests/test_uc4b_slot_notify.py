"""v0.20.18: UC4b-Absturz ohne Slot und Notify-Entities als Dienst.

1. Am 12.10.2026 zwischen 12:18 und 13:49 fiel der ganze Wattson-Tick sieben
   Mal aus: `AttributeError: 'NoneType' object has no attribute 'power'`. Der
   Plan sagte „ein" über den publizierten Wert, einen Slot für `now` gab es
   nicht, die Begründung griff trotzdem auf `current_slot.power` zu.
2. Seit dem 25.07.2026 wählt die Option „Benachrichtigungs-Empfänger"
   Notify-Entities, aufgerufen wurden sie als Dienst gleichen Namens — den es
   bei der Mobile App nicht gibt. Keine Anstecken-Erinnerung kam an.
"""
from __future__ import annotations

from pathlib import Path

from conftest import forecast

block_text = forecast.heizstab_block_text
notify_ziel = forecast.notify_ziel

# Dienste, wie HA sie am 13.10. listete (Auszug)
DIENSTE = {
    "send_message", "persistent_notification", "notify",
    "mobile_app_ios_hw23x69q47", "mobile_app_sonjas_iphone_17pro",
    "alexa_media_bad_echo",
}


def da(name: str) -> bool:
    return name in DIENSTE


class TestBlockText:
    def test_mit_slot(self):
        assert block_text(block_end="15:30", slot_power_w=1500.0,
                          published_now_w=1500.0) == "EMHASS-Block bis 15:30 (Slot 1500W)"

    def test_der_absturz_vom_12_10_kein_slot(self):
        text = block_text(block_end="13:30", slot_power_w=None, published_now_w=1500.0)
        assert "kein Slot" in text and "1500W" in text

    def test_ohne_alles(self):
        assert block_text(block_end="?", slot_power_w=None,
                          published_now_w=None) == "EMHASS-Block bis ?"

    def test_coordinator_greift_nicht_mehr_blind_auf_den_slot_zu(self):
        quelle = (
            Path(__file__).resolve().parents[1]
            / "custom_components" / "wattson" / "coordinator.py"
        ).read_text(encoding="utf-8")
        assert "current_slot.power:.0f" not in quelle
        assert "current_slot.power if current_slot else None" in quelle


class TestNotifyZiel:
    def test_entity_wird_mobile_app_dienst(self):
        """Der Fall seit Juli: Entity gewählt, Dienst heißt `mobile_app_…`."""
        assert notify_ziel("notify.ios_hw23x69q47", da) == (
            "mobile_app_ios_hw23x69q47", False,
        )
        assert notify_ziel("notify.sonjas_iphone_17pro", da) == (
            "mobile_app_sonjas_iphone_17pro", False,
        )

    def test_alter_dienstname_bleibt(self):
        """Der Default `notify.mobile_app_ios_hw23x69q47` geht unverändert durch."""
        assert notify_ziel("notify.mobile_app_ios_hw23x69q47", da) == (
            "mobile_app_ios_hw23x69q47", False,
        )

    def test_unbekannte_entity_geht_ueber_send_message(self):
        assert notify_ziel("notify.irgendein_geraet", da) == ("send_message", True)

    def test_nichts_passt(self):
        assert notify_ziel("irgendwas", lambda n: False) == (None, False)

    def test_negativprobe_alter_weg_fand_keinen_dienst(self):
        """So rief v0.20.17 auf: Entity-Objekt-ID direkt als Dienst."""
        assert not da("ios_hw23x69q47")
