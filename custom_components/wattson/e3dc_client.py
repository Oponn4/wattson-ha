"""E3DC-Proxy über e3dc_rscp HA-Integration (kein HTTP-Proxy mehr)."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

# e3dc_rscp device_id der S10E (unveränderlich, da feste RSCP-Verbindung)
_E3DC_DEVICE_ID = "7c466a00ea0b04fb85e228dff3cdb43a"

# HA-Sensoren für aktuelle Power-Limits (kW, e3dc_rscp-Integration)
_SENSOR_MAX_DISCHARGE = "sensor.s10e_maximum_discharge"
_SENSOR_MAX_CHARGE    = "sensor.s10e_maximum_charge"


class E3DCClient:
    """Schreibt E3DC-Power-Limits über e3dc_rscp-Services; liest aus HA-Sensoren.

    Ersetzt den alten HTTP-Proxy (10.42.2.5:8080/api/...).
    Gleiche Methoden-Signatur → coordinator.py unverändert.
    """

    def __init__(self, hass: HomeAssistant) -> None:
        self._hass = hass

    def _kw_sensor_to_w(self, entity_id: str, fallback: int) -> int:
        state = self._hass.states.get(entity_id)
        if state is None or state.state in ("unknown", "unavailable"):
            return fallback
        try:
            return round(float(state.state) * 1000)
        except (ValueError, TypeError):
            return fallback

    async def get_power_settings(self) -> dict | None:
        """Gibt {maxDischargePower, maxChargePower} in W zurück, oder None wenn unavailable."""
        max_d = self._kw_sensor_to_w(_SENSOR_MAX_DISCHARGE, -1)
        max_c = self._kw_sensor_to_w(_SENSOR_MAX_CHARGE, -1)
        if max_d < 0 or max_c < 0:
            _LOGGER.warning(
                "E3DC power_settings unavailable: discharge=%s, charge=%s",
                self._hass.states.get(_SENSOR_MAX_DISCHARGE),
                self._hass.states.get(_SENSOR_MAX_CHARGE),
            )
            return None
        return {"maxDischargePower": max_d, "maxChargePower": max_c}

    async def set_power_limits(
        self,
        max_charge_w: int | None = None,
        max_discharge_w: int | None = None,
    ) -> bool:
        data: dict = {"device_id": _E3DC_DEVICE_ID}
        if max_charge_w is not None:
            data["max_charge"] = max(0, int(max_charge_w))
        if max_discharge_w is not None:
            data["max_discharge"] = max(0, int(max_discharge_w))
        try:
            await self._hass.services.async_call(
                "e3dc_rscp", "set_power_limits", data, blocking=True,
            )
            return True
        except Exception as exc:
            _LOGGER.warning("e3dc_rscp.set_power_limits fehlgeschlagen: %s", exc)
            return False

    async def set_max_discharge_power(self, watts: int) -> bool:
        return await self.set_power_limits(max_discharge_w=watts)

    async def set_max_charge_power(self, watts: int) -> bool:
        return await self.set_power_limits(max_charge_w=watts)
