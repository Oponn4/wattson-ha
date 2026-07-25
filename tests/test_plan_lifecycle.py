"""Tests zum Fahrplan-Lebenszyklus (UC2: verschwundene Termine erkennen).

Die Wiedererkennung läuft über die uid — bzw. über denselben Fallback, den
UC2 beim Setzen benutzt, wenn der Kalender keine uid liefert. Beide Seiten
müssen denselben Schlüssel bilden, sonst wird entweder nie aufgeräumt oder
ein gültiger Plan gelöscht.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from conftest import forecast

BERLIN = timezone(timedelta(hours=2))
NOW = datetime(2026, 7, 25, 16, 0, tzinfo=BERLIN)


event_key = forecast.event_key


def event_uid(ev: dict) -> str:
    """Schlüssel wie in _cleanup_stale_trip_plan (Rohdaten-Seite)."""
    return event_key(ev, BERLIN)


def candidate_uid(ev: dict, start_dt: datetime) -> str:
    """Schlüssel wie in _evaluate_trip_candidates (Kandidaten-Seite).

    Beide Seiten rufen bewusst dieselbe Funktion — genau hier lagen die
    Schlüssel vorher auseinander.
    """
    return event_key(ev, BERLIN)


MIT_UID = {
    "start": "2026-07-26T12:00:00+02:00",
    "summary": "Wolfgangs Geburtstag",
    "location": "Kuralpe 2, 64686 Lautertal",
    "uid": "806C931A-8CDD-4BE4-980B-F3FD9ADC8854",
}
OHNE_UID = {
    "start": "2026-07-26T12:00:00+02:00",
    "summary": "Wolfgangs Geburtstag",
    "location": "Kuralpe 2, 64686 Lautertal",
}


class TestUidWiedererkennung:
    def test_echte_uid_wird_durchgereicht(self):
        assert event_uid(MIT_UID) == MIT_UID["uid"]

    def test_uid_stabil_ueber_ticks(self):
        """Gleiches Event zweimal gelesen → gleicher Schlüssel."""
        assert event_uid(dict(MIT_UID)) == event_uid(dict(MIT_UID))

    def test_fallback_beide_seiten_identisch(self):
        """Ohne uid müssen Roh- und Kandidatenseite denselben Key bilden.

        Sonst würde der Plan jeden Tick als „Termin weg" gelesen und gelöscht.
        """
        [ev] = forecast.relevant_events([OHNE_UID], NOW, ())
        assert candidate_uid(OHNE_UID, ev["_start_dt"]) == event_uid(OHNE_UID)

    def test_verschobener_termin_gilt_als_neu(self):
        """Ohne uid ist die Startzeit Teil des Keys → Verschiebung = neuer Plan."""
        verschoben = {**OHNE_UID, "start": "2026-07-26T14:00:00+02:00"}
        assert event_uid(verschoben) != event_uid(OHNE_UID)

    def test_uid_ueberlebt_verschiebung(self):
        """Mit uid bleibt es derselbe Termin, auch verschoben."""
        verschoben = {**MIT_UID, "start": "2026-07-26T14:00:00+02:00"}
        assert event_uid(verschoben) == event_uid(MIT_UID)

    def test_ganztags_ohne_uid_bleibt_konsistent(self):
        """Regression: Rohdaten "2026-07-26" vs. Kandidat "…T08:00:00+02:00".

        Vorher liefen die Schlüssel auseinander → der Fahrplan wäre in JEDEM
        Tick als „Termin verschwunden" gelesen und gelöscht worden.
        """
        ganztags = {"start": "2026-07-26", "summary": "Geburtstag",
                    "location": "Kuralpe 2"}
        [cand] = forecast.relevant_events([ganztags], NOW, ())
        assert candidate_uid(ganztags, cand["_start_dt"]) == event_uid(ganztags)
        # …und der Schlüssel trägt die normalisierte, tz-bewusste Zeit
        assert event_uid(ganztags).startswith("2026-07-26T08:00:00")


class TestVerschwundenErkennung:
    def _weg(self, gespeicherte_uid: str, events: list[dict]) -> bool:
        return not any(event_uid(ev) == gespeicherte_uid for ev in events)

    def test_termin_noch_da(self):
        assert self._weg(MIT_UID["uid"], [MIT_UID]) is False

    def test_termin_abgesagt(self):
        assert self._weg(MIT_UID["uid"], []) is True

    def test_anderer_termin_zaehlt_nicht(self):
        tennis = {"start": "2026-07-25T18:00:00+02:00", "summary": "Tennis",
                  "location": "Diez", "uid": "tennis-1"}
        assert self._weg(MIT_UID["uid"], [tennis]) is True

    def test_termin_ohne_ort_zaehlt_weiter_als_vorhanden(self):
        """Ort nachträglich gelöscht: Termin existiert noch, Plan bleibt.

        Rohdaten werden absichtlich ungefiltert geprüft — ein fehlender Ort
        oder ein gmaps-Ausfall darf keinen gültigen Plan wegräumen.
        """
        ohne_ort = {k: v for k, v in MIT_UID.items() if k != "location"}
        assert self._weg(MIT_UID["uid"], [ohne_ort]) is False
