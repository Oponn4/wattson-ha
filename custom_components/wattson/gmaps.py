"""Google Maps Distance Matrix — Wrapper mit In-Memory-Cache."""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass

import aiohttp

_LOGGER = logging.getLogger(__name__)

DISTANCE_MATRIX_URL = "https://maps.googleapis.com/maps/api/distancematrix/json"
CACHE_TTL_SECONDS = 7 * 24 * 3600   # 7 Tage pro Tupel


@dataclass(frozen=True)
class RouteResult:
    distance_km: float
    duration_min: int


class GoogleMapsClient:
    """Distance Matrix Wrapper. Caching pro (origin, destination)."""

    def __init__(self, api_key: str, session: aiohttp.ClientSession) -> None:
        self._api_key = api_key
        self._session = session
        self._cache: dict[tuple[str, str], tuple[float, RouteResult]] = {}

    async def distance(self, origin: str, destination: str) -> RouteResult | None:
        key = (origin.strip().lower(), destination.strip().lower())
        cached = self._cache.get(key)
        if cached:
            ts, result = cached
            if time.time() - ts < CACHE_TTL_SECONDS:
                _LOGGER.debug("gmaps cache hit: %s → %s = %.1fkm",
                              origin, destination, result.distance_km)
                return result

        params = {
            "origins": origin,
            "destinations": destination,
            "mode": "driving",
            "key": self._api_key,
        }
        try:
            async with self._session.get(
                DISTANCE_MATRIX_URL, params=params, timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                data = await resp.json()
        except (aiohttp.ClientError, TimeoutError) as e:
            _LOGGER.warning("gmaps Distance Matrix Call fehlgeschlagen: %s", e)
            return None

        if data.get("status") != "OK":
            _LOGGER.warning("gmaps Distance Matrix non-OK status: %s (%s)",
                            data.get("status"), data.get("error_message", ""))
            return None

        try:
            element = data["rows"][0]["elements"][0]
            if element.get("status") != "OK":
                _LOGGER.warning("gmaps Element non-OK: %s", element.get("status"))
                return None
            result = RouteResult(
                distance_km=element["distance"]["value"] / 1000.0,
                duration_min=int(round(element["duration"]["value"] / 60)),
            )
        except (KeyError, IndexError, TypeError) as e:
            _LOGGER.warning("gmaps Response unerwartet: %s", e)
            return None

        self._cache[key] = (time.time(), result)
        _LOGGER.info("gmaps: %s → %s = %.1fkm / %dmin",
                     origin, destination, result.distance_km, result.duration_min)
        return result
