"""Start-Freigabe (v0.20.20, siehe start.py).

HA meldet `running`, sobald der Start-Ablauf durch ist — nicht, sobald jede
Integration Werte liefert. Am 11.10.2026 fehlten die Proxon-Entities noch, als
der erste Tick lief, am 12. und 13.10. `tibber.get_prices`.
"""
from __future__ import annotations

from pathlib import Path

from conftest import start

fehlende = start.fehlende_abhaengigkeiten
freigabe = start.start_freigabe

ABLUFT = "sensor.proxon_fwt_temperatur_t07_abluft"
SOC = "sensor.s10e_state_of_charge"


def zustand_aus(werte: dict[str, str | None]):
    return lambda e: werte.get(e)


def dienste_aus(vorhanden: set[str]):
    return lambda domain, name: f"{domain}.{name}" in vorhanden


class TestFehlende:
    def test_alles_da(self):
        assert fehlende(
            entities=[ABLUFT, SOC], dienste=["tibber.get_prices"],
            zustand=zustand_aus({ABLUFT: "24.4", SOC: "61"}),
            dienst_da=dienste_aus({"tibber.get_prices"}),
        ) == []

    def test_proxon_noch_nicht_angelegt_wie_am_11_10(self):
        assert fehlende(
            entities=[ABLUFT, SOC], dienste=[],
            zustand=zustand_aus({SOC: "61"}), dienst_da=dienste_aus(set()),
        ) == [ABLUFT]

    def test_entity_ohne_wert_zaehlt_als_fehlend(self):
        for wert in ("unavailable", "unknown", "", "None"):
            assert fehlende(
                entities=[ABLUFT], dienste=[],
                zustand=zustand_aus({ABLUFT: wert}), dienst_da=dienste_aus(set()),
            ) == [ABLUFT], wert

    def test_tibber_dienst_fehlt_wie_am_13_10(self):
        assert fehlende(
            entities=[], dienste=["tibber.get_prices", "calendar.get_events"],
            zustand=zustand_aus({}), dienst_da=dienste_aus({"calendar.get_events"}),
        ) == ["tibber.get_prices"]

    def test_notify_mit_domain_praefix(self):
        """NOTIFY_SERVICE steht als `notify.mobile_app_…` in const.py."""
        assert fehlende(
            entities=[], dienste=["notify.mobile_app_ios_hw23x69q47"],
            zustand=zustand_aus({}),
            dienst_da=dienste_aus({"notify.mobile_app_ios_hw23x69q47"}),
        ) == []


class TestFreigabe:
    def test_alles_da_sofort(self):
        assert freigabe(fehlend=[], wartet_min=0.0) == (True, "alle Abhängigkeiten da")

    def test_wartet_solange_etwas_fehlt(self):
        frei, grund = freigabe(fehlend=["tibber.get_prices"], wartet_min=2.0)
        assert frei is False
        assert "wartet auf tibber.get_prices" in grund

    def test_nach_der_hoechstzeit_trotzdem(self):
        """Eine tote Integration darf nicht den ganzen Coordinator anhalten."""
        frei, grund = freigabe(fehlend=[ABLUFT], wartet_min=start.MAX_WARTEN_MIN)
        assert frei is True
        assert ABLUFT in grund


class TestEinbindung:
    QUELLE = (
        Path(__file__).resolve().parents[1]
        / "custom_components" / "wattson" / "coordinator.py"
    ).read_text(encoding="utf-8")

    def test_gate_steht_vor_jedem_eingriff(self):
        tick = self.QUELLE.split("async def _async_update_data")[1]
        gate = tick.index("frei, start_grund = self._start_pruefen(now)")
        assert gate < tick.index("if s.sleep_mode:")
        assert "return self._nur_lesend(s, f\"Start: {start_grund}\")" in tick

    def test_freigabe_gilt_bis_zum_neustart(self):
        pruefen = self.QUELLE.split("def _start_pruefen")[1].split("\n    def ")[0]
        assert "if self._start_freigegeben:" in pruefen
        assert "self._start_freigegeben = True" in pruefen

    def test_klimaanlagen_halten_den_start_nicht_auf(self):
        """Stromlos im Winter dauerhaft `unavailable`."""
        block = self.QUELLE.split("START_ENTITIES: tuple[str, ...] = (")[1].split(")")[0]
        assert "KLIMA" not in block
