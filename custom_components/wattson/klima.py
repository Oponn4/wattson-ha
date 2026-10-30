"""UC11: welcher Raumwert gilt, und darf Wattson überhaupt kühlen (v0.20.29).

Warum es das gibt: Am 30.10.2026 um 10:42 schaltete Wattson die Klimaanlage im
Office auf Kühlen, 25 °C, bei 10 °C draußen. Der Shelly BLU H&T hängt am
Lampenmast neben dem Südfenster, die tiefe Oktobersonne schien darauf, er
stieg in 13 min von 25,7 auf 29,6 °C. Proxon-Panel (Innenwand, Schatten) und
Klimaanlage (unter der Decke) zeigten 24,3 und 24,5 °C. Wattson las nur den
Shelly, und die Regel „innen warm, außen kühler" schaltete die Kühlung ein —
obwohl genau dann Lüften die Antwort ist.

Zwei Bausteine:
- `raumtemperatur`: mittlerer Wert aus allen verfügbaren Sensoren des Raums,
  ein einzelner Ausreißer setzt sich so nicht durch.
- `kuehlsperre`: an kühlen Tagen und bei kühler Außenluft kühlt Wattson nicht
  selbst, höchstens der Fenster-Hinweis geht raus.

Bewusst frei von Home-Assistant-Importen, damit ohne HA testbar.
"""
from __future__ import annotations

import statistics


def raumtemperatur(*werte: float | None) -> float | None:
    """Raumtemperatur aus mehreren Sensoren.

    Ab drei Werten der Median: ein Sensor in der Sonne oder an der Decke
    verschiebt ihn nicht. Bei zwei Werten der niedrigere — welcher von beiden
    falsch liegt, ist nicht zu entscheiden, und zu kalt geschätzt heißt nur,
    Wattson kühlt nicht. None, wenn kein Sensor einen Wert hat.
    """
    da = [w for w in werte if w is not None]
    if not da:
        return None
    if len(da) == 2:
        return min(da)
    return statistics.median(da)


def kuehlsperre(
    *,
    aussen_c: float,
    tages_max_c: float | None,
    aussen_min_c: float,
    saison_max_c: float,
) -> str | None:
    """Grund, warum Wattson nicht selbst kühlen darf, oder None.

    - Saison: Tages-Höchstwert unter `saison_max_c` (wie UC12). Unbekannte
      Vorhersage sperrt nicht, dann entscheidet die Außentemperatur allein.
    - Außenluft: unter `aussen_min_c` bringt das Fenster mehr als die Klima.
    """
    if tages_max_c is not None and tages_max_c < saison_max_c:
        return (
            f"kühler Tag (Höchstwert {tages_max_c:.1f} °C < {saison_max_c:.1f} °C)"
        )
    if aussen_c < aussen_min_c:
        return f"außen {aussen_c:.1f} °C < {aussen_min_c:.1f} °C → Lüften reicht"
    return None
