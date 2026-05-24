"""Config Flow für Wattson."""
from __future__ import annotations

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
    CONF_AUTO_CALENDARS,
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


def _schema(defaults: dict) -> vol.Schema:
    return vol.Schema({
        vol.Required("dry_run", default=defaults.get("dry_run", True)): bool,
        vol.Optional(
            CONF_GMAPS_KEY,
            default=defaults.get(CONF_GMAPS_KEY, ""),
        ): str,
        vol.Optional(
            CONF_HOME_ADDRESS,
            default=defaults.get(CONF_HOME_ADDRESS, DEFAULT_HOME_ADDRESS),
        ): str,
        vol.Optional(
            CONF_AUTO_CALENDARS,
            default=defaults.get(CONF_AUTO_CALENDARS, DEFAULT_AUTO_CALENDARS),
        ): selector.EntitySelector(
            selector.EntitySelectorConfig(domain="calendar", multiple=True),
        ),
        vol.Optional(
            CONF_EVCC_VEHICLE_NAME,
            default=defaults.get(CONF_EVCC_VEHICLE_NAME, DEFAULT_EVCC_VEHICLE_NAME),
        ): str,
        vol.Optional(
            CONF_VEHICLE_CONSUMPTION,
            default=defaults.get(CONF_VEHICLE_CONSUMPTION, DEFAULT_VEHICLE_CONSUMPTION),
        ): vol.Coerce(float),
        vol.Optional(
            CONF_VEHICLE_CAPACITY,
            default=defaults.get(CONF_VEHICLE_CAPACITY, DEFAULT_VEHICLE_CAPACITY),
        ): vol.Coerce(float),
        vol.Optional(
            CONF_SAFETY_MARGIN,
            default=defaults.get(CONF_SAFETY_MARGIN, DEFAULT_SAFETY_MARGIN),
        ): vol.All(int, vol.Range(min=0, max=100)),
        vol.Optional(
            CONF_EVENT_LOOKAHEAD,
            default=defaults.get(CONF_EVENT_LOOKAHEAD, DEFAULT_EVENT_LOOKAHEAD),
        ): vol.All(int, vol.Range(min=1, max=168)),
        vol.Optional(
            CONF_E3DC_URL,
            default=defaults.get(CONF_E3DC_URL, DEFAULT_E3DC_URL),
        ): str,
        vol.Optional(
            CONF_E3DC_USER,
            default=defaults.get(CONF_E3DC_USER, DEFAULT_E3DC_USER),
        ): str,
        vol.Optional(
            CONF_E3DC_PASSWORD,
            default=defaults.get(CONF_E3DC_PASSWORD, DEFAULT_E3DC_PASSWORD),
        ): str,
    })


class WattsonConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None):
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")
        if user_input is not None:
            return self.async_create_entry(title="Wattson", data=user_input)
        return self.async_show_form(step_id="user", data_schema=_schema({}))

    @staticmethod
    @callback
    def async_get_options_flow(entry):
        return WattsonOptionsFlow()


class WattsonOptionsFlow(config_entries.OptionsFlow):
    async def async_step_init(self, user_input=None):
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)
        current = {**self.config_entry.data, **self.config_entry.options}
        return self.async_show_form(step_id="init", data_schema=_schema(current))
