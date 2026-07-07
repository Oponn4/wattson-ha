# Use Cases

Stand: v0.18.1 (2026-06-17). Alle live außer UC9 (Hardware-blocked).

| UC | Was | Seit |
|---|---|---|
| [UC1](#uc1--soc-warnung) | SOC-Warnung <20% | früh |
| [UC2](#uc2--kalender-vorladen) | Kalender-Trip → required SOC → evcc-Plan | v0.11 |
| [UC4a](#uc4a--t300-solltemperatur) | T300-Soll nach Tibber-Fenster | früh |
| [UC4b](#uc4b--e-heizstab-plan-aware) | Heizstab plan-aware (EMHASS deferrable0) | v0.16.0 |
| [UC6](#uc6--e-auto-lademodus-3-level) | E-Auto 3-Level pv/minpv/now (EMHASS deferrable1) | v0.17.1 |
| [UC9](#uc9--1p3p-umschaltung) | 1P/3P-Umschaltung | ⛔ blocked |
| [UC10](#uc10--e3dc-discharge-steuerung) | E3DC maxDischargePower = EMHASS p_batt | v0.12/0.13 |
| [UC11](#uc11--klima-og-advisor) | Klima OG Advisor (Notify statt Aktion) | v0.14.1 |
| [UC12](#uc12--proxon-kühlung) | Proxon-Kühlung, adaptive Schwellen | v0.17.0 |
| [UC14](#uc14--netzladen) | E3DC-Netzladen bei großem Spread | v0.14.0 |

## UC1 — SOC-Warnung

Push bei Auto-SOC < 20%. Bewusst reaktiv (Sicherheitsnetz).

## UC2 — Kalender-Vorladen

Nächstes relevantes Event aus `calendar.amazone` (Location vorhanden, kein
Teams/Patchday) → Google Distance Matrix (gecacht, 7 Tage TTL) →
`required_soc = (km × 2) × Verbrauch / 63 kWh + 25% Marge` →
`evcc_intg.set_vehicle_plan` (startdate = Event − 30 min, evcc plant die
günstigsten Stunden selbst). Sensor: `sensor.wattson_naechste_fahrt`.
Erbt UC6-Override: hat der User den Mode manuell gesetzt, greift UC2 nicht ein.

## UC4a — T300-Solltemperatur

Günstigste 2h-Phase der nächsten 12h: jetzt günstig → 55°C, teuer → 45°C,
sonst 52°C. **Noch nicht EMHASS-integriert** (siehe roadmap.md).

## UC4b — E-Heizstab plan-aware

Liest EMHASS-Forward-Plan (`deferrables_schedule`, deferrable0, Slots ≥ 500W).
Off nur nach 2-Cycle-Confirmation (`UC4B_CONFIRMATION_CYCLES`). Tank-Safety
bleibt. Fallback ohne EMHASS: PV-Surplus-Heuristik mit eigener Hysterese.

Reihenfolge seit v0.18.8: **Failsafe → Urlaub/Legionellen → EMHASS-Plan/Heuristik.**

**Dauerlauf-Failsafe (v0.18.8):** Heizstab länger als
`HEIZSTAB_MAX_CONTINUOUS_H` (4h) kontinuierlich an → Zwangsabschaltung
**am Override-System vorbei** (einzige _try_act-Umgehung; Dauerlauf-Schutz
schlägt Override-Respekt) + Push ohne Quiet-Hours, max 1/h. Hintergrund:
32h- und 26h-Dauerläufe Anfang Juli 2026 durch verpuffte Modbus-Writes +
Phantom-Override.

**Urlaub-Gate (v0.18.8):** Urlaubsmodus → kein EMHASS-/PV-Heizen, Stab aus.

**Legionellen-Aufheizung (v0.18.8, nur Urlaub):** T300 hat kein eigenes
Legionellen-Programm. Alle `LEGIONELLA_INTERVAL_DAYS` (7) heizt UC4b den Stab
bis `LEGIONELLA_TARGET_C` (60°C = Tank-Max), Push bei Abschluss, Zeitpunkt
persistiert in `wattson_state.json` (`misc.legionella_last_done`). Im
Normalbetrieb unnötig (Zapfung + PV-Fenster).

Startfenster seit **v0.18.10** als 3-Stufen-Eskalation über das Lauf-Alter
(Dunkelflauten-Hedge, PV = inverser Flauten-Melder):

| Alter | Startbedingung |
|---|---|
| ≥ 5 Tage (`EARLY_PV_DAYS`) | PV-Überschuss ≥ 1700W → vorziehen |
| ≥ 9 Tage (`INTERVAL`+`GRACE`) | cheapest_4h **und** price_level nicht expensive |
| ≥ 12 Tage (`HARD_DAYS`) | cheapest_4h bedingungslos (Hygiene > Preis) |

`_legionella_active` wird erst nach **erfolgreichem** Einschalten gesetzt —
vorher wird das Fenster jeden Tick neu bewertet (Bugfix 2026-07-07: gearmter
Lauf wurde vom Override-Cooldown geblockt und feuerte um 00:02 ins teuerste
Fenster). Lauf-Deckel `LEGIONELLA_MAX_RUNTIME_H` (6h) statt des 4h-Failsafe —
der Stab schafft real nur ~1.7 K/h auf T21-Mitte.

**Gerätesemantik (Feldtest 2026-07-07):** Freigabe-Register 2001 = App-Funktion
„E-Heizstab/Boost" (Aktor, regelt selbst aufs Boost-Ziel Reg 2003 = 59°C) —
deshalb `LEGIONELLA_TARGET_C` = 58.5. **Betriebsart LF1/LF2 (Reg 2002) NIE
verwenden**: Legacy-Modi, die neue Proxon-App kennt sie nicht (zeigt
„Warmwasser aus") und der Modus legt den Warmwasser-Betrieb still — Boost
heizt darin nicht, WP auch nicht (4h-Test ohne jede Reaktion).

**Safety-Reminder:** Heizstab an + `price_level ∈ {expensive, very_expensive}`
→ Push mit [Aus]/[Ignorieren], 60min-Cooldown, Quiet-Hours-Suppress.
Action-Automation: `automation.wattson_heizstab_safety_action`.

## UC6 — E-Auto-Lademodus (3-Level)

| Mode | Bedingung |
|---|---|
| `now` | SOC < 50% **und** (Trip < 12h **oder** EMHASS-Plan-Slot ≥ 500W), oder Trip-Plan mit Required-SOC nicht erreicht + Trip < 12h |
| `minpv` | Trip-Plan aktiv (Plan greifen lassen), oder im EMHASS-Plan-Slot, oder `price_level ∈ {very_cheap, cheap, normal}` + SOC < Target |
| `pv` | Default — SOC voll oder expensive ohne Plan |

Plan-aware via `deferrables_schedule` (deferrable1). Anti-Jitter:
`mode_rank = {now:3, minpv:2, pv:1, off:0}` — Upshift sofort, Downshift erst
nach 2 Cycles Confirmation. `UC6_MODE_HOLD_MINUTES = 10`.
Design-Präferenz: lieber länger `minpv` als pv↔now-Pendeln.

## UC9 — 1P/3P-Umschaltung

Shelly-Lasttrenner soll L2+L3 abklemmen für 1P-PV-Laden (5.2 kWp liefert nie
4.14 kW 3P-Floor). **Blocked:** 4mm-Kabel + Shelly Pro 3EM nicht verkabelt.

## UC10 — E3DC Discharge-Steuerung

`maxDischargePower` = EMHASS `p_batt_forecast` (clamp 0–1500W; < Threshold → 0W
Sperre) via `e3dc.set_power_limits`. Fallback-Heuristik: binäres Lock über
cheapest/expensive-4h-Fenster. Pausiert wenn UC14 aktiv (kein Doppel-POST).

## UC11 — Klima OG Advisor

**v0.18 — Smart-UC11:** Pro-Raum Humidex aus Shelly BLU H&T-Sensoren (Office EE37, Schlaf 757E).

| Raum | Modus | Begründung |
|------|-------|------------|
| Office | Auto (`set_hvac_mode`) | eigener HT-Sensor, tagsüber kein Schlafrisiko |
| Schlafzimmer | Advisor (Notify) | Sonja leichter Schläfer → keine autonome Nacht-Aktion |

Trigger: `humidex_innen ≥ 30` (some discomfort) ∧ Δinnen−außen ≥ +3°C
— **oder** `humidex ≥ 35` (great discomfort, egal Außen). Max 1 Notify/h, nicht 22–7 Uhr.

UC12 B Schwüle: `humidity_proxy_pct` = max(HT-Office, HT-Schlaf) statt TP357 Wohnzimmer.

- v0.15.1: Fenster-auf-Empfehlung statt Klima bei Δ-Humidex ≥ 3
- v0.15.2: Notify unterdrückt wenn Proxon-Kühlung (UC12) bereits läuft
- v0.18.0: echte pro-Raum RH + Office Auto-Mode
- v0.18.1: Window-Guard `binary_sensor.office_doof_window_office_links_window` → kein Auto-Klima-Start; läuft Klima schon → abschalten

`switch.wattson_klimaanlagen_og` = UC11 Enable-Toggle.

## UC12 — Proxon-Kühlung

Adaptive Schwellen, drei Korrektur-Ebenen (A: v0.17.0, B+C: v0.17.2):

```
A  delta   = 0.15 × (outside_max − 20)        # weather.forecast_home Tages-Max
   trigger = clamp(24.0 + delta, 23.5, 25.0)
   heat    = clamp(25.5 + delta, 25.5, 27.0)
B  RH-Proxy ≥ 60% (TP357 Wohnzimmer)  → trigger −0.5   # schwül fühlt sich wärmer an
C  Abluft-Trend ≥ +0.3°C/h            → heat −0.5      # Hitze kommt, früher forcen
   heat    = max(heat, trigger + 0.5)                   # Heat nie unter Trigger
   off     = trigger − 1.0 (Hysterese)
```

Trend-Quelle: in-memory Sample-Buffer der Abluft (60-min-Fenster, gültig ab
20 min Spanne). Nach HA-Restart wird der Buffer einmalig aus der
Recorder-Historie geseedet (v0.17.3, downgesampelt aufs 5-min-Tick-Raster) —
der Trend ist damit sofort wieder da; ohne Recorder füllt er sich live.
Aktive Korrekturen erscheinen im `begruendung`-Attribut von
`sensor.wattson_kuhlung`.

Entscheidung in fünf Stufen (v0.18.7):
1. Urlaubsmodus → **aus, immer** (auch bei Hitze — niemand zu Hause)
2. Sleep-Mode → aus, **auch bei Hitze** (Kühlung treibt Lüfterstufe auf max;
   seit v0.18.7 bricht Force-Hitze den Schlaf nicht mehr, kühlt nach Sleep-Ende)
3. Abluft ≥ heat → kühlen, auch bei expensive + Push
   (`_uc12_send_heat_notify`, 60min-Cooldown)
4. Abluft ≤ off → aus
5. dazwischen: PV ≥ 1500W → an; cheapest_4h + Spread < 15ct → an; Hysterese
   hält an, **bricht aber bei expensive ohne PV**; sonst aus

Zusätzlich Kühl-Reminder bei manuellem Override in teurem Fenster (v0.15.0).

## UC14 — Netzladen

Alle Bedingungen nötig: EMHASS `p_batt < 0` ∧ Spread ≥ 11 ct/kWh zum teuersten
Slot 24h ∧ Fensterlänge ≥ dynamisch nach freiem Akku-Platz ∧ SOC < 90%.
Aktion: `set_power_limits(charge=1500, discharge=0)`. Ende: charge zurück auf
Default, discharge bleibt 0 — UC10 übernimmt im selben Cycle. POST-Verify im
Folge-Cycle (E3DC-Self-Reset-Problematik).
Why 11 ct: ~15% Round-Trip-Verlust + Marge, EEG-Vergütung als Opportunity-Cost.
