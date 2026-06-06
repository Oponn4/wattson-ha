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
    DeferrableSlot,
    PriceSlot,
    calculate_required_soc,
    cheapest_window,
    consecutive_cheap_minutes_from_now,
    deferrable_slot_at,
    humidex,
    is_in_window,
    most_expensive_window,
    next_deferrable_on_block,
    next_relevant_event,
    parse_deferrable_schedule,
    parse_tibber_response,
    upcoming_slots,
)
from .gmaps import GoogleMapsClient
from .e3dc_client import E3DCClient
from .override import OverrideManager, UCDefinition
from .const import (
    BATTERY_FULL,
    BATTERY_NOT_FULL,
    CHEAP_LEVELS,
    DOMAIN,
    EVCC_PLAN_BUFFER_MINUTES,
    SKIP_LOCATION_KEYWORDS,
    UC_DEFINITIONS,
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
    AWAY_LONG_HOURS,
    BATTERIE_KAPAZITAT_KWH,
    CLIMATE_COOL_OFFSET_C,
    E3DC_MAX_DISCHARGE_W,
    CLIMATE_ECO_OFFSET_C,
    CLIMATE_PEAK_OFFSET_C,
    CLIMATE_PRECOOL_OFFSET_C,
    COOL_ABLUFT_HYSTERESE_C,
    COOL_ABLUFT_TRIGGER_C,
    EMHASS_BATT_DISCHARGE_MIN_W,
    EMHASS_DEFERRABLE_ON_MIN_W,
    EMHASS_OPTIM_OK,
    ENTITY_COOL_SNOOZE,
    ENTITY_EMHASS_OPTIM_STATUS,
    ENTITY_EMHASS_P_BATT_FORECAST,
    ENTITY_EMHASS_P_DEFERRABLE0,
    ENTITY_EMHASS_P_DEFERRABLE1,
    ENTITY_FRISCHLUFT,
    ENTITY_KLIMA_OFFICE,
    ENTITY_KLIMA_SCHLAFZIMMER,
    ENTITY_PERSON_CHRISTIAN,
    ENTITY_PERSON_SONJA,
    ENTITY_PROXON_ABLUFT,
    ENTITY_PROXON_COOL_ENABLE,
    ENTITY_PROXON_SOLL_OFFICE,
    ENTITY_PROXON_SOLL_SCHLAFZIMMER,
    ENTITY_URLAUB_MODE,
    ENTITY_WEATHER_FORECAST,
    HOT_FORECAST_THRESHOLD_C,
    MIN_SPREAD_EUR,
    PV_BYPASS_FACTOR,
    PV_COOLING_MIN_W,
    PV_KLIMA_MIN_W,
    SCAN_INTERVAL_SECONDS,
    SMART_SPREAD_THRESHOLD_EUR,
    SOC_BATTERY_RESERVE,
    SOC_TARGET,
    SOC_WARNUNG,
    T300_TANK_MAX,
    T300_TEMP_CHEAP,
    T300_TEMP_MIN,
    T300_TEMP_NORMAL,
    T300_TEMP_TEUER,
    UC4B_CONFIRMATION_CYCLES,
    UC4B_REMINDER_COOLDOWN_MIN,
    UC6_MODE_HOLD_MINUTES,
    UC11_AUTO_ACTION,
    UC11_NOTIFY_COOLDOWN_MIN,
    UC11_QUIET_END_H,
    UC11_QUIET_START_H,
    UC12_EXPENSIVE_LEVELS,
    UC12_REMINDER_COOLDOWN_MIN,
    UC14_BAT_CAPACITY_KWH,
    UC14_CHARGE_POWER_KW,
    UC14_FORCE_CHARGE_W,
    UC14_MIN_SPREAD_CT_KWH,
    UC14_MIN_WINDOW_MINUTES,
    UC14_SOC_MAX_PCT,
    UC14_TOPUP_OVERHEAD_FACTOR,
    HUMIDEX_INSIDE_OUTSIDE_MIN_DELTA,
    HUMIDEX_UNCOMFORTABLE,
    HUMIDEX_WARM_THRESHOLD,
    ENTITY_HUMIDITY_PROXY,
)

_LOGGER = logging.getLogger(__name__)


@dataclass
class WattsonTripConfig:
    """Config-Werte für UC2 (Calendar-basiertes Vorladen)."""
    gmaps: GoogleMapsClient | None
    home_address: str
    auto_calendars: list[str]    # Kalender deren Termine als Auto-Fahrt gelten
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
    trip_calendar: str = ""
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
    expensive_4h_start: datetime | None = None
    expensive_4h_end: datetime | None = None
    expensive_4h_avg: float | None = None

    # UC10
    uc10_spread_eur: float = 0.0
    uc10_idle_active: bool = False
    uc14_active: bool = False
    uc14_spread_ct: float = 0.0
    uc14_window_minutes: int = 0
    uc14_needed_minutes: int = 0

    # UC12 — Kühlung
    cooling_active: bool = False    # ob UC12 die Freigabe gerade gegeben hat
    abluft_temp: float = 0.0
    cool_enable_on: bool = False    # tatsächlicher Switch-Status
    cool_snooze_until: datetime | None = None  # Reminder-Snooze (aus Helper)

    # EMHASS — externer LP-Optimizer (v0.9.0)
    emhass_status: str = "unknown"           # "Optimal" wenn EMHASS bereit
    emhass_p_batt_plan: float = 0.0          # W, EMHASS-Plan für jetzt
    emhass_p_deferrable0_plan: float = 0.0   # W, T300-Heizstab Plan (current slot)
    heizstab_schedule: list[DeferrableSlot] = field(default_factory=list)  # 24h Forward-Plan
    emhass_p_deferrable1_plan: float = 0.0   # W, Wallbox Plan
    emhass_available: bool = False           # ob EMHASS-Daten nutzbar

    # UC11 — Klimaanlagen OG
    urlaub_mode: bool = False
    frischluft_temp: float = 20.0            # Außen via Proxon
    forecast_max_temp_c: float = 20.0        # heutiger Höchstwert aus Weather
    klima_office_target: float = 23.0
    klima_office_current: float = 22.0
    klima_office_hvac: str = "off"
    klima_schlaf_target: float = 23.0
    klima_schlaf_current: float = 22.0
    klima_schlaf_hvac: str = "off"
    proxon_soll_office: float = 21.0
    proxon_soll_schlaf: float = 21.0
    # UC11 v2 — Anwesenheit
    christian_home: bool = True
    sonja_home: bool = True
    all_away: bool = False
    all_away_since: datetime | None = None  # für Long-Away-Erkennung

    # UC-Status (für Sensoren) — string-werte: aktiv / disabled / user-override / dry-run
    uc_status: dict[str, str] = field(default_factory=dict)
    uc_reason: dict[str, str] = field(default_factory=dict)

    # intern
    low_soc_notified: bool = False


class WattsonCoordinator(DataUpdateCoordinator[WattsonData]):

    def __init__(self, hass: HomeAssistant, dry_run: bool,
                 trip_cfg: WattsonTripConfig | None = None,
                 e3dc: E3DCClient | None = None) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=SCAN_INTERVAL_SECONDS),
        )
        self._dry_run = dry_run
        self._trip_cfg = trip_cfg
        self._e3dc = e3dc
        self._prev: WattsonData = WattsonData(dry_run=dry_run)
        self._planned_event_uid: str | None = None
        self._last_max_discharge: int | None = None  # für UC10 override-detection
        self._all_away_since: datetime | None = None  # Tracking für UC11 v2
        # UC6-Hysterese: verhindert 5-min-Mode-Oszillation
        self._uc6_last_mode_change_utc: datetime | None = None
        self._uc6_last_set_target: str | None = None
        # UC14-Grid-Charge: Memo für POST-verify (nächster cycle prüft ob persistiert)
        self._uc14_active: bool = False
        self._last_max_charge: int | None = None
        # UC11-Advisor: Notify-Cooldown pro Raum
        self._uc11_last_notify_utc: dict[str, datetime] = {}
        # UC12-Kühl-Reminder: Notify-Cooldown
        self._uc12_last_reminder_utc: datetime | None = None
        # UC4b plan-aware: Anti-Jitter-Counter + Safety-Reminder-Cooldown
        self._uc4b_off_signal_count: int = 0
        self._uc4b_last_reminder_utc: datetime | None = None
        self._override = OverrideManager(
            hass,
            [UCDefinition(uc_id, display, default)
             for uc_id, _slug, display, default in UC_DEFINITIONS],
        )

    @property
    def override(self) -> OverrideManager:
        return self._override

    def on_uc_resume(self, uc_id: str) -> None:
        """Hook: ein UC-Resume wurde gedrückt — Coordinator-Memory-State zurücksetzen
        damit nächster Cycle nicht wieder "Override neu erkannt" detected.

        Notwendig weil UC10/UC14 ihren Override-Detect über coordinator-Memory
        (`_last_max_discharge`, `_last_max_charge`) machen, nicht über den
        OverrideManager's `_actions` Dict.
        """
        if uc_id == "uc10":
            self._last_max_discharge = None
        if uc_id == "uc14":
            self._last_max_charge = None
            self._uc14_active = False
        if uc_id == "uc6":
            # Mode-Hysterese vergessen damit nächster Cycle sauber neu greift
            self._uc6_last_mode_change_utc = None
            self._uc6_last_set_target = None
        _LOGGER.info("Coordinator state reset für UC %s nach Resume", uc_id)

    async def async_setup(self) -> None:
        """Wird vom __init__ vor first_refresh aufgerufen."""
        await self._override.async_load()

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
        # Default-Call liefert nur aktuellen Tag — explizit start/end angeben
        # damit auch morgige Day-Ahead-Preise enthalten sind (ab ~13:00 verfügbar)
        now = dt_util.now()
        end = (now + timedelta(days=2)).replace(
            hour=0, minute=0, second=0, microsecond=0,
        )
        try:
            response = await self.hass.services.async_call(
                "tibber", "get_prices",
                {"start": now.isoformat(), "end": end.isoformat()},
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
        """Ungetrackte Aktion (z.B. Notify) — kein Override-Check."""
        desc = f"{domain}.{service}({kwargs})"
        if self._dry_run:
            _LOGGER.info("[DRY-RUN] %s", desc)
        else:
            await self.hass.services.async_call(domain, service, kwargs, blocking=False)
            _LOGGER.info("Aktion: %s", desc)
        return desc

    def _uc6_hysteresis_block(self, new_target: str, now: datetime) -> str | None:
        """Returns block-reason wenn UC6-Mode-Switch wegen Hysterese unterdrückt wird,
        sonst None (= darf wechseln).

        Logik: nach Wattson-eigenem Mode-Set muss UC6_MODE_HOLD_MINUTES vergehen
        bevor erneut gewechselt werden darf. Verhindert 5-min-Oszillation wenn
        EMHASS-Plan an der Schwelle pendelt. Erzwungener Wechsel wird erst nach
        Ablauf erlaubt — User-Override-Pfad (externe Änderung) bleibt unberührt.
        """
        if self._uc6_last_mode_change_utc is None:
            return None
        # neuer Target identisch zu zuletzt gesetztem → kein Wechsel, kein Block
        if new_target == self._uc6_last_set_target:
            return None
        elapsed = dt_util.utcnow() - self._uc6_last_mode_change_utc
        hold = timedelta(minutes=UC6_MODE_HOLD_MINUTES)
        if elapsed >= hold:
            return None
        remaining = int((hold - elapsed).total_seconds() // 60) + 1
        return (f"letzter Set {self._uc6_last_set_target!r} vor "
                f"{int(elapsed.total_seconds()//60)} min, "
                f"min-Halt {UC6_MODE_HOLD_MINUTES} min (Rest {remaining} min)")

    def _uc_idle_status(self, uc_id: str) -> str:
        """Status wenn UC im Tick aktiv geblieben ist aber keine Aktion nötig war."""
        if not self._override.is_enabled(uc_id):
            return "disabled"
        if self._override.in_cooldown(uc_id):
            remaining = self._override.cooldown_remaining_minutes(uc_id)
            return f"user-override ({remaining}min Rest)"
        return "aktiv"

    async def _try_act(
        self, uc_id: str, entity_id: str, value_for_track,
        domain: str, service: str, service_data: dict,
    ) -> tuple[bool, str]:
        """Override-bewusste Aktion. Returns (acted, reason)."""
        if not self._override.is_enabled(uc_id):
            return False, "disabled"

        if self._override.in_cooldown(uc_id):
            remaining = self._override.cooldown_remaining_minutes(uc_id)
            return False, f"user-override ({remaining}min Rest)"

        # User-Eingriff seit letzter Wattson-Aktion?
        current = self._state(entity_id)
        if self._override.detect_override(entity_id, current):
            await self._override.async_record_override(uc_id, entity_id, current)
            remaining = self._override.cooldown_remaining_minutes(uc_id)
            return False, f"user-override neu erkannt ({remaining}min Rest)"

        desc = f"{domain}.{service}({service_data})"
        if self._dry_run:
            _LOGGER.info("[DRY-RUN] %s", desc)
            return True, f"DRY-RUN: {desc}"

        await self.hass.services.async_call(domain, service, service_data, blocking=False)
        await self._override.async_record_action(uc_id, entity_id, value_for_track)
        _LOGGER.info("Aktion: %s", desc)
        return True, desc

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
        s.abluft_temp          = self._fval(ENTITY_PROXON_ABLUFT, 22.0)
        s.cool_enable_on       = self._state(ENTITY_PROXON_COOL_ENABLE) == "on"
        snooze_ts = self._attr(ENTITY_COOL_SNOOZE, "timestamp", None)
        try:
            s.cool_snooze_until = (
                dt_util.utc_from_timestamp(float(snooze_ts)) if snooze_ts else None
            )
        except (TypeError, ValueError):
            s.cool_snooze_until = None

        # EMHASS State lesen — wenn nicht "Optimal" oder Sensor weg → fallback heuristik
        s.emhass_status = self._state(ENTITY_EMHASS_OPTIM_STATUS, "unknown") or "unknown"
        s.emhass_p_batt_plan = self._fval(ENTITY_EMHASS_P_BATT_FORECAST, 0.0)
        s.emhass_p_deferrable0_plan = self._fval(ENTITY_EMHASS_P_DEFERRABLE0, 0.0)
        # UC4b: Forward-Plan aus EMHASS-Attribut (deferrables_schedule)
        s.heizstab_schedule = parse_deferrable_schedule(
            self._attr(ENTITY_EMHASS_P_DEFERRABLE0, "deferrables_schedule", []),
            key="p_deferrable0",
        )
        s.emhass_p_deferrable1_plan = self._fval(ENTITY_EMHASS_P_DEFERRABLE1, 0.0)
        s.emhass_available = s.emhass_status == EMHASS_OPTIM_OK

        # UC11 — Klima State
        s.urlaub_mode = self._state(ENTITY_URLAUB_MODE) == "on"
        s.frischluft_temp = self._fval(ENTITY_FRISCHLUFT, 20.0)
        s.proxon_soll_office = self._fval(ENTITY_PROXON_SOLL_OFFICE, 21.0)
        s.proxon_soll_schlaf = self._fval(ENTITY_PROXON_SOLL_SCHLAFZIMMER, 21.0)
        s.klima_office_hvac = self._state(ENTITY_KLIMA_OFFICE, "off") or "off"
        s.klima_office_current = float(self._attr(ENTITY_KLIMA_OFFICE, "current_temperature", 22.0) or 22.0)
        s.klima_office_target = float(self._attr(ENTITY_KLIMA_OFFICE, "temperature", 23.0) or 23.0)
        s.klima_schlaf_hvac = self._state(ENTITY_KLIMA_SCHLAFZIMMER, "off") or "off"
        s.klima_schlaf_current = float(self._attr(ENTITY_KLIMA_SCHLAFZIMMER, "current_temperature", 22.0) or 22.0)
        s.klima_schlaf_target = float(self._attr(ENTITY_KLIMA_SCHLAFZIMMER, "temperature", 23.0) or 23.0)
        # Heute-Höchsttemperatur aus Weather-Forecast (für Pre-Cool-Trigger)
        forecast = self._attr(ENTITY_WEATHER_FORECAST, "forecast", []) or []
        if forecast and isinstance(forecast, list) and len(forecast) > 0:
            s.forecast_max_temp_c = float(forecast[0].get("temperature", 20.0) or 20.0)
        # Anwesenheit (UC11 v2)
        s.christian_home = self._state(ENTITY_PERSON_CHRISTIAN, "unknown") == "home"
        s.sonja_home = self._state(ENTITY_PERSON_SONJA, "unknown") == "home"
        s.all_away = not (s.christian_home or s.sonja_home)
        if s.all_away:
            if self._all_away_since is None:
                self._all_away_since = dt_util.now()
            s.all_away_since = self._all_away_since
        else:
            self._all_away_since = None
            s.all_away_since = None

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
            if (w := most_expensive_window(s.forecast_slots, 240, now, lookahead_hours=24)):
                s.expensive_4h_start, s.expensive_4h_end, s.expensive_4h_avg = w
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
            for uc_id, _slug, _display, _default in UC_DEFINITIONS:
                s.uc_status[uc_id] = "schlafmodus"
                s.uc_reason[uc_id] = "Schlafmodus aktiv"
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
            acted, act_desc = await self._try_act(
                "uc4a", ENTITY_T300_SOLL, new_temp,
                "input_number", "set_value",
                {"entity_id": ENTITY_T300_SOLL, "value": new_temp},
            )
            if acted:
                actions.append(act_desc)
                s.uc_status["uc4a"] = "aktiv"
                s.uc_reason["uc4a"] = reason
            else:
                _LOGGER.info("UC4a übersprungen: %s", act_desc)
                s.uc_status["uc4a"] = act_desc
                s.uc_reason["uc4a"] = f"{reason} (geblockt: {act_desc})"
        else:
            _LOGGER.info("T300: %.1f°C OK (%s)", s.t300_solltemperatur, reason)
            # Aktiv aber nichts zu tun — Status reflektiert das
            s.uc_status.setdefault("uc4a", self._uc_idle_status("uc4a"))
            s.uc_reason["uc4a"] = reason

        # ── UC4b: E-Heizstab (vorausschauend, EMHASS-Plan-basiert) ──────────
        # v0.16.0: liest deferrables_schedule (Forward-Plan) statt p_def0.state.
        # Confirmation-Cycles gegen EMHASS-Replan-Jitter. Heuristik bleibt Fallback.
        # Tank-Safety gilt IMMER.
        tank_safe = s.t300_tank_temp < T300_TANK_MAX
        if s.emhass_available and s.heizstab_schedule:
            current_slot = deferrable_slot_at(s.heizstab_schedule, now)
            plan_says_on = (
                current_slot is not None
                and current_slot.power >= EMHASS_DEFERRABLE_ON_MIN_W
            )
            if plan_says_on and tank_safe:
                # Im On-Block — Counter reset, Block-Ende für Logging
                self._uc4b_off_signal_count = 0
                should_on = True
                block = next_deferrable_on_block(
                    s.heizstab_schedule, now, EMHASS_DEFERRABLE_ON_MIN_W,
                )
                block_end_str = block[1].strftime("%H:%M") if block else "?"
                uc4b_source = (
                    f"EMHASS-Block bis {block_end_str} "
                    f"(Slot {current_slot.power:.0f}W)"
                )
            elif not tank_safe:
                self._uc4b_off_signal_count = 0
                should_on = False
                uc4b_source = (
                    f"Tank-Limit ({s.t300_tank_temp:.1f}°C ≥ {T300_TANK_MAX}°C)"
                )
            else:
                # Plan sagt off — Confirmation-Cycles bevor wirklich ausschalten
                self._uc4b_off_signal_count += 1
                if (self._uc4b_off_signal_count < UC4B_CONFIRMATION_CYCLES
                        and s.t300_heizstab_on):
                    should_on = True
                    uc4b_source = (
                        f"EMHASS off-Signal "
                        f"{self._uc4b_off_signal_count}/{UC4B_CONFIRMATION_CYCLES} "
                        f"— halte ON gegen Jitter"
                    )
                else:
                    should_on = False
                    next_block = next_deferrable_on_block(
                        s.heizstab_schedule, now, EMHASS_DEFERRABLE_ON_MIN_W,
                    )
                    next_str = (
                        f", nächster Block ab {next_block[0].strftime('%H:%M')}"
                        if next_block else ""
                    )
                    uc4b_source = f"EMHASS Plan: jetzt kein Block{next_str}"
            should_off = not should_on
        else:
            # Heuristik-Fallback (EMHASS nicht verfügbar / kein Schedule)
            self._uc4b_off_signal_count = 0
            should_on = (
                s.pv_surplus >= PV_SURPLUS_ON
                and s.battery_soc >= BATTERY_FULL
                and tank_safe
            )
            should_off = (
                s.pv_surplus < PV_SURPLUS_OFF
                or s.battery_soc < BATTERY_NOT_FULL
                or not tank_safe
            )
            uc4b_source = (f"Heuristik (PV-Über {s.pv_surplus}W, "
                           f"Bat {s.battery_soc}%, Tank {s.t300_tank_temp:.1f}°C)")
        heizstab_reason = ""
        if should_on and not s.t300_heizstab_on:
            heizstab_reason = f"Heizstab EIN — {uc4b_source}"
            _LOGGER.info("E-%s", heizstab_reason)
            acted, act_desc = await self._try_act(
                "uc4b", ENTITY_T300_HEIZSTAB, "on",
                "switch", "turn_on",
                {"entity_id": ENTITY_T300_HEIZSTAB},
            )
            if acted:
                actions.append(act_desc)
                s.uc_status["uc4b"] = "aktiv"
            else:
                _LOGGER.info("UC4b übersprungen: %s", act_desc)
                s.uc_status["uc4b"] = act_desc
                heizstab_reason = f"{heizstab_reason} (geblockt: {act_desc})"
        elif should_off and s.t300_heizstab_on:
            heizstab_reason = f"Heizstab AUS — {uc4b_source}"
            _LOGGER.info("E-%s", heizstab_reason)
            acted, act_desc = await self._try_act(
                "uc4b", ENTITY_T300_HEIZSTAB, "off",
                "switch", "turn_off",
                {"entity_id": ENTITY_T300_HEIZSTAB},
            )
            if acted:
                actions.append(act_desc)
                s.uc_status["uc4b"] = "aktiv"
            else:
                _LOGGER.info("UC4b übersprungen: %s", act_desc)
                s.uc_status["uc4b"] = act_desc
                heizstab_reason = f"{heizstab_reason} (geblockt: {act_desc})"
        else:
            heizstab_reason = (f"Stabil ({'an' if s.t300_heizstab_on else 'aus'}) — "
                               f"{uc4b_source}")
            s.uc_status.setdefault("uc4b", self._uc_idle_status("uc4b"))
        s.uc_reason["uc4b"] = heizstab_reason

        # UC4b Safety-Reminder: Heizstab an UND Strompreis ≥ expensive → Push
        await self._uc4b_send_safety_notify(s, now, actions)

        # ── UC12: Proxon Kühlung (läuft vor UC10 weil UC10 das Ergebnis braucht) ──
        await self._handle_uc12_cooling(s, now, actions)

        # ── UC11: Klimaanlagen OG (Office + Schlafzimmer) ──
        await self._handle_uc11_klima(s, now, actions)

        # ── UC14: Netzladen bei großem Spread (läuft VOR UC10, setzt s.uc14_active) ──
        await self._handle_uc14_grid_charge(s, now, actions)

        # ── UC10: E3DC Discharge-Sperre in günstigen Stunden ──
        await self._handle_uc10_discharge_lock(s, now, actions)

        # ── UC2: Kalender-basiertes Vorladen (vor UC6/7 weil setzt Plan-Mode-Hinweis) ──
        await self._handle_trip_planning(s, now, actions)

        # ── UC6/UC7: evcc Modus — EMHASS-driven mit Heuristik-Fallback ──────
        if s.car_connected:
            needs_charge = s.car_soc < SOC_TARGET
            if s.trip_plan_set:
                # UC2-Plan aktiv → evcc soll planen, niemals "now" forcieren
                target_mode = "pv"
                reason = (f"Trip-Plan aktiv ({s.trip_title}, "
                          f"Ziel {s.trip_required_soc}% bis "
                          f"{s.trip_start.strftime('%d.%m %H:%M') if s.trip_start else '?'}) "
                          f"— pv-Mode damit Plan greift")
            elif s.emhass_available:
                # EMHASS plant Wallbox als deferrable1
                # > 500W → "now" (lade jetzt), sonst "pv" (warten auf Solar/günstig)
                if s.emhass_p_deferrable1_plan >= EMHASS_DEFERRABLE_ON_MIN_W:
                    target_mode = "now"
                    reason = (f"EMHASS Wallbox-Plan {s.emhass_p_deferrable1_plan:.0f}W "
                              f"≥ {EMHASS_DEFERRABLE_ON_MIN_W}W → now "
                              f"(SOC {s.car_soc:.0f}%)")
                else:
                    target_mode = "pv"
                    reason = (f"EMHASS Wallbox-Plan {s.emhass_p_deferrable1_plan:.0f}W "
                              f"→ pv (SOC {s.car_soc:.0f}%)")
            else:
                # Fallback Heuristik (alte Logik)
                in_cheapest_4h = bool(
                    s.cheapest_4h_start
                    and is_in_window(now, s.cheapest_4h_start, s.cheapest_4h_end)
                )
                if needs_charge and in_cheapest_4h:
                    target_mode = "now"
                    reason = (f"Heuristik: günstigste 4h "
                              f"{s.cheapest_4h_start.strftime('%H:%M')}–{s.cheapest_4h_end.strftime('%H:%M')} "
                              f"@ {s.cheapest_4h_avg * 100:.1f}ct (SOC {s.car_soc:.0f}%<{SOC_TARGET}%)")
                elif not s.forecast_slots and s.price_level in CHEAP_LEVELS:
                    target_mode = "minpv"
                    reason = f"Heuristik: reaktiv günstig ({s.price_level}, kein Forecast)"
                else:
                    target_mode = "pv"
                    if not needs_charge:
                        reason = f"Heuristik: SOC {s.car_soc:.0f}% ≥ {SOC_TARGET}%"
                    elif s.cheapest_4h_start:
                        reason = (f"Heuristik: warte auf günstigste 4h "
                                  f"{s.cheapest_4h_start.strftime('%H:%M')}")
                    else:
                        reason = "Heuristik: Standard pv"

            s.evcc_target = target_mode
            s.evcc_reason = reason
            if target_mode != s.evcc_mode:
                # Hysterese: nach Wattson-eigenem Mode-Set mindestens
                # UC6_MODE_HOLD_MINUTES halten, verhindert 5-min-Oszillation
                hold_block = self._uc6_hysteresis_block(target_mode, now)
                if hold_block is not None:
                    _LOGGER.info("evcc: %s → %s gehalten — %s",
                                 s.evcc_mode, target_mode, hold_block)
                    s.uc_status["uc6"] = "aktiv"
                    s.evcc_reason = f"{reason} (Hysterese: {hold_block})"
                else:
                    _LOGGER.info("evcc: %s → %s (%s)", s.evcc_mode, target_mode, reason)
                    acted, act_desc = await self._try_act(
                        "uc6", ENTITY_EVCC_MODE, target_mode,
                        "select", "select_option",
                        {"entity_id": ENTITY_EVCC_MODE, "option": target_mode},
                    )
                    if acted:
                        actions.append(act_desc)
                        s.uc_status["uc6"] = "aktiv"
                        self._uc6_last_mode_change_utc = dt_util.utcnow()
                        self._uc6_last_set_target = target_mode
                    else:
                        _LOGGER.info("UC6 übersprungen: %s", act_desc)
                        s.uc_status["uc6"] = act_desc
                        s.evcc_reason = f"{reason} (geblockt: {act_desc})"
            else:
                _LOGGER.info("evcc: %s OK (%s)", s.evcc_mode, reason)
                s.uc_status.setdefault("uc6", self._uc_idle_status("uc6"))
        else:
            s.evcc_reason = "Auto nicht angeschlossen"
            s.uc_status.setdefault("uc6", self._uc_idle_status("uc6"))
        s.uc_reason["uc6"] = s.evcc_reason

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

        s.last_actions = actions if actions else ["Keine Änderungen"]
        self._prev = s
        return s

    async def _fetch_calendar_events(self, entity_ids: list[str], hours: int) -> list[dict]:
        if not entity_ids:
            return []
        try:
            resp = await self.hass.services.async_call(
                "calendar", "get_events",
                {"entity_id": entity_ids, "duration": {"hours": hours}},
                blocking=True, return_response=True,
            )
        except HomeAssistantError as e:
            _LOGGER.warning("calendar.get_events fehlgeschlagen: %s", e)
            return []
        if not resp:
            return []
        # Response ist {entity_id: {"events": [...]}, ...} — mergen
        merged: list[dict] = []
        for cal_id, cal_data in resp.items():
            if isinstance(cal_data, dict):
                for ev in cal_data.get("events", []):
                    merged.append({**ev, "_calendar": cal_id})
        return merged

    async def _uc4b_send_safety_notify(
        self, s: WattsonData, now: datetime, actions: list[str]
    ) -> None:
        """UC4b Safety-Net: warnt wenn Heizstab läuft und Strompreis ≥ expensive.

        Greift wenn EMHASS-Plan suboptimal entscheidet, ein User-Override den Stab
        vergessen lässt oder Proxon-intern den Stab anwirft. Wattson schaltet nicht
        selbst aus — der Button entscheidet. Respektiert Schlafmodus, Quiet-Hours
        (22-7) und 60min-Cooldown.
        """
        if not s.t300_heizstab_on:
            return
        if s.price_level not in UC12_EXPENSIVE_LEVELS:
            return
        if s.sleep_mode or now.hour >= UC11_QUIET_START_H or now.hour < UC11_QUIET_END_H:
            actions.append(
                "UC4b Safety-Reminder unterdrückt (Schlafmodus/Quiet-Hours)"
            )
            return
        if self._uc4b_last_reminder_utc is not None:
            elapsed_min = (now - self._uc4b_last_reminder_utc).total_seconds() / 60
            if elapsed_min < UC4B_REMINDER_COOLDOWN_MIN:
                return

        price_ct = s.price * 100 if s.price else 0
        notify_data = {
            "title": "Heizstab läuft bei teurem Strom",
            "message": (
                f"Tank {s.t300_tank_temp:.1f}°C, Strompreis {s.price_level} "
                f"({price_ct:.1f} ct/kWh). Ausschalten?"
            ),
            "data": {
                "tag": "wattson_uc4b_heizstab",  # gruppiert + ersetzt vorherige
                "actions": [
                    {"action": "WATTSON_HEIZSTAB_AUS", "title": "Aus",
                     "icon": "sfsymbols:power"},
                    {"action": "WATTSON_HEIZSTAB_IGNORE", "title": "Ignorieren",
                     "icon": "sfsymbols:xmark"},
                ],
            },
        }

        if self._dry_run:
            _LOGGER.info("[DRY-RUN] UC4b safety notify: %s", notify_data["message"])
            actions.append(f"DRY-RUN: UC4b Safety-Reminder ({s.price_level})")
            return
        try:
            await self.hass.services.async_call(
                "notify", NOTIFY_SERVICE.split(".", 1)[1], notify_data, blocking=False,
            )
            self._uc4b_last_reminder_utc = now
            actions.append(f"UC4b Safety-Reminder gesendet ({s.price_level})")
            _LOGGER.info(
                "UC4b safety reminder sent: heizstab on @ %s (%.1f ct/kWh)",
                s.price_level, price_ct,
            )
        except Exception as ex:  # noqa: BLE001
            _LOGGER.warning("UC4b safety reminder failed: %s", ex)

    async def _handle_uc11_klima(
        self, s: WattsonData, now: datetime, actions: list[str]
    ) -> None:
        """UC11: Klimaanlagen OG (Office + Schlafzimmer).
        Sleep-Mode = NICHTS (Frau leichter Schläfer, Office=Nachbarzimmer).
        Urlaub-Mode = alles aus.
        Sonst: Komfort-Sollwert = Proxon-Heiz-Soll + 2°C, modifiziert durch
        PV-Pre-Cool / Tibber-Peak-Bump."""
        s.uc_status["uc11"] = self._uc_idle_status("uc11")
        s.uc_reason["uc11"] = ""

        if not self._override.is_enabled("uc11"):
            s.uc_status["uc11"] = "disabled"
            s.uc_reason["uc11"] = "disabled (per Switch)"
            return
        if self._override.in_cooldown("uc11"):
            remaining = self._override.cooldown_remaining_minutes("uc11")
            s.uc_status["uc11"] = f"user-override ({remaining}min Rest)"
            s.uc_reason["uc11"] = f"user-override aktiv ({remaining}min Rest)"
            return

        # STRICT Sleep-Mode: NICHTS — auch Office nicht (Nachbarzimmer)
        if s.sleep_mode:
            s.uc_reason["uc11"] = "Schlafmodus → NICHTS (Frau leichter Schläfer)"
            return

        # Urlaub: beide aus
        if s.urlaub_mode:
            await self._uc11_handle_room(s, actions, "office", forced_off=True,
                                         reason_prefix="Urlaub")
            await self._uc11_handle_room(s, actions, "schlaf", forced_off=True,
                                         reason_prefix="Urlaub")
            s.uc_reason["uc11"] = "Urlaub-Modus aktiv → beide Klimas aus"
            return

        # Long-Away (>24h): wie Urlaub
        away_hours = 0.0
        if s.all_away_since:
            away_hours = (now - s.all_away_since).total_seconds() / 3600
            if away_hours > AWAY_LONG_HOURS:
                await self._uc11_handle_room(s, actions, "office", forced_off=True,
                                             reason_prefix=f"Long-Away {away_hours:.1f}h")
                await self._uc11_handle_room(s, actions, "schlaf", forced_off=True,
                                             reason_prefix=f"Long-Away {away_hours:.1f}h")
                s.uc_reason["uc11"] = (
                    f"Niemand zuhause seit {away_hours:.1f}h → beide Klimas aus"
                )
                return

        # Eco-Mode (kurze Abwesenheit) wird per Modifier in _uc11_handle_room behandelt
        await self._uc11_handle_room(s, actions, "office")
        await self._uc11_handle_room(s, actions, "schlaf")
        if not s.uc_reason["uc11"]:
            s.uc_reason["uc11"] = (
                f"OK (office {s.klima_office_current:.1f}°C/{s.klima_office_hvac}, "
                f"schlaf {s.klima_schlaf_current:.1f}°C/{s.klima_schlaf_hvac})"
            )

    async def _uc11_handle_room(
        self, s: WattsonData, actions: list[str], room: str,
        forced_off: bool = False, reason_prefix: str = "",
    ) -> None:
        """Hilfsfunktion: Steuere ein Klima-Raum nach UC11-Regeln."""
        if room == "office":
            entity = ENTITY_KLIMA_OFFICE
            proxon_soll = s.proxon_soll_office
            current_hvac = s.klima_office_hvac
            inside_temp = s.klima_office_current
            current_target = s.klima_office_target
        else:
            entity = ENTITY_KLIMA_SCHLAFZIMMER
            proxon_soll = s.proxon_soll_schlaf
            current_hvac = s.klima_schlaf_hvac
            inside_temp = s.klima_schlaf_current
            current_target = s.klima_schlaf_target

        # Forced-off (Urlaub)
        if forced_off:
            if current_hvac != "off":
                acted, desc = await self._try_act(
                    "uc11", entity, "off",
                    "climate", "set_hvac_mode",
                    {"entity_id": entity, "hvac_mode": "off"},
                )
                if acted:
                    actions.append(f"{room} off ({reason_prefix})")
            return

        # Cool-Sollwert berechnen
        cool_target = proxon_soll + CLIMATE_COOL_OFFSET_C
        modifier_parts = []

        # Modifier: niemand zuhause (kurze Abwesenheit) → Eco-Bump
        if s.all_away:
            cool_target += CLIMATE_ECO_OFFSET_C
            modifier_parts.append("Eco (niemand da)")

        # Modifier: Hitze-Forecast + jetzt PV → Pre-Cool (überschreibt Eco wenn aktiv)
        if (s.forecast_max_temp_c > HOT_FORECAST_THRESHOLD_C
                and s.pv_surplus > PV_KLIMA_MIN_W):
            cool_target += CLIMATE_PRECOOL_OFFSET_C
            modifier_parts.append("Pre-Cool")

        # Modifier: in Tibber-Peak → Sollwert hoch (sparen)
        in_expensive = bool(
            s.expensive_4h_start and s.expensive_4h_end
            and is_in_window(dt_util.now(), s.expensive_4h_start, s.expensive_4h_end)
        )
        if in_expensive:
            cool_target += CLIMATE_PEAK_OFFSET_C
            modifier_parts.append("Tibber-Peak")
        modifier_str = (" + " + " + ".join(modifier_parts)) if modifier_parts else ""

        # Komfort-Check via Humidex (gefühlte Temperatur, RH-Proxy aus Wohnzimmer)
        rh_proxy = self._fval(ENTITY_HUMIDITY_PROXY, 50.0)
        inside_hx = humidex(inside_temp, rh_proxy)
        outside_hx = humidex(s.frischluft_temp, rh_proxy)  # RH-proxy auch außen (provisorisch)
        delta_hx = inside_hx - outside_hx

        # Trigger-Bedingung:
        # - Innen ≥ 28 humidex → unbequem (egal Außen)
        # - ODER Innen ≥ 26 humidex UND Innen ≥ Außen + 2°C (Klima besser als Lüften)
        too_hot = inside_hx >= HUMIDEX_UNCOMFORTABLE
        warm_and_outside_higher = (
            inside_hx >= HUMIDEX_WARM_THRESHOLD
            and delta_hx >= HUMIDEX_INSIDE_OUTSIDE_MIN_DELTA
        )
        if not (too_hot or warm_and_outside_higher):
            return

        # Begründung für State
        reason = (
            f"{room}: T {inside_temp:.1f}°C/{rh_proxy:.0f}%RH (proxy), "
            f"humidex {inside_hx:.1f}°C vs außen {outside_hx:.1f}°C "
            f"({'unbequem' if too_hot else 'warm + Außen kühler'})"
        )

        if UC11_AUTO_ACTION:
            # Autonome Aktion (v0.15+, aktuell deaktiviert)
            target_mode = "cool"
            target_temp = cool_target
            if current_hvac != target_mode:
                acted, _ = await self._try_act(
                    "uc11", entity, target_mode,
                    "climate", "set_hvac_mode",
                    {"entity_id": entity, "hvac_mode": target_mode},
                )
                if acted:
                    actions.append(
                        f"{room} → {target_mode} {target_temp:.1f}°C{modifier_str}"
                    )
            if abs(current_target - target_temp) >= 0.5:
                acted, _ = await self._try_act(
                    "uc11", entity, target_temp,
                    "climate", "set_temperature",
                    {"entity_id": entity, "temperature": target_temp},
                )
                if acted:
                    actions.append(
                        f"{room} Soll {current_target:.1f}→{target_temp:.1f}°C{modifier_str}"
                    )
        else:
            # Advisor-Mode (v0.14.1 Default): Notify mit Empfehlung
            # ...außer Proxon-Kühlung läuft eh schon und entfeuchtet die Innenluft.
            # Dann würde Fenster-Auf das torpedieren und Klima wäre Doppelmoppel.
            if s.cool_enable_on:
                actions.append(
                    f"UC11 {room}: Notify unterdrückt (Proxon-Kühlung läuft, entfeuchtet)"
                )
            else:
                await self._uc11_send_advisor_notify(
                    room, entity, inside_temp, inside_hx, outside_hx, cool_target,
                    actions, reason,
                )

    async def _uc11_send_advisor_notify(
        self, room: str, entity: str, inside_temp: float, inside_hx: float,
        outside_hx: float, cool_target: float, actions: list[str], reason: str,
    ) -> None:
        """UC11 Advisor: Sendet Push-Notify wenn Klima sinnvoll wäre. Respektiert
        Quiet-Hours (22-7) und Cooldown (60 min pro Raum). v0.15+ wird das durch
        Smart-Auto-Mode ersetzt."""
        now = dt_util.now()
        # Quiet-Hours: zwischen 22 und 7 Uhr nicht stören
        hour = now.hour
        if hour >= UC11_QUIET_START_H or hour < UC11_QUIET_END_H:
            actions.append(f"UC11 {room}: Notify unterdrückt (Quiet-Hours)")
            return
        # Cooldown
        last = self._uc11_last_notify_utc.get(room)
        if last is not None:
            elapsed_min = (now - last).total_seconds() / 60
            if elapsed_min < UC11_NOTIFY_COOLDOWN_MIN:
                remaining = UC11_NOTIFY_COOLDOWN_MIN - elapsed_min
                actions.append(
                    f"UC11 {room}: Notify unterdrückt ({remaining:.0f}min Cooldown)"
                )
                return

        room_de = {"office": "Office", "schlaf": "Schlafzimmer"}.get(room, room)
        delta_hx = inside_hx - outside_hx
        # Fenster reicht, wenn Innen nicht extrem (≥ 35 = great discomfort) UND
        # Außenluft spürbar kühler — dann Lüftungs-Vorschlag statt Klima.
        fenster_reicht = (
            inside_hx < HUMIDEX_UNCOMFORTABLE
            and delta_hx >= HUMIDEX_INSIDE_OUTSIDE_MIN_DELTA
        )

        if fenster_reicht:
            title = f"Fenster {room_de} auf?"
            message = (
                f"Innen {inside_temp:.1f}°C / gefühlt {inside_hx:.1f}°C — "
                f"außen Hx {outside_hx:.1f}°C (Δ {delta_hx:.1f}). "
                f"Lüften reicht, Klima spart Strom."
            )
            button_actions = [
                {"action": f"WATTSON_KLIMA_{room.upper()}_FENSTER",
                 "title": "Fenster auf", "icon": "sfsymbols:wind"},
                {"action": f"WATTSON_KLIMA_{room.upper()}_ON",
                 "title": "Klima trotzdem", "icon": "sfsymbols:snowflake"},
                {"action": f"WATTSON_KLIMA_{room.upper()}_OFF",
                 "title": "Ignorieren", "icon": "sfsymbols:xmark"},
            ]
        else:
            title = f"Klima {room_de} sinnvoll?"
            message = (
                f"{inside_temp:.1f}°C, gefühlt {inside_hx:.1f}°C "
                f"(außen Hx {outside_hx:.1f}°C). "
                f"Soll-Cool {cool_target:.0f}°C."
            )
            button_actions = [
                {"action": f"WATTSON_KLIMA_{room.upper()}_ON",
                 "title": f"{room_de} AN", "icon": "sfsymbols:snowflake"},
                {"action": f"WATTSON_KLIMA_{room.upper()}_OFF",
                 "title": "Ignorieren", "icon": "sfsymbols:xmark"},
            ]

        notify_data = {
            "title": title,
            "message": message,
            "data": {
                "tag": f"wattson_uc11_{room}",  # gruppiert + ersetzt vorherige
                "actions": button_actions,
            },
        }

        if self._dry_run:
            _LOGGER.info("[DRY-RUN] UC11 advisor notify %s: %s", room, message)
            actions.append(f"DRY-RUN: notify({room}) {message}")
        else:
            try:
                await self.hass.services.async_call(
                    "notify",
                    NOTIFY_SERVICE.split(".", 1)[1],
                    notify_data,
                    blocking=False,
                )
                self._uc11_last_notify_utc[room] = now
                actions.append(f"UC11 {room}: Notify gesendet ({message})")
                _LOGGER.info("UC11 advisor notify gesendet (%s): %s", room, message)
            except Exception as ex:
                _LOGGER.warning("UC11 notify fehlgeschlagen: %s", ex)

    async def _handle_uc12_cooling(
        self, s: WattsonData, now: datetime, actions: list[str]
    ) -> None:
        """UC12: Proxon-Kühlung-Freigabe netzdienlich steuern. Setzt s.cooling_active
        damit UC10 die Discharge-Sperre entsprechend lockern kann."""
        s.uc_status["uc12"] = self._uc_idle_status("uc12")
        s.uc_reason["uc12"] = ""

        if not self._override.is_enabled("uc12"):
            s.uc_status["uc12"] = "disabled"
            s.uc_reason["uc12"] = "disabled (per Switch)"
            s.cooling_active = s.cool_enable_on  # respect aktuellen Zustand
            return

        if self._override.in_cooldown("uc12"):
            remaining = self._override.cooldown_remaining_minutes("uc12")
            s.uc_status["uc12"] = f"user-override ({remaining}min Rest)"
            s.uc_reason["uc12"] = f"user-override aktiv ({remaining}min Rest)"
            s.cooling_active = s.cool_enable_on
            # Reminder: User hat Kühlung von Hand an → erinnern wenn kühl genug / teuer
            await self._uc12_send_reminder(s, now, actions)
            return

        # Entscheidung berechnen
        if s.sleep_mode:
            should_cool = False
            reason = f"Schlafmodus → Kühlung aus (Abluft {s.abluft_temp:.1f}°C)"
        elif s.abluft_temp <= COOL_ABLUFT_TRIGGER_C:
            should_cool = False
            reason = (f"Abluft {s.abluft_temp:.1f}°C ≤ "
                      f"{COOL_ABLUFT_TRIGGER_C}°C (kein Bedarf)")
        else:
            # Innen zu warm — evaluiere ob freigeben
            spread = (s.expensive_4h_avg - s.cheapest_4h_avg
                      if s.expensive_4h_avg and s.cheapest_4h_avg else 0)
            in_cheapest = bool(
                s.cheapest_4h_start
                and is_in_window(now, s.cheapest_4h_start, s.cheapest_4h_end)
            )

            if s.pv_surplus >= PV_COOLING_MIN_W:
                should_cool = True
                reason = (f"PV-Überschuss {s.pv_surplus}W ≥ {PV_COOLING_MIN_W}W "
                          f"(Abluft {s.abluft_temp:.1f}°C)")
            elif in_cheapest and spread < SMART_SPREAD_THRESHOLD_EUR:
                should_cool = True
                reason = (f"cheapest_4h, spread {spread*100:.1f}ct < "
                          f"{SMART_SPREAD_THRESHOLD_EUR*100:.1f}ct → UC12 Priorität "
                          f"(Abluft {s.abluft_temp:.1f}°C)")
            elif in_cheapest:
                should_cool = False
                reason = (f"cheapest_4h, aber spread {spread*100:.1f}ct ≥ "
                          f"{SMART_SPREAD_THRESHOLD_EUR*100:.1f}ct → UC10 Priorität, "
                          f"Kühlung warten (Abluft {s.abluft_temp:.1f}°C)")
            else:
                should_cool = False
                reason = (f"kein PV-Überschuss + nicht in cheapest_4h "
                          f"(Abluft {s.abluft_temp:.1f}°C, "
                          f"Preis-Level {s.price_level})")

        # Hysterese gegen Schwingen — wenn Kühlung gerade läuft, erst bei Trigger-1 ausgehen
        if s.cool_enable_on and not should_cool and s.abluft_temp > (
            COOL_ABLUFT_TRIGGER_C - COOL_ABLUFT_HYSTERESE_C
        ) and not s.sleep_mode:
            should_cool = True
            reason = (f"Hysterese: Kühlung läuft + Abluft {s.abluft_temp:.1f}°C noch "
                      f"über {COOL_ABLUFT_TRIGGER_C - COOL_ABLUFT_HYSTERESE_C}°C")

        s.cooling_active = should_cool
        s.uc_reason["uc12"] = reason

        # Switch anpassen wenn nötig
        if should_cool == s.cool_enable_on:
            s.uc_status["uc12"] = self._uc_idle_status("uc12")
            return

        target_value = "on" if should_cool else "off"
        service = "turn_on" if should_cool else "turn_off"
        _LOGGER.info("UC12: switch %s (%s)", target_value, reason)

        acted, act_desc = await self._try_act(
            "uc12", ENTITY_PROXON_COOL_ENABLE, target_value,
            "switch", service,
            {"entity_id": ENTITY_PROXON_COOL_ENABLE},
        )
        if acted:
            actions.append(act_desc)
            s.uc_status["uc12"] = "aktiv"
        else:
            s.uc_status["uc12"] = act_desc
            s.uc_reason["uc12"] = f"{reason} (geblockt: {act_desc})"

    async def _uc12_send_reminder(
        self, s: WattsonData, now: datetime, actions: list[str]
    ) -> None:
        """UC12 Reminder: User hat Kühlung von Hand an (Override aktiv) und vergisst
        evtl. das Ausschalten. Push wenn kühl genug (Abluft ≤ Trigger) ODER Preis-Level
        ≥ expensive. Wattson schaltet NIE selbst — die Buttons entscheiden. Respektiert
        Schlafmodus/Quiet-Hours, Snooze (Helper) und Cooldown (1/h)."""
        if not s.cool_enable_on:
            return  # Kühlung ist aus → nichts zu erinnern

        cool_enough = s.abluft_temp <= COOL_ABLUFT_TRIGGER_C
        expensive = s.price_level in UC12_EXPENSIVE_LEVELS
        if not (cool_enough or expensive):
            return

        # Schlafmodus / Quiet-Hours: nicht stören (Frau leichter Schläfer)
        if s.sleep_mode or now.hour >= UC11_QUIET_START_H or now.hour < UC11_QUIET_END_H:
            actions.append("UC12 Reminder unterdrückt (Schlafmodus/Quiet-Hours)")
            return

        # Snooze aktiv?
        if s.cool_snooze_until and now < s.cool_snooze_until:
            return

        # Cooldown — max 1 Reminder/h
        if self._uc12_last_reminder_utc is not None:
            elapsed_min = (now - self._uc12_last_reminder_utc).total_seconds() / 60
            if elapsed_min < UC12_REMINDER_COOLDOWN_MIN:
                return

        if cool_enough and expensive:
            grund = f"kühl genug (Abluft {s.abluft_temp:.1f}°C) + Strom teuer ({s.price_level})"
        elif cool_enough:
            grund = f"kühl genug — Abluft {s.abluft_temp:.1f}°C ≤ {COOL_ABLUFT_TRIGGER_C:.0f}°C"
        else:
            grund = f"Strom teuer ({s.price_level})"

        notify_data = {
            "title": "Proxon-Kühlung noch an",
            "message": f"Du hast die Kühlung von Hand an. {grund}. Ausschalten?",
            "data": {
                "tag": "wattson_uc12_kuehlung",  # gruppiert + ersetzt vorherige
                "actions": [
                    {"action": "WATTSON_KUEHL_AUS", "title": "Aus",
                     "icon": "sfsymbols:power"},
                    {"action": "WATTSON_KUEHL_SNOOZE_30", "title": "30 min",
                     "icon": "sfsymbols:clock"},
                    {"action": "WATTSON_KUEHL_SNOOZE_60", "title": "1 h",
                     "icon": "sfsymbols:clock"},
                ],
            },
        }

        if self._dry_run:
            _LOGGER.info("[DRY-RUN] UC12 reminder: %s", grund)
            actions.append(f"DRY-RUN: UC12 reminder ({grund})")
            return
        try:
            await self.hass.services.async_call(
                "notify", NOTIFY_SERVICE.split(".", 1)[1], notify_data, blocking=False,
            )
            self._uc12_last_reminder_utc = now
            actions.append(f"UC12 Reminder gesendet ({grund})")
            _LOGGER.info("UC12 reminder gesendet: %s", grund)
        except Exception as ex:  # noqa: BLE001
            _LOGGER.warning("UC12 reminder fehlgeschlagen: %s", ex)

    async def _handle_uc14_grid_charge(
        self, s: WattsonData, now: datetime, actions: list[str]
    ) -> None:
        """UC14: Batterie aus Netz laden bei Spread ≥ 11 ct + Fenster passend zum freien SOC-Platz.

        Aktiv-Bedingungen (alle erfüllt):
        - EMHASS verfügbar UND `p_batt < 0` (Plan sagt: laden)
        - Aktueller Preis ≤ max_price_next_24h − 11 ct (großer Spread)
        - SOC < 90%
        - Genug zusammenhängende günstige Minuten ab now: max(30min, freier_SOC×4.6kWh/1.5kW×1.1)
        - Override-aware (Sleep/Urlaub/manueller Eingriff)
        """
        s.uc_status["uc14"] = self._uc_idle_status("uc14")
        s.uc_reason["uc14"] = ""

        def _set_inactive(reason: str) -> None:
            s.uc_reason["uc14"] = reason
            s.uc14_active = False

        if self._e3dc is None:
            _set_inactive("deaktiviert (kein E3DC konfiguriert)")
            return
        if not self._override.is_enabled("uc14"):
            s.uc_status["uc14"] = "disabled"
            _set_inactive("disabled (per Switch)")
            return
        if self._override.in_cooldown("uc14"):
            remaining = self._override.cooldown_remaining_minutes("uc14")
            s.uc_status["uc14"] = f"user-override ({remaining}min Rest)"
            _set_inactive(f"user-override aktiv ({remaining}min Rest)")
            return
        if s.sleep_mode:
            await self._end_uc14_grid_charge_if_active(s, actions, "Schlafmodus")
            _set_inactive("Schlafmodus aktiv")
            return
        if not s.emhass_available:
            await self._end_uc14_grid_charge_if_active(s, actions, "EMHASS weg")
            _set_inactive("EMHASS nicht verfügbar")
            return
        if s.emhass_p_batt_plan >= 0:
            await self._end_uc14_grid_charge_if_active(s, actions, "EMHASS p_batt≥0")
            _set_inactive(f"EMHASS will nicht laden (p_batt={s.emhass_p_batt_plan:.0f}W)")
            return
        if s.battery_soc >= UC14_SOC_MAX_PCT:
            await self._end_uc14_grid_charge_if_active(s, actions, f"SOC≥{UC14_SOC_MAX_PCT}%")
            _set_inactive(f"SOC {s.battery_soc}% ≥ {UC14_SOC_MAX_PCT}%")
            return
        if not s.forecast_slots:
            await self._end_uc14_grid_charge_if_active(s, actions, "Forecast leer")
            _set_inactive("kein Tibber-Forecast verfügbar")
            return

        # Spread-Check: Max-Preis nächste 24h finden
        upcoming = upcoming_slots(s.forecast_slots, now, 24)
        if not upcoming:
            await self._end_uc14_grid_charge_if_active(s, actions, "keine Slots")
            _set_inactive("keine Forecast-Slots in nächsten 24h")
            return
        max_price = max(sl.price for sl in upcoming)
        spread_threshold_eur = UC14_MIN_SPREAD_CT_KWH / 100.0
        trigger_price = max_price - spread_threshold_eur
        current_price = s.price
        spread_ct = (max_price - current_price) * 100
        s.uc14_spread_ct = spread_ct

        if current_price > trigger_price:
            await self._end_uc14_grid_charge_if_active(s, actions, f"Spread {spread_ct:.1f}ct zu klein")
            _set_inactive(
                f"Preis {current_price*100:.1f}ct, Spread nur {spread_ct:.1f}ct "
                f"< {UC14_MIN_SPREAD_CT_KWH:.0f}ct (Max heute {max_price*100:.1f}ct)"
            )
            return

        # Fenster-Länge nach freiem SOC-Platz
        free_pct = UC14_SOC_MAX_PCT - s.battery_soc
        needed_kwh = free_pct / 100.0 * UC14_BAT_CAPACITY_KWH * UC14_TOPUP_OVERHEAD_FACTOR
        needed_minutes = max(
            UC14_MIN_WINDOW_MINUTES,
            int(needed_kwh / UC14_CHARGE_POWER_KW * 60),
        )
        cheap_minutes = consecutive_cheap_minutes_from_now(
            s.forecast_slots, now, trigger_price,
        )
        s.uc14_window_minutes = cheap_minutes
        s.uc14_needed_minutes = needed_minutes

        if cheap_minutes < needed_minutes:
            await self._end_uc14_grid_charge_if_active(
                s, actions, f"Fenster {cheap_minutes}min < {needed_minutes}min benötigt",
            )
            _set_inactive(
                f"Fenster zu kurz: {cheap_minutes} min < {needed_minutes} min "
                f"(SOC {s.battery_soc}%→{UC14_SOC_MAX_PCT}% braucht {needed_kwh:.2f} kWh)"
            )
            return

        # → Bedingungen erfüllt, UC14 aktivieren
        reason = (
            f"Spread {spread_ct:.1f}ct (jetzt {current_price*100:.1f}ct vs Max "
            f"{max_price*100:.1f}ct), Fenster {cheap_minutes} min "
            f"(brauche {needed_minutes} min für SOC {s.battery_soc}%→{UC14_SOC_MAX_PCT}%)"
        )

        # Aktuelle Settings holen für Override-Detect
        current_settings = await self._e3dc.get_power_settings()
        if current_settings is None:
            _set_inactive("E3DC nicht erreichbar")
            return
        current_max_charge = int(current_settings.get("maxChargePower", UC14_FORCE_CHARGE_W))

        # Override-Detection: hat User maxChargePower extern geändert?
        if self._last_max_charge is not None and self._uc14_active:
            if abs(current_max_charge - self._last_max_charge) > 50:
                prev = self._last_max_charge
                await self._override.async_record_override(
                    "uc14", "e3dc_max_charge_power", current_max_charge,
                )
                self._last_max_charge = None
                self._uc14_active = False
                remaining = self._override.cooldown_remaining_minutes("uc14")
                s.uc_status["uc14"] = f"user-override neu erkannt ({remaining}min)"
                s.uc_reason["uc14"] = (
                    f"User hat maxChargePower extern auf {current_max_charge}W "
                    f"gesetzt (war {prev}W)"
                )
                return

        # Idempotenz: wenn schon aktiv und gesetzt, nichts tun
        if (self._uc14_active
                and abs(UC14_FORCE_CHARGE_W - current_max_charge) <= 50
                and int(current_settings.get("maxDischargePower", 1500)) == 0):
            s.uc14_active = True
            s.uc_status["uc14"] = "aktiv"
            s.uc_reason["uc14"] = f"aktiv — {reason}"
            return

        # Setzen: max_charge=1500 UND max_discharge=0 in einem Call
        desc = (f"e3dc.set_power_limits(charge={UC14_FORCE_CHARGE_W}W, discharge=0W) "
                f"← UC14 Netzladen")
        _LOGGER.info("UC14: %s — %s", desc, reason)

        if self._dry_run:
            _LOGGER.info("[DRY-RUN] %s", desc)
            actions.append(f"DRY-RUN: {desc}")
            self._uc14_active = True
            s.uc14_active = True
            s.uc_status["uc14"] = "aktiv"
            s.uc_reason["uc14"] = reason
            return

        success = await self._e3dc.set_power_limits(
            max_charge_w=UC14_FORCE_CHARGE_W, max_discharge_w=0,
        )
        if success:
            self._last_max_charge = UC14_FORCE_CHARGE_W
            self._last_max_discharge = 0  # UC10 verlässt sich darauf
            self._uc14_active = True
            s.uc14_active = True
            actions.append(desc)
            s.uc_status["uc14"] = "aktiv"
            s.uc_reason["uc14"] = reason
        else:
            s.uc_status["uc14"] = "fehler"
            s.uc_reason["uc14"] = "E3DC POST set_power_limits fehlgeschlagen"

    async def _end_uc14_grid_charge_if_active(
        self, s: WattsonData, actions: list[str], suffix: str,
    ) -> None:
        """Beendet UC14 sauber: max_charge zurück auf Default (1500W), max_discharge
        bleibt erstmal 0 — UC10 setzt im selben Cycle neu nach EMHASS-Plan."""
        if not self._uc14_active:
            return
        desc = (f"e3dc.set_max_charge_power({UC14_FORCE_CHARGE_W}W default) "
                f"← UC14 Ende ({suffix})")
        _LOGGER.info("UC14: %s", desc)
        if self._dry_run:
            actions.append(f"DRY-RUN: {desc}")
        else:
            await self._e3dc.set_max_charge_power(UC14_FORCE_CHARGE_W)
            actions.append(desc)
        self._uc14_active = False
        self._last_max_charge = None
        # _last_max_discharge bleibt — UC10 übernimmt jetzt

    async def _handle_uc10_discharge_lock(
        self, s: WattsonData, now: datetime, actions: list[str]
    ) -> None:
        """UC10: E3DC-Batterie-Discharge granular steuern via maxDischargePower.
        EMHASS-driven: setzt maxDischargePower = EMHASS p_batt_plan (clamped 0-1500).
        Fallback Heuristik: lock=on → 0W, lock=off → 1500W.

        Wenn UC14 (Netzladen) aktiv ist, hat UC14 bereits max_discharge=0 gesetzt
        — UC10 macht dann nichts (kein eigener POST → kein doppelter Write)."""
        s.uc_status["uc10"] = self._uc_idle_status("uc10")
        s.uc_reason["uc10"] = ""

        if self._e3dc is None:
            s.uc_reason["uc10"] = "deaktiviert (kein E3DC konfiguriert)"
            return
        if s.uc14_active:
            s.uc_reason["uc10"] = "UC14 Netzladen aktiv — UC10 pausiert"
            return
        if not self._override.is_enabled("uc10"):
            s.uc_status["uc10"] = "disabled"
            s.uc_reason["uc10"] = "disabled (per Switch)"
            return
        if self._override.in_cooldown("uc10"):
            remaining = self._override.cooldown_remaining_minutes("uc10")
            s.uc_status["uc10"] = f"user-override ({remaining}min Rest)"
            s.uc_reason["uc10"] = f"user-override aktiv ({remaining}min Rest)"
            return

        # Entscheidung: EMHASS-Plan vs Heuristik → target maxDischargePower
        if s.emhass_available:
            # EMHASS plant Discharge granular (z.B. 600W). Wir folgen direkt.
            # Wenn Plan < threshold → 0W (Sperre), sonst clamp 0..1500
            if s.emhass_p_batt_plan < EMHASS_BATT_DISCHARGE_MIN_W:
                target_w = 0
            else:
                target_w = min(int(s.emhass_p_batt_plan), E3DC_MAX_DISCHARGE_W)
            decision_source = f"EMHASS p_batt={s.emhass_p_batt_plan:.0f}W"
            should_lock = target_w == 0
        else:
            # Fallback Heuristik (binary lock on/off)
            if not (s.cheapest_4h_avg is not None and s.expensive_4h_avg is not None
                    and s.cheapest_4h_start and s.cheapest_4h_end):
                # Kein Forecast → kein Eingriff (Default Power-Limit setzen)
                target_w = E3DC_MAX_DISCHARGE_W
                decision_source = "kein EMHASS UND kein Tibber-Forecast → Default"
                should_lock = False
            else:
                spread = s.expensive_4h_avg - s.cheapest_4h_avg
                s.uc10_spread_eur = spread
                in_cheapest = is_in_window(now, s.cheapest_4h_start, s.cheapest_4h_end)
                pv_bypass_threshold = BATTERIE_KAPAZITAT_KWH * PV_BYPASS_FACTOR
                pv_bypass_active = s.pv_fc_tomorrow > pv_bypass_threshold
                cooling_bypass = bool(
                    s.cooling_active and spread < SMART_SPREAD_THRESHOLD_EUR
                )
                should_lock = bool(
                    spread >= MIN_SPREAD_EUR
                    and in_cheapest
                    and s.battery_soc >= SOC_BATTERY_RESERVE
                    and not pv_bypass_active
                    and not cooling_bypass
                )
                target_w = 0 if should_lock else E3DC_MAX_DISCHARGE_W
                bypass_parts = []
                if pv_bypass_active:
                    bypass_parts.append("PV-bypass")
                if cooling_bypass:
                    bypass_parts.append("UC12-bypass")
                bypass_str = f" [{', '.join(bypass_parts)}]" if bypass_parts else ""
                decision_source = (
                    f"Heuristik (spread {spread*100:.1f}ct, SOC {s.battery_soc}%)"
                    f"{bypass_str}"
                )

        s.uc10_idle_active = should_lock

        # Aktuelle E3DC power_settings holen für Override-Detection
        current_settings = await self._e3dc.get_power_settings()
        if current_settings is None:
            s.uc_reason["uc10"] = "E3DC nicht erreichbar"
            return
        current_max_discharge = int(current_settings.get("maxDischargePower", E3DC_MAX_DISCHARGE_W))

        # Override-Detection: hat User maxDischargePower extern geändert?
        if self._last_max_discharge is not None:
            # Toleranz 50W gegen Float-Rundung
            if abs(current_max_discharge - self._last_max_discharge) > 50:
                prev = self._last_max_discharge
                await self._override.async_record_override(
                    "uc10", "e3dc_max_discharge_power", current_max_discharge,
                )
                # Memory zurücksetzen — sonst feuert der Detect direkt nach
                # Cooldown-Ende oder Resume erneut (Race beobachtet 2026-05-27)
                self._last_max_discharge = None
                remaining = self._override.cooldown_remaining_minutes("uc10")
                s.uc_status["uc10"] = f"user-override neu erkannt ({remaining}min)"
                s.uc_reason["uc10"] = (
                    f"User hat maxDischargePower extern auf {current_max_discharge}W "
                    f"gesetzt (war {prev}W)"
                )
                return

        # Nur setzen wenn deutlich anders (>50W) — vermeidet unnötige Writes
        if abs(target_w - current_max_discharge) <= 50:
            s.uc_reason["uc10"] = (
                f"OK ({target_w}W max-discharge) — {decision_source}"
            )
            self._last_max_discharge = current_max_discharge
            return

        desc = f"e3dc.set_max_discharge_power({target_w}W) ← war {current_max_discharge}W"
        reason = f"{desc} — {decision_source}"
        _LOGGER.info("UC10: %s", reason)

        if self._dry_run:
            _LOGGER.info("[DRY-RUN] %s", desc)
            actions.append(f"DRY-RUN: {desc}")
            s.uc_status["uc10"] = "aktiv"
            s.uc_reason["uc10"] = reason
        else:
            success = await self._e3dc.set_max_discharge_power(target_w)
            if success:
                self._last_max_discharge = target_w
                actions.append(desc)
                s.uc_status["uc10"] = "aktiv"
                s.uc_reason["uc10"] = reason
            else:
                s.uc_status["uc10"] = "fehler"
                s.uc_reason["uc10"] = "E3DC POST set_max_discharge_power fehlgeschlagen"

    async def _handle_trip_planning(
        self, s: WattsonData, now: datetime, actions: list[str]
    ) -> None:
        # Default: aktiv mit reason — wird ggf. überschrieben
        s.uc_status["uc2"] = self._uc_idle_status("uc2")
        cfg = self._trip_cfg
        if not self._override.is_enabled("uc2"):
            s.trip_reason = "disabled (per Switch)"
            s.uc_status["uc2"] = "disabled"
            s.uc_reason["uc2"] = s.trip_reason
            return
        # UC2 erbt UC6's mode-Override — wenn User mode überschrieben hat,
        # macht ein Plan ohnehin keinen Sinn (pv-Mode wird nicht greifen)
        if self._override.in_cooldown("uc6"):
            remaining = self._override.cooldown_remaining_minutes("uc6")
            s.trip_reason = f"pausiert — evcc Mode-Override aktiv ({remaining}min Rest)"
            s.uc_status["uc2"] = f"user-override via uc6 ({remaining}min Rest)"
            s.uc_reason["uc2"] = s.trip_reason
            return
        if cfg is None or cfg.gmaps is None:
            s.trip_reason = "deaktiviert (kein Google Maps Key)"
            s.uc_status["uc2"] = "aktiv"
            s.uc_reason["uc2"] = s.trip_reason
            return
        if not cfg.auto_calendars:
            s.trip_reason = "deaktiviert (keine Kalender konfiguriert)"
            s.uc_status["uc2"] = "aktiv"
            s.uc_reason["uc2"] = s.trip_reason
            return

        events = await self._fetch_calendar_events(cfg.auto_calendars, cfg.lookahead_hours)
        event = next_relevant_event(events, now, SKIP_LOCATION_KEYWORDS)
        if event is None:
            s.trip_reason = "kein relevanter Termin in Sicht"
            self._planned_event_uid = None
            return

        s.trip_title = event.get("summary", "?")
        s.trip_location = event.get("location", "")
        s.trip_start = event["_start_dt"]
        s.trip_calendar = event.get("_calendar", "")

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
        s.uc_reason["uc2"] = s.trip_reason
        self._planned_event_uid = event_uid
