"""Wattson Forecast — Helpers zum Analysieren von Preis-/PV-Vorhersagen."""
from __future__ import annotations

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
