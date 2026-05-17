"""Wattson DataUpdateCoordinator — Entscheidungslogik."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .forecast import (
    PriceSlot,
    calculate_required_soc,
    cheapest_window,
    is_in_window,
    most_expensive_window,
    next_relevant_event,
    parse_tibber_response,
)
from .gmaps import GoogleMapsClient
from .const import (
    BATTERY_FULL,
    BATTERY_NOT_FULL,
    CHEAP_LEVELS,
    DOMAIN,
    EVCC_PLAN_BUFFER_MINUTES,
    SKIP_LOCATION_KEYWORDS,
    ENTITY_BATTERY_SOC,
    ENTITY_EVCC_CONNECTED,
    ENTITY_EVCC_MODE,
    ENTITY_EVCC_RANGE,
    ENTITY_EVCC_SOC,
    ENTITY_PRICE,
    ENTITY_PRICE_LEVEL,
    ENTITY_PRICE_RANKING,
    ENTITY_PV_FC_HOUR,
    ENTITY_PV_FC_NEXT_HOUR,
    ENTITY_PV_FC_NOW,
    ENTITY_PV_FC_REMAINING,
    ENTITY_PV_FC_TOMORROW,
    ENTITY_PV_PEAK_TODAY,
    ENTITY_PV_PEAK_TOMORROW,
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
    SOC_TARGET,
    SOC_WARNUNG,
    T300_TANK_MAX,
    T300_TEMP_CHEAP,
    T300_TEMP_MIN,
    T300_TEMP_NORMAL,
    T300_TEMP_TEUER,
)

_LOGGER = logging.getLogger(__name__)


@dataclass
class WattsonTripConfig:
    """Config-Werte für UC2 (Calendar-basiertes Vorladen)."""
    gmaps: GoogleMapsClient | None
    home_address: str
    calendar_entity: str
    vehicle_consumption: float   # kWh/100km
    vehicle_capacity: float      # kWh
    safety_margin: int           # %
    evcc_vehicle_name: str
    lookahead_hours: int


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
    t300_reason: str = ""
    evcc_target: str = "pv"
    evcc_reason: str = ""

    # PV-Forecast (forecast.solar)
    pv_fc_now: int = 0                       # W aktuell erwartet
    pv_fc_current_hour: float = 0.0          # kWh diese Stunde
    pv_fc_next_hour: float = 0.0             # kWh nächste Stunde
    pv_fc_today_remaining: float = 0.0       # kWh Rest heute
    pv_fc_tomorrow: float = 0.0              # kWh morgen
    pv_peak_today: datetime | None = None
    pv_peak_tomorrow: datetime | None = None

    # UC2 — nächste Fahrt
    trip_title: str = ""
    trip_location: str = ""
    trip_start: datetime | None = None
    trip_distance_km: float | None = None
    trip_required_soc: int | None = None
    trip_plan_set: bool = False
    trip_reason: str = ""

    # Forecast (Tibber)
    forecast_slots: list[PriceSlot] = field(default_factory=list)
    cheapest_2h_start: datetime | None = None
    cheapest_2h_end: datetime | None = None
    cheapest_2h_avg: float | None = None
    expensive_2h_start: datetime | None = None
    expensive_2h_end: datetime | None = None
    expensive_2h_avg: float | None = None
    cheapest_4h_start: datetime | None = None
    cheapest_4h_end: datetime | None = None
    cheapest_4h_avg: float | None = None

    # intern
    low_soc_notified: bool = False


class WattsonCoordinator(DataUpdateCoordinator[WattsonData]):

    def __init__(self, hass: HomeAssistant, dry_run: bool,
                 trip_cfg: WattsonTripConfig | None = None) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=SCAN_INTERVAL_SECONDS),
        )
        self._dry_run = dry_run
        self._trip_cfg = trip_cfg
        self._prev: WattsonData = WattsonData(dry_run=dry_run)
        self._planned_event_uid: str | None = None

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

    def _dtval(self, entity_id: str) -> datetime | None:
        raw = self._state(entity_id)
        if not raw:
            return None
        try:
            return datetime.fromisoformat(raw)
        except (ValueError, TypeError):
            return None

    async def _fetch_tibber_forecast(self) -> list[PriceSlot]:
        try:
            response = await self.hass.services.async_call(
                "tibber", "get_prices", {},
                blocking=True, return_response=True,
            )
        except HomeAssistantError as e:
            _LOGGER.warning("Tibber-Forecast nicht verfügbar: %s", e)
            return []
        slots = parse_tibber_response(response)
        if not slots:
            _LOGGER.warning("Tibber-Forecast leer")
        return slots

    async def _act(self, domain: str, service: str, **kwargs) -> str:
        desc = f"{domain}.{service}({kwargs})"
        if self._dry_run:
            _LOGGER.info("[DRY-RUN] %s", desc)
        else:
            await self.hass.services.async_call(domain, service, kwargs, blocking=False)
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

        # ── PV-Forecast (forecast.solar) ─────────────────────────────────────
        s.pv_fc_now            = self._ival(ENTITY_PV_FC_NOW)
        s.pv_fc_current_hour   = self._fval(ENTITY_PV_FC_HOUR)
        s.pv_fc_next_hour      = self._fval(ENTITY_PV_FC_NEXT_HOUR)
        s.pv_fc_today_remaining = self._fval(ENTITY_PV_FC_REMAINING)
        s.pv_fc_tomorrow       = self._fval(ENTITY_PV_FC_TOMORROW)
        s.pv_peak_today        = self._dtval(ENTITY_PV_PEAK_TODAY)
        s.pv_peak_tomorrow     = self._dtval(ENTITY_PV_PEAK_TOMORROW)

        # ── Tibber-Forecast holen + Fenster berechnen ─────────────────────────
        s.forecast_slots = await self._fetch_tibber_forecast()
        now = dt_util.now()
        if s.forecast_slots:
            if (w := cheapest_window(s.forecast_slots, 120, now, lookahead_hours=12)):
                s.cheapest_2h_start, s.cheapest_2h_end, s.cheapest_2h_avg = w
            if (w := most_expensive_window(s.forecast_slots, 120, now, lookahead_hours=12)):
                s.expensive_2h_start, s.expensive_2h_end, s.expensive_2h_avg = w
            if (w := cheapest_window(s.forecast_slots, 240, now, lookahead_hours=24)):
                s.cheapest_4h_start, s.cheapest_4h_end, s.cheapest_4h_avg = w
            if s.cheapest_2h_start and s.expensive_2h_start:
                _LOGGER.info(
                    "Tibber-Forecast — günstigste 2h: %s–%s (%.3f€) | teuerste 2h: %s–%s (%.3f€) | günstigste 4h: %s–%s (%.3f€)",
                    s.cheapest_2h_start.strftime("%H:%M"),
                    s.cheapest_2h_end.strftime("%H:%M"), s.cheapest_2h_avg,
                    s.expensive_2h_start.strftime("%H:%M"),
                    s.expensive_2h_end.strftime("%H:%M"), s.expensive_2h_avg,
                    s.cheapest_4h_start.strftime("%H:%M") if s.cheapest_4h_start else "?",
                    s.cheapest_4h_end.strftime("%H:%M") if s.cheapest_4h_end else "?",
                    s.cheapest_4h_avg if s.cheapest_4h_avg else 0.0,
                )

        _LOGGER.info(
            "PV-Forecast — jetzt %dW | diese Std %.1fkWh | nächste Std %.1fkWh | Rest heute %.1fkWh | morgen %.1fkWh | Peak heute: %s",
            s.pv_fc_now, s.pv_fc_current_hour, s.pv_fc_next_hour,
            s.pv_fc_today_remaining, s.pv_fc_tomorrow,
            s.pv_peak_today.strftime("%H:%M") if s.pv_peak_today else "?",
        )

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
            s.t300_target = s.t300_solltemperatur
            s.evcc_target = s.evcc_mode
            s.t300_reason = "Schlafmodus"
            s.evcc_reason = "Schlafmodus"
            self._prev = s
            return s

        # ── UC4a: T300 Solltemperatur vorausschauend ─────────────────────────
        # Notfall vor Forecast — Tank zu kalt → immer heizen
        if s.t300_tank_temp < T300_TEMP_MIN:
            new_temp = T300_TEMP_NORMAL
            reason = f"Notfall (Tank {s.t300_tank_temp:.1f}°C<{T300_TEMP_MIN}°C)"
        elif s.cheapest_2h_start and is_in_window(now, s.cheapest_2h_start, s.cheapest_2h_end):
            new_temp = T300_TEMP_CHEAP
            reason = (f"günstigste 2h "
                      f"{s.cheapest_2h_start.strftime('%H:%M')}–{s.cheapest_2h_end.strftime('%H:%M')} "
                      f"@ {s.cheapest_2h_avg * 100:.1f}ct")
        elif s.expensive_2h_start and is_in_window(now, s.expensive_2h_start, s.expensive_2h_end):
            new_temp = T300_TEMP_TEUER
            reason = (f"teuerste 2h "
                      f"{s.expensive_2h_start.strftime('%H:%M')}–{s.expensive_2h_end.strftime('%H:%M')} "
                      f"@ {s.expensive_2h_avg * 100:.1f}ct")
        elif not s.forecast_slots:
            # Forecast nicht verfügbar — Fallback reaktiv
            if s.price_ranking <= 0.33:
                new_temp = T300_TEMP_CHEAP
                reason = f"günstig reaktiv (Rank {s.price_ranking:.2f}, kein Forecast)"
            elif s.price_ranking >= 0.67:
                new_temp = T300_TEMP_TEUER
                reason = f"teuer reaktiv (Rank {s.price_ranking:.2f}, kein Forecast)"
            else:
                new_temp = T300_TEMP_NORMAL
                reason = f"normal reaktiv (Rank {s.price_ranking:.2f}, kein Forecast)"
        else:
            new_temp = T300_TEMP_NORMAL
            reason = f"normal (Rank {s.price_ranking:.2f})"

        s.t300_target = new_temp
        s.t300_reason = reason
        if abs(new_temp - s.t300_solltemperatur) >= 1.0:
            _LOGGER.info("T300: %.1f°C → %.1f°C (%s)", s.t300_solltemperatur, new_temp, reason)
            actions.append(await self._act("input_number", "set_value",
                                           entity_id=ENTITY_T300_SOLL, value=new_temp))
        else:
            _LOGGER.info("T300: %.1f°C OK (%s)", s.t300_solltemperatur, reason)

        # ── UC4b: E-Heizstab bei PV-Überschuss + Speicher voll ───────────────
        # AN nur wenn: Überschuss da UND Speicher (fast) voll UND Tank nicht zu heiß
        should_on = (
            s.pv_surplus >= PV_SURPLUS_ON
            and s.battery_soc >= BATTERY_FULL
            and s.t300_tank_temp < T300_TANK_MAX
        )
        # AUS wenn: Überschuss zu klein ODER Speicher unter Schwelle ODER Tank heiß
        should_off = (
            s.pv_surplus < PV_SURPLUS_OFF
            or s.battery_soc < BATTERY_NOT_FULL
            or s.t300_tank_temp >= T300_TANK_MAX
        )
        if should_on and not s.t300_heizstab_on:
            _LOGGER.info("E-Heizstab EIN (Überschuss %dW, Bat %d%%, Tank %.1f°C)",
                         s.pv_surplus, s.battery_soc, s.t300_tank_temp)
            actions.append(await self._act("switch", "turn_on", entity_id=ENTITY_T300_HEIZSTAB))
        elif should_off and s.t300_heizstab_on:
            _LOGGER.info("E-Heizstab AUS (Überschuss %dW, Bat %d%%, Tank %.1f°C)",
                         s.pv_surplus, s.battery_soc, s.t300_tank_temp)
            actions.append(await self._act("switch", "turn_off", entity_id=ENTITY_T300_HEIZSTAB))

        # ── UC6/UC7: evcc Modus vorausschauend ───────────────────────────────
        if s.car_connected:
            needs_charge = s.car_soc < SOC_TARGET
            in_cheapest_4h = bool(
                s.cheapest_4h_start
                and is_in_window(now, s.cheapest_4h_start, s.cheapest_4h_end)
            )
            if needs_charge and in_cheapest_4h:
                target_mode = "now"
                reason = (f"günstigste 4h "
                          f"{s.cheapest_4h_start.strftime('%H:%M')}–{s.cheapest_4h_end.strftime('%H:%M')} "
                          f"@ {s.cheapest_4h_avg * 100:.1f}ct (SOC {s.car_soc:.0f}%<{SOC_TARGET}%)")
            elif not s.forecast_slots and s.price_level in CHEAP_LEVELS:
                # Forecast nicht verfügbar, Tibber-Level sagt günstig
                target_mode = "minpv"
                reason = f"reaktiv günstig ({s.price_level}, kein Forecast)"
            else:
                target_mode = "pv"
                if not needs_charge:
                    reason = f"SOC {s.car_soc:.0f}% ≥ {SOC_TARGET}% (kein Forcieren nötig)"
                elif s.cheapest_4h_start:
                    reason = (f"warte auf günstigste 4h "
                              f"{s.cheapest_4h_start.strftime('%H:%M')}")
                else:
                    reason = "Standard"

            s.evcc_target = target_mode
            s.evcc_reason = reason
            if target_mode != s.evcc_mode:
                _LOGGER.info("evcc: %s → %s (%s)", s.evcc_mode, target_mode, reason)
                actions.append(await self._act("select", "select_option",
                                               entity_id=ENTITY_EVCC_MODE, option=target_mode))
            else:
                _LOGGER.info("evcc: %s OK (%s)", s.evcc_mode, reason)
        else:
            s.evcc_reason = "Auto nicht angeschlossen"

        # ── UC1: Niedrig-SOC Warnung ──────────────────────────────────────────
        if s.car_soc > 0 and s.car_soc < SOC_WARNUNG and not s.low_soc_notified:
            msg = f"ORA 03 Akku niedrig: {s.car_soc:.0f}% ({s.car_range} km)"
            _LOGGER.warning("UC1: %s", msg)
            actions.append(await self._act(
                "notify", NOTIFY_SERVICE.split(".")[1],
                message=msg, title="⚡ Wattson: Niedriger Ladestand",
            ))
            s.low_soc_notified = True
        elif s.car_soc >= SOC_WARNUNG:
            s.low_soc_notified = False

        # ── UC2: Kalender-basiertes Vorladen ──────────────────────────────────
        await self._handle_trip_planning(s, now, actions)

        s.last_actions = actions if actions else ["Keine Änderungen"]
        self._prev = s
        return s

    async def _fetch_calendar_events(self, entity_id: str, hours: int) -> list[dict]:
        try:
            resp = await self.hass.services.async_call(
                "calendar", "get_events",
                {"entity_id": entity_id, "duration": {"hours": hours}},
                blocking=True, return_response=True,
            )
        except HomeAssistantError as e:
            _LOGGER.warning("calendar.get_events fehlgeschlagen: %s", e)
            return []
        if not resp:
            return []
        cal_data = resp.get(entity_id) or {}
        return cal_data.get("events", []) if isinstance(cal_data, dict) else []

    async def _handle_trip_planning(
        self, s: WattsonData, now: datetime, actions: list[str]
    ) -> None:
        cfg = self._trip_cfg
        if cfg is None or cfg.gmaps is None:
            s.trip_reason = "deaktiviert (kein Google Maps Key)"
            return

        events = await self._fetch_calendar_events(cfg.calendar_entity, cfg.lookahead_hours)
        event = next_relevant_event(events, now, SKIP_LOCATION_KEYWORDS)
        if event is None:
            s.trip_reason = "kein relevanter Termin in Sicht"
            self._planned_event_uid = None
            return

        s.trip_title = event.get("summary", "?")
        s.trip_location = event.get("location", "")
        s.trip_start = event["_start_dt"]

        route = await cfg.gmaps.distance(cfg.home_address, s.trip_location)
        if route is None:
            s.trip_reason = f"Distanz für '{s.trip_location}' nicht ermittelbar"
            return
        s.trip_distance_km = route.distance_km

        required_soc = calculate_required_soc(
            route.distance_km, cfg.vehicle_consumption,
            cfg.vehicle_capacity, cfg.safety_margin,
        )
        s.trip_required_soc = required_soc

        if s.car_soc >= required_soc:
            s.trip_reason = (f"SOC {s.car_soc:.0f}% ≥ benötigt {required_soc}% "
                             f"({s.trip_title}, {route.distance_km:.0f} km)")
            return

        # Plan nur einmal pro Event setzen (idempotent via UID)
        event_uid = event.get("uid") or f"{s.trip_start.isoformat()}:{s.trip_title}"
        if self._planned_event_uid == event_uid and self._prev.trip_plan_set:
            s.trip_plan_set = True
            s.trip_reason = (f"Plan aktiv: {required_soc}% bis {s.trip_start.strftime('%d.%m %H:%M')} "
                             f"({s.trip_title})")
            return

        departure = s.trip_start - timedelta(minutes=EVCC_PLAN_BUFFER_MINUTES)
        if departure <= now:
            s.trip_reason = f"Termin {s.trip_title} zu kurzfristig — Plan nicht mehr sinnvoll"
            return

        _LOGGER.info(
            "UC2: setze Plan für '%s' (%s) — Ziel %d%% bis %s (%.0f km, %s Termin)",
            s.trip_title, s.trip_location, required_soc,
            departure.strftime("%d.%m %H:%M"), route.distance_km,
            s.trip_start.strftime("%d.%m %H:%M"),
        )
        actions.append(await self._act(
            "evcc_intg", "set_vehicle_plan",
            startdate=departure.isoformat(),
            vehicle=cfg.evcc_vehicle_name,
            soc=required_soc,
        ))
        s.trip_plan_set = True
        s.trip_reason = (f"Plan gesetzt: {required_soc}% bis {departure.strftime('%d.%m %H:%M')} "
                         f"({s.trip_title}, {route.distance_km:.0f} km)")
        self._planned_event_uid = event_uid
