# Wattson — Home Energy Coordinator

Home Assistant Custom Component der **vorausschauend** PV, Speicher, E-Auto und
Wärmepumpe basierend auf Tibber-Forecast koordiniert.

> ⚠️ **Alpha** — Entity-IDs sind aktuell hardgecodet auf das Setup des Autors.
> Vor Nutzung in eigenem Setup `const.py` anpassen.

## Voraussetzungen

- Home Assistant ≥ 2024.11
- Tibber-Integration (für `tibber.get_prices` Service)
- evcc-Integration für E-Auto-Steuerung
- Optional: E3DC-Integration für PV/Speicher-Daten
- Optional: Proxon T300 Integration für Wärmepumpe

## Installation via HACS

1. HACS → ⋮ → Custom repositories
2. URL: `https://github.com/Oponn4/wattson-ha`, Type: `Integration`
3. "Wattson Energy Coordinator" installieren
4. Home Assistant neu starten
5. Einstellungen → Geräte & Dienste → Integration hinzufügen → "Wattson"
6. **Dry-Run aktiviert lassen** für ersten Test

## Was Wattson tut

Alle 5 Minuten: liest Tibber-Preise/-Forecast, EMHASS-Plan, PV, Speicher-SOC,
T300, Auto-SOC, Kalender — und entscheidet je Use Case **plan-aware** (aus dem
Forward-Plan, nicht reaktiv auf Momentanwerte). Kurzfassung:

- **UC2** Kalender-Trip → Distanz → required SOC → evcc-Ladeplan
- **UC4a** T300-Solltemperatur nach günstigstem Tibber-Fenster
- **UC4b** E-Heizstab nach EMHASS-Forward-Plan + Safety-Reminder
- **UC6** evcc-Modus 3-Level `pv`/`minpv`/`now` nach EMHASS-Plan + Trip
- **UC10** E3DC-Discharge granular nach EMHASS `p_batt`
- **UC11** Klima OG: Advisor-Notifications mit Action-Buttons
- **UC12** Proxon-Kühlung mit forecast-adaptiven Schwellen
- **UC14** E3DC-Netzladen bei großem Preis-Spread
- **UC1** Push bei Auto-SOC < 20%

## Dokumentation

- [docs/architektur.md](docs/architektur.md) — Leitprinzip, EMHASS-Hybrid, Patterns, Datenquellen
- [docs/use-cases.md](docs/use-cases.md) — alle UCs im Detail
- [docs/roadmap.md](docs/roadmap.md) — Plan-Reife, geplante Versionen, Historie

## Entities

| Entity | Zweck |
|---|---|
| `sensor.wattson_status` | `dry-run` oder `aktiv` |
| `sensor.wattson_letzte_aktion` | Letzte ausgeführte (oder simulierte) Aktion |
| `sensor.wattson_t300_zieltemperatur` | Aktuelles T300-Ziel laut Wattson |
| `sensor.wattson_evcc_zielmodus` | Aktueller evcc-Ziel-Modus |
| `sensor.wattson_gunstigste_2h` | Günstigstes 2h-Fenster nächste 12h |
| `sensor.wattson_gunstigste_4h` | Günstigstes 4h-Fenster nächste 24h |
| `sensor.wattson_teuerste_2h` | Teuerstes 2h-Fenster nächste 12h |
| `switch.wattson_dry_run` | Dry-Run Toggle |
| `button.wattson_zyklus_ausfuhren` | Manueller Zyklus |

## Dry-Run

Wenn aktiviert, werden Aktionen nur **geloggt**, nicht ausgeführt.
Logs zeigen `[DRY-RUN] domain.service(...)` statt der echten Service-Calls.

## Lizenz

Privates Projekt — Nutzung auf eigene Gefahr.
