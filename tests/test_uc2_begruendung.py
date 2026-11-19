"""UC2: Begründung landet auch auf der UC-Kachel (v0.20.33).

Die Kachel „E-Auto Fahrplan" im Wattson-Dashboard liest das Attribut
`begruendung` von `sensor.wattson_eauto_fahrplan`, gespeist aus
`uc_reason["uc2"]`. Der normale UC2-Weg schrieb seinen Satz nur nach
`trip_reason` (Sensor „Nächste Fahrt"). Am 19.11.2026 stand ein 85-%-Plan
für die Fahrt nach Bad Vilbel, die Kachel zeigte nur „aktiv".
"""
from __future__ import annotations

from pathlib import Path

WURZEL = Path(__file__).resolve().parents[1] / "custom_components" / "wattson"
COORDINATOR = (WURZEL / "coordinator.py").read_text(encoding="utf-8")
SENSOR = (WURZEL / "sensor.py").read_text(encoding="utf-8")


def _funktion(quelle: str, name: str) -> str:
    return quelle.split(f"async def {name}(")[1].split("\n    async def ")[0]


def test_erfolgreicher_lauf_uebernimmt_trip_reason():
    body = _funktion(COORDINATOR, "_run_trip_planning")
    try_teil = body.split("except Exception", 1)[0]
    assert "await self._handle_trip_planning(" in try_teil
    nach_aufruf = try_teil.split("await self._handle_trip_planning(", 1)[1]
    assert 's.uc_reason["uc2"] = s.trip_reason' in nach_aufruf


def test_fehlerweg_setzt_weiter_beides():
    body = _funktion(COORDINATOR, "_run_trip_planning")
    except_teil = body.split("except Exception", 1)[1]
    assert 's.trip_reason = f"Fehler: {ex}"' in except_teil
    assert 's.uc_reason["uc2"] = s.trip_reason' in except_teil


def test_kachel_liest_uc_reason():
    """Gegenprobe zur Annahme oben: der Status-Sensor zeigt `uc_reason`."""
    assert 'attrs = {"begruendung": d.uc_reason.get(self._uc_id, "")}' in SENSOR
