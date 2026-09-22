# Use Cases

Stand: v0.20.3 (2026-07-29). Alle live außer UC9 (Hardware-blocked).

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
→ `required_soc = (km × 2) × Verbrauch / Kapazität × (1 + safety_margin_percent)
+ TRIP_ARRIVAL_RESERVE_SOC`, aufgerundet auf 5er-Stufen. Sie deckt die
Verbrauchsunsicherheit ab, deshalb bleibt `Verbrauch` ein Jahresmittelwert
(20 kWh/100km; gemessen 16,7 Stadt / 22,7 Autobahn beladen).

**Relative Marge (v0.20.5):** Bis v0.20.4 waren es **additive Prozentpunkte**,
und das skalierte falsch herum — 4 km verlangten 35 % SOC (2,6 % Fahrstrom +
30 Punkte), während 100 km mit denselben 30 Punkten auskommen mussten. Umweg,
Stau und Kälte wachsen aber mit der Strecke. Jetzt multiplikativ; fix bleibt nur
`TRIP_ARRIVAL_RESERVE_SOC` (5 %) als Restladung nach der Rückkehr. Wirkung bei
Marge 30: Tennis 6,6 km 35 → 15 %, Spieleabend 12,8 km 40 → 20 %, Kuralpe
100,6 km 95 → 90 %.

**Heimadresse:** `home_address` muss die **Hausadresse** sein, nicht der Ort.
Stand bis 15.08.2026 auf „Limburg an der Lahn, Germany" (Stadt-Zentroid) —
damit maß gmaps jede Strecke ab Innenstadt, und ein Termin **im eigenen Haus**
(„Sonjas Eltern kommen", Location = eigene Adresse) kam als 4,1-km-Fahrt an.
Mit korrekter Adresse ergibt so ein Termin 0 km und damit nur die Restreserve —
ein Keyword-Filter für Besuchstermine erübrigt sich.

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

**Grundplan (v0.20):** Steht kein Termin an, setzt UC2 trotzdem einen Fahrplan:
`BASELINE_SOC` (50 %) bis `BASELINE_READY_HOUR` (07:00). Ohne den gab es an
terminlosen Tagen gar keinen Plan, dann hing alles an der Preisschwelle und
nichts garantierte einen Ladezustand. Mit Plan hat evcc immer etwas zu
optimieren und wählt Leistung wie Slots selbst. Ein Termin-Fahrplan hat Vorrang
und überschreibt ihn; liegt der SOC schon über 50 %, passiert nichts.

**Deckungs-Gate (v0.20.5):** Sind alle anstehenden Fahrten vom aktuellen SOC
gedeckt, entfällt der Grundplan — und ein noch stehender wird aus evcc gelöscht
(`_clear_baseline_plan`, nur Pläne mit `BASELINE_PLAN_UID`). Der Boden kennt
den Strompreis nicht: am 15.08.2026 um 06:02 zog er 11 kW zu 37,5 ct, um von 48
auf 51 % zu kommen, während die einzige Fahrt des Tages (13 km) 40 % brauchte
und mittags 18 ct anstanden. Als harte Reserve bleibt `BASELINE_FLOOR_SOC`
(30 %): darunter greift der Grundplan immer, denn der Kalender kennt nur die
geplanten Fahrten. Entscheidung liegt in `forecast.baseline_plan_needed`,
Tests in `tests/test_baseline_plan.py`.

Der Grundplan trägt die uid `BASELINE_PLAN_UID` und ist von der Stale-Erkennung
**ausgenommen** (`forecast.plan_is_stale`). Er stammt aus keinem Kalendertermin,
also findet die uid-Suche nie etwas — ohne die Ausnahme las die Aufräumroutine
das als „Termin abgesagt" und löschte den Plan im Tick nach dem Setzen. Am
27.07.2026 ab 21:36 lief genau das im Wechsel weiter, die Zusage stand nie
wirklich in evcc (Fix v0.20.2).

**Fremde Pläne sind tabu (v0.20.10):** UC2 schreibt nur noch, wenn der Plan in
evcc entweder fehlt oder der eigene ist — verglichen werden Ziel-SOC und
Zielzeit gegen `misc.uc2_plan` (`forecast.foreign_plan_note`). Gelesen wird
dafür der **hinterlegte** Plan (`sensor.evcc_auto_vehicle_plans_soc/_time`),
nicht der effektive: der steht auf 0, sobald evcc gerade nicht nach Plan lädt,
während der hinterlegte weiterbesteht.

Dazu endet ein Plan-Override nicht mehr stur um Mitternacht:
`cooldown_until_next_midnight(now, hold_until)` hält mindestens bis zur
Zielzeit des überschriebenen Plans.

> [!warning] Der Anlass: 19./20.09.2026
> 18:54:27 trägt Christian „100 % bis 20.09 10:45" in evcc ein. Wattson erkennt
> den Eingriff korrekt, `sensor.wattson_eauto_fahrplan` zählt den Cooldown
> herunter — 23:56:07 steht dort „user-override (3min Rest)". Um **00:01:08**
> ist die Frist um, und der Grundplan schreibt „50 % bis 12:00" darüber.
> Geladen wurde die Nacht dann ohne Plan: evccs `smartCostLimit` (20 ct) zog ab
> 00:15 volle 10,6 kW für 3 h 20 (≈ 35,5 kWh) zu 18,9–19,9 ct, bis zum 90 %-
> Limit der Anstecken-Automation. Das Mittagsfenster desselben Tages lag bei
> 17,8 ct.
>
> **Ein Cooldown ist eine Frist, ein fremder Plan ein Zustand.** Fristen laufen
> ab, während der Zustand bleibt — deshalb reicht die Override-Erkennung hier
> nicht, und deshalb steht die Besitzprüfung vor ihr. Dieselbe Familie wie der
> UC12-Fall vom 02.07.2026 (Kühlung ging 46 s nach Cooldown-Ende wieder an).

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

**Speicherfenster (v0.20.11):** Will der EMHASS-Plan gerade heizen
(`heizstab_plan_signal == "on"`), hebt UC4a den Sollwert auf
`T300_TEMP_SPEICHER` (55 °C) — noch vor der Preis-Logik, nur wenn der Strom
nicht gerade `expensive` ist und der Tank darunter liegt
(`forecast.t300_speicherfenster`).

Ohne das war der Plan zahnlos: der T300 heizt nur unter seinem Sollwert, und
die Heizstab-Freigabe von UC4b ist eine *Erlaubnis*, kein Auftrag. Am
19.09.2026 stand der Sollwert auf 52 °C bei 54,8 °C Tank — acht Freigaben,
`binary_sensor.proxon_t300_e_heiz_aktiv` durchgehend aus, 0,166 kWh in 2 h 08
(das war die Wärmepumpe, 19 min Kompressor). 1500 W hätten ~2 kWh gezogen.

Das Ziel liegt auf **55 °C** — das ist die Obergrenze des Registers. MODBUS-Liste
(Paperless Dok 2300): `4x2000 Normal Wassertemperatur, IST-Min 20, IST-Max 55`.
v0.20.11 hatte hier 57 stehen; das Gerät hätte den Wert abgewiesen (korrigiert
in v0.20.12). Mehr Vorrat ginge nur über `4x2003 Temperatur E-Heiz` (bis 70 °C)
plus Freigabe — dann heizt aber der **Stab** (COP 1) statt der Wärmepumpe
(COP ≈ 3). Für Preisverschiebung lohnt das nicht; für echten PV-Überschuss wäre
die geräteeigene PV-Funktion (`4x2010`, Lesewerte `3x0899 PV Eheiz AN`,
`3x0900 PV WP AN`) der vorgesehene Weg — noch nicht ausgewertet.

`T300_TARGET_MAX_C` (55 °C) deckelt jeden geschriebenen Sollwert auf die
Registergrenze. Im Haus sitzt kein thermostatischer Mischer — Tanktemperatur =
Armaturentemperatur; der Legionellen-Lauf (64,5 °C über `4x2003`) liegt bewusst
darüber und warnt seit v0.20.11 im Abschluss-Push davor.

> [!warning] UC4a schrieb bis v0.20.10 ins Leere
> `ENTITY_T300_SOLL` zeigte auf `number.proxon_t300_solltemperatur` — diese
> Entity existiert nicht, sie heißt `number.hwr_proxon_t300_target_temperature`.
> Dazu lief der Write über `input_number.set_value` statt `number.set_value`.
> Beides zusammen: `_fval` lieferte still den Default 52,0, `_try_act` meldete
> Erfolg, und der T300-Sollwert stand 14 Tage konstant auf 52,0, während
> `sensor.wattson_warmwasser_soll` „aktiv — günstigste 2h" zeigte. Dasselbe
> galt für `ENTITY_T300_BOOST_TEMP`, also für den Legionellen-Boost-Swap.
>
> Seit v0.20.11 prüft `_warn_missing_entities()` alle Schreib-Ziele
> (`CRITICAL_WRITE_ENTITIES`) und protokolliert fehlende. Merksatz der Familie:
> *ein laufender UC ist kein Beleg für einen wirksamen UC.*
>
> Die Prüfung läuft seit v0.20.13 im **ersten Tick nach dem Hochlauf**, nicht in
> `async_setup`. Dort stand sie in v0.20.12 — und meldete beim ersten echten
> Start am 22.09.2026 alle sieben Ziele als fehlend, obwohl jedes existierte:
> proxon, evcc und die Klima-Integration legen ihre Entities später an. Ein
> Wächter, der immer anschlägt, sagt nichts.

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

**v0.20.11 — zwei Befunde vom 19.09.2026.** Der Stab wurde acht Mal zwischen
13:32 und 17:22 freigegeben und gesperrt, Periode 30 min (aus bei :22/:52, an
bei :02/:32), während `sensor.p_deferrable0` durchgehend 1500 W meldete.

- **„Kein Slot" galt als „Plan sagt aus".** EMHASS veröffentlicht den
  Forward-Plan ab der *nächsten* Halbstunden-Grenze; der laufende Slot fehlt.
  Live gemessen am 20.09. um 14:58:28: erster Eintrag 15:00:00.
  `deferrable_slot_at()` lieferte None, der Off-Zähler lief, nach zwei Ticks
  ging der Stab aus. Jetzt entscheidet `forecast.heizstab_plan_signal`
  dreiwertig: Slot → publizierter Ist-Wert → `"unbekannt"`, und bei
  `"unbekannt"` wird der Zustand **gehalten**. Der Forward-Plan ist eine
  Vorhersage, `sensor.p_deferrable0` die Gegenwart.
- **Bedarfs-Gate** (`forecast.heizstab_kann_wirken`): freigegeben wird nur, wenn
  der Tank mindestens `UC4B_ELEMENT_HYSTERESE_C` (5 K) unter dem **E-Heiz-Ziel**
  liegt (Reg 4x2003, `ENTITY_T300_BOOST_TEMP`). Laut Bedienungsanleitung
  (Paperless Dok 2363, S. 17/35) ist D01 die Temperatur, *bis zu der* der Stab
  „parallel zur Wärmepumpe" mitheizt — eine Hysterese nennt das Handbuch nicht,
  die 5 K sind aus drei Messungen abgeleitet. Nicht der Warmwasser-Sollwert — drei Messungen bei Ziel 59 °C: 56,9 → aus, 54,8 → aus,
  53,8 → an (binnen 3 s, +2,5 K in 20 min). An beiden September-Tagen lag der
  Tank *über* dem Sollwert; der Unterschied war allein der Abstand zum
  E-Heiz-Ziel. Die erste Fassung verglich gegen den Sollwert und hätte den
  wirksamen Lauf vom 20.09. unterdrückt. Gilt auch im Heuristik-Zweig.

Dazu `UC4B_MIN_DWELL_MIN` (15 min) für die abwägenden Zweige — gemessen am
eigenen letzten Write, nicht an `last_changed` (das setzt jeder Modbus-Aussetzer
zurück). Failsafe, Tank-Limit, Urlaub und Legionellen gehen weiter sofort durch.

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

### Totband um die Bedarfsschwelle (v0.20.2)

Läuft `minpv` bereits, darf der Preis bis `Schwelle + CHARGE_THRESHOLD_HYSTERESE_CT`
(0,5 ct) steigen, bevor auf `pv` zurückgefallen wird. Der Einstieg bleibt bei der
gerechneten Schwelle — das Band gilt nur nach oben, sonst würde es die Freigabe
verschleppen. Laufender Modus ist das Gedächtnis, wie bei `heat_active`.

Anders als bei UC12 pendelt hier nicht der Messwert um die Schwelle, sondern die
**Schwelle um den Messwert**: sie wird jeden Tick neu gerechnet, der 24-h-Fensterrand
wandert und `needed_slots` springt in ganzen Schritten durch das sortierte
Preisarray. Am 28.07.2026 gemessen: Preis konstant 17,9 ct, Schwelle 18,0 ct →
`minpv` 12:49, `pv` 13:14, `minpv` 13:24. `UC6_MODE_HOLD_MINUTES` (10) und die
Downshift-Confirmation (2 Cycles) erklären die Abstände — sie begrenzen die Rate,
verhindern das Kippen aber nicht.

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

### evccs neues Mode-Schema (`smart` + `alwaysCharge`)

evcc [PR#32490](https://github.com/evcc-io/evcc/pull/32490) ersetzt
`off|pv|minpv|now` durch `off|smart|now` plus einen zweiten Selector
`alwaysCharge` (`off|on|once`). `smart` ist das alte `pv`; `alwaysCharge=on`
schiebt das Netzminimum darunter, ist also `minpv`. `once` gilt bis zum
Abstecken.

Wattson rechnet intern **weiter in `pv|minpv|now|off`** — daran hängen
Rangordnung, Totband und Hysterese samt ihrer Herleitungen. Übersetzt wird nur
an der Grenze (`evcc_modes.py`):

| Wattson | altes evcc | neues evcc |
|---|---|---|
| `off` | `off` | `mode=off` |
| `pv` | `pv` | `mode=smart`, `alwaysCharge=off` |
| `minpv` | `minpv` | `mode=smart`, `alwaysCharge=on` |
| `now` | `now` | `mode=now` |

Welches Schema läuft, verrät der Selector selbst: hat er `minpv` in den
Optionen, ist es das alte. Kein Versionsvergleich, keine Konfiguration —
ha-evcc (ab 2026.8.3) baut den Selector passend zum laufenden evcc auf. Der
`alwaysCharge`-Selector wird an seinem Optionssatz erkannt, weil seine
Entity-ID aus dem übersetzten Namen entsteht.

`alwaysCharge` wird **zuerst** geschrieben: bei `now` → `pv` stünde der
Schalter sonst für einen Tick noch auf `on` und der Wechsel liefe durch genau
den Zustand, den er verlässt. Bei `off` und `now` bleibt er unangetastet, dort
ist er wirkungslos. Beide Writes gehen durch **einen** `_try_act`-Aufruf
(`extra_writes`), damit ein Override auf einem der Selectors auch den anderen
stoppt — sonst schriebe Wattson einen halben Modus.

Warum vorgebaut, obwohl der PR noch Draft ist: CT102 zieht evcc-Updates
viermal täglich (`evcc-guarded-update.timer`, 08/12/16/20 Uhr, Guard nur gegen
angestecktes Auto). Ein Stable-Release mit dem neuen Schema liegt binnen
Stunden auf der Anlage — ab dann würde UC6 auf einen Selector schreiben, der
`minpv` nicht mehr kennt.

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

### Totband am Hitze-Zweig (v0.20.1)

Der Off-Zweig hatte seit jeher eine Hysterese (`off_c = trigger_c −
COOL_ABLUFT_HYSTERESE_C`), der Hitze-Zweig nicht — dort stand ein blankes
`abluft >= heat_c`.

Am 27.07.2026 pendelte die Abluft ab 18:50 zwischen 25,0 und 25,4 °C, also um
die (adaptive) Hitze-Schwelle. Ergebnis: ein Tick sah den oberen Wert und
schaltete die Kühlung ein, der nächste sah den unteren, und die Grundregel
(„kein PV-Überschuss, nicht in cheapest_4h, expensive") schaltete wieder aus.
Sägezahn: rund 5 Minuten an, 25 Minuten aus, dazu ein Push pro Zyklus.
Selbstverstärkend, weil die kurze Kühlung die Temperatur drückt.

`forecast.heat_active` hat jetzt dasselbe Totband: einschalten ab `heat_c`,
ausschalten erst unter `heat_c − COOL_ABLUFT_HYSTERESE_C`. Der laufende
Zustand ist das Gedächtnis, es braucht keine eigene Zustandsvariable. Die
Heat-Notify feuert zudem nur noch beim Einschalten, nicht mehr stündlich
während des Laufs.

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
   hyst_eff = min(1.0, max(0, heat − (trigger + 0.5)))  # v0.20.9: Totband-Kappe
   heat_eff = heat − hyst_eff, solange die Hitze der Grund ist
```

Die Kappe sitzt am **Band**, nicht an `heat`: eine Kappe an der Schwelle
(`max(heat, trigger + 0.5 + 1.0)`) hätte Korrektur C bei Trigger 24,0
vollständig aufgehoben — `max(25.0, 25.5)` ist wieder 25,5.

Trend-Quelle: in-memory Sample-Buffer der Abluft (60-min-Fenster, gültig ab
20 min Spanne). Nach HA-Restart wird der Buffer einmalig aus der
Recorder-Historie geseedet (v0.17.3, downgesampelt aufs 5-min-Tick-Raster) —
der Trend ist damit sofort wieder da; ohne Recorder füllt er sich live.
Aktive Korrekturen erscheinen im `begruendung`-Attribut von
`sensor.wattson_kuhlung`.

Entscheidung in fünf Stufen (v0.18.7), seit v0.20.9 als reine Funktion
`forecast.cool_decision` — testbar über einen ganzen Tagesverlauf, nicht nur
über die einzelne Schwelle:
1. Urlaubsmodus → **aus, immer** (auch bei Hitze — niemand zu Hause)
2. Sleep-Mode → aus, **auch bei Hitze** (Kühlung treibt Lüfterstufe auf max;
   seit v0.18.7 bricht Force-Hitze den Schlaf nicht mehr, kühlt nach Sleep-Ende)
3. Abluft ≥ heat → kühlen, auch bei expensive + Push
   (`_uc12_send_heat_notify`, 60min-Cooldown)
4. Abluft ≤ off → aus
5. dazwischen: PV ≥ 1500W → an; cheapest_4h + Spread < 15ct → an; Hysterese
   hält an, **bricht aber bei expensive ohne PV**; sonst aus

Zusätzlich Kühl-Reminder bei manuellem Override in teurem Fenster (v0.15.0).

### v0.20.9 — drei Befunde vom 19.09.2026

Die Freigabe stand an dem Tag 19,5 h (18.09. 13:42 → 19.09. 09:16) und danach
noch 7 h (14:02 → 20:56, von Hand beendet), dazwischen zehn Schaltvorgänge im
5-min-Takt. Drei unabhängige Ursachen:

**1. Hitze-Totband hing am Schalter statt am Grund.** `heat_active` bekam
`currently_cooling=s.cool_enable_on`. Damit erbte jede aus PV- oder
Preisgründen laufende Kühlung ab `heat_c − 1 K` das Totband — und mit ihm das
Recht, die Expensive-Sperre zu brechen. Um 19:17 meldete Wattson
„Hitze 24.8°C ≥ 25.5°C"; verglichen wurde gegen 24,5. Echte Hitze gab es nie,
Tagesmax war 25,1 °C. Der Parameter heißt jetzt `heat_forced` und bekommt
`WattsonData.cool_heat_forced`: gesetzt nur vom Hitze-Zweig, gelöscht von jedem
anderen. Nach HA-Neustart ist er False — die sichere Richtung, das Band rastet
dann erst an der nackten Schwelle wieder ein. Die Begründung nennt seither die
*verglichene* Schwelle plus Hinweis „Totband, Schwelle 25.5°C".

**2. PV-Zweig ohne Totband.** `pv_surplus >= 1500` wurde alle 5 Minuten neu
entschieden, während der Überschuss an einem Wolkentag genau darum pendelte
(5-min-Mittel 1775/1477/1428/1327/2025 … 1557/1607/1511). Jetzt
`COOL_PV_HYSTERESE_W` (250 W) als Band plus `COOL_MIN_DWELL_MIN` (20 min)
Mindest-Verweildauer. Die Kappe gilt nur für die weichen Zweige (PV, Preis,
Hysterese); Urlaub, Schlaf, Unter-Off und Hitze gehen sofort durch — sie
bedeuten Komfort oder Verschwendung, nicht Optimierung.

Das PV-Band hängt an `cool_pv_forced`, nicht am Schalter — dieselbe Trennung
wie bei der Hitze. Sonst erbt eine aus `cheapest_4h` oder der Hysterese offene
Freigabe den gesenkten Einstieg (1250 W), und ein Überschuss, der die 1500 W
nie erreicht hat, hält die Kühlung durch ein teures Fenster.

Drei Details, die beim Review aufgefallen sind:

- **Merker nur bei offener Freigabe.** `_try_act` ruft den Service mit
  `blocking=False`; „abgeschickt" ist kein „angekommen", und ein Hand-Aus fällt
  erst einen Tick später auf. Der Coordinator schreibt den Merker deshalb nach
  dem Write (`_uc12_set_latches`) und verrechnet ihn beim Lesen zusätzlich mit
  dem tatsächlichen Switch-Zustand (`… and s.cool_enable_on`). Sonst spannte ein
  verlorener Write das Band auf und UC12 meldete „Hitze 24.8°C ≥ 24.5°C" bei
  geschlossener Freigabe.
- **Verweildauer zählt den eigenen Write**, nicht `last_changed` des Switch
  (`_uc12_dwell_minutes`). HA setzt `last_changed` bei jedem `unavailable`-Blip
  und beim Restore zurück; beim flappenden Proxon-Modbus (Stale-Frame-Debt)
  hätte die Sperre irgendwann alles aufgehalten. Sie soll das eigene Takten
  bremsen, nicht auf Fremdzustände reagieren.
- **Die Expensive-Sperre fällt nicht unter die Kappe.** `hysterese_gebrochen`
  ist kein Feinschliff, sondern Schutz: unter der Kappe hätte sie bis zu vier
  Ticks Verzug — 20 Minuten Import zum Tageshöchstpreis, um einen
  Schaltvorgang zu sparen.

> [!note] Der Fix begrenzt die Rate, nicht die Zahl
> Im nachgestellten Verlauf (`tests/test_uc12_entscheidung.py`) fallen die
> Schaltvorgänge von 9 auf 7, aber die kürzeste Haltezeit steigt von 5 auf
> 20 Minuten. Mehr ist mit dieser Eingangsgröße nicht zu holen: der Überschuss
> war an dem Tag über 20 Minuten lang wirklich weg (721/840 W um 11:35, unter
> 500 W ab 13:15). Dann ist Ausschalten richtig und kein Sägezahn.

**3. Schlafmodus fror die Freigabe ein.** Das Gate in `_async_update_data`
kehrt vor allen Handlern zurück; UC12s eigener „Schlafmodus → aus"-Zweig war
für eine *schon offene* Freigabe damit toter Code. Seit v0.20.9 ruft das Gate
`_handle_uc12_cooling(..., sleep_only_off=True)`: nachts ausschalten ist
erlaubt (das *senkt* die Lüfterstufe), einschalten bleibt gesperrt. Ein
Hand-Eingriff schlägt das weiterhin — der Weg läuft über `_try_act`, also über
Override-Cooldown und `user_touch_at`. Im Schlafpfad bleibt der Status
`schlafmodus` bzw. `schlafmodus → aus`, und der Kühl-Reminder unterbleibt: sein
Push wird ohnehin unterdrückt, hängte aber je Tick eine Zeile in
`last_actions`. UC12 steht deshalb **nicht** in `SLEEP_EXEMPT_UCS` — die
Ausnahme dort heißt „darf nachts frei entscheiden".

Nicht Teil von v0.20.9, bewusst offen: `expensive` hängt weiter am
Tibber-**Level**. Am 19.09. kostete die Stunde um 19:45 **33,94 ct** und das
Level stand auf `normal` (es ist relativ zum 3-Tage-Mittel) — die Sperre hätte
also ohnehin nicht gegriffen. Eine absolute Grenze oder ein Tages-Perzentil
gehört dazu, ist aber eine eigene Entscheidung.

## UC14 — Netzladen

Alle Bedingungen nötig: EMHASS `p_batt < 0` ∧ Spread ≥ 11 ct/kWh zum teuersten
Slot 24h ∧ Fensterlänge ≥ dynamisch nach freiem Akku-Platz ∧ SOC < 90%.
Aktion: `set_power_limits(charge=1500, discharge=0)`. Ende: charge zurück auf
Default, discharge bleibt 0 — UC10 übernimmt im selben Cycle. POST-Verify im
Folge-Cycle (E3DC-Self-Reset-Problematik).
Why 11 ct: ~15% Round-Trip-Verlust + Marge, EEG-Vergütung als Opportunity-Cost.

**Totband + Kappe am Ladewunsch (v0.20.3):** `p_batt` zappelt um die Null und
fällt dabei auf exakt 0.00 — am 29.07.2026 zwischen 09:30 und 11:40 real −1500,
0.00, −414, −189, −36, 0.00, −11.89. Jeder Nulldurchgang beendete UC14, der
nächste Tick startete es neu: fünf E3DC-Schreibvorgänge in vier Stunden, während
`sensor.wattson_netzladen_batterie_status` durchgehend `aktiv` zeigte.

`forecast.grid_charge_holds` hält jetzt bis `UC14_P_BATT_DEADBAND_W` (200 W).
**Ein Band allein reicht hier nicht:** 0.00 ist ein Wert, auf dem der Sensor
stehen bleiben kann (EMHASS publiziert nicht neu) — er käme nie über die
Bandgrenze und UC14 liefe endlos mit 1500 W aus dem Netz. Deshalb zusätzlich
`UC14_P_BATT_HOLD_CYCLES` (3): so viele Ticks in Folge ohne Ladewunsch beenden
es trotzdem. Am 29.07. hätte genau das gegriffen — Zacken um 10:35 und 10:55
gehalten, die 30-Minuten-Null ab 11:00 beendet.

## Totband als gemeinsames Muster

Drei Vorfälle im Juli 2026 hatten dieselbe Ursache: ein blankes `>=`/`<=` gegen
eine Schwelle, alle 5 Minuten neu ausgewertet, und ein Signal, das genau darum
herum pendelt.

| UC | Datum | Was pendelte | Folge |
|---|---|---|---|
| UC12 | 27.07. | Abluft um die Hitze-Schwelle | Kühlung sägte, ein Push pro Zyklus |
| UC6 | 28.07. | die **Schwelle** um den Preis | Lademodus kippte minpv↔pv |
| UC14 | 29.07. | EMHASS `p_batt` um die Null | E3DC-Schreibsalve |
| UC12 | 19.09. | PV-Überschuss um die 1500 W | Freigabe kippte 10× in 3,5 h |

Gemeinsames Primitiv: `forecast.deadband_hold`. Eingeschaltet wird immer an der
nackten Schwelle, das Band verbreitert nur den Ausstieg — andersherum würde es
die Reaktion verschleppen.

**Wem das Band gehört:** einem Grund, nicht einem Aktor. Der laufende Zustand
darf das Gedächtnis sein, solange er eindeutig zu genau einem Grund gehört —
UC6-Lademodus und UC14-Ladewunsch tun das. Der UC12-Kühlschalter nicht: ihn
stellen fünf Zweige. Am 19.09.2026 stand er trotzdem im Hitze-Zweig als
Gedächtnis, und damit erbte jede PV- oder Preis-Kühlung das Force-Recht der
Hitze. Seit v0.20.9 trägt jeder Grund seinen eigenen Merker (`heat_forced`,
`pv_forced`) — die „zusätzliche Zustandsvariable", die den anderen drei Fällen
erspart bleibt.

**Wann ein Band nicht genügt:** wenn der Sperrwert ein Wert ist, auf dem das
Signal stehen bleiben kann (UC14: `p_batt == 0`). Dann gehört eine Zähler-Kappe
dazu. Bei Abluft und Preis passiert das nicht — sie stehen nie exakt auf der
Schwelle fest. Der PV-Überschuss dagegen kann bei dünner Bewölkung stundenlang
*innerhalb* des Bands liegen: dort ist die Kappe die Mindest-Verweildauer
`COOL_MIN_DWELL_MIN`, die den Wechsel nicht verhindert, sondern seine Rate
begrenzt.
