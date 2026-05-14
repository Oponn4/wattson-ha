"""Wattson DataUpdateCoordinator — Entscheidungslogik."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import (
    CHEAP_LEVELS,
    DOMAIN,
    ENTITY_BATTERY_SOC,
    ENTITY_EVCC_CONNECTED,
    ENTITY_EVCC_MODE,
    ENTITY_EVCC_RANGE,
    ENTITY_EVCC_SOC,
    ENTITY_PRICE,
    ENTITY_PRICE_LEVEL,
    ENTITY_PRICE_RANKING,
    ENTITY_PV_POWER,
    ENTITY_PV_SURPLUS,
    ENTITY_SLEEP,
    ENTITY_T300_HEIZSTAB,
    ENTITY_T300_SOLL,
    ENTITY_T300_TANK,
    NOTIFY_SERVICE,
    PV_SURPLUS_OFF,
    PV_SURPLUS_ON,
    SCAN_INTERVAL_SECONDS,
    SOC_WARNUNG,
    T300_TEMP_CHEAP,
    T300_TEMP_MIN,
    T300_TEMP_NORMAL,
    T300_TEMP_TEUER,
)

_LOGGER = logging.getLogger(__name__)


@dataclass
class WattsonData:
    """Aktueller Systemzustand + Wattson-Status."""
    # Tibber
    price: float = 0.0
    price_ranking: float = 0.5
    price_level: str = "normal"

    # PV / E3DC
    pv_power: int = 0
    battery_soc: int = 0
    pv_surplus: int = 0

    # T300
    t300_tank_temp: float = 50.0
    t300_solltemperatur: float = 52.0
    t300_heizstab_on: bool = False

    # evcc / Auto
    car_connected: bool = False
    car_soc: float = 0.0
    car_range: int = 0
    evcc_mode: str = "pv"

    # Guards
    sleep_mode: bool = False

    # Wattson-Status (für Sensoren)
    dry_run: bool = True
    last_actions: list[str] = field(default_factory=list)
    t300_target: float = 52.0
    evcc_target: str = "pv"

    # intern
    low_soc_notified: bool = False


class WattsonCoordinator(DataUpdateCoordinator[WattsonData]):

    def __init__(self, hass: HomeAssistant, dry_run: bool) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=SCAN_INTERVAL_SECONDS),
        )
        self._dry_run = dry_run
        self._prev: WattsonData = WattsonData(dry_run=dry_run)

    @property
    def dry_run(self) -> bool:
        return self._dry_run

    @dry_run.setter
    def dry_run(self, value: bool) -> None:
        self._dry_run = value
        if self.data:
            self.data.dry_run = value

    def _state(self, entity_id: str, default=None):
        state = self.hass.states.get(entity_id)
        if state is None or state.state in ("unknown", "unavailable"):
            return default
        return state.state

    def _attr(self, entity_id: str, attribute: str, default=None):
        state = self.hass.states.get(entity_id)
        if state is None:
            return default
        return state.attributes.get(attribute, default)

    def _fval(self, entity_id: str, default: float = 0.0) -> float:
        try:
            return float(self._state(entity_id, default))
        except (TypeError, ValueError):
            return default

    def _ival(self, entity_id: str, default: int = 0) -> int:
        return int(self._fval(entity_id, default))

    def _act(self, domain: str, service: str, **kwargs) -> str:
        desc = f"{domain}.{service}({kwargs})"
        if self._dry_run:
            _LOGGER.info("[DRY-RUN] %s", desc)
        else:
            self.hass.services.call(domain, service, kwargs, blocking=False)
            _LOGGER.info("Aktion: %s", desc)
        return desc

    async def _async_update_data(self) -> WattsonData:
        s = WattsonData(dry_run=self._dry_run)

        # Zustand lesen
        s.price         = self._fval(ENTITY_PRICE)
        s.price_ranking = float(self._attr(ENTITY_PRICE_RANKING, "intraday_price_ranking", 0.5) or 0.5)
        s.price_level   = self._state(ENTITY_PRICE_LEVEL, "normal") or "normal"
        s.pv_power      = self._ival(ENTITY_PV_POWER)
        s.battery_soc   = self._ival(ENTITY_BATTERY_SOC)
        s.pv_surplus    = self._ival(ENTITY_PV_SURPLUS)
        s.t300_tank_temp       = self._fval(ENTITY_T300_TANK, 50.0)
        s.t300_solltemperatur  = self._fval(ENTITY_T300_SOLL, 52.0)
        s.t300_heizstab_on     = self._state(ENTITY_T300_HEIZSTAB) == "on"
        s.car_connected        = self._state(ENTITY_EVCC_CONNECTED) == "on"
        s.car_soc              = self._fval(ENTITY_EVCC_SOC)
        s.car_range            = self._ival(ENTITY_EVCC_RANGE)
        s.evcc_mode            = self._state(ENTITY_EVCC_MODE, "pv") or "pv"
        s.sleep_mode           = self._state(ENTITY_SLEEP) == "on"
        s.low_soc_notified     = self._prev.low_soc_notified

        actions: list[str] = []
        prefix = "[DRY-RUN] " if self._dry_run else ""

        _LOGGER.info(
            "%sZyklus — PV:%dW Bat:%d%% Überschuss:%dW | "
            "Tibber:%.3f€ Rank:%.2f (%s) | "
            "T300:%.1f°C Soll:%.1f°C | Auto:%.0f%% %s evcc:%s",
            prefix,
            s.pv_power, s.battery_soc, s.pv_surplus,
            s.price, s.price_ranking, s.price_level,
            s.t300_tank_temp, s.t300_solltemperatur,
            s.car_soc, "an" if s.car_connected else "weg", s.evcc_mode,
        )

        if s.sleep_mode:
            _LOGGER.info("Schlafmodus — keine Aktionen")
            s.last_actions = ["Schlafmodus aktiv"]
            self._prev = s
            return s

        # ── UC4a: T300 Solltemperatur via Tibber ──────────────────────────────
        if s.t300_tank_temp < T300_TEMP_MIN:
            new_temp = T300_TEMP_NORMAL
            reason = f"Notfall (Tank {s.t300_tank_temp:.1f}°C)"
        elif s.price_ranking <= 0.33 or s.price < 0.20:
            new_temp = T300_TEMP_CHEAP
            reason = f"günstig (Rank {s.price_ranking:.2f})"
        elif s.price_ranking >= 0.67 and s.price >= 0.20:
            new_temp = T300_TEMP_TEUER
            reason = f"teuer (Rank {s.price_ranking:.2f})"
        else:
            new_temp = T300_TEMP_NORMAL
            reason = f"normal (Rank {s.price_ranking:.2f})"

        s.t300_target = new_temp
        if abs(new_temp - s.t300_solltemperatur) >= 1.0:
            _LOGGER.info("T300: %.1f°C → %.1f°C (%s)", s.t300_solltemperatur, new_temp, reason)
            actions.append(self._act("input_number", "set_value",
                                     entity_id=ENTITY_T300_SOLL, value=new_temp))
        else:
            _LOGGER.info("T300: %.1f°C OK (%s)", s.t300_solltemperatur, reason)

        # ── UC4b: E-Heizstab bei PV-Überschuss ───────────────────────────────
        if s.pv_surplus >= PV_SURPLUS_ON and not s.t300_heizstab_on:
            _LOGGER.info("E-Heizstab EIN (Überschuss %dW)", s.pv_surplus)
            actions.append(self._act("switch", "turn_on", entity_id=ENTITY_T300_HEIZSTAB))
        elif s.pv_surplus < PV_SURPLUS_OFF and s.t300_heizstab_on:
            _LOGGER.info("E-Heizstab AUS (Überschuss %dW)", s.pv_surplus)
            actions.append(self._act("switch", "turn_off", entity_id=ENTITY_T300_HEIZSTAB))

        # ── UC6/UC7: evcc Modus ───────────────────────────────────────────────
        if s.car_connected:
            if s.price_level in CHEAP_LEVELS:
                target_mode = "minpv"
                reason = f"Strom günstig ({s.price_level})"
            elif s.pv_power > 500 and s.battery_soc >= 60:
                target_mode = "pv"
                reason = f"PV {s.pv_power}W, Bat {s.battery_soc}%"
            else:
                target_mode = "pv"
                reason = "Standard"

            s.evcc_target = target_mode
            if target_mode != s.evcc_mode:
                _LOGGER.info("evcc: %s → %s (%s)", s.evcc_mode, target_mode, reason)
                actions.append(self._act("select", "select_option",
                                         entity_id=ENTITY_EVCC_MODE, option=target_mode))
            else:
                _LOGGER.info("evcc: %s OK (%s)", s.evcc_mode, reason)

        # ── UC1: Niedrig-SOC Warnung ──────────────────────────────────────────
        if s.car_soc > 0 and s.car_soc < SOC_WARNUNG and not s.low_soc_notified:
            msg = f"ORA 03 Akku niedrig: {s.car_soc:.0f}% ({s.car_range} km)"
            _LOGGER.warning("UC1: %s", msg)
            actions.append(self._act(
                "notify", NOTIFY_SERVICE.split(".")[1],
                message=msg, title="⚡ Wattson: Niedriger Ladestand",
            ))
            s.low_soc_notified = True
        elif s.car_soc >= SOC_WARNUNG:
            s.low_soc_notified = False

        s.last_actions = actions if actions else ["Keine Änderungen"]
        self._prev = s
        return s
