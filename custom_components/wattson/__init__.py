"""Wattson — Home Energy Coordinator."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo

from .const import DOMAIN
from .coordinator import WattsonCoordinator

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


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    dry_run = entry.options.get("dry_run", entry.data.get("dry_run", True))
    coordinator = WattsonCoordinator(hass, dry_run=dry_run)
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
