"""Wattson Forecast — Helpers zum Analysieren von Preis-/PV-Vorhersagen."""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta


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


def next_relevant_event(
    events: list[dict], now: datetime, skip_keywords: tuple[str, ...]
) -> dict | None:
    """Erstes Event mit nutzbarem Location-Feld in der Zukunft.

    events: Liste von HA-Calendar-Events (jeweils dict mit start/end/summary/location/uid)
    Format der Service-Response: {"events": [{"start": "...", "summary": "...", "location": "..."}]}
    """
    skip_lower = tuple(k.lower() for k in skip_keywords)
    relevant: list[dict] = []
    for ev in events:
        loc = (ev.get("location") or "").strip()
        if not loc:
            continue
        if any(kw in loc.lower() for kw in skip_lower):
            continue
        start_str = ev.get("start") or ""
        try:
            start_dt = datetime.fromisoformat(start_str.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            continue
        if start_dt <= now:
            continue
        relevant.append({**ev, "_start_dt": start_dt})
    if not relevant:
        return None
    relevant.sort(key=lambda e: e["_start_dt"])
    return relevant[0]


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
    if soc_with_margin < 5:
        soc_with_margin = 5
    if soc_with_margin > 100:
        soc_with_margin = 100
    # Aufrunden auf round_step
    return int(((soc_with_margin + round_step - 1) // round_step) * round_step)
