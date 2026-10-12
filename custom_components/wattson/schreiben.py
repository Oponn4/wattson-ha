"""Einen Write absetzen, auf die Antwort warten, das Ergebnis zurücklesen.

Warum es das gibt (v0.20.16): bis v0.20.15 schickte `_try_act` jeden Write mit
`blocking=False` ab und buchte ihn sofort. Ob er ankam, sollte der nächste Tick
herausfinden. Am 08.10.2026 lehnte die Proxon den Heizstab-Write um 13:04:57
mit Modbus-Exception 0x03 ab. Wattson buchte „eingeschaltet", die
Mindest-Verweildauer hielt den Zustand 15 min fest, und als UC4b um 13:30
wieder einschalten wollte, war das 11-min-Fenster für „Write kam nicht an"
vorbei: der eigene verlorene Write galt als Hand-Eingriff, UC4b war bis
Mitternacht gesperrt.

Jetzt gilt ein Write erst dann als ausgeführt, wenn der Service ohne Fehler
zurückkam **und** die Entity den Zielwert zeigt. Sonst nach einer Pause erneut,
insgesamt `versuche` Mal. Eile hat Wattson nicht: ein Tick dauert 5 min.

Bewusst frei von Home-Assistant-Importen: Service-Aufruf und Zustandsabfrage
kommen als Funktionen herein, so ist die Logik ohne HA-Installation testbar.
"""
from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import Any

VERSUCHE = 3
PAUSE_ZWISCHEN_VERSUCHEN_S = 5.0
# Wie lange nach dem Service-Call auf den Zielwert gewartet wird. Proxon zeigt
# ihn sofort (optimistischer Wert), evcc erst nach dem eigenen Poll — für evcc
# ist die Verzögerung nicht gemessen, deshalb großzügig.
BESTAETIGEN_TIMEOUT_S = 30.0
BESTAETIGEN_TAKT_S = 0.5


async def schreiben_bestaetigt(
    aufrufen: Callable[[], Awaitable[Any]],
    lesen: Callable[[], Any],
    ist_ziel: Callable[[Any], bool],
    *,
    versuche: int = VERSUCHE,
    pause_s: float = PAUSE_ZWISCHEN_VERSUCHEN_S,
    bestaetigen_timeout_s: float = BESTAETIGEN_TIMEOUT_S,
    takt_s: float = BESTAETIGEN_TAKT_S,
    schlafen: Callable[[float], Awaitable[None]] = asyncio.sleep,
    uhr: Callable[[], float] = time.monotonic,
) -> str | None:
    """Write ausführen und bestätigen. None = angekommen, sonst der Grund.

    `aufrufen` setzt den Service-Call ab und wartet auf ihn; jede Ausnahme
    daraus zählt als abgelehnter Versuch. `lesen` liefert den aktuellen
    Zustand, `ist_ziel` sagt, ob er dem gewollten Wert entspricht.
    """
    grund = "kein Versuch"
    for versuch in range(1, versuche + 1):
        try:
            await aufrufen()
        except Exception as err:  # noqa: BLE001 — jeder Fehlschlag ist ein Fehlversuch
            grund = f"Versuch {versuch}/{versuche}: {type(err).__name__}: {err}"
        else:
            ende = uhr() + bestaetigen_timeout_s
            while True:
                if ist_ziel(lesen()):
                    return None
                if uhr() >= ende:
                    break
                await schlafen(takt_s)
            grund = (
                f"Versuch {versuch}/{versuche}: Ist {lesen()!r} "
                f"nach {bestaetigen_timeout_s:.0f} s"
            )
        if versuch < versuche:
            await schlafen(pause_s)
    return grund
