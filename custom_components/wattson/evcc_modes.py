"""Übersetzung zwischen Wattsons Lade-Vokabular und evccs Mode-API.

evcc PR#32490 (Discussion #3530, "Redesign PV Mode") ersetzt die Modi
`off|pv|minpv|now` durch `off|smart|now` plus einen zweiten Selector
`alwaysCharge` (`off|on|once`). `smart` ist das alte `pv` inklusive Tarif und
Fahrplan; `alwaysCharge=on` schiebt das Netzminimum darunter — also das alte
`minpv`. `once` ist dasselbe, aber nur bis zum Abstecken.

Wattson behält intern das alte Vokabular. Nicht aus Bequemlichkeit: die drei
Level tragen die gesamte UC6-Logik (Rangordnung für Downshift-Confirmation,
Totband am `minpv`-Einstieg, Hysterese-Merker) und deren Begründungen stammen
aus gemessenen Vorfällen. Ein Rename würde nichts davon besser machen, aber
jede dieser Herleitungen unlesbar. Übersetzt wird darum nur an der Grenze zu
evcc — beim Lesen des Ist-Zustands und beim Schreiben des Ziels.

Welches Schema anliegt, entscheidet der Selector selbst: hat er `minpv` in den
Optionen, läuft altes evcc. Kein Versions-Vergleich, keine Konfiguration — die
Integration (ha-evcc ab 2026.8.3) baut den Selector ohnehin passend zum
laufenden evcc auf.
"""
from __future__ import annotations

# Wattson-Modus → (evcc `mode`, evcc `alwaysCharge`). None heißt "nicht
# anfassen": in `off` und `now` ist der Minimum-Schalter wirkungslos, und ein
# überflüssiger Write wäre nur ein weiterer Grund für einen Override-Fehlalarm.
_TO_EVCC: dict[str, tuple[str, str | None]] = {
    "off":   ("off",   None),
    "pv":    ("smart", "off"),
    "minpv": ("smart", "on"),
    "now":   ("now",   None),
}

ALWAYS_CHARGE_OPTIONS = frozenset({"off", "on", "once"})

# Rollen, die `plan_writes` zurückgibt.
ROLE_MODE = "mode"
ROLE_ALWAYS_CHARGE = "alwayscharge"


def is_new_scheme(mode_options: list[str] | None) -> bool:
    """Läuft evcc mit dem neuen Mode-Schema?

    Leere oder fehlende Optionen (Entity unavailable) gelten als altes Schema:
    dann ist evcc ohnehin nicht erreichbar, und die konservative Annahme hält
    die Erkennung an einer positiven Beobachtung fest statt an einer Lücke.
    """
    return bool(mode_options) and "minpv" not in mode_options


def normalize_mode(mode: str | None, always_charge: str | None = None) -> str:
    """evcc-Ist-Zustand → Wattson-Vokabular.

    `once` liest sich als `minpv`, weil es genau das tut. Wattson schreibt es
    nie selbst; steht es von Hand da und will Wattson ebenfalls `minpv`, bleibt
    es unangetastet — der Vergleich passt dann bereits.
    """
    if mode in ("off", "pv", "minpv", "now"):
        return mode
    if mode == "smart":
        return "minpv" if always_charge in ("on", "once") else "pv"
    return "pv"


def plan_writes(target: str, *, new_scheme: bool) -> list[tuple[str, str]]:
    """Wattson-Ziel → Liste von `(Rolle, Option)` in Schreibreihenfolge.

    `alwaysCharge` zuerst: beim Weg von `now` nach `pv` steht der Schalter
    womöglich noch auf `on`. Erst `mode` zu schreiben hieße, für die Dauer
    eines Ticks in `smart`+`on` (= `minpv`) zu landen — genau der Zustand, den
    dieser Wechsel gerade verlassen will.
    """
    if not new_scheme:
        return [(ROLE_MODE, target)]
    mode, always_charge = _TO_EVCC[target]
    writes: list[tuple[str, str]] = []
    if always_charge is not None:
        writes.append((ROLE_ALWAYS_CHARGE, always_charge))
    writes.append((ROLE_MODE, mode))
    return writes
