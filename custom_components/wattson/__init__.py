"""Wattson — Home Energy Coordinator."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.device_registry import DeviceInfo

from .const import (
    CONF_AUTO_CALENDARS,
    CONF_CALENDAR_ENTITY,
    CONF_E3DC_PASSWORD,
    CONF_E3DC_URL,
    CONF_E3DC_USER,
    CONF_EVCC_VEHICLE_NAME,
    CONF_EVENT_LOOKAHEAD,
    CONF_GMAPS_KEY,
    CONF_HOME_ADDRESS,
    CONF_SAFETY_MARGIN,
    CONF_VEHICLE_CAPACITY,
    CONF_VEHICLE_CONSUMPTION,
    DEFAULT_AUTO_CALENDARS,
    DEFAULT_E3DC_PASSWORD,
    DEFAULT_E3DC_URL,
    DEFAULT_E3DC_USER,
    DEFAULT_EVCC_VEHICLE_NAME,
    DEFAULT_EVENT_LOOKAHEAD,
    DEFAULT_HOME_ADDRESS,
    DEFAULT_SAFETY_MARGIN,
    DEFAULT_VEHICLE_CAPACITY,
    DEFAULT_VEHICLE_CONSUMPTION,
    DOMAIN,
)
from .coordinator import WattsonCoordinator, WattsonTripConfig
from .e3dc_client import E3DCClient
from .gmaps import GoogleMapsClient

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["sensor", "switch", "button"]


def wattson_device_info(entry: ConfigEntry) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name="Wattson",
        manufacturer="Christian",
        model="Energy Coordinator",
        configuration_url="https://github.com/Oponn4/wattson-ha",
    )


def _opt(entry: ConfigEntry, key: str, default):
    return entry.options.get(key, entry.data.get(key, default))


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    dry_run = _opt(entry, "dry_run", True)

    gmaps_key = _opt(entry, CONF_GMAPS_KEY, "")
    gmaps = None
    if gmaps_key:
        gmaps = GoogleMapsClient(gmaps_key, async_get_clientsession(hass))

    # Multi-Calendar mit Migration: alter Single-Key calendar_entity → Liste
    auto_calendars = _opt(entry, CONF_AUTO_CALENDARS, None)
    if not auto_calendars:
        legacy = _opt(entry, CONF_CALENDAR_ENTITY, None)
        auto_calendars = [legacy] if legacy else list(DEFAULT_AUTO_CALENDARS)

    trip_cfg = WattsonTripConfig(
        gmaps=gmaps,
        home_address=_opt(entry, CONF_HOME_ADDRESS, DEFAULT_HOME_ADDRESS),
        auto_calendars=auto_calendars,
        vehicle_consumption=float(_opt(entry, CONF_VEHICLE_CONSUMPTION, DEFAULT_VEHICLE_CONSUMPTION)),
        vehicle_capacity=float(_opt(entry, CONF_VEHICLE_CAPACITY, DEFAULT_VEHICLE_CAPACITY)),
        safety_margin=int(_opt(entry, CONF_SAFETY_MARGIN, DEFAULT_SAFETY_MARGIN)),
        evcc_vehicle_name=_opt(entry, CONF_EVCC_VEHICLE_NAME, DEFAULT_EVCC_VEHICLE_NAME),
        lookahead_hours=int(_opt(entry, CONF_EVENT_LOOKAHEAD, DEFAULT_EVENT_LOOKAHEAD)),
    )

    e3dc_url = _opt(entry, CONF_E3DC_URL, DEFAULT_E3DC_URL) or ""
    e3dc = None
    if e3dc_url.strip():
        e3dc = E3DCClient(
            e3dc_url.strip(),
            _opt(entry, CONF_E3DC_USER, DEFAULT_E3DC_USER) or "",
            _opt(entry, CONF_E3DC_PASSWORD, DEFAULT_E3DC_PASSWORD) or "",
            async_get_clientsession(hass),
        )

    coordinator = WattsonCoordinator(
        hass, dry_run=dry_run, trip_cfg=trip_cfg, e3dc=e3dc,
    )
    await coordinator.async_setup()
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
    return unload_ok
