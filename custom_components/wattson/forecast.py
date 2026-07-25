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
    # Aufrunden auf round_step
    return int(((soc_with_margin + round_step - 1) // round_step) * round_step)


@dataclass(frozen=True)
class TripCandidate:
    """Ein auswertbarer Kalender-Termin: Route bekannt, SOC-Bedarf gerechnet."""
    title: str
    location: str
    calendar: str
    start: datetime          # tz-aware
    distance_km: float       # einfache Strecke
    required_soc: int        # für Hin+Rück inkl. Marge
    uid: str = ""

    def satisfied_by(self, car_soc: float) -> bool:
        return car_soc >= self.required_soc


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


def reminder_stage_due_times(
    price_deadline: datetime | None,
    latest_feasible: datetime | None,
    stage1_lead_min: int,
    stage2_lead_min: int,
    stage3_buffer_min: int,
    quiet_start_h: int,
    quiet_end_h: int,
) -> dict[int, datetime | None]:
    """Fälligkeit der drei Eskalationsstufen, aus der Nachtruhe vorgezogen.

    Stufen 1+2 hängen an der Preis-Deadline, Stufe 3 an der Machbarkeitsgrenze
    (und ist damit preisunabhängig — sie feuert auch ohne Forecast).
    """
    def _due(when: datetime | None, minutes: int) -> datetime | None:
        if when is None:
            return None
        return pull_out_of_quiet_hours(
            when - timedelta(minutes=minutes), quiet_start_h, quiet_end_h
        )

    return {
        1: _due(price_deadline, stage1_lead_min),
        2: _due(price_deadline, stage2_lead_min),
        3: _due(latest_feasible, stage3_buffer_min),
    }


def current_reminder_stage(
    now: datetime, stage_due: dict[int, datetime | None]
) -> int:
    """Höchste fällige Stufe (0 = noch nichts).

    Höchste gewinnt: zieht die Nachtruhe zwei Stufen auf dieselbe Zeit, wird
    die dringendere gemeldet statt beide.
    """
    stage = 0
    for candidate in sorted(stage_due):
        due = stage_due[candidate]
        if due is not None and now >= due:
            stage = candidate
    return stage


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
