"""Fahrplan-Schreibzugriff direkt auf die evcc-REST-API.

Warum nicht über die `evcc_intg`-Integration: deren Service
`evcc_intg.set_vehicle_plan` meldet in Home Assistant Erfolg, ohne dass in
evcc ein Plan entsteht (verifiziert am 2026-07-25 — HA sagt „Successfully
executed", `GET /api/state` zeigt danach `plan=None`; derselbe Vorgang direkt
gegen die API liefert HTTP 200 und den Plan). Weil der Service-Aufruf nicht
fehlschlägt, sondern stillschweigend wirkungslos bleibt, hat UC2 zehn Tage
lang „Plan aktiv" gemeldet, ohne je einen gesetzt zu haben.

Die hier verwendeten Endpunkte sind gegen evcc 0.312 geprüft:
  POST   /api/vehicles/{name}/plan/soc/{soc}/{rfc3339}
  DELETE /api/vehicles/{name}/plan/soc
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING
from urllib.parse import quote

import aiohttp

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

REQUEST_TIMEOUT_S = 10


class EvccClient:
    """Setzt und löscht Fahrzeug-Fahrpläne über die evcc-REST-API."""

    def __init__(self, hass: HomeAssistant, base_url: str) -> None:
        self._hass = hass
        self._base_url = base_url.rstrip("/")

    @property
    def configured(self) -> bool:
        return bool(self._base_url)

    async def _request(self, method: str, path: str) -> dict | None:
        """Antwort-JSON, oder None bei Fehler (wird geloggt, nie geworfen)."""
        from homeassistant.helpers.aiohttp_client import async_get_clientsession

        url = f"{self._base_url}{path}"
        session = async_get_clientsession(self._hass)
        try:
            async with session.request(
                method, url, timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT_S)
            ) as resp:
                if resp.status != 200:
                    body = (await resp.text())[:200]
                    _LOGGER.warning(
                        "evcc %s %s → HTTP %s: %s", method, path, resp.status, body
                    )
                    return None
                return await resp.json(content_type=None)
        except (aiohttp.ClientError, TimeoutError) as ex:
            _LOGGER.warning("evcc %s %s fehlgeschlagen: %s", method, path, ex)
            return None

    async def set_vehicle_plan(
        self, vehicle: str, soc: int, departure: datetime
    ) -> bool:
        """Fahrplan setzen. True nur, wenn evcc ihn bestätigt zurückmeldet."""
        if not self.configured:
            _LOGGER.warning("evcc-URL nicht konfiguriert — Fahrplan nicht gesetzt")
            return False
        stamp = quote(departure.isoformat(), safe="")
        result = await self._request(
            "POST", f"/api/vehicles/{quote(vehicle)}/plan/soc/{int(soc)}/{stamp}"
        )
        # evcc antwortet mit dem angelegten Plan — als Quittung auswerten,
        # statt HTTP 200 blind zu glauben
        if not isinstance(result, dict) or result.get("soc") is None:
            _LOGGER.warning(
                "evcc hat den Fahrplan nicht bestätigt (Antwort: %s)", result
            )
            return False
        _LOGGER.info(
            "evcc-Fahrplan gesetzt: %s → %s%% bis %s",
            vehicle, result.get("soc"), result.get("time"),
        )
        return True

    async def delete_vehicle_plan(self, vehicle: str) -> bool:
        if not self.configured:
            return False
        result = await self._request(
            "DELETE", f"/api/vehicles/{quote(vehicle)}/plan/soc"
        )
        if result is None:
            return False
        _LOGGER.info("evcc-Fahrplan für %s gelöscht", vehicle)
        return True
