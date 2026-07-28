"""Wattson Forecast — Helpers zum Analysieren von Preis-/PV-Vorhersagen."""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta, tzinfo

from .const import ALL_DAY_DEPARTURE_HOUR


@dataclass(frozen=True)
class PriceSlot:
    start: datetime  # tz-aware
    price: float     # EUR/kWh

    @property
    def end(self) -> datetime:
        return self.start + timedelta(minutes=15)


def parse_tibber_response(response: dict | None) -> list[PriceSlot]:
    """Parse dict von tibber.get_prices in sortierte PriceSlot-Liste."""
    if not response:
        return []
    prices = response.get("prices", {})
    slots: list[PriceSlot] = []
    for home_data in prices.values():
        if not isinstance(home_data, list):
            continue
        for item in home_data:
            try:
                slots.append(PriceSlot(
                    start=datetime.fromisoformat(item["start_time"]),
                    price=float(item["price"]),
                ))
            except (KeyError, ValueError, TypeError):
                continue
    slots.sort(key=lambda s: s.start)
    return slots


def upcoming_slots(
    slots: list[PriceSlot], now: datetime, hours: int
) -> list[PriceSlot]:
    """Slots die ab now bis now+hours laufen oder beginnen."""
    cutoff = now + timedelta(hours=hours)
    return [s for s in slots if s.end > now and s.start < cutoff]


def _best_window(
    slots: list[PriceSlot],
    duration_minutes: int,
    now: datetime,
    lookahead_hours: int,
    prefer_low: bool,
) -> tuple[datetime, datetime, float] | None:
    window_size = duration_minutes // 15
    if window_size < 1:
        return None
    upcoming = upcoming_slots(slots, now, lookahead_hours)
    if len(upcoming) < window_size:
        return None
    best_avg: float | None = None
    best_idx = 0
    for i in range(len(upcoming) - window_size + 1):
        window = upcoming[i:i + window_size]
        avg = sum(s.price for s in window) / window_size
        if best_avg is None or (avg < best_avg if prefer_low else avg > best_avg):
            best_avg = avg
            best_idx = i
    if best_avg is None:
        return None
    return (
        upcoming[best_idx].start,
        upcoming[best_idx + window_size - 1].end,
        best_avg,
    )


def cheapest_window(
    slots: list[PriceSlot], duration_minutes: int, now: datetime,
    lookahead_hours: int = 12,
) -> tuple[datetime, datetime, float] | None:
    return _best_window(slots, duration_minutes, now, lookahead_hours, prefer_low=True)


def most_expensive_window(
    slots: list[PriceSlot], duration_minutes: int, now: datetime,
    lookahead_hours: int = 12,
) -> tuple[datetime, datetime, float] | None:
    return _best_window(slots, duration_minutes, now, lookahead_hours, prefer_low=False)


def is_in_window(now: datetime, start: datetime, end: datetime) -> bool:
    return start <= now < end


def humidex(temp_c: float, rh_pct: float) -> float:
    """Gefühlte-Temperatur nach Humidex (Kanada). Robust für 0-100% RH und alle T.

    Formel: humidex = T + 0.5555 × (e − 10), e = 6.11 × exp(5417.7530 × (1/273.16 − 1/Td))
    Mit Dewpoint Td aus Magnus-Approx.
    """
    if rh_pct <= 0 or temp_c < -40:
        return temp_c
    rh = max(1.0, min(100.0, rh_pct)) / 100.0
    # Magnus dewpoint
    a, b = 17.27, 237.7
    alpha = (a * temp_c) / (b + temp_c) + math.log(rh)
    td = (b * alpha) / (a - alpha)
    # Wasserdampfdruck am Dewpoint (hPa)
    td_k = td + 273.15
    e = 6.11 * math.exp(5417.7530 * (1.0/273.16 - 1.0/td_k))
    return temp_c + 0.5555 * (e - 10.0)


def consecutive_cheap_minutes_from_now(
    slots: list[PriceSlot], now: datetime, max_price_eur_kwh: float,
) -> int:
    """Wie viele Minuten ab `now` durchgängig unter `max_price_eur_kwh` bleiben.

    Wenn der aktuelle (now-überdeckende) Slot bereits teurer ist: 0.
    Stoppt beim ersten Slot, der den Schwellwert überschreitet. Verwendet für
    UC14 Netzladen-Fenster-Detection.
    """
    sorted_slots = sorted(slots, key=lambda s: s.start)
    consecutive = 0
    started = False
    for slot in sorted_slots:
        if slot.end <= now:
            continue
        if slot.price > max_price_eur_kwh:
            break
        # Erster relevanter Slot: zähle nur den verbleibenden Teil bis end
        if not started:
            remaining = (slot.end - now).total_seconds() / 60
            consecutive += max(0, int(remaining))
            started = True
        else:
            consecutive += 15
    return consecutive


def parse_event_start(
    start_raw: object, tz: tzinfo | None, all_day_hour: int = ALL_DAY_DEPARTURE_HOUR,
) -> datetime | None:
    """Event-Start aus HA-Calendar-Response in tz-aware datetime.

    HA liefert zwei Formate: getimte Events als ISO-String mit Offset
    ("2026-07-26T12:00:00+02:00"), Ganztags-Events als reines Datum
    ("2026-07-26"). `fromisoformat` wirft beim Datum NICHT, sondern gibt ein
    naives datetime zurück — ein späterer Vergleich mit tz-aware `now` würfe
    dann TypeError. Darum hier immer tz-aware normalisieren.

    Ganztags-Events haben keine Abfahrtszeit. Statt sie zu verwerfen (echte
    Fahrten gingen verloren) wird `all_day_hour` lokal angenommen — früh genug,
    dass eher zu zeitig als zu spät geladen wird.
    """
    if not isinstance(start_raw, str) or not start_raw:
        return None
    try:
        parsed = datetime.fromisoformat(start_raw.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    if parsed.tzinfo is None:
        is_date_only = "T" not in start_raw
        if is_date_only:
            parsed = parsed.replace(hour=all_day_hour)
        parsed = parsed.replace(tzinfo=tz)
    return parsed


def event_key(ev: dict, tz: tzinfo | None) -> str:
    """Stabiler Schlüssel für einen Kalendertermin.

    Bevorzugt die uid des Kalenders. Fehlt sie (manche Quellen liefern keine),
    dient normalisierter Start + Titel als Ersatz. Die Normalisierung ist
    wichtig: Rohdaten nennen Ganztags-Termine "2026-07-26", der ausgewertete
    Kandidat dagegen "2026-07-26T08:00:00+02:00". Ohne gemeinsame Funktion
    gingen beide Seiten auseinander und ein gültiger Fahrplan würde als
    „Termin verschwunden" gelöscht.
    """
    uid = ev.get("uid")
    if uid:
        return str(uid)
    start = parse_event_start(ev.get("start"), tz)
    start_part = start.isoformat() if start else str(ev.get("start"))
    return f"{start_part}:{ev.get('summary', '?')}"


def next_relevant_event(
    events: list[dict], now: datetime, skip_keywords: tuple[str, ...]
) -> dict | None:
    """Erstes Event mit nutzbarem Location-Feld in der Zukunft.

    events: Liste von HA-Calendar-Events (jeweils dict mit start/end/summary/location/uid)
    Format der Service-Response: {"events": [{"start": "...", "summary": "...", "location": "..."}]}
    """
    relevant = relevant_events(events, now, skip_keywords)
    return relevant[0] if relevant else None


def relevant_events(
    events: list[dict], now: datetime, skip_keywords: tuple[str, ...]
) -> list[dict]:
    """Alle zukünftigen Events mit nutzbarer Location, nach Start sortiert.

    Jedes Event bekommt `_start_dt` (tz-aware) angehängt. Unparsbare Starts
    werden übersprungen, damit ein kaputtes Event nicht den Tick reißt.
    """
    skip_lower = tuple(k.lower() for k in skip_keywords)
    relevant: list[dict] = []
    for ev in events:
        loc = (ev.get("location") or "").strip()
        if not loc:
            continue
        if any(kw in loc.lower() for kw in skip_lower):
            continue
        start_dt = parse_event_start(ev.get("start"), now.tzinfo)
        if start_dt is None or start_dt <= now:
            continue
        relevant.append({**ev, "_start_dt": start_dt})
    relevant.sort(key=lambda e: e["_start_dt"])
    return relevant


def calculate_required_soc(
    distance_km: float,
    consumption_kwh_100km: float,
    capacity_kwh: float,
    safety_margin_percent: int,
    round_step: int = 5,
) -> int:
    """SOC% nötig für Hin+Rückfahrt + Sicherheitspuffer, gerundet auf round_step%."""
    energy_needed_kwh = (distance_km * 2.0) * consumption_kwh_100km / 100.0
    soc_pct = (energy_needed_kwh / capacity_kwh) * 100.0
    soc_with_margin = soc_pct + safety_margin_percent
    soc_with_margin = max(soc_with_margin, 5)
    soc_with_margin = min(soc_with_margin, 100)
    # Aufrunden auf round_step. math.ceil, nicht der Integer-Trick
    # `(x + step - 1) // step` — der rundet bei Fließkomma-Resten unter 1 ab
    # (90.1 ergab 90 statt 95) und hat damit knappe Fahrten zu knapp geplant.
    return min(int(math.ceil(soc_with_margin / round_step) * round_step), 100)


@dataclass(frozen=True)
class TripCandidate:
    """Ein auswertbarer Kalender-Termin: Route bekannt, SOC-Bedarf gerechnet."""
    title: str
    location: str
    calendar: str
    start: datetime          # tz-aware, Termin-BEGINN (nicht Abfahrt)
    distance_km: float       # einfache Strecke
    required_soc: int        # für Hin+Rück inkl. Marge
    uid: str = ""
    travel_minutes: int = 0  # einfache Fahrzeit laut Routing

    def satisfied_by(self, car_soc: float) -> bool:
        return car_soc >= self.required_soc

    def departure(self, ready_buffer_minutes: int) -> datetime:
        """Spätester Zeitpunkt, zu dem das Auto geladen dastehen muss.

        Termin-Beginn minus Fahrzeit minus Fertigmach-Puffer. Ohne die
        Fahrzeit zielte der Ladeplan auf den Termin-Beginn — bei 71 min
        Anfahrt wäre das Auto erst fertig, wenn man längst unterwegs ist.
        """
        return self.start - timedelta(
            minutes=self.travel_minutes + ready_buffer_minutes
        )


@dataclass(frozen=True)
class BindingTrip:
    """Ergebnis der Trip-Auswahl.

    `deadline_trip` gibt die Zeit vor (früheste ungedeckte Fahrt),
    `required_soc` das Ziel (Maximum über alle ungedeckten Fahrten).
    Beide können aus verschiedenen Terminen stammen: steht morgens eine
    kleine und abends eine große Fahrt an, wird vor der kleinen schon auf
    das große Ziel geladen.
    """
    deadline_trip: TripCandidate
    required_soc: int
    soc_driver: TripCandidate    # Termin, der required_soc diktiert


def select_binding_trip(
    candidates: list[TripCandidate], car_soc: float
) -> BindingTrip | None:
    """Bindende Ladeanforderung über ALLE anstehenden Fahrten.

    Vorher wurde nur der zeitlich nächste Termin betrachtet — reichte dessen
    SOC, brach die Planung ab und spätere, größere Fahrten blieben unsichtbar
    (Vorfall 2026-07-25: „Tennis" 6 km maskierte eine 100-km-Fahrt am Folgetag).

    None, wenn keine Fahrt zusätzliche Ladung braucht.

    Vereinfachung: der Verbrauch der früheren Fahrten wird nicht vom SOC der
    späteren abgezogen. Das Ziel ist damit eher zu hoch als zu niedrig; nach
    jeder Fahrt rechnet der nächste Tick ohnehin neu.
    """
    unsatisfied = [c for c in candidates if not c.satisfied_by(car_soc)]
    if not unsatisfied:
        return None
    deadline_trip = min(unsatisfied, key=lambda c: c.start)
    soc_driver = max(unsatisfied, key=lambda c: c.required_soc)
    return BindingTrip(
        deadline_trip=deadline_trip,
        required_soc=soc_driver.required_soc,
        soc_driver=soc_driver,
    )


SLOT_HOURS = 0.25  # PriceSlot-Länge


@dataclass(frozen=True)
class ChargePlanWindow:
    """Wann muss das Auto spätestens hängen, damit günstig geladen werden kann."""
    slots_needed: int
    best_cost_eur: float           # billigstmöglich bei Anstecken jetzt
    cost_now_eur: float            # = best_cost_eur (Referenz für Meldungen)
    price_deadline: datetime | None  # spätestes Anstecken im Toleranzrahmen
    latest_feasible: datetime | None  # spätestes Anstecken, das energetisch reicht
    truncated: bool                # Forecast reicht nicht bis zur Abfahrt

    def extra_cost_eur(self, cost_eur: float) -> float:
        return max(0.0, cost_eur - self.best_cost_eur)


def _cheapest_n_cost(
    slots: list[PriceSlot], start: datetime, end: datetime, n: int, kwh_per_slot: float,
) -> float | None:
    """Kosten der n günstigsten Slots in [start, end). None wenn zu wenige."""
    window = [s for s in slots if s.start >= start and s.end <= end]
    if len(window) < n:
        return None
    cheapest = sorted(s.price for s in window)[:n]
    return sum(p * kwh_per_slot for p in cheapest)


def plan_charge_window(
    slots: list[PriceSlot],
    now: datetime,
    departure: datetime,
    energy_kwh: float,
    power_kw: float,
    tolerance_eur_per_kwh: float,
) -> ChargePlanWindow | None:
    """Preis-Deadline fürs Anstecken bestimmen.

    Der Abstand zur Abfahrt ist als Trigger untauglich: liegt das billige
    Fenster 17 h vor der Abfahrt (Sommer-PV-Kurve) und die Nacht doppelt so
    teuer, ist eine „6 h vorher"-Erinnerung wertlos. Maßgeblich ist, wann die
    letzte noch bezahlbare Slot-Kombination wegfällt.

    Vorgehen: n = benötigte Slots. Referenz sind die n günstigsten Slots von
    jetzt bis Abfahrt. Dann vorwärts scannen — spätestes Anstecken, bei dem die
    n günstigsten des Restfensters nicht mehr als `tolerance_eur_per_kwh`
    teurer sind, ist die Deadline. Die Kostenfunktion steigt monoton, weil ein
    späterer Start nur Slots verlieren kann.

    None, wenn Abfahrt vergangen, keine Preise bekannt oder die Energie schon
    ab jetzt nicht mehr reinpasst.
    """
    if departure <= now or energy_kwh <= 0 or power_kw <= 0:
        return None
    kwh_per_slot = power_kw * SLOT_HOURS
    if kwh_per_slot <= 0:
        return None
    n = math.ceil(energy_kwh / kwh_per_slot)
    if n < 1:
        return None

    usable = sorted(
        (s for s in slots if s.end > now and s.start < departure),
        key=lambda s: s.start,
    )
    if not usable:
        return None
    horizon_end = usable[-1].end
    effective_end = min(departure, horizon_end)
    truncated = horizon_end < departure

    best = _cheapest_n_cost(usable, usable[0].start, effective_end, n, kwh_per_slot)
    if best is None:
        # Energie passt schon ab jetzt nicht mehr in die bekannten Slots
        return ChargePlanWindow(
            slots_needed=n, best_cost_eur=0.0, cost_now_eur=0.0,
            price_deadline=None, latest_feasible=None, truncated=truncated,
        )

    tolerance_total = tolerance_eur_per_kwh * energy_kwh
    price_deadline: datetime | None = None
    latest_feasible: datetime | None = None
    for slot in usable:
        cost = _cheapest_n_cost(usable, slot.start, effective_end, n, kwh_per_slot)
        if cost is None:
            break  # ab hier passt die Energie nicht mehr — Fenster zu klein
        latest_feasible = slot.start
        if cost - best <= tolerance_total:
            price_deadline = slot.start

    return ChargePlanWindow(
        slots_needed=n,
        best_cost_eur=best,
        cost_now_eur=best,
        price_deadline=price_deadline,
        latest_feasible=latest_feasible,
        truncated=truncated,
    )


def cost_from(
    slots: list[PriceSlot], start: datetime, departure: datetime,
    slots_needed: int, power_kw: float,
) -> float | None:
    """Was das Laden kostet, wenn erst ab `start` angesteckt wird."""
    usable = [s for s in slots if s.end > start and s.start < departure]
    if not usable:
        return None
    return _cheapest_n_cost(
        usable, min(s.start for s in usable), departure,
        slots_needed, power_kw * SLOT_HOURS,
    )


def pull_out_of_quiet_hours(
    when: datetime, quiet_start_h: int, quiet_end_h: int
) -> datetime:
    """Meldezeit aus der Nachtruhe nach VORNE ziehen, nicht unterdrücken.

    Eine Erinnerung, die um 03:30 fällig wäre, muss um 21:59 raus — sonst
    verschluckt die Nachtruhe genau die nachtkritischen Fälle (Billigfenster
    liegt nachts). Ein einfaches „in Nachtruhe → return" wäre hier fatal.
    """
    hour = when.hour
    in_quiet = hour >= quiet_start_h or hour < quiet_end_h
    if not in_quiet:
        return when
    boundary = when.replace(hour=quiet_start_h, minute=0, second=0, microsecond=0)
    if hour < quiet_end_h:
        boundary -= timedelta(days=1)   # frühmorgens → Grenze war am Vorabend
    return boundary - timedelta(minutes=1)


@dataclass(frozen=True)
class ChargeDecision:
    """Ergebnis der Lademodus-Entscheidung."""
    mode: str      # "now" | "minpv" | "pv"
    reason: str


def heat_active(
    *,
    abluft_c: float,
    heat_c: float,
    hysteresis_c: float,
    currently_cooling: bool,
) -> bool:
    """Gilt "echte Hitze" — mit Totband gegen Schwingen.

    Einschalten ab `heat_c`, ausschalten erst unter `heat_c - hysteresis_c`.
    Ohne das entscheidet ein blankes `>=` über eine Schwelle, um die die
    Abluft herumpendelt: ein Tick sieht 25,4 und schaltet die Kühlung ein, der
    nächste sieht 25,1 und die Grundregel schaltet wieder aus. Am 27.07.2026
    lief das als Sägezahn — 5 min an, 25 min aus, ein Push pro Zyklus.

    Der laufende Zustand ist das Gedächtnis, deshalb braucht es keine eigene
    Zustandsvariable.
    """
    schwelle = (heat_c - hysteresis_c) if currently_cooling else heat_c
    return abluft_c >= schwelle


def charge_threshold_ct(
    slots: list[PriceSlot],
    *,
    needed_kwh: float,
    power_kw: float,
    now: datetime,
    until: datetime | None = None,
    floor_ct: float = 0.0,
) -> float | None:
    """Ab welchem Preis lohnt Laden — aus Bedarf und Kurve, nicht aus Geschmack.

    Nimmt die günstigsten Slots im Fenster, bis der Bedarf gedeckt ist, und
    gibt den Preis des teuersten davon zurück. Alles darunter ist "günstig
    genug", alles darüber nicht.

    Das ersetzt sowohl feste Cent-Grenzen als auch Tibbers Level. Eine feste
    Grenze altert (20 ct sind im Sommer günstig und im Winter unerreichbar),
    und Tibbers Level hängen am gleitenden Mittel statt am eigenen Bedarf.
    Diese Schwelle wandert von selbst mit Saison, Kurve und Ladezustand: viel
    nachzuladen weitet sie, wenig verengt sie.

    Gibt None, wenn keine Preisdaten vorliegen — dann bleibt nur der Fahrplan.
    """
    if needed_kwh <= 0 or power_kw <= 0:
        return floor_ct or None

    window = [
        sl for sl in slots
        if sl.end > now and (until is None or sl.start < until)
    ]
    if not window:
        return None

    slot_hours = 0.25  # PriceSlot ist eine Viertelstunde
    needed_slots = max(1, math.ceil(needed_kwh / (power_kw * slot_hours)))

    prices = sorted(sl.price * 100.0 for sl in window)
    if needed_slots >= len(prices):
        # Fenster reicht ohnehin nicht — dann ist jeder Slot nötig.
        return max(prices[-1], floor_ct)

    return max(prices[needed_slots - 1], floor_ct)


def decide_charge_mode(
    *,
    car_connected: bool,
    plan_active: bool,
    plan_at_risk: bool,
    price_ct: float | None,
    threshold_ct: float | None,
    eeg_ct: float,
    pv_surplus_w: int,
    car_soc: float,
    limit_soc: int,
    pv_surplus_min_w: int,
    current_mode: str | None = None,
    threshold_band_ct: float = 0.0,
) -> ChargeDecision:
    """Lademodus bestimmen.

    Vier Regime, jedes mit einem Grund statt einer Geschmacksgrenze:

    * Fahrplan kippt zeitlich      -> `now`, überstimmt alles
    * Preis unter Einspeisevergütung -> `now`, Netzstrom ist dann billiger als
      die eigene Sonne. Greift selten (2 von 7 Monaten 2026, nur bei
      Negativpreisen im Frühjahr) und kostet nichts, wenn nicht.
    * Preis unter der Bedarfsschwelle -> `minpv`, Netzminimum plus alle Sonne.
      Das Arbeitspferd, besonders im Winter, wo "relativ günstig" absolut
      immer noch teuer ist.
    * sonst                        -> `pv`, nur Überschuss.

    Warum nicht `smartCostLimit` in evcc statt `now`: das Limit ist dort ein
    Schalter auf Volllast unabhängig von der Sonne. Für das EEG-Regime ist das
    genau richtig, für das Winter-Regime falsch — ein Knopf kann beide nicht.
    Also entscheidet Wattson und evcc führt aus.

    `threshold_band_ct` ist das Totband der Bedarfsschwelle (v0.20.2): läuft
    bereits `minpv`, darf der Preis bis `Schwelle + Band` steigen, bevor auf
    `pv` zurückgefallen wird. Der laufende Modus ist das Gedächtnis, genau wie
    bei `heat_active` — keine zusätzliche Zustandsvariable. Nötig, weil hier
    nicht der Messwert um die Schwelle pendelt, sondern die Schwelle um den
    Messwert: sie wird jeden Tick neu gerechnet und springt in Slot-Schritten.
    """
    if not car_connected:
        return ChargeDecision("pv", "Auto nicht angeschlossen")

    if plan_active and plan_at_risk:
        return ChargeDecision("now", "Fahrplan schafft es zeitlich nicht mehr")

    if car_soc >= limit_soc:
        return ChargeDecision("pv", f"SOC {car_soc:.0f}% ≥ Limit {limit_soc}%")

    if price_ct is None:
        return ChargeDecision("pv", "keine Preisdaten — nur PV-Überschuss")

    if price_ct <= eeg_ct:
        return ChargeDecision(
            "now", f"{price_ct:.1f} ct ≤ Einspeisevergütung {eeg_ct:.1f} ct"
        )

    if threshold_ct is not None:
        # Totband nur nach oben und nur, solange minpv schon läuft: der
        # Einstieg bleibt bei der gerechneten Schwelle, der Ausstieg bekommt
        # Luft. Umgekehrt würde das Band die Freigabe verschleppen.
        band = threshold_band_ct if current_mode == "minpv" else 0.0
        if price_ct <= threshold_ct + band:
            im_band = band > 0.0 and price_ct > threshold_ct
            grund = (
                f"{price_ct:.1f} ct ≤ Bedarfsschwelle {threshold_ct:.1f} ct"
                f" + Totband {band:.1f} ct"
                if im_band
                else f"{price_ct:.1f} ct ≤ Bedarfsschwelle {threshold_ct:.1f} ct"
            )
            return ChargeDecision("minpv", grund)

    sun = pv_surplus_w >= pv_surplus_min_w
    if plan_active:
        return ChargeDecision("pv", "Fahrplan aktiv — evcc wählt die Slots")

    if threshold_ct is None:
        return ChargeDecision("pv", f"{price_ct:.1f} ct, keine Schwelle bekannt")

    hint = f", PV {pv_surplus_w} W" if sun else ""
    return ChargeDecision(
        "pv", f"{price_ct:.1f} ct > Schwelle {threshold_ct:.1f} ct{hint}"
    )


def plan_is_stale(
    *,
    stored_uid: str | None,
    event_uids: list[str],
    baseline_uid: str,
) -> bool:
    """Ist der gespeicherte Fahrplan verwaist — gehört er zu keinem Termin mehr?

    Der Grundplan ist ausgenommen. Er stammt bewusst aus keinem Kalendertermin,
    also findet die Suche nach seiner uid nie etwas, und die Aufräumroutine
    hielt ihn für einen abgesagten Termin. Ergebnis am 27.07.2026 ab 21:36:
    UC2 setzte den Grundplan, der nächste Tick löschte ihn wieder, im Wechsel
    bis in die Nacht — die Zusage "50 % bis 07:00" stand nie wirklich in evcc.

    Als reine Funktion herausgezogen, weil der Coordinator Home Assistant
    importiert und in den Tests nicht ladbar ist.
    """
    if stored_uid is None:
        return False
    if stored_uid == baseline_uid:
        return False
    return stored_uid not in event_uids


def needs_forced_charging(
    plan_set: bool,
    trip_start: datetime | None,
    latest_feasible: datetime | None,
    now: datetime,
    fallback_hours: int,
) -> bool:
    """Muss sofort geladen werden, statt dem Fahrplan zu vertrauen?

    Früher rein zeitlich („Abfahrt < N h"). Das ist falsch, weil der
    Sofort-Modus den tarifoptimierten Fahrplan überstimmt und preisblind lädt.
    Maßgeblich ist, ob der Plan zeitlich noch durchkommt: erst ab
    `latest_feasible` reicht die verbleibende Zeit nicht mehr.

    Ohne bekannte Grenze (keine Preis-/Bedarfsdaten) bleibt die alte
    Zeitregel als Rückfallebene.
    """
    if not plan_set or trip_start is None:
        return False
    if latest_feasible is not None:
        return now >= latest_feasible
    return (trip_start - now) <= timedelta(hours=fallback_hours)


@dataclass(frozen=True)
class PluginReminder:
    """Eine Erinnerung, das Auto anzustecken."""
    kind: str      # "ankunft" | "fahrt"
    title: str
    message: str
    urgent: bool


def plugin_reminder_due(
    *,
    car_home: bool,
    car_plugged: bool,
    car_soc: float,
    comfort_soc: int,
    trip_required_soc: int | None,
    trip_title: str,
    trip_at_risk: bool,
    minutes_since_arrival: float | None,
    arrival_window_min: int,
) -> PluginReminder | None:
    """Ist eine Anstecken-Erinnerung fällig?

    Bewusst EINE Sorte Meldung statt gestaffelter Preis-Eskalation. Das Einzige,
    was ein Mensch beisteuern muss, ist das Kabel — alles andere entscheidet das
    System selbst. Also gibt es auch nur eine Bitte, und die heißt "steck an".

    Der Zeitpunkt trägt die halbe Wirkung: beim Heimkommen steht man neben dem
    Auto, das Kabel ist zwei Meter weg. Dieselbe Meldung abends auf dem Sofa
    wird weggewischt. Deshalb ist das Ankunftsfenster der Normalfall; ohne
    Ankunftsbezug meldet nur noch die gefährdete Fahrt.

    Seltenheit ist Teil der Funktion: eine Erinnerung, die oft kommt, wird
    ignoriert — und mit ihr die eine wichtige. Darum liegt `comfort_soc`
    bewusst niedrig.
    """
    if not car_home or car_plugged:
        return None

    braucht_fahrt = (
        trip_required_soc is not None and car_soc < trip_required_soc
    )

    # Gefährdete Fahrt meldet unabhängig von der Ankunft — sonst verpasst man
    # sie, wenn das Auto schon länger ungenutzt dasteht.
    if braucht_fahrt and trip_at_risk:
        return PluginReminder(
            kind="fahrt",
            title="Auto anstecken — Zeit wird knapp",
            message=(
                f"{trip_title}: gebraucht {trip_required_soc} %, "
                f"drin sind {car_soc:.0f} %. Bitte anstecken."
            ),
            urgent=True,
        )

    frisch_angekommen = (
        minutes_since_arrival is not None
        and minutes_since_arrival <= arrival_window_min
    )
    if not frisch_angekommen:
        return None

    if braucht_fahrt:
        return PluginReminder(
            kind="ankunft",
            title="Auto anstecken",
            message=(
                f"ORA bei {car_soc:.0f} % — {trip_title} braucht "
                f"{trip_required_soc} %. Bitte anstecken."
            ),
            urgent=False,
        )
    if car_soc < comfort_soc:
        return PluginReminder(
            kind="ankunft",
            title="Auto anstecken",
            message=f"ORA bei {car_soc:.0f} % — bitte anstecken.",
            urgent=False,
        )
    return None


@dataclass(frozen=True)
class DeferrableSlot:
    """Ein EMHASS 30-min-Slot mit geplanter Deferrable-Leistung."""
    start: datetime  # tz-aware
    power: float     # W

    @property
    def end(self) -> datetime:
        return self.start + timedelta(minutes=30)


def parse_deferrable_schedule(
    attr_data: list | None, key: str = "p_deferrable0",
) -> list[DeferrableSlot]:
    """Parse EMHASS `deferrables_schedule`-Attribut in typisierte Slot-Liste.

    Eingabe: Liste von Dicts mit "date" (ISO-Datetime) + key (Power als String/Float).
    Output: aufsteigend nach Startzeit sortierte DeferrableSlot-Liste.
    """
    if not attr_data:
        return []
    slots: list[DeferrableSlot] = []
    for item in attr_data:
        try:
            start = datetime.fromisoformat(item["date"])
            power = float(item[key])
            slots.append(DeferrableSlot(start=start, power=power))
        except (KeyError, ValueError, TypeError):
            continue
    slots.sort(key=lambda s: s.start)
    return slots


def deferrable_slot_at(
    slots: list[DeferrableSlot], now: datetime,
) -> DeferrableSlot | None:
    """Slot der `now` enthält (start ≤ now < end), oder None."""
    for s in slots:
        if s.start <= now < s.end:
            return s
    return None


def next_deferrable_on_block(
    slots: list[DeferrableSlot], now: datetime, threshold_w: float,
) -> tuple[datetime, datetime] | None:
    """Findet das nächste oder aktuelle On-Block (start, end).

    Ein Block ist eine Sequenz zusammenhängender Slots mit power ≥ threshold_w.
    Returns None wenn kein On-Block im verbleibenden Plan existiert.
    """
    if not slots:
        return None
    # Filter: nur Slots ab/nach now relevant (laufender Slot zählt mit)
    relevant = [s for s in slots if s.end > now]
    if not relevant:
        return None
    block_start: datetime | None = None
    block_end: datetime | None = None
    for s in relevant:
        if s.power >= threshold_w:
            if block_start is None:
                block_start = s.start
            block_end = s.end
        else:
            if block_start is not None:
                # Block abgeschlossen
                return (block_start, block_end)  # type: ignore[return-value]
    if block_start is not None:
        return (block_start, block_end)  # type: ignore[return-value]
    return None
