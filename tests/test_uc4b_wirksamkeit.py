"""Tests zum Heizstab: Plan-Auskunft, Wirksamkeit, Speicherfenster (v0.20.11).

Gemessen am 19.09.2026. Der Heizstab wurde acht Mal zwischen 13:32 und 17:22
freigegeben und wieder gesperrt — Periode 30 min, aus bei :22/:52, an bei
:02/:32. Zwei unabhängige Ursachen:

**A — „kein Slot" galt als „Plan sagt aus".** EMHASS veröffentlicht den
Forward-Plan ab der *nächsten* Halbstunden-Grenze; der laufende Slot fehlt.
Live nachgemessen am 20.09. um 14:58:28: erster Eintrag 15:00:00, also kein
Slot, der `now` enthält. `sensor.p_deferrable0` meldete dabei durchgehend
1500 W — der Plan wollte heizen, nur die Abfrage fand ihn nicht.

**B — die Freigabe war wirkungslos.** Ab 13:32 stand der Tank auf 54,8 °C bei
Sollwert 52,0. `binary_sensor.proxon_t300_e_heiz_aktiv` blieb durchgehend aus,
der T300-Zähler stieg in 2 h 08 um 0,166 kWh (Wärmepumpe, Kompressor 19 min).
1500 W hätten in der Einschaltzeit ~2 kWh gezogen. Um 11:31, mit Tank unter
Sollwert, lief der Stab dagegen sofort mit.
"""
from __future__ import annotations

from itertools import pairwise
from pathlib import Path
from typing import ClassVar

import pytest
from conftest import const, forecast

signal = forecast.heizstab_plan_signal
kann_wirken = forecast.heizstab_kann_wirken
speicherfenster = forecast.t300_speicherfenster

MIN_W = const.EMHASS_DEFERRABLE_ON_MIN_W
HYST = const.UC4B_ELEMENT_HYSTERESE_C
ZIEL = 59.0  # E-Heiz-Ziel der Anlage (Reg 2003)
CHEAP = const.T300_TEMP_CHEAP
VORRAT = const.T300_TEMP_SPEICHER


class TestPlanAuskunft:
    def test_slot_entscheidet_wenn_vorhanden(self):
        assert signal(slot_power_w=1500, published_now_w=0, min_on_w=MIN_W) == "on"
        assert signal(slot_power_w=0, published_now_w=1500, min_on_w=MIN_W) == "off"

    def test_der_vorfall_kein_slot_aber_publizierter_wert(self):
        """20.09. 14:58: erster Slot 15:00, `p_deferrable0` = 1500 W."""
        assert signal(
            slot_power_w=None, published_now_w=1500, min_on_w=MIN_W,
        ) == "on"

    def test_ohne_alles_unbekannt_statt_aus(self):
        assert signal(
            slot_power_w=None, published_now_w=None, min_on_w=MIN_W,
        ) == "unbekannt"

    def test_publizierte_null_ist_eine_aussage(self):
        assert signal(
            slot_power_w=None, published_now_w=0.0, min_on_w=MIN_W,
        ) == "off"

    def test_schwelle_gilt_fuer_beide_quellen(self):
        assert signal(slot_power_w=MIN_W, published_now_w=None, min_on_w=MIN_W) == "on"
        assert signal(
            slot_power_w=MIN_W - 1, published_now_w=None, min_on_w=MIN_W,
        ) == "off"
        assert signal(
            slot_power_w=None, published_now_w=MIN_W, min_on_w=MIN_W,
        ) == "on"

    def test_gegenprobe_alte_logik_saegt(self):
        """Vor v0.20.11: fehlender Slot = aus. Nachgestellt über 90 Minuten.

        Drei Ticks je Halbstunde sehen den Slot, zwei nicht (EMHASS hat auf die
        nächste Grenze umgestellt). Mit dem Confirmation-Zähler (2) ergibt das
        genau das gemessene Takten.
        """
        slots = [1500, 1500, 1500, None, None] * 3     # 15 Ticks à 5 min = 75 min
        alt = ["on" if p is not None and p >= MIN_W else "off" for p in slots]
        wechsel_alt = sum(1 for a, b in pairwise(alt) if a != b)
        neu = [
            signal(slot_power_w=p, published_now_w=1500, min_on_w=MIN_W)
            for p in slots
        ]
        wechsel_neu = sum(1 for a, b in pairwise(neu) if a != b)
        assert wechsel_alt >= 4, "Gegenprobe trifft den alten Fehler nicht"
        assert wechsel_neu == 0
        assert set(neu) == {"on"}


class TestWirksamkeit:
    """Drei Messpunkte, alle bei E-Heiz-Ziel 59 °C."""

    @pytest.mark.parametrize("tank,lief,wann", [
        (56.9, False, "07.07. Feldtest (Wiki)"),
        (54.8, False, "19.09. 13:32, acht Freigaben ohne Wirkung"),
        (53.8, True, "20.09. 12:33, Stab lief binnen 3 s"),
    ])
    def test_gemessene_faelle(self, tank, lief, wann):
        assert kann_wirken(
            tank_c=tank, e_heiz_ziel_c=ZIEL, hysterese_c=HYST,
        ) is lief, wann

    def test_hysterese_liegt_zwischen_den_messpunkten(self):
        """4,2 K blieb aus, 5,2 K lief — dazwischen muss die Schwelle liegen."""
        assert 4.2 < HYST <= 5.2

    def test_der_sollwert_taugt_nicht_als_gate(self):
        """Erste Fassung verglich gegen 52 °C und hätte den 20.09. unterdrückt.

        An beiden Tagen lag der Tank *über* dem Warmwasser-Sollwert; der
        Unterschied war allein der Abstand zum E-Heiz-Ziel.
        """
        sollwert, lief, lief_nicht = 52.0, 53.8, 54.8
        assert lief > sollwert and lief_nicht > sollwert
        assert kann_wirken(tank_c=lief, e_heiz_ziel_c=ZIEL, hysterese_c=HYST)
        assert not kann_wirken(tank_c=lief_nicht, e_heiz_ziel_c=ZIEL, hysterese_c=HYST)

    def test_ohne_ziel_nicht_blockieren(self):
        assert kann_wirken(
            tank_c=54.8, e_heiz_ziel_c=None, hysterese_c=HYST,
        ) is True


class TestSpeicherfenster:
    def test_der_vorfall_haette_den_sollwert_gehoben(self):
        """Plan will heizen, Tank 54,8 unter dem Vorrats-Ziel → Vorrat statt Leerlauf."""
        assert speicherfenster(
            plan_signal="on", tank_c=54.8, storage_target_c=VORRAT, expensive=False,
        ) is True

    def test_kein_plan_kein_vorrat(self):
        for sig in ("off", "unbekannt"):
            assert speicherfenster(
                plan_signal=sig, tank_c=50.0, storage_target_c=VORRAT,
                expensive=False,
            ) is False

    def test_teurer_strom_schlaegt_den_plan(self):
        """Rückfalltür gegen eine kaputte Optimierung — netzdienlich zuerst."""
        assert speicherfenster(
            plan_signal="on", tank_c=50.0, storage_target_c=VORRAT, expensive=True,
        ) is False

    def test_voller_tank_braucht_keinen_vorrat(self):
        assert speicherfenster(
            plan_signal="on", tank_c=VORRAT, storage_target_c=VORRAT, expensive=False,
        ) is False

    def test_kette_greift_zusammen(self):
        """Vorrats-Ziel → Bedarf entsteht → Freigabe wirkt. Das war die Lücke."""
        tank = 54.8
        # Der Stab spränge bei diesem Tank nicht an …
        assert kann_wirken(tank_c=tank, e_heiz_ziel_c=ZIEL, hysterese_c=HYST) is False
        # … die Wärmepumpe hätte aber Arbeit, sobald der Sollwert hochgeht.
        assert speicherfenster(
            plan_signal="on", tank_c=tank, storage_target_c=VORRAT, expensive=False,
        ) is True

    def test_vorrat_endet_an_der_registergrenze(self):
        """Reg 4x2000 kann nicht über 55 °C. Mehr Vorrat ginge nur über
        Reg 4x2003 (E-Heiz, bis 70 °C) — dann heizt aber der Stab (COP 1)
        statt der Wärmepumpe. Deshalb liegt das Vorrats-Ziel auf 55."""
        assert VORRAT == CHEAP == const.T300_TARGET_MAX_C == 55.0


class TestVerweildauer:
    def test_konstante_ist_gesetzt_und_ueber_dem_tick(self):
        """Unter einem Tick wäre die Sperre wirkungslos."""
        assert const.UC4B_MIN_DWELL_MIN >= 2 * (const.SCAN_INTERVAL_SECONDS / 60)


class TestBindungImCoordinator:
    """Wächter auf die Aufrufstellen — `coordinator.py` ist hier nicht ladbar."""

    QUELLE: ClassVar[str] = (
        Path(__file__).resolve().parents[1]
        / "custom_components" / "wattson" / "coordinator.py"
    ).read_text(encoding="utf-8")

    def test_signal_wird_zentral_bestimmt(self):
        """UC4a und UC4b müssen dieselbe Auskunft sehen."""
        assert "s.heizstab_plan_signal = heizstab_plan_signal(" in self.QUELLE
        assert "signal = s.heizstab_plan_signal" in self.QUELLE

    def test_uc4b_prueft_den_bedarf(self):
        """Wörtlich der Zweig — `not s.t300_demand` allein stünde auch in der
        Heuristik, und der erste Entwurf dieses Wächters hat den Ausbau des
        Plan-Zweigs deshalb nicht bemerkt (Negativprobe schlug nicht an)."""
        assert (
            "elif plan_says_on and tank_safe and not s.t300_demand:" in self.QUELLE
        )

    def test_heuristik_prueft_den_bedarf_auch(self):
        assert "                and s.t300_demand" in self.QUELLE
        assert "                or not s.t300_demand" in self.QUELLE

    def test_bedarf_kommt_aus_dem_gelesenen_sollwert(self):
        assert "ENTITY_T300_SETPOINT" in self.QUELLE
        assert "heizstab_kann_wirken(" in self.QUELLE

    def test_uc4a_hebt_fuer_das_speicherfenster(self):
        assert "t300_speicherfenster(" in self.QUELLE

    def test_verweildauer_zaehlt_den_eigenen_write(self):
        assert "dwell = self._uc4b_dwell_minutes(now)" in self.QUELLE
        assert "self._uc4b_last_switch_at = now" in self.QUELLE

    def test_harte_zweige_bleiben_ohne_verweildauer(self):
        """Tank-Limit darf nicht 15 Minuten warten müssen."""
        quelle = self.QUELLE
        assert "uc4b_soft = False" in quelle
        assert quelle.index("uc4b_soft = False") < quelle.index(
            "dwell = self._uc4b_dwell_minutes(now)"
        )


class TestSchreibZiele:
    """Die Entities, auf die Wattson schreibt — sie müssen existieren.

    Bis v0.20.10 zeigten `ENTITY_T300_SOLL` und `ENTITY_T300_BOOST_TEMP` auf
    Namen ohne `hwr_`-Präfix. Die gibt es in dieser HA-Instanz nicht: `_fval`
    lieferte still den Default, `_try_act` rief einen Service auf eine
    nicht existierende Entity und meldete Erfolg. Der T300-Sollwert stand
    deshalb 14 Tage auf 52,0, während UC4a „günstigste 2h → 55 °C" schrieb.
    """

    QUELLE: ClassVar[str] = (
        Path(__file__).resolve().parents[1]
        / "custom_components" / "wattson" / "coordinator.py"
    ).read_text(encoding="utf-8")

    def test_t300_entities_tragen_den_bereichspraefix(self):
        assert const.ENTITY_T300_SOLL == "number.hwr_proxon_t300_target_temperature"
        assert const.ENTITY_T300_BOOST_TEMP == (
            "number.hwr_proxon_t300_electric_heater_temperature"
        )

    def test_uc4a_schreibt_auf_number_nicht_input_number(self):
        """`input_number.set_value` auf eine `number.`-Entity tut nichts.

        Geprüft wird die Aufrufform, nicht das Wort: im Kommentar daneben steht
        `input_number` weiterhin — als Erklärung, warum es dort nicht hingehört.
        """
        assert '"input_number", "set_value"' not in self.QUELLE
        assert '"number", "set_value"' in self.QUELLE

    def test_startup_prueft_die_schreib_ziele(self):
        assert "CRITICAL_WRITE_ENTITIES" in self.QUELLE
        assert "self._warn_missing_entities()" in self.QUELLE

    def test_pruefung_laeuft_nicht_in_async_setup(self):
        """v0.20.12 prüfte in `async_setup` — also bevor proxon, evcc und die
        Klima-Integration ihre Entities anlegen. Beim ersten echten Start am
        22.09.2026 meldete sie prompt alle sieben Ziele als fehlend, obwohl
        jedes existierte. Ein Wächter, der immer anschlägt, sagt nichts."""
        setup = self.QUELLE.split("async def async_setup")[1].split("def ")[0]
        assert "_warn_missing_entities" not in setup

    def test_pruefung_haengt_am_hochlauf_und_laeuft_einmal(self):
        assert (
            "if self.hass.state is CoreState.running and not self._entities_checked:"
            in self.QUELLE
        )
        assert "self._entities_checked = True" in self.QUELLE

    def test_alle_schreib_ziele_sind_bekannte_konstanten(self):
        """Tippfehler in der Liste würde die Prüfung stumm entwerten."""
        block = self.QUELLE.split("CRITICAL_WRITE_ENTITIES")[1].split(")")[0]
        namen = [
            zeile.strip().rstrip(",")
            for zeile in block.splitlines()
            if zeile.strip().startswith("ENTITY_")
        ]
        assert len(namen) >= 5
        for name in namen:
            assert hasattr(const, name), f"{name} gibt es in const.py nicht"


class TestSollwertDeckel:
    """Ohne Mischer ist die Tanktemperatur die Armaturentemperatur.

    Christian: „Wenn im Tank 70 °C sind, kommt das wirklich kochend aus der
    Armatur" — und: keine Kinder im Haus, acht Jahre Betrieb damit. Der Deckel
    ist deshalb Runaway-Schutz, kein Komfort-Limit: er greift im Normalbetrieb
    nie, fängt aber einen künftigen Zweig ab, der 65+ schreiben will.
    """

    QUELLE: ClassVar[str] = (
        Path(__file__).resolve().parents[1]
        / "custom_components" / "wattson" / "coordinator.py"
    ).read_text(encoding="utf-8")

    def test_deckel_entspricht_der_registergrenze(self):
        """MODBUS-Liste (Paperless Dok 2300), Reg 4x2000 „Normal
        Wassertemperatur": IST-Min 20 °C, IST-Max **55** °C. v0.20.11 hatte
        57 stehen — das Gerät nimmt den Wert nicht an."""
        assert const.T300_TARGET_MAX_C == 55.0

    def test_kein_uc4a_ziel_liegt_darueber(self):
        """Alle Sollwert-Kandidaten, die UC4a schreiben kann."""
        for kandidat in (
            const.T300_TEMP_NORMAL, const.T300_TEMP_CHEAP,
            const.T300_TEMP_TEUER, const.T300_TEMP_SPEICHER,
        ):
            assert kandidat <= const.T300_TARGET_MAX_C

    def test_deckel_steht_am_ende_der_kette(self):
        """Vor `s.t300_target = new_temp` — sonst umgeht ihn der nächste Zweig."""
        quelle = self.QUELLE
        assert "if new_temp > T300_TARGET_MAX_C:" in quelle
        assert quelle.index("if new_temp > T300_TARGET_MAX_C:") < quelle.index(
            "s.t300_target = new_temp"
        )

    def test_legionellen_push_warnt_vor_der_temperatur(self):
        """Der Lauf geht auf 64,5 °C — der Push muss das sagen."""
        assert "verbrüht man sich in" in self.QUELLE
        assert const.LEGIONELLA_TARGET_C > const.T300_TARGET_MAX_C
