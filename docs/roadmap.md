# Roadmap

Stand: 2026-06-11, v0.17.3.

## Plan-Reife pro UC

Maßstab ist das Leitprinzip (siehe [architektur.md](architektur.md)):
vorausgeplant statt reaktiv.

| UC | Reife | Lücke |
|---|---|---|
| UC2, UC4b, UC6, UC10, UC14 | ✅ vorausgeplant | — |
| UC4a | ⚠️ Forecast-Heuristik | nicht EMHASS-integriert |
| UC12 | ⚠️ forecast-/schwüle-/trend-skalierte Schwellen | Einschalten zustandsgetrieben, kein geplantes Pre-Cooling |
| UC11 | ⚠️ bewusst reaktiv (Advisor) | Smart-UC11 fehlt |
| UC1 | ✅ reaktiv gewollt | Sicherheitsnetz |

## Geplante Versionen

### v0.17.x — UC4a → EMHASS *(Kandidat, neu identifiziert 2026-06-10)*

T300-Solltemperatur als deferrable/thermisches Modell in EMHASS statt eigener
Tibber-Fenster-Heuristik — analog UC4b-Pattern (Forward-Plan + Confirmation).

### v0.18 — Smart-UC11 *(Task #62, blocked)*

Auto-Mode für Klima OG. Braucht alle Signale, nicht nur Snapshot-Temp:
Humidex pro Raum + außen, Trend, 24h-Prognose, Tür/Fenster-Sprünge,
Kosten/Komfort-Ratio, Koexistenz mit UC12 (Proxon entfeuchtet Zentralluft).

Logik-Skizze:
```
if innen_humidex < 24: nichts
if außen_humidex < innen − 3: notify "Fenster auf"
if kosten ≤ 0.20 OR pv ≥ 800W: klima freigeben
if trend > +0.5°C/h AND forecast_peak > 28: pre-cool 1h vorher
if klima_kosten_pro_h > 0.30 AND comfort_gewinn < 1: stopp
```

**Blocker — RH-Sensorik (Stand 2026-06-09):**
- HT-Schlafzimmer unavailable (Batterie?)
- Klimaanlage Schlafzimmer meldet indoor_humidity = 0.0
- Office hat keinen RH-Sensor
- Nur TP357 Wohnzimmer (`sensor.tp357_27f5_humidity`) liefert

User-Aufgabe: HT-Sensoren reparieren oder TP357 für Office + Schlafzimmer.

### Welle 5/6 — UC9 Hardware *(User-blocked)*

4mm-Kabel + Shelly Pro 3EM verkabeln, dann 1P/3P-Logik.

## Out-of-Scope (bewusst)

- Sauna-Nudge → `script.strompreis_auskunft`, nicht Wattson
- Speicher-Arbitrage (5 kWh zu klein, < 50 €/a)
- Anbieterwechsel (1×/Jahr manuell), Direktvermarktung

## Betriebsregeln

- Ersetzte HA-Automationen → deaktiviert + Label `ersetzt-durch-ec`
  (`automation.t300_warmwasser_steuerung` disabled 2026-05-27)
- Modbus-Sync-Bridges **müssen aktiv bleiben**:
  `automation.proxon_t300_soll_temperatur`, `automation.proxon_boost_temperatur`
- Spar-Potenzial gesamt geschätzt: ~600 €/Jahr

## Historie (abgeschlossen)

| Version | Inhalt |
|---|---|
| Welle 1–4 | Bugfixes, Robustheit, Forecast-Foundation, vorausschauende UCs |
| Welle 7 | UC2 Kalender-Vorladen (gmaps + set_vehicle_plan) |
| v0.13 | UC6 EMHASS-Refactor, Tibber-Forecast-Sensor |
| v0.14.0 | UC6-Hysterese, Override-Detect-Fix, **UC14 Netzladen** |
| v0.14.1 | UC11 → Advisor-Mode |
| v0.15.x | UC12 Kühl-Reminder, UC11 Fenster-auf + Proxon-Suppress |
| v0.16.0 | **UC4b plan-aware** + Safety-Reminder + Override-Unavailable-Guard |
| v0.17.0 | **UC12 adaptive Schwellen** + Force-Hitze |
| v0.17.1 | **UC6 plan-aware 3-Level-Mode** + Downshift-Confirmation |
| v0.17.2 | **Trend-Tracker + UC12 B (Schwüle) + C (Trend)** |
| v0.17.3 | Trend-Buffer-Seed aus Recorder-Historie nach Restart |
