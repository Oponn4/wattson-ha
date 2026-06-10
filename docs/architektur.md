# Architektur

## Leitprinzip

Wattson ist ein **in sich rundes System für optimierte, vorausgeplante Aktionen** —
keine reaktive Sammlung verschiedener Automationen wie sonst in Home Assistant.

Jeder Use Case agiert aus einem **Forward-Plan** heraus (EMHASS-Schedule,
Preis-/PV-/Wetter-Forecast, Kalender), nicht auf Momentanwerte. Reaktive Trigger
sind nur als Sicherheitsnetz legitim (SOC-Warnung, Safety-Notifies, Hitze-Force).

Bei jedem neuen UC oder Refactor lautet die erste Frage:
**„Was ist der Plan-Horizont, und woher kommt der Plan?"** —
nicht „auf welchen State-Change triggern wir?".

## Single Source of Truth

Wattson trifft **alle** Energie-Entscheidungen: Batterie-Mode, Auto-Lademodus +
Plan, T300-Sollwert + Heizstab, Klima-Empfehlungen, Proxon-Kühlung.
Konkurrierende Optimierer bleiben deaktiviert:

- **AI360** (E3DC Cloud-AI) bleibt aus — kennt weder ORA via evcc noch T300/Klima/Kalender
- **evcc** auf passiven Defaults (`pv` als Basis), Wattson steuert via
  `select.evcc_auto_mode` + `evcc_intg.set_vehicle_plan`
- E3DC-interne Optimierung (z.B. `weatherRegulatedCharge`) erst nach bewusster Integration
- 1KOMMA5°-Heartbeat wurde eliminiert

Mehrere autonome Optimierer parallel = Race Conditions (bei UC2/UC6 real erlebt).

## EMHASS-Hybrid

EMHASS (LXC 106, podman, Port 5000) liefert das LP-Optimum, Wattson orchestriert
plan-aware und macht alles, was EMHASS nicht kann.

| Bereich | Owner | Implementierung |
|---------|-------|-----------------|
| Battery-Schedule (SOC-Trajektorie) | EMHASS | LP mit Tibber-Preisen + PV-Forecast |
| T300-Heizstab | EMHASS → UC4b | deferrable0, plan-aware |
| Wallbox-Energie | EMHASS → UC6 | deferrable1, plan-aware |
| Kalender-Trip (UC2) | Wattson | gmaps-Distanz → `evcc_intg.set_vehicle_plan` (evcc plant selbst) |
| Notifications (UC1, Safety) | Wattson | EMHASS hat keinen Notify-Pfad |
| Proxon-Kühlung (UC12) | Wattson | thermisch + forecast-skalierte Schwellen |
| Klimaanlagen (UC11) | Wattson | Advisor-Mode (Notify mit Action-Buttons) |
| Override-Pattern | Wattson | User-Eingriff-Respekt, Cooldown |

## Plan-aware Pattern (Lesson learned)

EMHASS replant alle 5 Minuten; der Live-State `sensor.p_deferrableX.state`
jittert dabei um Thresholds. Reaktives Umsetzen erzeugte Toggle-Bugs in UC4b
(5 Heizstab-Toggles in 65 min, gefixt v0.16.0) und UC6 (20 Mode-Toggles an
einem Tag, gefixt v0.17.1). Daher gilt für **jeden** EMHASS-Konsumenten:

1. **Forward-Plan lesen** (`attributes.deferrables_schedule`,
   `parse_deferrable_schedule()` / `deferrable_slot_at()` in `forecast.py`),
   nie den Live-State
2. **Downshift/Off nur nach Confirmation-Cycles** (2 Cycles in Folge),
   Upshift sofort

## Override-Pattern

User-Eingriffe haben Vorrang: erkennt ein UC eine manuelle Änderung an seiner
Ziel-Entity, geht er in `user-override` mit Cooldown statt zurückzusetzen.
`detect_override` behandelt `None`/`unavailable`/`unknown` als „keine Meinung"
(kein Phantom-Override durch transient unavailable Entities).

## Rahmenbedingungen

- Tick: alle 5 Minuten (`SCAN_INTERVAL_SECONDS = 300`)
- Dry-Run via Config Flow + Switch
- Sleep-Guard: `input_boolean.sleepmode_helper`, Quiet Hours 22–7 Uhr
- Netzdienlichkeit hat Vorrang vor reiner Eigenoptimierung

## Hardware-Setup (Referenz)

- ORA 03 GT, 63 kWh (59.3 nutzbar), Elli Wallbox **3-phasig fest angeklemmt**
  → Min-Ladeleistung 3×230V×6A = **4.14 kW**
- 5.2 kWp PV (E3DC S10E, 5 kWh Speicher — zu klein für Arbitrage)
- Proxon FWT + T300 (WP, Pufferspeicher, E-Heizstab), 9 kW Sauna
- Verbrauch ~6700 kWh/a (inkl. ~2500 Auto, ~900 Sauna)

Konsequenz: reiner `pv`-Mode lädt das Auto fast nie autonom (PV-Überschuss real
1–3 kW < 4.14 kW Floor) — jede Ladung braucht Netzanteil, daher das
3-Level-Mode-Design in UC6.

## Datenquellen

| Quelle | Entities/Services |
|---|---|
| evcc | `select.evcc_auto_mode`, `sensor.evcc_auto_vehicle_soc`, `sensor.evcc_battery_soc`, `evcc_intg.set_vehicle_plan` |
| ora2mqtt | `sensor.gwm_ora_03_soc` / `_reichweite` |
| Tibber | `sensor.electricity_price_haus`, `sensor.haus_current_hour_price_level`, Service `tibber.get_prices` (96×15min) |
| EMHASS | `sensor.p_deferrable0/1` (+ `attributes.deferrables_schedule`), `sensor.p_batt_forecast`, optim_status |
| Solcast | PV-Forecast, 30-min-Slots |
| Kalender | `calendar.amazone` (M365 → iCloud via iOS Shortcut) |
| E3DC | REST `http://10.42.2.5:8080/api/poll`, `set_power_limits` |
| Proxon | `sensor.proxon_t300_t21_behalter_mitte`, `input_number.t300_solltemperatur`, `switch.proxon_t300_e_heizstab` |
| Google Maps | Distance Matrix API (`gmaps.py`, 7-Tage-Cache pro Route) |
