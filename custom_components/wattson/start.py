"""Start-Freigabe: erst handeln, wenn die Kern-Sensoren und Dienste da sind.

Warum es das gibt (v0.20.19): seit v0.20.6 handelt Wattson erst, wenn HA
`running` meldet. Das heißt aber nur, dass der Start-Ablauf durch ist — nicht,
dass jede Integration schon Werte liefert. Am 11.10.2026 waren die
Proxon-Entities nach dem Neustart noch nicht da, als der erste Tick lief; am
12. und 13.10. fehlte `tibber.get_prices` im Start-Tick. Liest Wattson in so
einem Moment, bekommt es Ersatzwerte (`_fval`-Default) und entscheidet auf
ihnen.

Die Freigabe wartet deshalb, bis alle Abhängigkeiten da sind — längstens
`max_warten_min`. Danach geht es trotzdem los: eine einzelne tote Integration
darf nicht den ganzen Coordinator anhalten. Die Freigabe gilt nur für den
Start; fällt später eine Integration aus, greift das wie bisher je UC.

Bewusst frei von Home-Assistant-Importen: Prüffunktionen kommen herein, so ist
die Logik ohne HA-Installation testbar.
"""
from __future__ import annotations

from collections.abc import Callable, Iterable

MAX_WARTEN_MIN = 10.0
NEUER_VERSUCH_S = 30.0

#: Werte, die keine Aussage erlauben — wie `override.UNKNOWN_VALUES`.
OHNE_WERT = ("unavailable", "unknown", "none", "")


def entity_hat_wert(state: str | None) -> bool:
    """True, wenn die Entity existiert und einen echten Wert trägt."""
    return state is not None and str(state).strip().lower() not in OHNE_WERT


def fehlende_abhaengigkeiten(
    *,
    entities: Iterable[str],
    dienste: Iterable[str],
    zustand: Callable[[str], str | None],
    dienst_da: Callable[[str, str], bool],
) -> list[str]:
    """Was fehlt noch? Entities ohne Wert und Dienste (`domain.service`)."""
    fehlend = [e for e in entities if not entity_hat_wert(zustand(e))]
    for dienst in dienste:
        domain, _, name = dienst.partition(".")
        if not dienst_da(domain, name):
            fehlend.append(dienst)
    return fehlend


def start_freigabe(
    *,
    fehlend: list[str],
    wartet_min: float,
    max_warten_min: float = MAX_WARTEN_MIN,
) -> tuple[bool, str]:
    """Darf Wattson handeln? Returns (freigegeben, Grund für den Status)."""
    if not fehlend:
        return True, "alle Abhängigkeiten da"
    if wartet_min >= max_warten_min:
        return True, (
            f"nach {wartet_min:.0f} min ohne {', '.join(fehlend)} gestartet"
        )
    return False, (
        f"wartet auf {', '.join(fehlend)} "
        f"({wartet_min:.0f} von {max_warten_min:.0f} min)"
    )
