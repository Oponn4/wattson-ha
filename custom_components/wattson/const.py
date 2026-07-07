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

# Heizstab-Failsafe (v0.18.8): länger als so viele Stunden kontinuierlich an
# → Zwangsabschaltung am Override-System vorbei + Push. Normalbetrieb sind
# Zyklen von 10–40 min (PV) bzw. EMHASS-Blöcke von 1–2 h; ein Legionellen-Lauf
# (52 → 60 °C) braucht ~1–1.5 h. Alles legitim liegt klar unter 4 h.
HEIZSTAB_MAX_CONTINUOUS_H = 4.0
HEIZSTAB_FAILSAFE_NOTIFY_COOLDOWN_MIN = 60  # Push max 1/h falls Off-Write verpufft

# Legionellen-Aufheizung im Urlaub (v0.18.8): T300 hat KEIN eigenes
# Legionellen-Programm; im Normalbetrieb sorgt Warmwasserzapfung + PV-Fenster
# für Durchsatz, im Urlaub steht das Wasser. Alle N Tage im günstigen Fenster
# (cheapest_4h oder PV-Überschuss) per Heizstab auf Zieltemperatur.
# 7 Tage / 60 °C = übliche Praxis für EFH-Kleinanlagen (DVGW W551-Umfeld).
LEGIONELLA_INTERVAL_DAYS = 7
# v0.18.11: Echte Desinfektion wie die alte Geräte-Legionellenfunktion —
# Christian: 65°C reicht (Abtötung in ~2 min; alte Funktion fuhr 70).
# Ablauf: Boost-Ziel (Reg 2003) für den Lauf auf LEGIONELLA_BOOST_TEMP_C
# heben, Boost (Reg 2001) an, Abschluss bei T21 ≥ TARGET (knapp unter dem
# Boost-Ziel, sonst wird der Lauf nie fertig), danach Reg 2003 restaurieren.
# Boost hat ~3–5 K Einschalt-Hysterese unterm Ziel (Feldtest 7.7.: Ziel 59 /
# Tank 56.9 → keine Reaktion; Ziel 65 → Stab an) — beim echten Lauf startet
# der Tank bei ~52 (WP-Soll), Hysterese also nie ein Problem.
# NIE Betriebsart LF1/LF2 (Reg 2002) verwenden: Legacy-Modi, neue App kennt
# sie nicht (zeigt „Warmwasser aus") und der Modus legt Warmwasser still.
LEGIONELLA_BOOST_TEMP_C  = 65.0
LEGIONELLA_TARGET_C      = 64.5
# Stab schafft real ~1.7 K/h auf T21-Mitte; 52→65 mit WP-Anteil ≈ 6–8h.
LEGIONELLA_MAX_RUNTIME_H = 12.0
# PV-Start nur vormittags/früher Nachmittag — der lange Lauf soll in Sonne
# und Billigfenster liegen, nicht in den Abendpeak laufen.
LEGIONELLA_PV_START_BEFORE_H = 13
# v0.18.10: 3-Stufen-Start-Eskalation (Dunkelflauten-Hedge, PV = inverser
# Flauten-Melder — Mehrtages-Preisforecast gibt es nicht):
#   ≥ EARLY_PV_DAYS:        PV-Überschuss → vorziehen (Sonnentag mitnehmen)
#   ≥ INTERVAL+GRACE_DAYS:  cheapest_4h, aber nur wenn price_level nicht
#                           expensive (Tibber-Level ist relativ → saisonfest)
#   ≥ HARD_DAYS:            cheapest_4h bedingungslos (Hygiene > Preis)
LEGIONELLA_EARLY_PV_DAYS = 5
LEGIONELLA_PV_GRACE_DAYS = 2
LEGIONELLA_HARD_DAYS     = 12

# Auto
SOC_WARNUNG  = 20  # % → Push-Notification
SOC_VORLADEN = 80  # % → Ziel bei langem Kalendertermin
SOC_TARGET   = 80  # % → unter diesem SOC wird in günstigste 4h forciert

# Tibber Preis-Level (Fallback wenn kein Forecast verfügbar)
CHEAP_LEVELS = ("very_cheap", "cheap")

# HA Entity IDs
ENTITY_PROXON_ABLUFT      = "sensor.proxon_fwt_temperatur_t07_abluft"
ENTITY_PROXON_COOL_ENABLE = "switch.proxon_fwt_kuhlung"
ENTITY_COOL_SNOOZE        = "input_datetime.wattson_kuhlung_snooze_bis" # UC12 Reminder-Snooze (von Action-Automation gesetzt)

# UC11 — Klimaanlagen OG (Office + Schlafzimmer)
ENTITY_KLIMA_OFFICE         = "climate.klimaanlage_office_air_conditioner"
ENTITY_KLIMA_SCHLAFZIMMER   = "climate.klimaanlage_schlafzimmer_air_conditioner"
ENTITY_PROXON_CLIMATE_OFFICE        = "climate.proxon_fwt_office"
ENTITY_PROXON_CLIMATE_SCHLAFZIMMER  = "climate.proxon_fwt_schlafen"
ENTITY_URLAUB_MODE          = "input_boolean.urlaubsmodus"
ENTITY_FRISCHLUFT           = "sensor.proxon_fwt_temperatur_t03_frischluft"
ENTITY_WEATHER_FORECAST     = "weather.forecast_home"           # Für Hitze-Forecast morgen
ENTITY_PERSON_CHRISTIAN     = "person.christian"
ENTITY_PERSON_SONJA         = "person.sonja"
ENTITY_PRICE          = "sensor.electricity_price_haus"   # state in EUR/kWh
ENTITY_PRICE_RANKING  = "sensor.electricity_price_haus"   # attr: intraday_price_ranking (float 0.0-1.0)
ENTITY_PRICE_LEVEL    = "sensor.haus_current_hour_price_level"
ENTITY_PV_SURPLUS     = "sensor.pv_uberschuss_der_letzen_15_minuten"
ENTITY_T300_TANK      = "sensor.proxon_t300_temperatur_t21_behalter_mitte"
ENTITY_T300_SOLL      = "number.proxon_t300_solltemperatur"
ENTITY_T300_HEIZSTAB  = "switch.proxon_t300_e_heizstab"
# Boost-Zieltemperatur (Reg 2003) — wird für Legionellen-Läufe temporär auf
# LEGIONELLA_BOOST_TEMP_C gehoben und danach restauriert
ENTITY_T300_BOOST_TEMP = "number.proxon_t300_temperatur_e_heiz"
ENTITY_EVCC_MODE      = "select.evcc_auto_mode"
ENTITY_EVCC_CONNECTED = "binary_sensor.evcc_auto_connected"
ENTITY_EVCC_SOC       = "sensor.evcc_auto_vehicle_soc"
ENTITY_EVCC_RANGE     = "sensor.evcc_auto_vehicle_range"
ENTITY_BATTERY_SOC    = "sensor.s10e_state_of_charge"   # % via e3dc_rscp
ENTITY_PV_POWER       = "sensor.s10e_solar_production"   # kW via e3dc_rscp
ENTITY_SLEEP          = "input_boolean.sleepmode_helper"

# EMHASS Sensors (publishes alle 5min via cron)
ENTITY_EMHASS_OPTIM_STATUS    = "sensor.optim_status"
ENTITY_EMHASS_P_BATT_FORECAST = "sensor.p_batt_forecast"     # W, positiv=Entladung
ENTITY_EMHASS_P_DEFERRABLE0   = "sensor.p_deferrable0"       # W, T300-Heizstab Plan
ENTITY_EMHASS_P_DEFERRABLE1   = "sensor.p_deferrable1"       # W, Wallbox Plan
ENTITY_EMHASS_SOC_FORECAST    = "sensor.soc_batt_forecast"   # % (auch 24h-Plan im Attribut)

EMHASS_OPTIM_OK            = "Optimal"
EMHASS_BATT_DISCHARGE_MIN_W = 100   # > 100W = "darf entladen", sonst sperren
EMHASS_DEFERRABLE_ON_MIN_W  = 500   # > 500W = "Heizstab/Wallbox sollte laufen"
EMHASS_MAX_PLAN_AGE_H      = 2      # Plan älter als 2h → unavailable + notify

# UC6 Hysterese: nach Mode-Switch mindestens N Minuten halten — verhindert 5-min-Oszillation
UC6_MODE_HOLD_MINUTES = 10  # v0.17.1: gesenkt von 15 — Confirmation übernimmt Anti-Jitter

# UC6 3-Level-Mode (v0.17.1) — 3-phasig fest + 5.2 kWp PV:
# pv-Mode lädt selten autonom (Min 4.14 kW Überschuss nötig), Default ist deshalb
# minpv für "günstig laden auch ohne Vollüberschuss", now nur bei echtem Notfall.
UC6_NOW_SOC_THRESHOLD_PCT     = 50     # SOC < X% + Trip-Termin → now
UC6_NOW_TRIP_URGENT_HOURS     = 12     # Trip in < X h → now
UC6_MINPV_PRICE_LEVELS        = ("very_cheap", "cheap", "normal")
# Downshift (Richtung "weniger laden") braucht Confirmation gegen Replan-Jitter
UC6_DOWNSHIFT_CONFIRMATION_CYCLES = 2  # 2 Cycles in Folge "kein Bedarf mehr"

# UC4b Plan-aware Execution (v0.16.0) — Wattson liest EMHASS-Plan vorausschauend
# statt Live-Werte reaktiv zu folgen. Anti-Replan-Jitter durch Confirmation-Cycles.
UC4B_CONFIRMATION_CYCLES   = 2     # so viele Cycles in Folge "Plan=off" bis ausschalten
UC4B_REMINDER_COOLDOWN_MIN = 60    # Safety-Reminder: max 1/h

# UC14 Netzladen aus Netz (siehe project_wattson_uc14_netzladen.md)
UC14_MIN_SPREAD_CT_KWH = 11.0      # Mindest-Spread günstigster vs teuerster Slot (User-Entscheidung)
UC14_SOC_MAX_PCT       = 90        # Lade nur bis 90% — drüber ist's zu teuer für Last-Hop-Verlust
UC14_BAT_CAPACITY_KWH  = 4.6       # E3DC S10E Akku-Kapazität (siehe reference_e3dc_spec.md)
UC14_CHARGE_POWER_KW   = 1.5       # E3DC max-Charge-Power Hardware
UC14_MIN_WINDOW_MINUTES = 30       # Floor — unter 30 min lohnt Setup nicht
UC14_TOPUP_OVERHEAD_FACTOR = 1.1   # +10% Puffer für Lade-Verluste am Top
UC14_FORCE_CHARGE_W = 1500         # max_charge_power während UC14 aktiv (Hardware-Max)

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

# ── Use Cases (für Override-Manager + UI-Switches/Sensoren/Buttons) ──
# Tuple: (uc_id, slug, display_name, default_enabled)
# uc_id = interner Code-Identifier (für Override-Manager, Status-Tracking)
# slug = User-facing Entity-ID-Suffix (kebab-case-frei, snake_case)
# display = friendly_name nach "Wattson "
UC_DEFINITIONS = [
    ("uc4a", "warmwasser_soll",     "Warmwasser Solltemperatur", True),
    ("uc4b", "warmwasser_heizstab", "Warmwasser Heizstab",       True),
    ("uc6",  "eauto_modus",         "E-Auto Modus",              True),
    ("uc2",  "eauto_fahrplan",      "E-Auto Fahrplan",           True),
    ("uc10", "batterie_schoner",    "Batterie Schoner",          True),
    ("uc12", "kuhlung",             "Kühlung",                   True),
    ("uc11", "klima",               "Klimaanlagen OG",           True),
    ("uc14", "netzladen",           "Netzladen Batterie",        True),
]

# Mapping für Migration v1 → v2: alte unique_id-Suffixe → neue
UNIQUE_ID_MIGRATION_V2 = {
    "uc4a_enabled":  "warmwasser_soll_enabled",
    "uc4a_status":   "warmwasser_soll_status",
    "uc4a_resume":   "warmwasser_soll_resume",
    "uc4b_enabled":  "warmwasser_heizstab_enabled",
    "uc4b_status":   "warmwasser_heizstab_status",
    "uc4b_resume":   "warmwasser_heizstab_resume",
    "uc6_enabled":   "eauto_modus_enabled",
    "uc6_status":    "eauto_modus_status",
    "uc6_resume":    "eauto_modus_resume",
    "uc2_enabled":   "eauto_fahrplan_enabled",
    "uc2_status":    "eauto_fahrplan_status",
    "uc2_resume":    "eauto_fahrplan_resume",
    "uc10_enabled":  "batterie_schoner_enabled",
    "uc10_status":   "batterie_schoner_status",
    "uc10_resume":   "batterie_schoner_resume",
    "uc12_enabled":  "kuhlung_enabled",
    "uc12_status":   "kuhlung_status",
    "uc12_resume":   "kuhlung_resume",
    # Sensoren mit unschönen Namen
    "t300_target":   "warmwasser_ziel",
    "evcc_target":   "eauto_ziel",
    "next_trip":     "naechste_fahrt",
}

# ── UC10 — E3DC Batterie-Discharge-Sperre in günstigen Stunden ──
CONF_E3DC_URL      = "e3dc_url"
CONF_E3DC_USER     = "e3dc_user"
CONF_E3DC_PASSWORD = "e3dc_password"

DEFAULT_E3DC_URL      = "http://10.42.2.5:8080"
DEFAULT_E3DC_USER     = "admin"
DEFAULT_E3DC_PASSWORD = "admin"

# Wirtschaftlichkeit
EEG_VERGUETUNG_EUR_KWH = 0.111  # Einspeisevergütung am Haus BGW29
MIN_SPREAD_EUR         = 0.07   # cheapest_4h vs expensive_4h muss >= 7ct sein damit UC10 lohnt
SOC_BATTERY_RESERVE    = 20     # % — unter diesem SOC keine Discharge-Sperre (Batterie eh leer)

# UC10 Phase 2: PV-Forecast-Bypass
# Wenn morgen mehr PV erwartet wird als BATTERIE_KAPAZITÄT × N, soll Discharge
# NICHT gesperrt werden — Batterie soll nachts entladen damit morgens Platz für
# PV-Aufnahme bleibt (verhindert Einspeisung @ 11.1ct statt Eigennutzung @ 30ct)
BATTERIE_KAPAZITAT_KWH = 4.6
PV_BYPASS_FACTOR       = 4.0    # pv_fc_tomorrow > 4.6 * 4.0 = 18.4 kWh → Bypass
E3DC_MAX_DISCHARGE_W   = 1500   # Hardware-Max der S10E Batterie

# UC12 — Proxon Kühlung
# Trigger/Heat sind ab v0.17 *Basis*-Werte; effektiv skaliert per Outdoor-Forecast
# in coordinator._compute_cool_thresholds(). Bei outside_max == COOL_OUTSIDE_REF_C
# kommen Trigger=BASE_C bzw. Heat=HEAT_BASE_C heraus. Slope > 0 hebt beide bei
# Hitzewelle an (Komfort-Adaption); Min/Max sind harte Grenzen.
COOL_ABLUFT_TRIGGER_C      = 24.0   # °C — Basis-Kühlbedarf bei outside_max ≈ Ref
COOL_ABLUFT_HYSTERESE_C    = 1.0    # °C — Hysterese gegen Schwingen
COOL_ABLUFT_HEAT_C         = 25.5   # °C — Basis-„echte Hitze" (bricht Sleep+expensive)
COOL_OUTSIDE_REF_C         = 20.0   # °C — Außen-Forecast-Referenz
COOL_OUTSIDE_SLOPE         = 0.15   # +0.15 °C Schwelle pro 1 °C Außen-Surplus über Ref
COOL_TRIGGER_MIN_C         = 23.5
COOL_TRIGGER_MAX_C         = 25.0
COOL_HEAT_MIN_C            = 25.5
COOL_HEAT_MAX_C            = 27.0
PV_COOLING_MIN_W           = 1500   # W — ab diesem PV-Überschuss darf gekühlt werden
SMART_SPREAD_THRESHOLD_EUR = 0.15   # spread >= 15ct → UC10 gewinnt vs UC12, sonst Komfort wichtiger

# UC12 v0.17.2 — B: Humidex-Korrektur (Schwüle), C: Trend-Korrektur.
# Beide korrigieren die v0.17-Schwellen nach unten: bei Schwüle fühlt sich
# dieselbe Abluft wärmer an (Trigger früher), bei steigendem Trend kommt die
# Hitze ohnehin (Heat/Force früher). RH-Quelle: TP357 Wohnzimmer als Proxy
# (ENTITY_HUMIDITY_PROXY) bis pro-Raum-RH-Sensoren da sind.
COOL_HUMIDEX_RH_PCT        = 60.0   # % RH ab der "schwül" gilt
COOL_HUMIDEX_TRIGGER_DELTA = -0.5   # °C auf Trigger bei Schwüle
COOL_TREND_RISE_C_PER_H    = 0.3    # °C/h Abluft-Anstieg ab dem Heat sinkt
COOL_TREND_HEAT_DELTA      = -0.5   # °C auf Heat bei steigendem Trend
TREND_WINDOW_MINUTES       = 60     # Fenster für Trend-Berechnung
TREND_MIN_SPAN_MINUTES     = 20     # Mindest-Datenspanne bevor Trend gilt

# UC12 Kühl-Reminder (während User-Override): erinnert ans Ausschalten wenn
# kühl genug ODER Preis-Level ≥ expensive. Wattson schaltet NIE selbst — nur Notify.
UC12_REMINDER_COOLDOWN_MIN    = 60   # max 1 Reminder/h
UC12_HEAT_NOTIFY_COOLDOWN_MIN = 60   # max 1 Heat-Notify/h (Auto-Pfad, Force-Hitze)
UC12_EXPENSIVE_LEVELS = ("expensive", "very_expensive")  # "viel teurer"-Trigger (User-Entscheidung)

# UC11 — Klimaanlagen OG
CLIMATE_COOL_OFFSET_C      = 2.0   # Klima-Cool-Sollwert = Proxon-Heiz-Soll + diese Offset
CLIMATE_PRECOOL_OFFSET_C   = -2.0  # bei Pre-Cool: zusätzlicher Offset zum Cool-Sollwert
CLIMATE_PEAK_OFFSET_C      = 1.0   # bei Tibber-Peak: zusätzlicher Offset (höher = sparen)

# UC11 Auto-Aktion (v0.18) — pro Raum; Office hat jetzt echte RH-Sensoren
# Schlafzimmer: Advisor-Mode (Sonja leichter Schläfer — keine autonome Nacht-Aktion)
UC11_AUTO_ACTION_OFFICE    = True
UC11_AUTO_ACTION_SCHLAF    = False
UC11_NOTIFY_COOLDOWN_MIN   = 60     # max 1 Notify/h pro Raum
UC11_QUIET_START_H         = 22     # ab 22 Uhr keine Notifies (Schlaf)
UC11_QUIET_END_H           = 7      # bis 7 Uhr keine Notifies
HUMIDEX_WARM_THRESHOLD     = 30.0   # ab humidex 30 = "some discomfort" → Notify wenn Spread passt
HUMIDEX_UNCOMFORTABLE      = 35.0   # ab 35 = "great discomfort", Notify auch ohne Außen-Spread
HUMIDEX_INSIDE_OUTSIDE_MIN_DELTA = 3.0  # Innen muss mindestens diese °C-Humidex über Außen liegen
ENTITY_HUMIDITY_PROXY      = "sensor.tp357_27f5_humidity"  # Wohnzimmer-RH (Fallback falls OG-HT unavailable)
ENTITY_HT_OFFICE_TEMP        = "sensor.shelly_blu_h_t_ee37_temperature"
ENTITY_HT_OFFICE_HUMIDITY    = "sensor.shelly_blu_h_t_ee37_humidity"
ENTITY_HT_SCHLAFZIMMER_TEMP  = "sensor.bthome_sensor_757e_temperature"
ENTITY_HT_SCHLAFZIMMER_HUMIDITY = "sensor.bthome_sensor_757e_humidity"
ENTITY_WINDOW_OFFICE_LINKS   = "binary_sensor.office_doof_window_office_links_window"
PV_KLIMA_MIN_W             = 2000  # PV-Überschuss-Schwelle für aktives Klima-Triggern
HOT_FORECAST_THRESHOLD_C   = 30.0  # Tagesforecast > X°C → Pre-Cooling sinnvoll
OUTDOOR_WARM_MIN_C         = 24.0  # Außen > X°C → Klima cooling sinnvoll (sonst Fenster auf)
CLIMATE_TARGET_HYSTERESE_C = 0.5   # Innen muss > target + diese Diff sein für cool-Start
CLIMATE_ECO_OFFSET_C       = 2.0   # Sollwert-Bump bei Abwesenheit (sparen)
AWAY_LONG_HOURS            = 24    # Beide weg > X Stunden → wie Urlaub
