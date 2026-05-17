DOMAIN = "wattson"
SCAN_INTERVAL_SECONDS = 300

# T300 Solltemperaturen
T300_TEMP_CHEAP   = 55.0
T300_TEMP_NORMAL  = 52.0
T300_TEMP_TEUER   = 45.0
T300_TEMP_MIN     = 45.0  # Unter dieser Temperatur immer heizen

# PV-Überschuss Schwellwerte für E-Heizstab
PV_SURPLUS_ON  = 1700  # W
PV_SURPLUS_OFF = 1600  # W

# E-Heizstab Vorbedingungen (Welle 4)
BATTERY_FULL     = 95   # % SOC ab dem Heizstab überhaupt erlaubt ist
BATTERY_NOT_FULL = 90   # % SOC unter dem Heizstab abschaltet
T300_TANK_MAX    = 60.0 # °C über dem Heizstab nicht weiter heizt

# Auto
SOC_WARNUNG  = 20  # % → Push-Notification
SOC_VORLADEN = 80  # % → Ziel bei langem Kalendertermin
SOC_TARGET   = 80  # % → unter diesem SOC wird in günstigste 4h forciert

# Tibber Preis-Level (Fallback wenn kein Forecast verfügbar)
CHEAP_LEVELS = ("very_cheap", "cheap")

# HA Entity IDs
ENTITY_PRICE          = "sensor.electricity_price_haus"   # state in EUR/kWh
ENTITY_PRICE_RANKING  = "sensor.electricity_price_haus"   # attr: intraday_price_ranking (float 0.0-1.0)
ENTITY_PRICE_LEVEL    = "sensor.haus_current_hour_price_level"
ENTITY_PV_SURPLUS     = "sensor.pv_uberschuss_der_letzen_15_minuten"
ENTITY_T300_TANK      = "sensor.proxon_t300_t21_behalter_mitte"
ENTITY_T300_SOLL      = "input_number.t300_solltemperatur"
ENTITY_T300_HEIZSTAB  = "switch.proxon_t300_e_heizstab"
ENTITY_EVCC_MODE      = "select.evcc_auto_mode"
ENTITY_EVCC_CONNECTED = "binary_sensor.evcc_auto_connected"
ENTITY_EVCC_SOC       = "sensor.evcc_auto_vehicle_soc"
ENTITY_EVCC_RANGE     = "sensor.evcc_auto_vehicle_range"
ENTITY_BATTERY_SOC    = "sensor.e3dc_batterie_soc_in_prozent"
ENTITY_PV_POWER       = "sensor.e3dc_photovoltaik_leistung_in_watt"
ENTITY_SLEEP          = "input_boolean.sleepmode_helper"

# forecast.solar (PV Forecast)
ENTITY_PV_FC_NOW       = "sensor.power_production_now"               # W
ENTITY_PV_FC_HOUR      = "sensor.energy_current_hour"                # kWh
ENTITY_PV_FC_NEXT_HOUR = "sensor.energy_next_hour"                   # kWh
ENTITY_PV_FC_REMAINING = "sensor.energy_production_today_remaining"  # kWh
ENTITY_PV_FC_TOMORROW  = "sensor.energy_production_tomorrow"         # kWh
ENTITY_PV_PEAK_TODAY   = "sensor.power_highest_peak_time_today"      # datetime
ENTITY_PV_PEAK_TOMORROW = "sensor.power_highest_peak_time_tomorrow"  # datetime

NOTIFY_SERVICE = "notify.mobile_app_ios_hw23x69q47"

# Welle 7 — UC2 Kalender-Vorladen (Defaults für Config Flow)
CONF_GMAPS_KEY            = "google_maps_api_key"
CONF_HOME_ADDRESS         = "home_address"
CONF_CALENDAR_ENTITY      = "calendar_entity"      # deprecated, siehe AUTO_CALENDARS
CONF_AUTO_CALENDARS       = "auto_calendars"       # Liste der für Auto-Fahrten relevanten Kalender
CONF_VEHICLE_CONSUMPTION  = "vehicle_consumption_kwh_100km"
CONF_VEHICLE_CAPACITY     = "vehicle_capacity_kwh"
CONF_SAFETY_MARGIN        = "safety_margin_percent"
CONF_EVCC_VEHICLE_NAME    = "evcc_vehicle_name"
CONF_EVENT_LOOKAHEAD      = "event_lookahead_hours"

DEFAULT_HOME_ADDRESS         = "Limburg an der Lahn, Germany"
DEFAULT_CALENDAR_ENTITY      = "calendar.amazone"  # deprecated
DEFAULT_AUTO_CALENDARS       = ["calendar.arbeit", "calendar.barchen"]
DEFAULT_VEHICLE_CONSUMPTION  = 20.0   # kWh/100km
DEFAULT_VEHICLE_CAPACITY     = 63.0   # kWh
DEFAULT_SAFETY_MARGIN        = 25     # %
DEFAULT_EVCC_VEHICLE_NAME    = "ora"
DEFAULT_EVENT_LOOKAHEAD      = 36     # h

# Skip Locations die offensichtlich keine echte Fahrt brauchen
SKIP_LOCATION_KEYWORDS = ("microsoft teams", "teams meeting", "zoom", "https://", "http://")

# Plan-Charging — Wattson setzt Plan max 1× pro Event, identifiziert via uid
EVCC_PLAN_BUFFER_MINUTES = 30  # Plan zielt N Min vor Event-Start
