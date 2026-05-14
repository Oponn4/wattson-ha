"""Wattson Dry-Run Switch."""
from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import WattsonCoordinator


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: WattsonCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([WattsonDryRunSwitch(coordinator, entry)])


class WattsonDryRunSwitch(CoordinatorEntity[WattsonCoordinator], SwitchEntity):
    def __init__(self, coordinator: WattsonCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_dry_run"
        self._attr_name = "Wattson Dry-Run"
        self._attr_icon = "mdi:test-tube"

    @property
    def is_on(self) -> bool:
        return self.coordinator.dry_run

    async def async_turn_on(self, **kwargs) -> None:
        self.coordinator.dry_run = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs) -> None:
        self.coordinator.dry_run = False
        self.async_write_ha_state()
