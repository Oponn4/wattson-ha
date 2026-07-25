"""Tests für die Schlafmodus-Ausnahme (UC2 darf nachts planen)."""
from __future__ import annotations

from conftest import const

SLEEP_EXEMPT_UCS = const.SLEEP_EXEMPT_UCS
UC_DEFINITIONS = const.UC_DEFINITIONS

ALL_UC_IDS = {uc_id for uc_id, _slug, _display, _default in UC_DEFINITIONS}

# UCs mit Wirkung im Haus (Heizstab, Klima, Kühlung, Batterie, evcc-Mode) oder
# mit Push — die müssen nachts stumm bleiben.
LOUD_UCS = {"uc4a", "uc4b", "uc6", "uc10", "uc11", "uc12", "uc14"}


def test_uc2_ist_ausgenommen():
    """Nachts liegende Billigfenster wären sonst unerreichbar."""
    assert "uc2" in SLEEP_EXEMPT_UCS


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
