# Use Cases

Stand: v0.20.0 (2026-07-27). Alle live außer UC9 (Hardware-blocked).

| UC | Was | Seit |
|---|---|---|
| [UC1](#uc1--soc-warnung) | SOC-Warnung <20% | früh |
| [UC2](#uc2--kalender-vorladen) | Kalender-Trip → required SOC → evcc-Plan + Anstecken-Erinnerung | v0.11 |
| [UC4a](#uc4a--t300-solltemperatur) | T300-Soll nach Tibber-Fenster | früh |
| [UC4b](#uc4b--e-heizstab-plan-aware) | Heizstab plan-aware (EMHASS deferrable0) | v0.16.0 |
| [UC6](#uc6--e-auto-lademodus-3-level) | E-Auto 3-Level pv/minpv/now, gerechnete Preisschwelle | v0.17.1 |
| [UC9](#uc9--1p3p-umschaltung) | 1P/3P-Umschaltung | ⛔ blocked |
| [UC10](#uc10--e3dc-discharge-steuerung) | E3DC maxDischargePower = EMHASS p_batt | v0.12/0.13 |
| [UC11](#uc11--klima-og-advisor) | Klima OG Advisor (Notify statt Aktion) | v0.14.1 |
| [UC12](#uc12--proxon-kühlung) | Proxon-Kühlung, adaptive Schwellen | v0.17.0 |
| [UC14](#uc14--netzladen) | E3DC-Netzladen bei großem Spread | v0.14.0 |

## UC1 — SOC-Warnung

Push bei Auto-SOC < 20%. Bewusst reaktiv (Sicherheitsnetz).

## UC2 — Kalender-Vorladen

Alle künftigen Events der konfigurierten Kalender (`auto_calendars`, Location
vorhanden, kein Teams/Patchday) → Google Distance Matrix (gecacht, 7 Tage TTL)
→ `required_soc = (km × 2) × Verbrauch / Kapazität + safety_margin_percent`,
aufgerundet auf 5er-Stufen. Die Marge sind **Prozentpunkte, additiv** (Default
26) — sie deckt die Verbrauchsunsicherheit ab, deshalb bleibt `Verbrauch` ein
Jahresmittelwert (20 kWh/100km; gemessen 16,7 Stadt / 22,7 Autobahn beladen).

**Abfahrt statt Termin (v0.18.13):** Ziel des Plans ist
`Termin − Fahrzeit − Puffer`, nicht der Termin selbst. Vorher zielte der Plan
auf den Terminbeginn und das Auto war regelmäßig nach der Abfahrt fertig.

**Plan-Schreibweg (v0.18.13):** direkt per evcc-REST
(`POST /api/vehicles/{name}/plan/soc/{soc}/{rfc3339}`), nicht über
`evcc_intg.set_vehicle_plan` — der Service meldet Erfolg, setzt aber nichts.
Erfolg gilt erst bei bestätigter Quittung im Response-Body. evcc sucht die
günstigen Stunden bis zur Deadline selbst.

Bei mehreren offenen Fahrten liefert die früheste die Deadline, die
teuerste den Ziel-SOC. Plan-Lifecycle persistiert (`misc.uc2_plan`), damit ein
Neustart keine Phantom-Pläne hinterlässt. UC2 läuft **auch im Schlafmodus**
(`SLEEP_EXEMPT_UCS`) — ein Plan für den Morgen entsteht sonst nie.

Sensor: `sensor.wattson_naechste_fahrt`. Erbt UC6-Override: hat der User den
Mode manuell gesetzt, greift UC2 nicht ein.

**Grundplan (v0.20):** Steht kein Termin an — oder deckt der SOC den Bedarf
schon — setzt UC2 trotzdem einen Fahrplan: `BASELINE_SOC` (50 %) bis
`BASELINE_READY_HOUR` (07:00). Ohne den gab es an terminlosen Tagen gar keinen
Plan, dann hing alles an der Preisschwelle und nichts garantierte einen
Ladezustand. Mit Plan hat evcc immer etwas zu optimieren und wählt Leistung wie
Slots selbst. Ein Termin-Fahrplan hat Vorrang und überschreibt ihn; liegt der
SOC schon über 50 %, passiert nichts.

**Anstecken-Erinnerung (v0.19):** eine Sorte Meldung statt gestaffelter
Preis-Eskalation. Auslöser: Heimkommen mit SOC unter `PLUGIN_COMFORT_SOC` (40)
innerhalb `PLUGIN_ARRIVAL_WINDOW_MIN` (20 min) — da steht man neben dem Auto —
oder eine Fahrt, die zeitlich zu kippen droht (dann dringend). Kein Preis und
kein Betrag im Text; die Bitte lautet „steck an". Angesteckt schweigt sie
immer, ein Quittungsknopf ist damit unnötig. Cooldown
`PLUGIN_REMINDER_COOLDOWN_MIN` (180 min).

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

**Legionellen-Aufheizung (v0.18.8, 65°C seit v0.18.11 — nur Urlaub):** Die
neue Proxon-App hat die Geräte-Legionellenfunktion entfernt (dafür Boost-Ziel
bis 70°C). UC4b übernimmt: alle `LEGIONELLA_INTERVAL_DAYS` (7) wird das
Boost-Ziel (Reg 2003, `number.proxon_t300_temperatur_e_heiz`) temporär auf
`LEGIONELLA_BOOST_TEMP_C` (65) gehoben, Boost (Reg 2001) eingeschaltet und bis
`LEGIONELLA_TARGET_C` (64.5, T21-Mitte) geheizt — echte Desinfektion statt
58°C-Sparversion (T20 unten bleibt sonst lauwarm). Danach Boost aus +
Boost-Ziel restauriert (`misc.legionella_prev_boost_temp`, dient zugleich als
Restart-Resume-Marker), Push bei Abschluss, Zeitpunkt persistiert
(`misc.legionella_last_done`). Im Normalbetrieb unnötig (Zapfung + PV-Fenster).

Startfenster seit **v0.18.10** als 3-Stufen-Eskalation über das Lauf-Alter
(Dunkelflauten-Hedge, PV = inverser Flauten-Melder):

| Alter | Startbedingung |
|---|---|
| ≥ 5 Tage (`EARLY_PV_DAYS`) | PV-Überschuss ≥ 1700W **vor 13 Uhr** → vorziehen |
| ≥ 9 Tage (`INTERVAL`+`GRACE`) | cheapest_4h **und** price_level nicht expensive |
| ≥ 12 Tage (`HARD_DAYS`) | cheapest_4h bedingungslos (Hygiene > Preis) |

`_legionella_active` wird erst nach **erfolgreichem** Einschalten gesetzt —
vorher wird das Fenster jeden Tick neu bewertet (Bugfix 2026-07-07: gearmter
Lauf wurde vom Override-Cooldown geblockt und feuerte um 00:02 ins teuerste
Fenster). Lauf-Deckel `LEGIONELLA_MAX_RUNTIME_H` (12h) statt des 4h-Failsafe —
der Stab schafft real ~1.7 K/h auf T21-Mitte, 52→65 ≈ 6–8h (WP hilft bis ~57).

**Gerätesemantik (Feldtests 2026-07-07):** Freigabe-Register 2001 = App-Funktion
„E-Heizstab/Boost": Aktor mit **Einschalt-Hysterese ~3–5 K unterm Boost-Ziel**
(Ziel 59 / Tank 56.9 → keine Reaktion; Ziel 65 → Stab an) — beim echten Lauf
startet der Tank bei ~52, Hysterese also irrelevant. **Betriebsart LF1/LF2
(Reg 2002) NIE verwenden**: Legacy-Modi, die neue Proxon-App kennt sie nicht
(zeigt „Warmwasser aus") und der Modus legt den Warmwasser-Betrieb still —
Boost heizt darin nicht, WP auch nicht (4h-Test ohne jede Reaktion).

**Safety-Reminder:** Heizstab an + `price_level ∈ {expensive, very_expensive}`
→ Push mit [Aus]/[Ignorieren], 60min-Cooldown, Quiet-Hours-Suppress.
Action-Automation: `automation.wattson_heizstab_safety_action`.

## UC6 — E-Auto-Lademodus (3-Level)

Seit **v0.20** hängt die Freigabe an einer **gerechneten Schwelle**, nicht mehr
an Tibber-Leveln (`forecast.decide_charge_mode`). Vier Regime:

| Mode | Bedingung |
|---|---|
| `now` | Fahrplan aktiv **und** zeitlich gefährdet — überstimmt alles |
| `now` | Preis ≤ `EEG_VERGUETUNG_CT` (11,1 ct) — Volllast aus dem Netz |
| `minpv` | Preis ≤ Bedarfsschwelle — Netzminimum plus alle Sonne |
| `pv` | alles andere |

### Warum keine feste Grenze und keine Level

Eine feste Cent-Grenze altert. 20 ct sind Ende Juli günstig; im Januar liegt
das Tagesminimum bei 18,0 ct und der Monatsmittelwert bei 30,9 — dieselbe
Grenze würde dort fast nie greifen, da bräuchte es 30 oder im Winter 60.

Tibber-Level lösen es nicht: sie hängen am gleitenden Mittel, nicht am eigenen
Bedarf. `normal` reicht bis ~115 % des Mittels, also Ende Juli 2026 bis ~35 ct.

`charge_threshold_ct` rechnet stattdessen: nimm die günstigsten Slots im
Fenster bis zur Abfahrt, bis der Bedarf gedeckt ist, und nimm den Preis des
teuersten davon. Die Schwelle wandert damit von selbst mit Saison, Kurve und
Ladezustand — viel nachzuladen weitet sie, wenig verengt sie. Kein Parameter,
den man nachprüfen müsste.

> [!warning] Eine **verstrichene** Abfahrt darf das Fenster nicht begrenzen.
> `s.trip_departure` bleibt nach dem Termin stehen; als Fensterende genommen
> findet sich kein Slot mehr, die Schwelle ist `None` und UC6 fällt stumm auf
> `pv`. Gefunden am 27.07.2026 beim Lauf gegen Livedaten (19:57, Abfahrt war
> 17:18). Liegt die Abfahrt in der Vergangenheit, gilt der 24-h-Horizont.

### Warum nicht evccs `smartCostLimit`

Naheliegend, aber es kann nur eines der Regime. Laut evcc-Doku schaltet das
Limit auf *fast-charging* „regardless of solar production". Für Preise unter
der Einspeisevergütung ist das genau richtig — Netzstrom ist dann billiger als
die eigene Sonne. Im Winter, wo „relativ günstig" absolut immer noch teuer
ist, ist es falsch; dort will man `minpv`. Ein Knopf kann beide nicht, deshalb
entscheidet Wattson und evcc führt aus.

Das EEG-Regime greift selten: 2026 nur April und Mai, mit Negativpreisen bis
−41 ct. Jan–Jul-Minima lagen sonst bei 11,7–18,0 ct. Es kostet nichts, wenn es
nicht greift.

### Sonnenschwelle

`UC6_SUN_SURPLUS_MIN_W` = 1700 W (= `PV_SURPLUS_ON`). Stand in v0.19.0 auf
4200 W, dem 3-phasigen Wallbox-Minimum — ein Denkfehler: diese Schwelle gehört
zum `pv`-Modus, wo nur Überschuss fließen soll. In `minpv` ist der Netzanteil
Absicht. Bei 5,2 kWp wurde 4200 W in 30 Tagen genau einmal erreicht (Spitze
4233 W, drei Stunden über 4000), der Zweig war toter Code.

### Sonstiges

Ein aktiver Fahrplan läuft in `pv`, nicht `minpv`: evcc kennt den Tarif und
sucht die Slots selbst, `minpv` würde den Plan preisunabhängig unterlaufen.

Vorbedingungen: abgesteckt → `pv`; SOC ≥ Limit → `pv`, außer bei gefährdetem
Fahrplan. Anti-Jitter: `mode_rank = {now:3, minpv:2, pv:1, off:0}` — Upshift
sofort, Downshift erst nach 2 Cycles Confirmation. `UC6_MODE_HOLD_MINUTES = 10`.

Seit **v0.19.1** läuft UC6 auch im **Schlafmodus** (`SLEEP_EXEMPT_UCS`). Er
schreibt nur einen select-Wert — kein Push, keine Hausaktorik — und die
günstigen Stunden liegen gerade nachts. Vorher war die Preisregel bis zum
manuellen „Guten Morgen" wirkungslos; der Schlafmodus endet nur dadurch.

**Hausbatterie:** `batteryDischargeControl` steht in evcc auf `true` (Runtime,
`POST /api/batterydischargecontrol/true` — **nicht** in `evcc.yaml`, dort
lässt der Site-Schema-Check evcc mit `FATAL: 'core.Site' has invalid keys`
nicht mehr starten). Ohne das entlud der Hausspeicher ins Auto; am 25.07.2026
nachgewiesen mit 68 % → 13 % in 80 min bei 1,44 kW.

✅ Die Wallbox ist seit 2026-07-26 **kein EMHASS-Deferrable** mehr — UC6 folgt
dem Plan nicht mehr, also darf EMHASS auch nicht mit ihm rechnen.

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
