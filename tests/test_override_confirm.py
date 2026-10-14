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

Gegenmaßnahmen damals: `async_observe` bestätigte Records im Tick,
`user_touch_at` (State-Context mit user_id) schlug die Wert-Heuristik, und
`failed_write` galt nur innerhalb einer Grace-Zeit.

Seit v0.20.22 gibt es weder `async_observe` noch `failed_write`: jeder Record
wird erst angelegt, wenn der Zielwert beim Schreiben zurückgelesen wurde
(`schreiben.py`), ist also von Anfang an bestätigt. Unbestätigte Records
älterer Versionen verwirft `async_load`.
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


# ── 1. Records sind beim Anlegen bestätigt ─────────────────────────────────

def test_record_ist_sofort_bestaetigt(mgr, clock):
    set_cooling_on(mgr)
    assert mgr.get_last_action(COOL).confirmed is True


def test_keine_beobachter_logik_mehr():
    """`async_observe`/`tracked_entities`/`FAILED_WRITE_GRACE` sind weg."""
    for name in ("async_observe", "tracked_entities"):
        assert not hasattr(OverrideManager, name), name
    assert not hasattr(override_mod, "FAILED_WRITE_GRACE")


# ── 2. Der Fall vom 31.07.2026 ──────────────────────────────────────────────

def test_manual_off_after_confirmation_is_override(mgr, clock):
    """Kernfall: bestätigter Write, danach Hand-Aus → Override, kein Retry."""
    set_cooling_on(mgr)                       # 21:21:29, bestätigt geschrieben
    clock.advance(minutes=5)

    clock.advance(hours=1, minutes=39)        # 23:05:57 Hand-Aus
    verdict = run(mgr.async_check_action(COOL, "off", uc_id="uc12"))

    assert verdict == "override"


def test_full_timeline_locks_wattson_out(mgr, clock):
    """Ende-zu-Ende: Hand-Aus sperrt UC12, Status zeigt user-override."""
    set_cooling_on(mgr)
    clock.advance(hours=1, minutes=44)

    assert run(mgr.async_check_action(COOL, "off", uc_id="uc12")) == "override"
    run(mgr.async_record_override("uc12", COOL, "off"))

    assert mgr.in_cooldown("uc12") is True
    assert mgr.status_for("uc12")["state"] == "user-override"
    # Cooldown mindestens 2 h, auch wenn Mitternacht näher liegt
    assert mgr.cooldown_remaining_minutes("uc12") >= 120


# ── 3. Verlorener Write: gar nicht gebucht, also nie ein Override ───────────

def test_verlorener_write_ohne_record_ist_kein_override(mgr, clock):
    """Regression 06.07. und 08.10.2026: `_try_act` bucht nur Angekommenes.
    Kam der Write nicht an, gibt es keinen Record — und ohne user_id kein
    Override, egal wie lange es her ist."""
    clock.advance(minutes=25)
    assert run(mgr.async_check_action(COOL, "off", uc_id="uc12")) == "ok"


def test_unavailable_entity_defers_decision(mgr, clock):
    set_cooling_on(mgr)
    clock.advance(minutes=30)
    assert run(mgr.async_check_action(COOL, "unavailable", uc_id="uc12")) == "ok"


def test_matching_value_returns_ok(mgr, clock):
    set_cooling_on(mgr)
    clock.advance(minutes=5)
    assert run(mgr.async_check_action(COOL, "on", uc_id="uc12")) == "ok"


# ── 4. Hand-Eingriff per State-Context (user_id) ────────────────────────────

def test_abweichung_vom_bestaetigten_write_ist_override(mgr, clock):
    """Aus-Klick kurz nach dem Write: mit und ohne user_id ein Eingriff —
    der Write war ja nachweislich angekommen."""
    set_cooling_on(mgr)
    touched = clock.advance(minutes=1)
    clock.advance(minutes=4)

    assert run(mgr.async_check_action(COOL, "off", uc_id="uc12")) == "override"
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
        COOL, "on", user_touch_at=touched, uc_id="uc12",
    )) == "ok"


def test_wattson_own_write_carries_no_user_touch(mgr, clock):
    """Ohne user_id (= Service-Call einer Integration) greift nur die Heuristik."""
    set_cooling_on(mgr)
    clock.advance(minutes=5)

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


def test_unbestaetigter_record_aus_alter_version_wird_verworfen(tmp_path, clock):
    """v0.20.22: Records mit `confirmed: false` stammen von vor v0.20.16 — ihr
    Write kam vielleicht nie an. Ohne den `failed_write`-Zweig wären sie eine
    Phantom-Override-Quelle; verworfen gilt nur noch ein echter Eingriff."""
    hass = FakeHass(tmp_path)
    state = tmp_path / override_mod.STATE_FILE_NAME
    state.write_text(
        '{"actions": {"' + COOL + '": {"value": "on", "set_at": "'
        + clock.now.isoformat() + '", "uc_id": "uc12", "prev_value": "off",'
        ' "confirmed": false}}}',
        encoding="utf-8",
    )

    mgr = OverrideManager(hass, UCS)
    run(mgr.async_load())

    assert mgr.get_last_action(COOL) is None
    assert run(mgr.async_check_action(COOL, "off", uc_id="uc12")) == "ok"
