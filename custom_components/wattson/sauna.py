"""Sauna-Plan: wann die Sauna Last zieht, damit EMHASS sie einplanen kann.

Warum es das gibt (v0.20.26): EMHASS kannte die Sauna nicht. Seine
Lastprognose (`typical`) rechnete am 25.10.2026 für 17–20 Uhr mit 0,3–0,8 kW,
die Sauna zieht 9 kW beim Aufheizen und im Mittel 3,6 kW danach. UC10 folgt
dem EMHASS-Plan, also hielt der Akku Strom für später zurück, während die
Sauna zum Tagesspitzenpreis aus dem Netz lief. Mit der Sauna als festem
Verbraucher entscheidet EMHASS selbst, ob der Akku jetzt in die Sauna geht
oder für später bleibt.

Zwei Quellen, in dieser Reihenfolge:

1. **Kalender.** Ein Termin mit „Sauna" im Titel. Sein Beginn ist die Zeit,
   ab der man drin sitzen will — aufgeheizt wird davor (`aufheiz_min`).
2. **Selbst erkennen.** Läuft die Sauna (`input_select.sauna_status` ist
   `vorheizen` oder `warm`) ohne passenden Termin, gilt ein Standardfenster ab
   dem Einschalten. Es verlängert sich, solange die Sauna an ist.

Ein Termin, zu dem die Sauna nicht eingeschaltet wurde, verfällt kurz nach
seinem Beginn: dann findet sie offensichtlich nicht statt.

Messwerte (vier Abende 3.–18.10.2026, `sensor.sauna_power`): Volllast
9,07 kW für 27–36 min bis zur Solltemperatur, danach taktet der Ofen bei
etwa 45 %, im Mittel 3,6 kW. Ein Abend zieht 8,8–11,1 kWh.

Bewusst frei von Home-Assistant-Importen, damit ohne HA testbar.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, tzinfo

STATUS_LAEUFT = ("vorheizen", "warm")


@dataclass(frozen=True)
class SaunaProfil:
    """Gemessenes Lastprofil und Fenster-Regeln (Werte in const.py)."""

    aufheiz_kw: float          # Volllast beim Aufheizen
    halten_kw: float           # Mittel nach dem Aufheizen, mit Leuten drin
    aufheiz_dauer_min: int     # so lange zieht der Ofen Volllast
    aufheiz_vorlauf_min: int   # so früh vor Termin-Beginn einschalten (mit Puffer)
    nutz_min: int              # Standarddauer drin, wenn kein Termin sie nennt
    nachlauf_min: int          # läuft sie noch, reicht der Plan mindestens so weit
    verfall_min: int           # Termin ohne Einschalten verfällt so lange nach Beginn
    stichwort: str             # im Termintitel, Groß-/Kleinschreibung egal


@dataclass(frozen=True)
class SaunaTermin:
    start: datetime    # ab hier sitzt man drin
    ende: datetime
    titel: str


@dataclass(frozen=True)
class SaunaPlan:
    start: datetime          # ab hier zieht die Sauna Last (Ofen an)
    ende: datetime
    quelle: str              # "kalender" | "erkannt"
    titel: str
    energie_kwh: float       # noch zu erwartende Energie ab `now`
    grund: str

    def leistung_w(self, now: datetime) -> int:
        """Mittlere Leistung über den Rest des Fensters (für EMHASS konstant)."""
        rest_h = (self.ende - max(self.start, now)).total_seconds() / 3600
        if rest_h <= 0:
            return 0
        return round(self.energie_kwh * 1000 / rest_h)


def ist_sauna_termin(ev: dict, stichwort: str) -> bool:
    return stichwort.casefold() in str(ev.get("summary") or "").casefold()


def _zeitpunkt(raw: object, tz: tzinfo | None) -> datetime | None:
    """Nur getimte Termine. Ganztags-Termine („2026-10-25") nennen keine Uhrzeit."""
    if not isinstance(raw, str) or "T" not in raw:
        return None
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=tz)


def sauna_termine(
    events: list[dict], stichwort: str, tz: tzinfo | None
) -> list[SaunaTermin]:
    """Sauna-Termine aus einer `calendar.get_events`-Antwort, nach Beginn sortiert."""
    termine: list[SaunaTermin] = []
    for ev in events:
        if not ist_sauna_termin(ev, stichwort):
            continue
        start = _zeitpunkt(ev.get("start"), tz)
        ende = _zeitpunkt(ev.get("end"), tz)
        if start is None:
            continue
        if ende is None or ende <= start:
            ende = None
        termine.append(SaunaTermin(
            start=start,
            ende=ende or start,  # wird in sauna_plan durch nutz_min ersetzt
            titel=str(ev.get("summary") or "Sauna"),
        ))
    termine.sort(key=lambda t: t.start)
    return termine


def _energie_kwh(
    von: datetime, bis: datetime, aufheiz_bis: datetime, p: SaunaProfil
) -> float:
    """Energie im Fenster [von, bis): bis `aufheiz_bis` Volllast, danach Halten."""
    if bis <= von:
        return 0.0
    heiz_ende = min(max(aufheiz_bis, von), bis)
    heiz_h = (heiz_ende - von).total_seconds() / 3600
    halt_h = (bis - heiz_ende).total_seconds() / 3600
    return round(heiz_h * p.aufheiz_kw + halt_h * p.halten_kw, 2)


def betriebsbeginn(
    status: str | None, status_seit: datetime | None, p: SaunaProfil
) -> datetime | None:
    """Wann die Sauna eingeschaltet wurde, aus dem Status-Helper.

    `vorheizen` beginnt mit dem Einschalten. `warm` beginnt, wenn das
    Aufheizen fertig ist — das Einschalten liegt dann `aufheiz_dauer_min`
    davor. So überlebt der Beginn einen HA-Neustart ohne eigenen Speicher.
    """
    if status not in STATUS_LAEUFT or status_seit is None:
        return None
    if status == "warm":
        return status_seit - timedelta(minutes=p.aufheiz_dauer_min)
    return status_seit


def sauna_plan(
    *,
    termine: list[SaunaTermin],
    now: datetime,
    status: str | None,
    beginn: datetime | None,
    p: SaunaProfil,
) -> SaunaPlan | None:
    """Das Sauna-Fenster, das EMHASS einplanen soll, oder None.

    termine: Sauna-Termine (siehe `sauna_termine`), beliebige Reihenfolge.
    status:  `input_select.sauna_status` (idle/vorheizen/warm/unknown).
    beginn:  Einschaltzeit laut `betriebsbeginn`, None wenn sie nicht läuft.
    """
    vorlauf = timedelta(minutes=p.aufheiz_vorlauf_min)
    aufheiz = timedelta(minutes=p.aufheiz_dauer_min)
    nutz = timedelta(minutes=p.nutz_min)
    nachlauf = timedelta(minutes=p.nachlauf_min)
    verfall = timedelta(minutes=p.verfall_min)
    laeuft = status in STATUS_LAEUFT

    def termin_ende(t: SaunaTermin) -> datetime:
        return t.ende if t.ende > t.start else t.start + nutz

    offen = sorted(
        (t for t in termine if termin_ende(t) > now),
        key=lambda t: t.start,
    )

    if laeuft:
        b = beginn or now
        # Termin passt zum laufenden Betrieb: eingeschaltet frühestens eine
        # Stunde vor dem geplanten Einschalten, und der Termin ist nicht vorbei.
        passend = next(
            (t for t in offen if t.start - vorlauf - timedelta(hours=1) <= b),
            None,
        )
        if passend is not None:
            start = min(b, passend.start - vorlauf)
            ende = max(termin_ende(passend), now + nachlauf)
            quelle, titel = "kalender", passend.titel
            grund = f"läuft, Termin „{passend.titel}“"
        else:
            start = b
            ende = max(b + aufheiz + nutz, now + nachlauf)
            quelle, titel = "erkannt", "Sauna (ohne Termin)"
            grund = "läuft ohne Termin — selbst erkannt"
        aufheiz_bis = (b + aufheiz) if status == "vorheizen" else now
        return SaunaPlan(
            start=start, ende=ende, quelle=quelle, titel=titel,
            energie_kwh=_energie_kwh(max(start, now), ende, aufheiz_bis, p),
            grund=grund,
        )

    for t in offen:
        if now > t.start + verfall:
            # Termin hat begonnen, Sauna ist aus: findet nicht statt.
            continue
        start = t.start - vorlauf
        ende = termin_ende(t)
        aufheiz_bis = max(start, now) + aufheiz
        return SaunaPlan(
            start=start, ende=ende, quelle="kalender", titel=t.titel,
            energie_kwh=_energie_kwh(max(start, now), ende, aufheiz_bis, p),
            grund=f"Termin „{t.titel}“, einschalten {start:%H:%M}",
        )
    return None
