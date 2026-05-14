"""Wattson Force-Cycle Button."""
from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import WattsonCoordinator


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: WattsonCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([WattsonRefreshButton(coordinator, entry)])


class WattsonRefreshButton(ButtonEntity):
    def __init__(self, coordinator: WattsonCoordinator, entry: ConfigEntry) -> None:
        self._coordinator = coordinator
        self._attr_unique_id = f"{entry.entry_id}_refresh"
        self._attr_name = "Wattson Zyklus ausführen"
        self._attr_icon = "mdi:refresh"

    async def async_press(self) -> None:
        await self._coordinator.async_request_refresh()
