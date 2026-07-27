"""Tests für die Schlafmodus-Ausnahme.

Maßstab ist nicht "hat Wirkung", sondern "weckt jemanden". Nachts stumm bleiben
müssen UCs, die im Haus etwas bewegen (Heizstab, Klima, Kühlung, Batterie) oder
pushen. Ausgenommen sind die, die nur einen Wert in evcc parken — der Nutzen
liegt gerade nachts, weil dort die günstigen Stunden liegen.
"""
from __future__ import annotations

from conftest import const

SLEEP_EXEMPT_UCS = const.SLEEP_EXEMPT_UCS
UC_DEFINITIONS = const.UC_DEFINITIONS

ALL_UC_IDS = {uc_id for uc_id, _slug, _display, _default in UC_DEFINITIONS}

# UCs mit Wirkung im Haus oder mit Push — die müssen nachts stumm bleiben.
LOUD_UCS = {"uc4a", "uc4b", "uc10", "uc11", "uc12", "uc14"}


def test_uc2_ist_ausgenommen():
    """Nachts liegende Billigfenster wären sonst unerreichbar."""
    assert "uc2" in SLEEP_EXEMPT_UCS


def test_uc6_ist_ausgenommen():
    """Seit v0.19.1. UC6 schreibt nur select.evcc_auto_mode — kein Push, keine
    Hausaktorik. Vorher war die Preisregel bis zum manuellen "Guten Morgen"
    wirkungslos: am 27.07.2026 hing der Schlafmodus von 23:53 bis in den Tag,
    und der günstige Mittagsblock wäre ungenutzt verstrichen."""
    assert "uc6" in SLEEP_EXEMPT_UCS


def test_keine_tippfehler_in_der_ausnahmeliste():
    """Ein Tippfehler würde stumm nichts bewirken — hier fällt er auf."""
    unbekannt = set(SLEEP_EXEMPT_UCS) - ALL_UC_IDS
    assert not unbekannt, f"unbekannte UC-IDs: {unbekannt}"


def test_laute_ucs_bleiben_gesperrt():
    versehentlich = set(SLEEP_EXEMPT_UCS) & LOUD_UCS
    assert not versehentlich, f"laute UCs dürfen nicht ausgenommen sein: {versehentlich}"


def test_loud_ucs_deckt_alle_ausser_ausnahmen_ab():
    """Wächter: neue UCs müssen bewusst einsortiert werden."""
    assert ALL_UC_IDS == LOUD_UCS | set(SLEEP_EXEMPT_UCS)
