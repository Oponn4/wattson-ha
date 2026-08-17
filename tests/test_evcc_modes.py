"""Tests der evcc-Mode-Übersetzung.

evcc PR#32490 ersetzt `off|pv|minpv|now` durch `off|smart|now` plus den
Selector `alwaysCharge` (`off|on|once`). Wattson rechnet intern weiter in
`pv|minpv|now|off`; übersetzt wird nur an der Grenze.

Der Anlass für den Vorbau: CT102 zieht evcc-Updates viermal täglich per
`evcc-guarded-update.timer`. Ein Release mit dem neuen Schema liegt also binnen
Stunden auf der Anlage, ohne dass jemand eingreifen könnte — ab dann würde
UC6 auf einen Selector schreiben, der `minpv` nicht mehr kennt.
"""
from __future__ import annotations

from conftest import evcc_modes

is_new_scheme = evcc_modes.is_new_scheme
normalize = evcc_modes.normalize_mode
plan = evcc_modes.plan_writes

MODE = evcc_modes.ROLE_MODE
AC = evcc_modes.ROLE_ALWAYS_CHARGE

OLD_OPTIONS = ["off", "pv", "minpv", "now"]
NEW_OPTIONS = ["off", "smart", "now"]


class TestSchemaErkennung:
    def test_altes_evcc(self):
        assert is_new_scheme(OLD_OPTIONS) is False

    def test_neues_evcc(self):
        assert is_new_scheme(NEW_OPTIONS) is True

    def test_ohne_optionen_konservativ_alt(self):
        """Entity unavailable → keine Erkennung, nicht raten."""
        assert is_new_scheme(None) is False
        assert is_new_scheme([]) is False


class TestLesen:
    def test_altes_schema_unveraendert(self):
        for m in OLD_OPTIONS:
            assert normalize(m) == m

    def test_smart_ohne_minimum_ist_pv(self):
        assert normalize("smart", "off") == "pv"

    def test_smart_mit_minimum_ist_minpv(self):
        assert normalize("smart", "on") == "minpv"

    def test_once_liest_sich_als_minpv(self):
        """`once` lädt am Minimum — bis zum Abstecken. Wattson schreibt es nie
        selbst; von Hand gesetzt darf es nicht als `pv` fehlgelesen werden."""
        assert normalize("smart", "once") == "minpv"

    def test_smart_ohne_alwayscharge_faellt_auf_pv(self):
        """Selector nicht gefunden → die vorsichtigere Lesart."""
        assert normalize("smart", None) == "pv"

    def test_off_und_now_ignorieren_alwayscharge(self):
        assert normalize("off", "on") == "off"
        assert normalize("now", "on") == "now"

    def test_unbekannt(self):
        assert normalize(None) == "pv"
        assert normalize("quatsch") == "pv"


class TestSchreibenAltesSchema:
    def test_ein_write_pro_modus(self):
        for m in OLD_OPTIONS:
            assert plan(m, new_scheme=False) == [(MODE, m)]


class TestSchreibenNeuesSchema:
    def test_pv(self):
        assert plan("pv", new_scheme=True) == [(AC, "off"), (MODE, "smart")]

    def test_minpv(self):
        assert plan("minpv", new_scheme=True) == [(AC, "on"), (MODE, "smart")]

    def test_now_laesst_alwayscharge_in_ruhe(self):
        assert plan("now", new_scheme=True) == [(MODE, "now")]

    def test_off_laesst_alwayscharge_in_ruhe(self):
        assert plan("off", new_scheme=True) == [(MODE, "off")]

    def test_alwayscharge_zuerst(self):
        """now→pv: stünde `mode` zuerst, läge Wattson für einen Tick in
        smart+on — also `minpv`, dem Zustand, den der Wechsel verlässt."""
        writes = plan("pv", new_scheme=True)
        assert writes[0][0] == AC


class TestRundlauf:
    def test_schreiben_dann_lesen_ergibt_das_ziel(self):
        """Jeder Wattson-Modus muss sich nach dem Schreiben wieder als
        derselbe lesen — sonst pendelt UC6 gegen sich selbst."""
        for target in ("off", "pv", "minpv", "now"):
            state = {"mode": "smart", AC: "on"}   # beliebiger Ausgangszustand
            for role, option in plan(target, new_scheme=True):
                state["mode" if role == MODE else AC] = option
            assert normalize(state["mode"], state[AC]) == target
