"""Tests für die Override-Erkennung (OverrideManager).

Hintergrund — der Fall vom 31.07.2026, `switch.proxon_fwt_kuhlung`:

    21:21:29  Wattson schaltet die Kühlung ein (Record: on, prev=off)
    23:05:57  Christian schaltet von Hand aus
    23:06:41  Wattson schaltet 44 s später wieder ein

Wattson hat den Eingriff nie als Override gewertet. Grund: `confirmed` wurde
ausschließlich in `async_check_action` gesetzt, und die lief nur aus `_try_act`
— also nur, wenn Wattson etwas ändern wollte. Solange Ist == Ziel war, wurde der
Record nie bestätigt, und das Hand-Aus fiel damit dauerhaft in den
`failed_write`-Zweig (Ist == prev_value bei `confirmed=False`) → Retry statt
Override.

Drei Gegenmaßnahmen, hier abgesichert:
  1. `async_observe` bestätigt Records im Tick, auch ohne Aktion
  2. `user_touch_at` (State-Context mit user_id) schlägt die Wert-Heuristik
  3. `failed_write` gilt nur noch innerhalb FAILED_WRITE_GRACE
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from conftest import override as override_mod

OverrideManager = override_mod.OverrideManager
UCDefinition = override_mod.UCDefinition

BERLIN = timezone(timedelta(hours=2))
COOL = "switch.proxon_fwt_kuhlung"
UCS = [UCDefinition("uc12", "Kühlung"), UCDefinition("uc4b", "Warmwasser Heizstab")]


def run(coro):
    """Coroutine synchron ausführen — spart die pytest-asyncio-Abhängigkeit."""
    return asyncio.run(coro)


class FakeHass:
    """Nur was der OverrideManager anfasst: config.path + Executor."""

    def __init__(self, tmp_path):
        self.config = SimpleNamespace(path=lambda name: str(tmp_path / name))

    async def async_add_executor_job(self, func, *args):
        return func(*args)


@pytest.fixture
def clock(monkeypatch):
    """Steuerbare Uhr für dt_util.now() im override-Modul."""

    class Clock:
        def __init__(self) -> None:
            self.now = datetime(2026, 7, 31, 21, 21, 29, tzinfo=BERLIN)

        def advance(self, **kwargs) -> datetime:
            self.now += timedelta(**kwargs)
            return self.now

    c = Clock()
    monkeypatch.setattr(override_mod.dt_util, "now", lambda: c.now)
    return c


@pytest.fixture
def mgr(tmp_path, clock):
    return OverrideManager(FakeHass(tmp_path), UCS)


def set_cooling_on(mgr, uc_id="uc12"):
    """Wattson schaltet die Kühlung ein (vorher war sie aus)."""
    run(mgr.async_record_action(uc_id, COOL, "on", prev_value="off"))


# ── 1. Bestätigung im Tick ──────────────────────────────────────────────────

def test_observe_confirms_action(mgr, clock):
    set_cooling_on(mgr)
    assert mgr.get_last_action(COOL).confirmed is False

    clock.advance(minutes=5)
    assert run(mgr.async_observe(COOL, "on")) is True
    assert mgr.get_last_action(COOL).confirmed is True


def test_observe_ignores_unavailable(mgr, clock):
    """Modbus-Aussetzer darf nicht als Bestätigung durchgehen."""
    set_cooling_on(mgr)
    for value in ("unavailable", "unknown", None, ""):
        assert run(mgr.async_observe(COOL, value)) is False
    assert mgr.get_last_action(COOL).confirmed is False


def test_observe_does_not_confirm_wrong_value(mgr, clock):
    set_cooling_on(mgr)
    assert run(mgr.async_observe(COOL, "off")) is False
    assert mgr.get_last_action(COOL).confirmed is False


def test_tracked_entities_lists_open_records(mgr):
    set_cooling_on(mgr)
    assert mgr.tracked_entities() == [COOL]
    run(mgr.async_drop_action(COOL))
    assert mgr.tracked_entities() == []


# ── 2. Der Fall vom 31.07.2026 ──────────────────────────────────────────────

def test_manual_off_after_confirmation_is_override(mgr, clock):
    """Kernfall: bestätigter Write, danach Hand-Aus → Override, kein Retry."""
    set_cooling_on(mgr)                       # 21:21:29
    clock.advance(minutes=5)
    run(mgr.async_observe(COOL, "on"))        # Tick bestätigt den Write

    clock.advance(hours=1, minutes=39)        # 23:05:57 Hand-Aus
    verdict = run(mgr.async_check_action(COOL, "off", uc_id="uc12"))

    assert verdict == "override"


def test_full_timeline_locks_wattson_out(mgr, clock):
    """Ende-zu-Ende: Hand-Aus sperrt UC12, Status zeigt user-override."""
    set_cooling_on(mgr)
    clock.advance(minutes=5)
    run(mgr.async_observe(COOL, "on"))
    clock.advance(hours=1, minutes=39)

    assert run(mgr.async_check_action(COOL, "off", uc_id="uc12")) == "override"
    run(mgr.async_record_override("uc12", COOL, "off"))

    assert mgr.in_cooldown("uc12") is True
    assert mgr.status_for("uc12")["state"] == "user-override"
    # Cooldown mindestens 2 h, auch wenn Mitternacht näher liegt
    assert mgr.cooldown_remaining_minutes("uc12") >= 120


# ── 3. Fehlgeschlagener Write bleibt ein Retry-Fall ─────────────────────────

def test_failed_write_within_grace_is_retry(mgr, clock):
    """Regression 2026-07-06: Modbus-Glitch darf kein Phantom-Override werden."""
    set_cooling_on(mgr)
    clock.advance(minutes=5)                  # ein Tick, Wert kam nicht an

    verdict = run(mgr.async_check_action(COOL, "off", uc_id="uc12"))

    assert verdict == "failed_write"


def test_unconfirmed_after_grace_is_override(mgr, clock):
    """Nach zwei Ticks hätte observe bestätigt — dann war es doch der User."""
    set_cooling_on(mgr)
    clock.advance(seconds=override_mod.FAILED_WRITE_GRACE.total_seconds() + 1)

    assert run(mgr.async_check_action(COOL, "off", uc_id="uc12")) == "override"


def test_unavailable_entity_defers_decision(mgr, clock):
    set_cooling_on(mgr)
    clock.advance(minutes=30)
    assert run(mgr.async_check_action(COOL, "unavailable", uc_id="uc12")) == "ok"


def test_matching_value_confirms_and_returns_ok(mgr, clock):
    set_cooling_on(mgr)
    clock.advance(minutes=5)
    assert run(mgr.async_check_action(COOL, "on", uc_id="uc12")) == "ok"
    assert mgr.get_last_action(COOL).confirmed is True


# ── 4. Hand-Eingriff per State-Context (user_id) ────────────────────────────

def test_user_touch_beats_failed_write_heuristic(mgr, clock):
    """Aus-Klick im selben Tick: ohne user_id nicht unterscheidbar, mit schon."""
    set_cooling_on(mgr)
    touched = clock.advance(minutes=1)        # User klickt vor dem ersten Tick
    clock.advance(minutes=4)

    assert run(mgr.async_check_action(COOL, "off", uc_id="uc12")) == "failed_write"
    assert run(mgr.async_check_action(
        COOL, "off", user_touch_at=touched, uc_id="uc12",
    )) == "override"


def test_user_touch_without_record_is_override(mgr, clock):
    """Kein Record (Neustart / UC war aus) — Hand-Eingriff zählt trotzdem."""
    touched = clock.now - timedelta(hours=1)

    assert run(mgr.async_check_action(
        COOL, "on", user_touch_at=touched, uc_id="uc12",
    )) == "override"


def test_stale_user_touch_without_record_ignored(mgr, clock):
    """Klick von vorgestern darf Wattson nicht dauerhaft aussperren."""
    touched = clock.now - override_mod.USER_TOUCH_TTL - timedelta(minutes=1)

    assert run(mgr.async_check_action(
        COOL, "on", user_touch_at=touched, uc_id="uc12",
    )) == "ok"


def test_user_touch_before_wattson_write_is_stale(mgr, clock):
    """Wattson hat nach dem Klick geschrieben → der Klick ist abgegolten."""
    touched = clock.now - timedelta(minutes=10)
    set_cooling_on(mgr)
    clock.advance(minutes=5)

    assert run(mgr.async_check_action(
        COOL, "off", user_touch_at=touched, uc_id="uc12",
    )) == "failed_write"


def test_wattson_own_write_carries_no_user_touch(mgr, clock):
    """Ohne user_id (= Service-Call einer Integration) greift nur die Heuristik."""
    set_cooling_on(mgr)
    clock.advance(minutes=5)
    run(mgr.async_observe(COOL, "on"))

    assert run(mgr.async_check_action(COOL, "on", user_touch_at=None, uc_id="uc12")) == "ok"


# ── 5. „Übernimm wieder": UC-Switch an + Resume ────────────────────────────

def test_enabling_uc_disarms_earlier_touch(mgr, clock):
    """UC12 wieder eingeschaltet → alter Hand-Eingriff blockiert nicht."""
    touched = clock.now - timedelta(hours=5)
    run(mgr.async_set_enabled("uc12", False))
    clock.advance(hours=5)
    run(mgr.async_set_enabled("uc12", True))

    assert run(mgr.async_check_action(
        COOL, "on", user_touch_at=touched, uc_id="uc12",
    )) == "ok"


def test_touch_after_enabling_still_counts(mgr, clock):
    run(mgr.async_set_enabled("uc12", True))
    touched = clock.advance(minutes=10)

    assert run(mgr.async_check_action(
        COOL, "on", user_touch_at=touched, uc_id="uc12",
    )) == "override"


def test_resume_disarms_the_triggering_touch(mgr, clock):
    """Resume muss wirken — sonst löst derselbe State-Context sofort neu aus."""
    set_cooling_on(mgr)
    clock.advance(minutes=5)
    run(mgr.async_observe(COOL, "on"))
    touched = clock.advance(minutes=30)
    run(mgr.async_record_override("uc12", COOL, "off"))
    assert mgr.in_cooldown("uc12") is True

    clock.advance(minutes=1)
    run(mgr.async_resume("uc12"))

    assert mgr.in_cooldown("uc12") is False
    assert run(mgr.async_check_action(
        COOL, "off", user_touch_at=touched, uc_id="uc12",
    )) == "ok"


def test_armed_at_is_per_uc(mgr, clock):
    """Ein Resume auf uc4b entschärft keinen Eingriff an uc12."""
    run(mgr.async_set_enabled("uc4b", True))
    touched = clock.now - timedelta(minutes=30)

    assert run(mgr.async_check_action(
        COOL, "on", user_touch_at=touched, uc_id="uc12",
    )) == "override"


# ── 6. Persistenz ───────────────────────────────────────────────────────────

def test_armed_at_survives_restart(tmp_path, clock):
    hass = FakeHass(tmp_path)
    mgr = OverrideManager(hass, UCS)
    run(mgr.async_set_enabled("uc12", True))
    touched = clock.now - timedelta(minutes=30)

    reloaded = OverrideManager(hass, UCS)
    run(reloaded.async_load())

    assert run(reloaded.async_check_action(
        COOL, "on", user_touch_at=touched, uc_id="uc12",
    )) == "ok"


def test_confirmed_flag_survives_restart(tmp_path, clock):
    hass = FakeHass(tmp_path)
    mgr = OverrideManager(hass, UCS)
    run(mgr.async_record_action("uc12", COOL, "on", prev_value="off"))
    clock.advance(minutes=5)
    run(mgr.async_observe(COOL, "on"))

    reloaded = OverrideManager(hass, UCS)
    run(reloaded.async_load())

    assert reloaded.get_last_action(COOL).confirmed is True
    assert run(reloaded.async_check_action(COOL, "off", uc_id="uc12")) == "override"


def test_legacy_record_without_confirmed_stays_trusted(tmp_path, clock):
    """Records aus v0.18.6 und früher haben kein confirmed-Feld → True annehmen."""
    hass = FakeHass(tmp_path)
    state = tmp_path / override_mod.STATE_FILE_NAME
    state.write_text(
        '{"actions": {"' + COOL + '": {"value": "on", "set_at": "'
        + clock.now.isoformat() + '", "uc_id": "uc12"}}}',
        encoding="utf-8",
    )

    mgr = OverrideManager(hass, UCS)
    run(mgr.async_load())

    assert mgr.get_last_action(COOL).confirmed is True
    assert run(mgr.async_check_action(COOL, "off", uc_id="uc12")) == "override"
