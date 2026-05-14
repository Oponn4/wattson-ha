"""Wattson Sensoren."""
from __future__ import annotations

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import wattson_device_info
from .const import DOMAIN
from .coordinator import WattsonCoordinator


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: WattsonCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([
        WattsonStatusSensor(coordinator, entry),
        WattsonLastActionSensor(coordinator, entry),
        WattsonT300TargetSensor(coordinator, entry),
        WattsonEvccTargetSensor(coordinator, entry),
    ])


class WattsonBaseSensor(CoordinatorEntity[WattsonCoordinator], SensorEntity):
    def __init__(self, coordinator: WattsonCoordinator, entry: ConfigEntry, key: str, name: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_name = f"Wattson {name}"
        self._attr_has_entity_name = False
        self._attr_device_info = wattson_device_info(entry)


class WattsonStatusSensor(WattsonBaseSensor):
    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry, "status", "Status")
        self._attr_icon = "mdi:lightning-bolt"

    @property
    def native_value(self):
        if self.coordinator.data is None:
            return "unbekannt"
        d = self.coordinator.data
        return "dry-run" if d.dry_run else "aktiv"


class WattsonLastActionSensor(WattsonBaseSensor):
    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry, "last_action", "Letzte Aktion")
        self._attr_icon = "mdi:history"

    @property
    def native_value(self):
        if self.coordinator.data is None:
            return None
        actions = self.coordinator.data.last_actions
        return actions[0] if actions else "Keine"

    @property
    def extra_state_attributes(self):
        if self.coordinator.data is None:
            return {}
        return {"alle_aktionen": self.coordinator.data.last_actions}


class WattsonT300TargetSensor(WattsonBaseSensor):
    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry, "t300_target", "T300 Zieltemperatur")
        self._attr_icon = "mdi:thermometer"
        self._attr_native_unit_of_measurement = "°C"

    @property
    def native_value(self):
        return self.coordinator.data.t300_target if self.coordinator.data else None


class WattsonEvccTargetSensor(WattsonBaseSensor):
    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry, "evcc_target", "evcc Zielmodus")
        self._attr_icon = "mdi:car-electric"

    @property
    def native_value(self):
        return self.coordinator.data.evcc_target if self.coordinator.data else None
