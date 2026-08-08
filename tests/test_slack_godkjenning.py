"""Slack-styrt godkjenning: en kollega eier et merke uten tilgang til dashbordet.

Den reelle risikoen her er DOBBELTPUBLISERING. `publiser_ett` sjekker ikke selv om
et svar er lest før, og et innlegg som går ut to ganger på en firmaside er en feil
alle ser. Derfor to uavhengige sperrer, og begge testes: ledgeren over behandlede
svar, og status-sjekken på selve utkastet.
"""

from __future__ import annotations

import json

import pytest

from brandpost import slack_godkjenning as sg


# ── svartolkningen ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("tekst,ventet", [
    ("publiser 2", [2]),
    ("Publiser: 2", [2]),
    ("publiser 2 og 4", [2, 4]),
    ("2, 4", [2, 4]),
    ("3", [3]),
    ("ja 1", [1]),
    ("PUBLISER 5.", [5]),
])
def test_tolker_godkjenninger(tekst, ventet):
    assert sg.tolk_svar(tekst) == ventet


@pytest.mark.parametrize("tekst", [
    "",
    "ser bra ut!",
    "den andre var litt tynn synes jeg",
    "kan vi ikke heller ta den neste uke?",
    "hva mener du med 2?",          # spørsmål, ikke godkjenning
    "jeg liker 2 best men vent",    # nøling er ikke et ja
])
def test_tolker_ikke_alt_annet(tekst):
    """Å tolke for villig er farligere enn å tolke for strengt: utfallet er en
    publisering på en firmaside, og den kan ikke trekkes tilbake."""
    assert sg.tolk_svar(tekst) == []


def test_avviser_urimelige_tall():
    """Noen limer inn en tabell. Da skal ikke tolv innlegg gå ut."""
    assert len(sg.tolk_svar("publiser 1 2 3 4 5 6 7 8")) <= 3
    assert sg.tolk_svar("publiser 0") == []
    assert sg.tolk_svar("publiser 99999") == []


# ── dobbeltpublisering ───────────────────────────────────────────────────────

def _oppsett(tmp_path, monkeypatch, status="proposed"):
    monkeypatch.setenv("BRANDPOST_WORKSPACE", str(tmp_path))
    d = tmp_path / "socials" / "2026-08-06"
    d.mkdir(parents=True)
    (d / "manifest.json").write_text(json.dumps({"drafts": [
        {"nr": 2, "brand": "akser", "brand_name": "Akser", "headline": "H",
         "body": "b", "status": status},
    ]}, ensure_ascii=False), encoding="utf-8")
    return d / "manifest.json"


def test_samme_svar_publiserer_bare_en_gang(tmp_path, monkeypatch):
    """Sperre 1: ledgeren. Leses tråden på nytt, skal et allerede behandlet svar
    hoppes over."""
    _oppsett(tmp_path, monkeypatch)
    kalt = []
    monkeypatch.setattr(sg.publisher, "publiser_ett",
                        lambda *a, **k: kalt.append(1) or {"posted": True, "url": "u"})
    monkeypatch.setattr(sg.brandkit, "load_brand",
                        lambda k: type("B", (), {"slack_token_env": "", "name": "Akser"})())
    monkeypatch.setattr(sg.slackmod, "read_replies",
                        lambda *a, **k: [{"ts": "111.1", "text": "publiser 2"}])
    sg.skriv_ledger({"traader": {"999.0": {"brand": "akser", "dag": "2026-08-06",
                                           "kanal": "C1", "nr": [2]}}}, tmp_path)

    r1 = sg.les_og_publiser(vault=tmp_path)
    r2 = sg.les_og_publiser(vault=tmp_path)   # samme svar, andre gang

    assert r1["publisert"] == 1
    assert r2["publisert"] == 0, "samme svar publiserte to ganger"
    assert len(kalt) == 1


def test_allerede_publisert_utkast_roeres_ikke(tmp_path, monkeypatch):
    """Sperre 2: status på utkastet, uavhengig av ledgeren. Går ledgeren tapt,
    skal et publisert innlegg fortsatt ikke gå ut igjen."""
    _oppsett(tmp_path, monkeypatch, status="published")
    monkeypatch.setattr(sg.publisher, "publiser_ett",
                        lambda *a, **k: pytest.fail("skulle ikke publisert"))
    monkeypatch.setattr(sg.brandkit, "load_brand",
                        lambda k: type("B", (), {"slack_token_env": "", "name": "Akser"})())
    monkeypatch.setattr(sg.slackmod, "read_replies",
                        lambda *a, **k: [{"ts": "222.2", "text": "publiser 2"}])
    sg.skriv_ledger({"traader": {"999.0": {"brand": "akser", "dag": "2026-08-06",
                                           "kanal": "C1", "nr": [2]}}}, tmp_path)

    r = sg.les_og_publiser(vault=tmp_path)
    assert r["publisert"] == 0 and r["hoppet"] == 1


def test_ukjent_nummer_feiler_uten_aa_stanse_resten(tmp_path, monkeypatch):
    _oppsett(tmp_path, monkeypatch)
    monkeypatch.setattr(sg.brandkit, "load_brand",
                        lambda k: type("B", (), {"slack_token_env": "", "name": "Akser"})())
    monkeypatch.setattr(sg.slackmod, "read_replies",
                        lambda *a, **k: [{"ts": "333.3", "text": "publiser 7"}])
    sg.skriv_ledger({"traader": {"999.0": {"brand": "akser", "dag": "2026-08-06",
                                           "kanal": "C1", "nr": [2]}}}, tmp_path)

    r = sg.les_og_publiser(vault=tmp_path)
    assert r["feilet"] == 1 and r["publisert"] == 0


# ── forslagsposten ───────────────────────────────────────────────────────────

def test_forslag_krever_kanal(tmp_path, monkeypatch):
    """Et merke uten [slack].channel skal si fra, ikke poste i en tilfeldig kanal."""
    monkeypatch.setenv("BRANDPOST_WORKSPACE", str(tmp_path))
    monkeypatch.setattr(sg.brandkit, "load_brand",
                        lambda k: type("B", (), {"slack_channel": "", "name": "X",
                                                 "slack_token_env": ""})())
    r = sg.post_forslag("akser", vault=tmp_path)
    assert r["sendt"] is False and "channel" in r["reason"]


def test_forslag_tar_bare_uvurderte(tmp_path, monkeypatch):
    """Allerede vurderte eller publiserte utkast skal ikke legges fram igjen."""
    monkeypatch.setenv("BRANDPOST_WORKSPACE", str(tmp_path))
    d = tmp_path / "socials" / "2026-08-06"
    d.mkdir(parents=True)
    (d / "manifest.json").write_text(json.dumps({"drafts": [
        {"nr": 1, "brand": "akser", "headline": "ny", "body": "b", "status": "proposed"},
        {"nr": 2, "brand": "akser", "headline": "vurdert", "body": "b",
         "status": "proposed", "verdict": "passed"},
        {"nr": 3, "brand": "akser", "headline": "ute", "body": "b", "status": "published"},
        {"nr": 4, "brand": "annet", "headline": "feil merke", "body": "b",
         "status": "proposed"},
    ]}, ensure_ascii=False), encoding="utf-8")

    monkeypatch.setattr(sg.brandkit, "load_brand",
                        lambda k: type("B", (), {"slack_channel": "C1", "name": "Akser",
                                                 "slack_token_env": ""})())
    sendt = {}
    monkeypatch.setattr(sg.slackmod, "send_message",
                        lambda tekst, **k: sendt.update(tekst=tekst)
                        or {"sent": True, "ts": "1.0"})

    r = sg.post_forslag("akser", vault=tmp_path, dag="2026-08-06")
    assert r["sendt"] and r["antall"] == 1
    assert "ny" in sendt["tekst"]
    for utelatt in ("vurdert", "ute", "feil merke"):
        assert utelatt not in sendt["tekst"]
    # Tråden må lagres, ellers finner steg 2 aldri svarene.
    assert "1.0" in sg.les_ledger(tmp_path)["traader"]
