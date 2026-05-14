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

# Auto
SOC_WARNUNG  = 20  # % → Push-Notification
SOC_VORLADEN = 80  # % → Ziel bei langem Kalendertermin

# Tibber Preis-Level
CHEAP_LEVELS = ("very_cheap", "cheap")

# HA Entity IDs
ENTITY_PRICE          = "sensor.haus_current_electricity_price"
ENTITY_PRICE_RANKING  = "sensor.electricity_price_haus"   # attr: intraday_price_ranking
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

NOTIFY_SERVICE = "notify.mobile_app_ios_hw23x69q47"
