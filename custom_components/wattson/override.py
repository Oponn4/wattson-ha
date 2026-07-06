"""Wattson Override-Manager — User-Eingriffe respektieren, JSON-persistiert."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

_LOGGER = logging.getLogger(__name__)

STATE_FILE_NAME = "wattson_state.json"
FLOAT_TOLERANCE = 0.5         # °C oder generischer numerischer Slack
MIN_COOLDOWN_HOURS = 2        # nicht weniger als 2h Cooldown, selbst spätabends


@dataclass
class ActionRecord:
    """Eine vom Coordinator durchgeführte Aktion (für Override-Detection).

    prev_value = Ist-Zustand unmittelbar vor der Aktion. confirmed wird True,
    sobald der Zielwert einmal beobachtet wurde — erst ab dann gilt eine
    spätere Abweichung als User-Override. Vorher gilt Ist==prev_value als
    fehlgeschlagener Write (Modbus-Glitch), nicht als Eingriff.
    """
    value: Any
    set_at: datetime
    uc_id: str
    prev_value: Any = None
    confirmed: bool = False


@dataclass
class OverrideRecord:
    """Ein laufender User-Override für einen UC."""
    entity_id: str
    detected_at: datetime
    cooldown_until: datetime
    observed_value: Any


@dataclass
class UCDefinition:
    uc_id: str
    name: str
    default_enabled: bool = True


def cooldown_until_next_midnight(now: datetime) -> datetime:
    """Nächste Mitternacht, aber mindestens now+MIN_COOLDOWN."""
    midnight = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    minimum = now + timedelta(hours=MIN_COOLDOWN_HOURS)
    return max(midnight, minimum)


def values_equal(a: Any, b: Any, tolerance: float = FLOAT_TOLERANCE) -> bool:
    """Tolerant comparison: floats via tolerance, alles andere via str-Cast."""
    if a is None or b is None:
        return a is b
    try:
        return abs(float(a) - float(b)) <= tolerance
    except (TypeError, ValueError):
        return str(a).strip().lower() == str(b).strip().lower()


class OverrideManager:
    """Tracks Wattson-Aktionen, erkennt User-Overrides, persistiert UC-Enable + Override-State."""

    def __init__(self, hass: HomeAssistant, ucs: list[UCDefinition]) -> None:
        self._hass = hass
        self._path = Path(hass.config.path(STATE_FILE_NAME))
        self._ucs: dict[str, UCDefinition] = {u.uc_id: u for u in ucs}
        self._enabled: dict[str, bool] = {u.uc_id: u.default_enabled for u in ucs}
        self._actions: dict[str, ActionRecord] = {}
        self._overrides: dict[str, OverrideRecord] = {}
        self._misc: dict[str, Any] = {}

    # ── Persistence ──────────────────────────────────────────────────────────

    async def async_load(self) -> None:
        """Initial load — non-existent file ist OK."""
        def _read() -> dict:
            if not self._path.exists():
                return {}
            try:
                return json.loads(self._path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as e:
                _LOGGER.warning("Wattson state file %s unlesbar: %s", self._path, e)
                return {}

        data = await self._hass.async_add_executor_job(_read)
        if not data:
            return

        for uc_id, enabled in (data.get("uc_enabled") or {}).items():
            if uc_id in self._enabled:
                self._enabled[uc_id] = bool(enabled)

        for ent_id, raw in (data.get("actions") or {}).items():
            try:
                self._actions[ent_id] = ActionRecord(
                    value=raw["value"],
                    set_at=datetime.fromisoformat(raw["set_at"]),
                    uc_id=raw.get("uc_id", ""),
                    prev_value=raw.get("prev_value"),
                    # Legacy-Records (vor v0.18.7) haben kein confirmed-Feld →
                    # True annehmen, damit sie sich wie bisher verhalten
                    confirmed=bool(raw.get("confirmed", True)),
                )
            except (KeyError, ValueError, TypeError) as e:
                _LOGGER.warning("Action-Record für %s ignoriert: %s", ent_id, e)

        self._misc = dict(data.get("misc") or {})

        for uc_id, raw in (data.get("overrides") or {}).items():
            if uc_id not in self._ucs:
                continue
            try:
                self._overrides[uc_id] = OverrideRecord(
                    entity_id=raw["entity_id"],
                    detected_at=datetime.fromisoformat(raw["detected_at"]),
                    cooldown_until=datetime.fromisoformat(raw["cooldown_until"]),
                    observed_value=raw.get("observed_value"),
                )
            except (KeyError, ValueError, TypeError) as e:
                _LOGGER.warning("Override-Record für %s ignoriert: %s", uc_id, e)

    async def _async_persist(self) -> None:
        data = {
            "uc_enabled": self._enabled,
            "misc": self._misc,
            "actions": {
                ent: {
                    "value": rec.value,
                    "set_at": rec.set_at.isoformat(),
                    "uc_id": rec.uc_id,
                    "prev_value": rec.prev_value,
                    "confirmed": rec.confirmed,
                }
                for ent, rec in self._actions.items()
            },
            "overrides": {
                uc: {
                    "entity_id": rec.entity_id,
                    "detected_at": rec.detected_at.isoformat(),
                    "cooldown_until": rec.cooldown_until.isoformat(),
                    "observed_value": rec.observed_value,
                }
                for uc, rec in self._overrides.items()
            },
        }

        def _write() -> None:
            tmp = self._path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
            tmp.replace(self._path)

        try:
            await self._hass.async_add_executor_job(_write)
        except OSError as e:
            _LOGGER.warning("Wattson state file %s nicht schreibbar: %s", self._path, e)

    # ── UC enable/disable ────────────────────────────────────────────────────

    def is_enabled(self, uc_id: str) -> bool:
        return self._enabled.get(uc_id, True)

    async def async_set_enabled(self, uc_id: str, value: bool) -> None:
        if uc_id not in self._ucs:
            return
        self._enabled[uc_id] = value
        await self._async_persist()

    # ── Misc key/value (JSON-persistiert, z.B. legionella_last_done) ────────

    def get_misc(self, key: str) -> Any:
        return self._misc.get(key)

    async def async_set_misc(self, key: str, value: Any) -> None:
        self._misc[key] = value
        await self._async_persist()

    # ── Action recording ─────────────────────────────────────────────────────

    async def async_record_action(
        self, uc_id: str, entity_id: str, value: Any, prev_value: Any = None,
    ) -> None:
        """Wattson hat (real, kein dry-run) entity_id auf value gesetzt."""
        self._actions[entity_id] = ActionRecord(
            value=value, set_at=dt_util.now(), uc_id=uc_id,
            prev_value=prev_value, confirmed=False,
        )
        await self._async_persist()

    def get_last_action(self, entity_id: str) -> ActionRecord | None:
        return self._actions.get(entity_id)

    async def async_drop_action(self, entity_id: str) -> None:
        """Action-Record verwerfen (z.B. nach erkanntem Write-Fehlschlag)."""
        if self._actions.pop(entity_id, None) is not None:
            await self._async_persist()

    # ── Override detection ───────────────────────────────────────────────────

    async def async_check_action(
        self, entity_id: str, current_value: Any, tolerance: float = FLOAT_TOLERANCE,
    ) -> str:
        """Verdikt über die letzte Wattson-Aktion vs. Ist-Zustand.

        Returns:
          "ok"           — kein Record, Entity transient weg, oder Ist == Zielwert
          "failed_write" — Zielwert kam nie an, Ist == Zustand vor der Aktion
                           (z.B. Modbus-Glitch); Caller darf erneut schreiben
          "override"     — jemand hat den Wert verstellt → User-Eingriff

        Wenn current_value None oder 'unavailable'/'unknown' ist → "ok":
        Entity ist transient weg (z.B. Modbus-Reconnect, Coordinator-Refresh).
        Entscheidung wird vertagt statt einen Phantom-Override auszulösen, der
        Wattson sonst bis Mitternacht aussperrt.

        Ein unbestätigter Record, dessen Ist wieder dem prev_value entspricht,
        gilt als fehlgeschlagener Write und NICHT als Override — das war die
        Phantom-Override-Quelle (uc12/uc4b, 2026-07-06 00:06). Kehrt der Wert
        NACH einmaliger Bestätigung zum alten Zustand zurück, ist es ein User.
        """
        last = self._actions.get(entity_id)
        if last is None:
            return "ok"
        if current_value is None or str(current_value).strip().lower() in (
            "unavailable", "unknown", "none", ""
        ):
            return "ok"
        if values_equal(last.value, current_value, tolerance):
            if not last.confirmed:
                last.confirmed = True
                await self._async_persist()
            return "ok"
        if not last.confirmed and values_equal(last.prev_value, current_value, tolerance):
            return "failed_write"
        return "override"

    async def async_record_override(
        self, uc_id: str, entity_id: str, observed_value: Any,
    ) -> OverrideRecord:
        """User-Override erkannt → Cooldown setzen + persist."""
        now = dt_util.now()
        rec = OverrideRecord(
            entity_id=entity_id,
            detected_at=now,
            cooldown_until=cooldown_until_next_midnight(now),
            observed_value=observed_value,
        )
        self._overrides[uc_id] = rec
        # Action-Record löschen damit Override nicht endlos re-detected wird wenn
        # User Wert ändert und Cooldown abläuft — beim nächsten erfolgreichen
        # Wattson-Act wird neu aufgezeichnet
        self._actions.pop(entity_id, None)
        await self._async_persist()
        _LOGGER.info(
            "UC %s: User-Override erkannt auf %s — Cooldown bis %s",
            uc_id, entity_id, rec.cooldown_until.isoformat(),
        )
        return rec

    def in_cooldown(self, uc_id: str, now: datetime | None = None) -> bool:
        rec = self._overrides.get(uc_id)
        if rec is None:
            return False
        return (now or dt_util.now()) < rec.cooldown_until

    def cooldown_remaining_minutes(self, uc_id: str, now: datetime | None = None) -> int:
        rec = self._overrides.get(uc_id)
        if rec is None:
            return 0
        delta = rec.cooldown_until - (now or dt_util.now())
        return max(0, int(delta.total_seconds() // 60))

    def get_override(self, uc_id: str) -> OverrideRecord | None:
        return self._overrides.get(uc_id)

    async def async_resume(self, uc_id: str) -> None:
        """Manueller Resume — clear Override und löscht alte Action-Tracking."""
        if uc_id in self._overrides:
            rec = self._overrides.pop(uc_id)
            self._actions.pop(rec.entity_id, None)
            await self._async_persist()
            _LOGGER.info("UC %s: Override per Resume gelöscht", uc_id)

    # ── Convenience ──────────────────────────────────────────────────────────

    def status_for(self, uc_id: str, now: datetime | None = None) -> dict:
        """Status-Dict für Sensor: state + attributes."""
        if not self.is_enabled(uc_id):
            return {"state": "disabled", "attrs": {}}
        if self.in_cooldown(uc_id, now):
            rec = self._overrides[uc_id]
            remaining = self.cooldown_remaining_minutes(uc_id, now)
            return {
                "state": "user-override",
                "attrs": {
                    "override_entity": rec.entity_id,
                    "override_seit": rec.detected_at.isoformat(),
                    "cooldown_bis": rec.cooldown_until.isoformat(),
                    "cooldown_rest_min": remaining,
                    "beobachteter_wert": rec.observed_value,
                },
            }
        return {"state": "aktiv", "attrs": {}}
