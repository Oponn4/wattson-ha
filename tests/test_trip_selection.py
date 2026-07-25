"""Tests für die Trip-Auswahl (UC2 Event-Masking, Vorfall 2026-07-25)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import ClassVar

from conftest import forecast

TripCandidate = forecast.TripCandidate
select_binding_trip = forecast.select_binding_trip
calculate_required_soc = forecast.calculate_required_soc

BERLIN = timezone(timedelta(hours=2))


def trip(title: str, start: datetime, distance_km: float, required_soc: int) -> TripCandidate:
    return TripCandidate(
        title=title, location=f"{title}-Ort", calendar="calendar.barchen",
        start=start, distance_km=distance_km, required_soc=required_soc,
        uid=f"uid-{title}",
    )


# Der echte Fall: kleine Fahrt heute Abend, große Fahrt am Folgetag
TENNIS = trip("Tennis", datetime(2026, 7, 25, 18, 0, tzinfo=BERLIN), 6.6, 30)
GEBURTSTAG = trip("Wolfgangs Geburtstag", datetime(2026, 7, 26, 12, 0, tzinfo=BERLIN), 100.6, 90)


class TestMaskingRegression:
    def test_kleine_fahrt_maskiert_grosse_nicht(self):
        """Kern des Vorfalls: SOC 53% deckt Tennis, nicht aber die 100-km-Fahrt."""
        got = select_binding_trip([TENNIS, GEBURTSTAG], car_soc=53.0)
        assert got is not None
        assert got.required_soc == 90
        assert got.deadline_trip.title == "Wolfgangs Geburtstag"

    def test_alte_logik_haette_abgebrochen(self):
        """Gegenprobe: Tennis allein betrachtet ist gedeckt → kein Plan."""
        assert TENNIS.satisfied_by(53.0) is True
        assert select_binding_trip([TENNIS], car_soc=53.0) is None


class TestSelectBindingTrip:
    def test_alles_gedeckt_gibt_none(self):
        assert select_binding_trip([TENNIS, GEBURTSTAG], car_soc=95.0) is None

    def test_leere_liste_gibt_none(self):
        assert select_binding_trip([], car_soc=50.0) is None

    def test_deadline_von_frueher_fahrt_ziel_von_spaeterer(self):
        """Beide ungedeckt: früheste Abfahrt gibt Zeit, größter Bedarf gibt Ziel."""
        frueh = trip("Frueh", datetime(2026, 7, 26, 8, 0, tzinfo=BERLIN), 60.0, 60)
        spaet = trip("Spaet", datetime(2026, 7, 26, 20, 0, tzinfo=BERLIN), 110.0, 95)
        got = select_binding_trip([frueh, spaet], car_soc=50.0)
        assert got is not None
        assert got.deadline_trip.title == "Frueh"      # Zeitvorgabe
        assert got.soc_driver.title == "Spaet"         # Zielvorgabe
        assert got.required_soc == 95

    def test_gedeckte_fahrt_gibt_keine_deadline(self):
        """Eine gedeckte frühe Fahrt darf die Deadline nicht nach vorn ziehen."""
        got = select_binding_trip([TENNIS, GEBURTSTAG], car_soc=53.0)
        assert got is not None
        assert got.deadline_trip.title == "Wolfgangs Geburtstag"

    def test_reihenfolge_der_eingabe_irrelevant(self):
        vorwaerts = select_binding_trip([TENNIS, GEBURTSTAG], car_soc=53.0)
        rueckwaerts = select_binding_trip([GEBURTSTAG, TENNIS], car_soc=53.0)
        assert vorwaerts == rueckwaerts

    def test_soc_exakt_auf_bedarf_ist_gedeckt(self):
        assert select_binding_trip([GEBURTSTAG], car_soc=90.0) is None
        got = select_binding_trip([GEBURTSTAG], car_soc=89.9)
        assert got is not None and got.required_soc == 90


class TestVollerPfadAbRohdaten:
    """Rohe calendar.get_events-Response → Kandidaten → Auswahl.

    Deckt die Kette ab, die am 25.07. versagt hat. Distanzen sind die live
    von gmaps gelieferten Werte (Geocoding selbst ist hier nicht Gegenstand).
    """

    RAW: ClassVar[list[dict]] = [
        {
            "start": "2026-07-25T18:00:00+02:00",
            "end": "2026-07-25T19:30:00+02:00",
            "summary": "Tennis",
            "location": "ESV Blau-Weiß Limburg e.V.\nStephanshügel 26\n65549 Diez\nDeutschland",
            "_calendar": "calendar.barchen",
        },
        {
            "start": "2026-07-26T12:00:00+02:00",
            "end": "2026-07-26T15:00:00+02:00",
            "summary": "Wolfgangs Geburtstag",
            "location": "Kuralpe Kreuzhof\nKuralpe 2\n64686 Lautertal (Odenwald)\nDeutschland",
            "_calendar": "calendar.barchen",
        },
        # ganztags ohne Ort — muss rausfallen, ohne etwas zu reißen
        {"start": "2026-06-29", "end": "2026-08-08", "summary": "Sommerferien"},
        # Teams-Termin — kein Fahrbedarf
        {
            "start": "2026-07-25T17:00:00+02:00",
            "end": "2026-07-25T18:00:00+02:00",
            "summary": "Go-Live b7",
            "location": "Microsoft Teams-Besprechung",
        },
    ]
    DISTANCES: ClassVar[dict[str, float]] = {"Tennis": 6.557, "Wolfgangs Geburtstag": 100.6}

    def _candidates(self, now: datetime) -> list[TripCandidate]:
        from conftest import const

        out = []
        for ev in forecast.relevant_events(self.RAW, now, const.SKIP_LOCATION_KEYWORDS):
            km = self.DISTANCES[ev["summary"]]
            out.append(TripCandidate(
                title=ev["summary"], location=ev["location"],
                calendar=ev.get("_calendar", ""), start=ev["_start_dt"],
                distance_km=km,
                required_soc=calculate_required_soc(km, 20, 63, 26),
                uid=ev.get("uid") or f"{ev['_start_dt'].isoformat()}:{ev['summary']}",
            ))
        return out

    def test_ferien_und_teams_fallen_raus(self):
        got = self._candidates(datetime(2026, 7, 25, 16, 0, tzinfo=BERLIN))
        assert [c.title for c in got] == ["Tennis", "Wolfgangs Geburtstag"]

    def test_um_16_uhr_bindet_geburtstag_auf_90(self):
        """Genau die Situation von 15:18: hätte den Plan setzen müssen."""
        cands = self._candidates(datetime(2026, 7, 25, 16, 0, tzinfo=BERLIN))
        got = select_binding_trip(cands, car_soc=53.0)
        assert got is not None
        assert got.deadline_trip.title == "Wolfgangs Geburtstag"
        assert got.required_soc == 90
        assert got.deadline_trip.start == datetime(2026, 7, 26, 12, 0, tzinfo=BERLIN)

    def test_nach_dem_laden_kein_plan_mehr_nötig(self):
        cands = self._candidates(datetime(2026, 7, 25, 16, 0, tzinfo=BERLIN))
        assert select_binding_trip(cands, car_soc=90.0) is None


class TestRequiredSocRechnung:
    def test_kuralpe_ergibt_90_prozent(self):
        """Live gegen gmaps geprüft: 100,6 km, ORA 03 (20 kWh/100km, 63 kWh, 26%)."""
        assert calculate_required_soc(100.6, 20, 63, 26) == 90

    def test_tennis_ergibt_30_prozent(self):
        assert calculate_required_soc(6.557, 20, 63, 26) == 30

    def test_deckelt_auf_100(self):
        assert calculate_required_soc(500, 20, 63, 26) == 100
