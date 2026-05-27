"""Async HTTP wrapper für e3dc-rest API (https://github.com/vchrisb/e3dc-rest)."""
from __future__ import annotations

import logging
from dataclasses import dataclass

import aiohttp

_LOGGER = logging.getLogger(__name__)

REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=10)


@dataclass
class E3DCPoll:
    soc: int                # %
    pv_power: int           # W
    house_power: int        # W
    battery_power: int      # W (positiv=Entladung, negativ=Laden — je nach API-Variante)
    grid_power: int         # W (positiv=Bezug, negativ=Einspeisung)


class E3DCClient:
    """Minimaler Client für e3dc-rest API. Read-only safe, Schreiboperationen
    sollten von Wattson-Coordinator über Dry-Run-Pfad gehen."""

    def __init__(self, base_url: str, user: str, password: str, session: aiohttp.ClientSession) -> None:
        self._base_url = base_url.rstrip("/")
        self._auth = aiohttp.BasicAuth(user, password)
        self._session = session

    async def _get(self, path: str) -> dict | None:
        url = f"{self._base_url}{path}"
        try:
            async with self._session.get(url, auth=self._auth, timeout=REQUEST_TIMEOUT) as resp:
                if resp.status != 200:
                    _LOGGER.warning("E3DC GET %s → HTTP %d", path, resp.status)
                    return None
                return await resp.json()
        except (aiohttp.ClientError, TimeoutError) as e:
            _LOGGER.warning("E3DC GET %s fehlgeschlagen: %s", path, e)
            return None

    async def _post(self, path: str, payload: dict) -> bool:
        url = f"{self._base_url}{path}"
        try:
            async with self._session.post(
                url, auth=self._auth, json=payload, timeout=REQUEST_TIMEOUT,
            ) as resp:
                if resp.status != 200:
                    body = await resp.text()
                    _LOGGER.warning("E3DC POST %s → HTTP %d: %s", path, resp.status, body[:200])
                    return False
                return True
        except (aiohttp.ClientError, TimeoutError) as e:
            _LOGGER.warning("E3DC POST %s fehlgeschlagen: %s", path, e)
            return False

    async def poll(self) -> E3DCPoll | None:
        data = await self._get("/api/poll")
        if not data:
            return None
        try:
            cons = data.get("consumption", {})
            prod = data.get("production", {})
            return E3DCPoll(
                soc=int(data.get("stateOfCharge", 0)),
                pv_power=int(prod.get("solar", 0)),
                house_power=int(cons.get("house", 0)),
                battery_power=int(cons.get("battery", 0)),
                grid_power=int(prod.get("grid", 0)),
            )
        except (KeyError, ValueError, TypeError) as e:
            _LOGGER.warning("E3DC poll-Parse fehlgeschlagen: %s", e)
            return None

    async def get_idle_periods(self) -> dict | None:
        """Returns {idleCharge: [...], idleDischarge: [...]} oder None.
        Bei frischer E3DC ohne Idle-Konfig liefert API null → wir geben dann
        leere Default-Struktur zurück, damit Set-Operationen funktionieren."""
        data = await self._get("/api/idle_periods")
        if data is None or data == {}:
            return {"idleCharge": [], "idleDischarge": []}
        return data

    async def set_idle_periods(self, periods: dict) -> bool:
        """Setzt komplette idle_periods Struktur. Format wie get_idle_periods.
        Erwartet {idleCharge: [{day, start: [h,m], end: [h,m], active}], idleDischarge: [...]}."""
        return await self._post("/api/idle_periods", periods)

    async def get_power_settings(self) -> dict | None:
        return await self._get("/api/power_settings")

    async def set_power_settings(self, settings: dict) -> bool:
        return await self._post("/api/power_settings", settings)

    async def set_max_discharge_power(self, watts: int) -> bool:
        """Setzt nur maxDischargePower; übernimmt aktuellen maxChargePower
        und dischargeStartPower damit nichts unbeabsichtigt verändert wird.
        Aktiviert auch powerLimitsUsed=True (sonst werden Limits ignoriert)."""
        return await self.set_power_limits(max_discharge_w=watts)

    async def set_max_charge_power(self, watts: int) -> bool:
        """Setzt nur maxChargePower (für UC14 Netzladen)."""
        return await self.set_power_limits(max_charge_w=watts)

    async def set_power_limits(
        self, max_charge_w: int | None = None, max_discharge_w: int | None = None,
    ) -> bool:
        """Atomarer Set beider Power-Limits — vermeidet doppelten POST bei UC14.
        Ungesetzte Parameter behalten aktuellen Wert. powerLimitsUsed wird immer
        auf True gesetzt (sonst ignoriert die Anlage Limits)."""
        current = await self.get_power_settings()
        if current is None:
            _LOGGER.warning("E3DC: kann power_settings nicht lesen für set_power_limits")
            return False
        payload = {
            "powerLimitsUsed": True,
            "maxChargePower": int(max(0, max_charge_w))
                if max_charge_w is not None
                else int(current.get("maxChargePower", 1500)),
            "maxDischargePower": int(max(0, max_discharge_w))
                if max_discharge_w is not None
                else int(current.get("maxDischargePower", 1500)),
            "dischargeStartPower": int(current.get("dischargeStartPower", 65)),
        }
        return await self._post("/api/power_settings", payload)


def make_discharge_period(weekday: int, start_h: int, start_m: int, end_h: int, end_m: int) -> dict:
    """Erstellt einen einzelnen idleDischarge-Eintrag im e3dc-rest Format."""
    return {
        "day": weekday,
        "start": [start_h, start_m],
        "end": [end_h, end_m],
        "active": True,
    }


def empty_periods_for_week() -> dict:
    """Alle 7 Tage mit inaktiven 00:00-00:00 Slots — explizites "alles aus"."""
    return {
        "idleCharge": [
            {"day": d, "start": [0, 0], "end": [0, 0], "active": False}
            for d in range(7)
        ],
        "idleDischarge": [
            {"day": d, "start": [0, 0], "end": [0, 0], "active": False}
            for d in range(7)
        ],
    }
