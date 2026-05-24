"""Wattson Switches — Dry-Run + UC Enable-Toggles."""
from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import wattson_device_info
from .const import DOMAIN, UC_DEFINITIONS
from .coordinator import WattsonCoordinator


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: WattsonCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list[SwitchEntity] = [WattsonDryRunSwitch(coordinator, entry)]
    for uc_id, slug, display, _ in UC_DEFINITIONS:
        entities.append(WattsonUCEnabledSwitch(coordinator, entry, uc_id, slug, display))
    async_add_entities(entities)


class WattsonDryRunSwitch(CoordinatorEntity[WattsonCoordinator], SwitchEntity):
    def __init__(self, coordinator: WattsonCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_dry_run"
        self._attr_name = "Wattson Dry-Run"
        self._attr_icon = "mdi:test-tube"
        self._attr_device_info = wattson_device_info(entry)

    @property
    def is_on(self) -> bool:
        return self.coordinator.dry_run

    async def async_turn_on(self, **kwargs) -> None:
        self.coordinator.dry_run = True
        self.async_write_ha_state()
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs) -> None:
        self.coordinator.dry_run = False
        self.async_write_ha_state()
        await self.coordinator.async_request_refresh()


class WattsonUCEnabledSwitch(CoordinatorEntity[WattsonCoordinator], SwitchEntity):
    """Pro-UC On/Off — User kann einen Use Case komplett deaktivieren."""

    _attr_icon = "mdi:auto-mode"

    def __init__(
        self, coordinator: WattsonCoordinator, entry: ConfigEntry,
        uc_id: str, slug: str, display_name: str,
    ) -> None:
        super().__init__(coordinator)
        self._uc_id = uc_id
        self._attr_unique_id = f"{entry.entry_id}_{slug}_enabled"
        self._attr_name = f"Wattson {display_name}"
        self._attr_device_info = wattson_device_info(entry)

    @property
    def is_on(self) -> bool:
        return self.coordinator.override.is_enabled(self._uc_id)

    async def async_turn_on(self, **kwargs) -> None:
        await self.coordinator.override.async_set_enabled(self._uc_id, True)
        self.async_write_ha_state()
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs) -> None:
        await self.coordinator.override.async_set_enabled(self._uc_id, False)
        self.async_write_ha_state()
        await self.coordinator.async_request_refresh()
