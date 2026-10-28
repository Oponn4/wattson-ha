"""Kalender abrufen, ohne dass ein Fehler den Tick abbricht (v0.20.28).

Warum es das gibt: Bis v0.20.27 fing `_fetch_calendar_events` nur
`HomeAssistantError`. Die CalDAV-Integration reicht Fehler der Bibliothek aber
roh durch. Am 28.10.2026 um 21:45 meldete iCloud
`caldav.lib.error.RateLimitError ... Retry after: 1862`, der Fehler flog bis in
`_async_update_data`, und Wattson war für einen Tick `unavailable`. Seit
v0.20.26 (Sauna-Plan fragt `calendar.barchen` jeden Tick) passierte das fünf
Mal in drei Tagen.

Bewusst frei von Home-Assistant-Importen, damit ohne HA testbar.
"""
from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from typing import Any

_LOGGER = logging.getLogger(__name__)

Abruf = Callable[[list[str], int], Awaitable[dict[str, Any] | None]]


async def termine_holen(
    abruf: Abruf, entity_ids: list[str], hours: int,
) -> list[dict] | None:
    """Events der Kalender, zusammengeführt.

    None = Abruf fehlgeschlagen, [] = wirklich keine Termine. Die
    Unterscheidung ist wichtig: das Aufräumen alter Fahrpläne darf einen
    gültigen Plan nicht löschen, nur weil der Kalender gerade nicht antwortet.

    Jeder Fehler zählt als „nicht abrufbar", nicht nur `HomeAssistantError`:
    welche Ausnahme eine Kalender-Integration durchreicht, liegt nicht bei uns.
    """
    if not entity_ids:
        return []
    try:
        resp = await abruf(entity_ids, hours)
    except Exception as e:  # noqa: BLE001 — s. Docstring
        _LOGGER.warning(
            "calendar.get_events fehlgeschlagen (%s): %s", type(e).__name__, e,
        )
        return None
    if not resp:
        return None
    # Response ist {entity_id: {"events": [...]}, ...} — mergen
    merged: list[dict] = []
    for cal_id, cal_data in resp.items():
        if isinstance(cal_data, dict):
            for ev in cal_data.get("events", []):
                merged.append({**ev, "_calendar": cal_id})
    return merged


def abruf_intervall_min(
    now: datetime, *, normal_min: int, abend_min: int, abend_h: tuple[int, int],
) -> int:
    """Abstand zwischen zwei Abrufen: im Abendfenster enger, sonst stündlich.

    `now` in Ortszeit. Spontane Sauna-Termine entstehen typischerweise
    zwischen 15 und 20 Uhr; außerhalb reicht einmal je Stunde.
    """
    von, bis = abend_h
    return abend_min if von <= now.hour < bis else normal_min


def abruf_faellig(
    letzter_versuch: datetime | None, now: datetime, intervall_min: int,
) -> bool:
    """Darf der Kalender wieder gefragt werden?

    Gezählt wird der letzte *Versuch*, nicht der letzte Erfolg: bei einem
    Rate-Limit soll Wattson nicht jeden Tick nachhaken.
    """
    if letzter_versuch is None:
        return True
    return now - letzter_versuch >= timedelta(minutes=intervall_min)
