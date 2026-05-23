"""Wattson Buttons — Force-Cycle + UC Resume."""
from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import wattson_device_info
from .const import DOMAIN, UC_DEFINITIONS
from .coordinator import WattsonCoordinator


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: WattsonCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list[ButtonEntity] = [WattsonRefreshButton(coordinator, entry)]
    for uc_id, name, _ in UC_DEFINITIONS:
        entities.append(WattsonUCResumeButton(coordinator, entry, uc_id, name))
    async_add_entities(entities)


class WattsonRefreshButton(ButtonEntity):
    def __init__(self, coordinator: WattsonCoordinator, entry: ConfigEntry) -> None:
        self._coordinator = coordinator
        self._attr_unique_id = f"{entry.entry_id}_refresh"
        self._attr_name = "Wattson Zyklus ausführen"
        self._attr_icon = "mdi:refresh"
        self._attr_device_info = wattson_device_info(entry)

    async def async_press(self) -> None:
        await self._coordinator.async_request_refresh()


class WattsonUCResumeButton(ButtonEntity):
    """Override-Cooldown manuell beenden — Wattson darf wieder eingreifen."""

    _attr_icon = "mdi:play-circle"

    def __init__(
        self, coordinator: WattsonCoordinator, entry: ConfigEntry,
        uc_id: str, display_name: str,
    ) -> None:
        self._coordinator = coordinator
        self._uc_id = uc_id
        self._attr_unique_id = f"{entry.entry_id}_{uc_id}_resume"
        self._attr_name = f"Wattson {uc_id.upper()} {display_name} Resume"
        self._attr_device_info = wattson_device_info(entry)

    async def async_press(self) -> None:
        await self._coordinator.override.async_resume(self._uc_id)
        await self._coordinator.async_request_refresh()
