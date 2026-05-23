"""Wattson Sensoren."""
from __future__ import annotations

from homeassistant.components.sensor import SensorEntity
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
    entities: list[SensorEntity] = [
        WattsonStatusSensor(coordinator, entry),
        WattsonLastActionSensor(coordinator, entry),
        WattsonT300TargetSensor(coordinator, entry),
        WattsonEvccTargetSensor(coordinator, entry),
        WattsonCheapestWindowSensor(coordinator, entry, hours=2),
        WattsonCheapestWindowSensor(coordinator, entry, hours=4),
        WattsonExpensiveWindowSensor(coordinator, entry, hours=2),
        WattsonNextTripSensor(coordinator, entry),
    ]
    for uc_id, name, _ in UC_DEFINITIONS:
        entities.append(WattsonUCStatusSensor(coordinator, entry, uc_id, name))
    async_add_entities(entities)


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

    @property
    def extra_state_attributes(self):
        if self.coordinator.data is None:
            return {}
        return {"begruendung": self.coordinator.data.t300_reason}


class WattsonEvccTargetSensor(WattsonBaseSensor):
    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry, "evcc_target", "evcc Zielmodus")
        self._attr_icon = "mdi:car-electric"

    @property
    def native_value(self):
        return self.coordinator.data.evcc_target if self.coordinator.data else None

    @property
    def extra_state_attributes(self):
        if self.coordinator.data is None:
            return {}
        return {"begruendung": self.coordinator.data.evcc_reason}


class WattsonCheapestWindowSensor(WattsonBaseSensor):
    def __init__(self, coordinator, entry, hours: int):
        super().__init__(coordinator, entry, f"cheapest_{hours}h",
                         f"Günstigste {hours}h")
        self._attr_icon = "mdi:cash-clock"
        self._hours = hours

    @property
    def _window(self):
        d = self.coordinator.data
        if d is None:
            return (None, None, None)
        if self._hours == 2:
            return (d.cheapest_2h_start, d.cheapest_2h_end, d.cheapest_2h_avg)
        if self._hours == 4:
            return (d.cheapest_4h_start, d.cheapest_4h_end, d.cheapest_4h_avg)
        return (None, None, None)

    @property
    def native_value(self):
        start, end, _ = self._window
        if start is None or end is None:
            return None
        return f"{start.strftime('%H:%M')}–{end.strftime('%H:%M')}"

    @property
    def extra_state_attributes(self):
        start, end, avg = self._window
        if start is None:
            return {}
        return {
            "start": start.isoformat(),
            "end": end.isoformat(),
            "avg_price_eur_kwh": round(avg, 4) if avg is not None else None,
        }


class WattsonExpensiveWindowSensor(WattsonBaseSensor):
    def __init__(self, coordinator, entry, hours: int):
        super().__init__(coordinator, entry, f"expensive_{hours}h",
                         f"Teuerste {hours}h")
        self._attr_icon = "mdi:cash-remove"
        self._hours = hours

    @property
    def _window(self):
        d = self.coordinator.data
        if d is None or self._hours != 2:
            return (None, None, None)
        return (d.expensive_2h_start, d.expensive_2h_end, d.expensive_2h_avg)

    @property
    def native_value(self):
        start, end, _ = self._window
        if start is None or end is None:
            return None
        return f"{start.strftime('%H:%M')}–{end.strftime('%H:%M')}"

    @property
    def extra_state_attributes(self):
        start, end, avg = self._window
        if start is None:
            return {}
        return {
            "start": start.isoformat(),
            "end": end.isoformat(),
            "avg_price_eur_kwh": round(avg, 4) if avg is not None else None,
        }


class WattsonUCStatusSensor(WattsonBaseSensor):
    """Pro-UC Status: aktiv / disabled / user-override (Xmin) / schlafmodus."""

    _attr_icon = "mdi:traffic-light"

    def __init__(self, coordinator, entry, uc_id: str, display_name: str):
        super().__init__(coordinator, entry, f"{uc_id}_status",
                         f"{uc_id.upper()} {display_name} Status")
        self._uc_id = uc_id

    @property
    def native_value(self):
        d = self.coordinator.data
        if d is None:
            return None
        return d.uc_status.get(self._uc_id, self.coordinator._uc_idle_status(self._uc_id))

    @property
    def extra_state_attributes(self):
        d = self.coordinator.data
        if d is None:
            return {}
        info = self.coordinator.override.status_for(self._uc_id)
        attrs = {"begruendung": d.uc_reason.get(self._uc_id, "")}
        attrs.update(info["attrs"])
        return attrs


class WattsonNextTripSensor(WattsonBaseSensor):
    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry, "next_trip", "Nächste Fahrt")
        self._attr_icon = "mdi:map-marker-path"

    @property
    def native_value(self):
        d = self.coordinator.data
        if d is None or not d.trip_title:
            return None
        return d.trip_title

    @property
    def extra_state_attributes(self):
        d = self.coordinator.data
        if d is None:
            return {}
        return {
            "ort": d.trip_location,
            "start": d.trip_start.isoformat() if d.trip_start else None,
            "kalender": d.trip_calendar,
            "distanz_km": d.trip_distance_km,
            "benoetigter_soc": d.trip_required_soc,
            "plan_gesetzt": d.trip_plan_set,
            "begruendung": d.trip_reason,
        }
