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
