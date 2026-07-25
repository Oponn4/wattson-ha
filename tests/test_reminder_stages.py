"""Tests für die Eskalationsstufen des Plug-in-Reminders."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from conftest import forecast

reminder_stage_due_times = forecast.reminder_stage_due_times
current_reminder_stage = forecast.current_reminder_stage

BERLIN = timezone(timedelta(hours=2))
QUIET_START, QUIET_END = 22, 7

STAGE1_LEAD, STAGE2_LEAD, STAGE3_BUFFER = 90, 20, 30


def due(price_deadline, latest_feasible):
    return reminder_stage_due_times(
        price_deadline, latest_feasible,
        STAGE1_LEAD, STAGE2_LEAD, STAGE3_BUFFER, QUIET_START, QUIET_END,
    )


class TestStageDueTimes:
    def test_tagsuber_normale_vorlaeufe(self):
        deadline = datetime(2026, 7, 25, 18, 0, tzinfo=BERLIN)
        feasible = datetime(2026, 7, 26, 9, 0, tzinfo=BERLIN)
        got = due(deadline, feasible)
        assert got[1] == datetime(2026, 7, 25, 16, 30, tzinfo=BERLIN)
        assert got[2] == datetime(2026, 7, 25, 17, 40, tzinfo=BERLIN)
        assert got[3] == datetime(2026, 7, 26, 8, 30, tzinfo=BERLIN)

    def test_nachtdeadline_wird_auf_vorabend_gezogen(self):
        """Winterfall: Billigfenster nachts → Meldung muss vor 22 Uhr raus."""
        deadline = datetime(2026, 7, 26, 3, 0, tzinfo=BERLIN)
        got = due(deadline, datetime(2026, 7, 26, 5, 0, tzinfo=BERLIN))
        assert got[1] == datetime(2026, 7, 25, 21, 59, tzinfo=BERLIN)
        assert got[2] == datetime(2026, 7, 25, 21, 59, tzinfo=BERLIN)
        assert got[3] == datetime(2026, 7, 25, 21, 59, tzinfo=BERLIN)

    def test_ohne_preis_deadline_nur_stufe3(self):
        """Kein Forecast → Machbarkeits-Notnagel bleibt trotzdem scharf."""
        got = due(None, datetime(2026, 7, 26, 9, 0, tzinfo=BERLIN))
        assert got[1] is None and got[2] is None
        assert got[3] == datetime(2026, 7, 26, 8, 30, tzinfo=BERLIN)

    def test_ohne_alles_keine_faelligkeit(self):
        got = due(None, None)
        assert all(v is None for v in got.values())


class TestCurrentStage:
    DEADLINE = datetime(2026, 7, 25, 18, 0, tzinfo=BERLIN)
    FEASIBLE = datetime(2026, 7, 26, 9, 0, tzinfo=BERLIN)

    def test_vor_allem_stufe_null(self):
        got = current_reminder_stage(
            datetime(2026, 7, 25, 15, 0, tzinfo=BERLIN), due(self.DEADLINE, self.FEASIBLE)
        )
        assert got == 0

    def test_nach_vorwarnung_stufe_eins(self):
        got = current_reminder_stage(
            datetime(2026, 7, 25, 16, 45, tzinfo=BERLIN), due(self.DEADLINE, self.FEASIBLE)
        )
        assert got == 1

    def test_kurz_vor_deadline_stufe_zwei(self):
        got = current_reminder_stage(
            datetime(2026, 7, 25, 17, 45, tzinfo=BERLIN), due(self.DEADLINE, self.FEASIBLE)
        )
        assert got == 2

    def test_an_der_machbarkeitsgrenze_stufe_drei(self):
        got = current_reminder_stage(
            datetime(2026, 7, 26, 8, 45, tzinfo=BERLIN), due(self.DEADLINE, self.FEASIBLE)
        )
        assert got == 3

    def test_nachtruhe_ueberspringt_stufe_eins(self):
        """Beide auf 21:59 gezogen → direkt die dringendere Stufe."""
        deadline = datetime(2026, 7, 26, 3, 0, tzinfo=BERLIN)
        feasible = datetime(2026, 7, 26, 5, 0, tzinfo=BERLIN)
        got = current_reminder_stage(
            datetime(2026, 7, 25, 22, 5, tzinfo=BERLIN), due(deadline, feasible)
        )
        assert got == 3

    def test_stufe_drei_ohne_preisdaten(self):
        got = current_reminder_stage(
            datetime(2026, 7, 26, 8, 45, tzinfo=BERLIN), due(None, self.FEASIBLE)
        )
        assert got == 3

    def test_exakt_auf_faelligkeit_zaehlt(self):
        got = current_reminder_stage(
            datetime(2026, 7, 25, 16, 30, tzinfo=BERLIN), due(self.DEADLINE, self.FEASIBLE)
        )
        assert got == 1
