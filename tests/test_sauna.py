"""Sauna-Plan (v0.20.26): Kalender zuerst, sonst selbst erkennen.

Anlass 25.10.2026: Sauna geplant ab 18 Uhr, Preis 17:15–19:15 bei 25–26 ct.
EMHASS rechnete für den Abend mit 0,3–0,8 kW Hauslast und hielt den Akku
zurück. Mit der Sauna als festem Verbraucher (Testlauf gegen EMHASS 0.18.7,
16:08) entlud er 1,4 kW von 17 bis 19:30 und lag danach bei 5 %.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from conftest import const, sauna

TZ = timezone(timedelta(hours=1))
P = sauna.SaunaProfil(
    aufheiz_kw=const.SAUNA_AUFHEIZ_KW,
    halten_kw=const.SAUNA_HALTEN_KW,
    aufheiz_dauer_min=const.SAUNA_AUFHEIZ_DAUER_MIN,
    aufheiz_vorlauf_min=const.SAUNA_AUFHEIZ_VORLAUF_MIN,
    nutz_min=const.SAUNA_NUTZ_MIN,
    nachlauf_min=const.SAUNA_NACHLAUF_MIN,
    verfall_min=const.SAUNA_VERFALL_MIN,
    stichwort=const.SAUNA_STICHWORT,
)


def t(hh, mm=0, tag=25):
    return datetime(2026, 10, tag, hh, mm, tzinfo=TZ)


def ev(summary, start, end):
    return {"summary": summary, "start": start.isoformat(), "end": end.isoformat()}


def termine(*events):
    return sauna.sauna_termine(list(events), const.SAUNA_STICHWORT, TZ)


MITTAG = t(12)


def plan(events=(), now=MITTAG, status="idle", beginn=None):
    return sauna.sauna_plan(
        termine=termine(*events), now=now, status=status, beginn=beginn, p=P,
    )


ABEND = ev("Sauna 🧖", t(18), t(20))


# --- Termine erkennen ---------------------------------------------------

def test_titel_egal_wie_geschrieben():
    assert sauna.ist_sauna_termin({"summary": "SAUNA mit Sonja"}, "sauna")
    assert sauna.ist_sauna_termin({"summary": "Saunaabend"}, "sauna")


def test_anderer_termin_ist_keine_sauna():
    assert not sauna.ist_sauna_termin({"summary": "Spieleabend"}, "sauna")
    assert not sauna.ist_sauna_termin({}, "sauna")


def test_ganztags_termin_wird_ignoriert():
    ganz = {"summary": "Sauna", "start": "2026-10-25", "end": "2026-10-26"}
    assert termine(ganz) == []


# --- Kalender, Sauna noch aus --------------------------------------------

def test_termin_einschalten_vor_beginn():
    p = plan([ABEND], now=t(12))
    assert p.quelle == "kalender"
    assert p.start == t(17, 20)
    assert p.ende == t(20)


def test_termin_energie_wie_gemessen():
    # 35 min × 9 kW + 125 min × 3,6 kW = 12,75 kWh; gemessen 8,8–11,1 kWh
    # an Abenden mit kürzerer Nutzung — Größenordnung muss passen.
    p = plan([ABEND], now=t(12))
    assert 10.0 < p.energie_kwh < 14.0
    assert 4000 < p.leistung_w(t(12)) < 5000


def test_termin_ohne_einschalten_verfaellt():
    assert plan([ABEND], now=t(18, 21)) is None


def test_termin_kurz_nach_beginn_bleibt():
    # 18:10 noch aus: vielleicht nur spät dran. Heizen ab jetzt annehmen.
    p = plan([ABEND], now=t(18, 10))
    assert p is not None
    assert p.energie_kwh > 0


def test_naechster_termin_nach_verfallenem():
    morgen = ev("Sauna", t(18, tag=26), t(20, tag=26))
    p = plan([ABEND, morgen], now=t(19))
    assert p.start == t(17, 20, tag=26)


def test_termin_ohne_ende_nutzt_standarddauer():
    nur_start = {"summary": "Sauna", "start": t(18).isoformat(), "end": t(18).isoformat()}
    p = plan([nur_start], now=t(12))
    assert p.ende == t(18) + timedelta(minutes=const.SAUNA_NUTZ_MIN)


def test_kein_termin_sauna_aus_kein_plan():
    assert plan([], now=t(12)) is None


# --- Selbst erkennen (Rückfall) -------------------------------------------

def test_erkannt_ohne_termin():
    p = plan([], now=t(15, 5), status="vorheizen", beginn=t(15))
    assert p.quelle == "erkannt"
    assert p.start == t(15)
    # 35 min Aufheizen + 120 min drin
    assert p.ende == t(15) + timedelta(minutes=155)


def test_erkannt_verlaengert_sich_solange_sie_laeuft():
    p = plan([], now=t(18), status="warm", beginn=t(15))
    assert p.ende == t(18, 30)
    # Aufheizen vorbei: nur noch Halten
    assert p.leistung_w(t(18)) == round(const.SAUNA_HALTEN_KW * 1000)


def test_erkannt_ignoriert_termin_von_morgen():
    morgen = ev("Sauna", t(18, tag=26), t(20, tag=26))
    p = plan([morgen], now=t(15, 5), status="vorheizen", beginn=t(15))
    assert p.quelle == "erkannt"


def test_negativprobe_sauna_aus_heisst_kein_erkannter_plan():
    assert plan([], now=t(15, 5), status="idle", beginn=None) is None
    assert plan([], now=t(15, 5), status="unknown", beginn=None) is None


# --- Kalender und Betrieb zusammen ---------------------------------------

def test_puenktlich_eingeschaltet_bleibt_kalender():
    p = plan([ABEND], now=t(17, 30), status="vorheizen", beginn=t(17, 20))
    assert p.quelle == "kalender"
    assert (p.start, p.ende) == (t(17, 20), t(20))


def test_frueher_eingeschaltet_zieht_start_vor():
    p = plan([ABEND], now=t(16, 50), status="vorheizen", beginn=t(16, 45))
    assert p.quelle == "kalender"
    assert p.start == t(16, 45)


def test_viel_zu_frueh_eingeschaltet_ist_eigener_lauf():
    # 14 Uhr an, Termin 18 Uhr: das ist nicht das geplante Aufheizen
    p = plan([ABEND], now=t(14, 5), status="vorheizen", beginn=t(14))
    assert p.quelle == "erkannt"


def test_laenger_als_termin_wird_verlaengert():
    p = plan([ABEND], now=t(20, 15), status="warm", beginn=t(17, 20))
    assert p.ende == t(20, 45)


# --- Beginn aus dem Status-Helper ------------------------------------------

def test_beginn_vorheizen_ist_einschaltzeit():
    assert sauna.betriebsbeginn("vorheizen", t(17, 20), P) == t(17, 20)


def test_beginn_warm_liegt_eine_aufheizdauer_davor():
    assert sauna.betriebsbeginn("warm", t(18), P) == t(18) - timedelta(
        minutes=const.SAUNA_AUFHEIZ_DAUER_MIN
    )


def test_beginn_aus_ist_none():
    assert sauna.betriebsbeginn("idle", t(18), P) is None
