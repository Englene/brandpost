"""Bunken: emne, dom og karantene.

Kalendervisningen lar deg vurdere utkast der de tilfeldigvis havnet. Bunken gir
deg dem én av gangen: ja eller nei. Det krever tre ting som ikke fantes før:

  1. et EMNE på utkastet, finere enn pilaren. Seks pilarer mot ~17 innlegg i
     måneden gjør pilaren ubrukelig som sperre.
  2. en DOM fra eieren, lagret ved siden av status og ikke i den.
  3. KARANTENE med to ulike vinduer, fordi et nei betyr «ikke nå» og ikke «aldri».

Punkt 3 er det som gjør at bunken ikke gjentar feilen fra 22. juli 2026, da alt
generert ble sperret og åtte vinkler brant uten at én var publisert.
"""
from __future__ import annotations

import json
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

from brandpost import store

NOW = datetime(2026, 7, 31, 10, 0)


def _dag(vault: Path, navn: str, drafts: list[dict]) -> Path:
    d = store.socials_dir(vault) / navn
    d.mkdir(parents=True, exist_ok=True)
    p = d / "manifest.json"
    p.write_text(json.dumps({"drafts": drafts}, ensure_ascii=False), encoding="utf-8")
    return p


# ── clean_topic ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("inn,ut", [
    ("ESA-retur", "esa-retur"),
    ("esa  retur", "esa-retur"),        # samme poeng, annen skrivemåte
    ("  ESA Retur  ", "esa-retur"),
    ("Frist: 1. mai!", "frist-1-mai"),
    ("Blårev og æøå", "blårev-og-æøå"),  # norske tegn overlever
    ("", ""),
    (None, ""),
])
def test_clean_topic_normaliserer(inn, ut):
    assert store.clean_topic(inn) == ut


def test_clean_topic_kappes():
    assert len(store.clean_topic("a" * 200)) <= 60


# ── Tekst-utkast uten bilde ──────────────────────────────────────────────────

def test_write_draft_uten_png_lager_ikke_bildefil(tmp_path):
    """Bunken lager mange forslag som de fleste av forkastes. Et gpt-image-2-kall
    per forslag ville vært betalt for søppel."""
    spec = {"headline": "Betalt inn, ikke hentet ut", "body": "tekst",
            "why_now": "fordi", "emne": "ESA-retur", "pillar": "data-bevis"}
    meta = store.write_draft(tmp_path, "demo", spec, None, index=1, when=NOW)

    assert meta["png_path"] == ""
    assert list((store.socials_dir(tmp_path) / "2026-07-31").glob("*.png")) == []
    # md-fila skal fortsatt skrives, men uten død bildelenke
    md = Path(meta["md_path"]).read_text(encoding="utf-8")
    assert "![[" not in md
    assert "bilde lages når utkastet får et ja" in md


def test_write_draft_med_png_er_uendret(tmp_path):
    """Den vanlige veien skal ikke ha endret seg."""
    spec = {"headline": "Med bilde", "body": "b", "why_now": "w"}
    meta = store.write_draft(tmp_path, "demo", spec, b"\x89PNG-fake", index=1, when=NOW)
    assert meta["png_path"].endswith(".png")
    assert Path(meta["png_path"]).read_bytes() == b"\x89PNG-fake"
    assert "![[" in Path(meta["md_path"]).read_text(encoding="utf-8")


def test_emne_persisteres_og_normaliseres(tmp_path):
    spec = {"headline": "H", "emne": "ESA  Retur", "pillar": "data-bevis"}
    meta = store.write_draft(tmp_path, "demo", spec, None, index=1, when=NOW)
    assert meta["emne"] == "esa-retur"
    assert 'emne: "esa-retur"' in Path(meta["md_path"]).read_text(encoding="utf-8")


# ── Dommen ───────────────────────────────────────────────────────────────────

def test_mark_verdict_setter_dom_og_tidsstempel(tmp_path):
    mpath = _dag(tmp_path, "2026-07-31", [{"emne": "a", "status": "proposed"}])
    manifest = json.loads(mpath.read_text(encoding="utf-8"))
    store.mark_verdict(mpath, manifest, 0, "passed")

    lagret = json.loads(mpath.read_text(encoding="utf-8"))["drafts"][0]
    assert lagret["verdict"] == "passed"
    assert lagret["verdict_at"]
    # Dommen er et SIDESPOR: status skal ikke ha flyttet seg.
    assert lagret["status"] == "proposed"


def test_mark_verdict_avviser_ukjent_dom(tmp_path):
    mpath = _dag(tmp_path, "2026-07-31", [{"emne": "a", "status": "proposed"}])
    manifest = json.loads(mpath.read_text(encoding="utf-8"))
    with pytest.raises(ValueError):
        store.mark_verdict(mpath, manifest, 0, "kanskje")


# ── Karantene ────────────────────────────────────────────────────────────────

def test_planlagt_emne_er_hardt_sperret(tmp_path):
    _dag(tmp_path, "2026-07-20", [{"emne": "esa-retur", "status": "planlagt",
                                   "scheduled_at": "2026-07-28T10:00"}])
    res = store.blocked_topics(tmp_path, now=NOW)
    assert "esa-retur" in res["hard"]


def test_gammelt_publisert_emne_slippes_fri(tmp_path):
    """Karantenen skal gå ut, ellers tørker idébanken inn."""
    _dag(tmp_path, "2026-06-15", [{"emne": "gammelt", "status": "published",
                                   "published_at": "2026-06-21T10:00"}])
    res = store.blocked_topics(tmp_path, now=NOW)
    assert res["hard"] == []


def test_avvist_emne_er_mykt_sperret_ikke_hardt(tmp_path):
    _dag(tmp_path, "2026-07-29", [{"emne": "skattefunn-frist", "status": "proposed",
                                   "verdict": "passed", "verdict_at": "2026-07-30T09:00"}])
    res = store.blocked_topics(tmp_path, now=NOW)
    assert res["soft"] == ["skattefunn-frist"]
    assert res["hard"] == []


def test_avvist_slippes_fri_raskere_enn_planlagt(tmp_path):
    """Kjernen i «skyv, ikke brenn»: et nei fra for 20 dager siden skal være ute
    av karantene, mens et planlagt innlegg fra samme dag fortsatt er sperret."""
    _dag(tmp_path, "2026-07-05", [
        {"emne": "gammelt-nei", "status": "proposed",
         "verdict": "passed", "verdict_at": "2026-07-10T09:00"},
        {"emne": "gammelt-ja", "status": "planlagt", "scheduled_at": "2026-07-10T09:00"},
    ])
    res = store.blocked_topics(tmp_path, now=NOW)
    assert "gammelt-nei" not in res["soft"]      # 21 dager siden > SOFT_TOPIC_DAYS
    assert "gammelt-ja" in res["hard"]           # 21 dager siden < HARD_TOPIC_DAYS


def test_samme_emne_i_begge_lister_havner_kun_i_hard(tmp_path):
    _dag(tmp_path, "2026-07-28", [
        {"emne": "dobbel", "status": "planlagt", "scheduled_at": "2026-07-29T10:00"},
        {"emne": "dobbel", "status": "proposed",
         "verdict": "passed", "verdict_at": "2026-07-30T09:00"},
    ])
    res = store.blocked_topics(tmp_path, now=NOW)
    assert res["hard"] == ["dobbel"]
    assert res["soft"] == []


def test_skrivemaate_varianter_dedupliseres(tmp_path):
    _dag(tmp_path, "2026-07-28", [{"emne": "ESA  Retur", "status": "planlagt",
                                   "scheduled_at": "2026-07-29T10:00"}])
    _dag(tmp_path, "2026-07-27", [{"emne": "esa-retur", "status": "planlagt",
                                   "scheduled_at": "2026-07-28T10:00"}])
    res = store.blocked_topics(tmp_path, now=NOW)
    assert res["hard"] == ["esa-retur"]


def test_utkast_uten_emne_ignoreres(tmp_path):
    """Utkast fra før emne-feltet fantes skal ikke sperre noe."""
    _dag(tmp_path, "2026-07-28", [{"status": "planlagt", "scheduled_at": "2026-07-29T10:00"},
                                  {"emne": "", "status": "published",
                                   "published_at": "2026-07-29T10:00"}])
    res = store.blocked_topics(tmp_path, now=NOW)
    assert res == {"hard": [], "soft": []}


def test_uvurdert_forslag_sperrer_emnet_sitt_for_unikhet(tmp_path):
    """Ligger et forslag i bunken og venter på dom, er emnet opptatt. Ti forslag
    skal ikke være tre varianter av samme poeng: det er meningsløst å swipe
    gjennom det samme tre ganger.

    Merk at dette IKKE er en tidsregel som de to andre. Sperren varer bare så
    lenge forslaget ligger der: sier eieren nei, flyttes emnet til den myke lista
    og kan komme tilbake senere."""
    _dag(tmp_path, "2026-07-30", [{"emne": "urørt", "status": "proposed"}])
    res = store.blocked_topics(tmp_path, now=NOW)
    assert res["hard"] == ["urørt"]


def test_emnet_frigjoeres_naar_forslaget_avvises(tmp_path):
    """Overgangen fra «opptatt i bunken» til «swipet vekk»: emnet skal falle ut
    av hard-lista og ned i den myke, ellers hadde et nei vært hardere enn et ja."""
    _dag(tmp_path, "2026-07-30", [{"emne": "urørt", "status": "proposed",
                                   "verdict": "passed",
                                   "verdict_at": "2026-07-30T09:00"}])
    res = store.blocked_topics(tmp_path, now=NOW)
    assert res["hard"] == []
    assert res["soft"] == ["urørt"]


def test_taaler_uleselig_manifest(tmp_path):
    d = store.socials_dir(tmp_path) / "2026-07-30"
    d.mkdir(parents=True, exist_ok=True)
    (d / "manifest.json").write_text("{ ikke json", encoding="utf-8")
    _dag(tmp_path, "2026-07-29", [{"emne": "ok", "status": "planlagt",
                                   "scheduled_at": "2026-07-30T10:00"}])
    assert store.blocked_topics(tmp_path, now=NOW)["hard"] == ["ok"]


# ── Guarden i genereringen ───────────────────────────────────────────────────

def test_guard_forkaster_sperret_emne():
    """En promptinstruks er en oppfordring. Modellen har fått beskjed om å ikke
    gjenta seg siden 22. juli og gjør det likevel, så sperren må være i kode."""
    from brandpost import cli
    sperret = {"hard": ["esa-retur"], "soft": []}
    posts = [{"headline": "A", "emne": "ESA-Retur"}, {"headline": "B", "emne": "ny-vinkel"}]
    ut = cli._guard_topics(posts, sperret)
    assert [p["headline"] for p in ut] == ["B"]


def test_guard_normaliserer_emne_paa_alt_den_slipper_gjennom():
    from brandpost import cli
    posts = [{"headline": "A", "emne": "Ny  Vinkel"}]
    ut = cli._guard_topics(posts, {"hard": [], "soft": []})
    assert ut[0]["emne"] == "ny-vinkel"


def test_guard_slipper_utkast_uten_emne():
    """Utkast fra før feltet fantes skal ikke forsvinne."""
    from brandpost import cli
    ut = cli._guard_topics([{"headline": "A"}], {"hard": ["noe"], "soft": []})
    assert len(ut) == 1


def test_guard_bryr_seg_ikke_om_myk_liste():
    """Soft er en oppfordring til modellen, ikke en sperre. Ellers ville et nei
    vært like endelig som en publisering, og vi var tilbake til 22. juli."""
    from brandpost import cli
    posts = [{"headline": "A", "emne": "swipet-vekk"}]
    ut = cli._guard_topics(posts, {"hard": [], "soft": ["swipet-vekk"]})
    assert len(ut) == 1


def test_emne_block_tom_naar_ingenting_er_sperret():
    from brandpost import cli
    assert cli._emne_block({"hard": [], "soft": []}) == ""


def test_emne_block_skiller_forbudt_fra_uoensket():
    from brandpost import cli
    blokk = cli._emne_block({"hard": ["a"], "soft": ["b"]})
    assert "FORBUDT" in blokk and "UNNGÅ OM MULIG" in blokk
    # Instruksen må si hva nivået er, ellers kollapser emnet til pilar-nivå.
    assert "POENGET, ikke for området" in blokk


# ── Bunken i dashbordet ──────────────────────────────────────────────────────

@pytest.fixture()
def bunke_client(tmp_path, monkeypatch):
    """Dashbord mot en tom arbeidsmappe, med to tekst-utkast i bunken."""
    monkeypatch.setenv("BRANDPOST_WORKSPACE", str(tmp_path))
    monkeypatch.delenv("LINKEDIN_ENABLED", raising=False)
    from fastapi.testclient import TestClient
    from main import app

    d = store.socials_dir(tmp_path) / "2026-07-31"
    d.mkdir(parents=True, exist_ok=True)
    md = d / "post-1-demo-betalt-inn.md"
    md.write_text('---\nimage: ""\n---\n\n# H\n\n_(bilde lages når utkastet får et ja)_\n',
                  encoding="utf-8")
    (d / "manifest.json").write_text(json.dumps({"drafts": [
        {"nr": 1, "brand": "demo", "headline": "Betalt inn, ikke hentet ut",
         "emne": "esa-retur", "body": "brødtekst", "why_now": "aktuelt",
         "status": "proposed", "motif": "flat vektor", "format": "motiv",
         "png_path": "", "md_path": str(md), "spec": {}},
        {"nr": 2, "brand": "demo", "headline": "Fristen er ikke der du tror",
         "emne": "skattefunn-frist", "body": "b2", "why_now": "w2",
         "status": "proposed", "format": "motiv", "png_path": "", "spec": {}},
    ]}, ensure_ascii=False), encoding="utf-8")
    return TestClient(app), tmp_path, d / "manifest.json"


def test_bunken_viser_forste_kort(bunke_client):
    client, _, _ = bunke_client
    r = client.get("/some/bunke")
    assert r.status_code == 200
    assert "Betalt inn, ikke hentet ut" in r.text
    assert "2 igjen i bunken" in r.text


def test_kortet_viser_bildet_naar_det_finnes(bunke_client):
    """Et LinkedIn-innlegg vurderes på bilde og tekst sammen, så bildet er ferdig
    laget når forslaget havner i bunken."""
    client, tmp_path, mpath = bunke_client
    d = store.socials_dir(tmp_path) / "2026-07-31"
    png = d / "post-1-demo-betalt-inn.png"
    png.write_bytes(b"\x89PNG-fake")
    m = json.loads(mpath.read_text(encoding="utf-8"))
    m["drafts"][0]["png_path"] = str(png)
    mpath.write_text(json.dumps(m, ensure_ascii=False), encoding="utf-8")

    r = client.get("/some/bunke")
    assert f"/some/media/2026-07-31/{png.name}" in r.text
    assert "Bildet feilet" not in r.text


def test_kortet_faller_tilbake_paa_motivet_naar_bildet_mangler(bunke_client):
    """Ett feilet bildekall skal ikke skjule teksten: den er det dyre å lage."""
    client, _, _ = bunke_client          # fixturen har png_path=""
    r = client.get("/some/bunke")
    assert "Bildet feilet" in r.text
    assert "flat vektor" in r.text       # motivet vises som erstatning


def test_nei_lagrer_dom_og_gaar_videre(bunke_client):
    client, _, mpath = bunke_client
    r = client.post("/some/api/bunke/2026-07-31/1/pass")
    assert r.status_code == 200
    assert "Fristen er ikke der du tror" in r.text      # neste kort
    d = json.loads(mpath.read_text(encoding="utf-8"))["drafts"][0]
    assert d["verdict"] == "passed"
    assert d["status"] == "proposed"                    # dommen er et sidespor


def test_ja_uten_gyldig_dato_skriver_ingenting(bunke_client):
    """Et ja uten dato er en intensjon, ikke en plan."""
    client, _, mpath = bunke_client
    r = client.post("/some/api/bunke/2026-07-31/1/like", data={"when": "i morgen"})
    assert "Ugyldig tidspunkt" in r.text
    d = json.loads(mpath.read_text(encoding="utf-8"))["drafts"][0]
    assert d["status"] == "proposed" and "verdict" not in d


def test_ja_planlegger_og_rendrer_bildet(bunke_client, monkeypatch):
    client, _, mpath = bunke_client
    monkeypatch.setattr("brandpost.render.render_post",
                        lambda *a, **k: {"png": b"\x89PNG", "how": "mock"})
    r = client.post("/some/api/bunke/2026-07-31/1/like",
                    data={"when": "2026-08-05T10:00"})
    assert r.status_code == 200

    d = json.loads(mpath.read_text(encoding="utf-8"))["drafts"][0]
    assert d["verdict"] == "liked"
    assert d["status"] == "planlagt"
    assert d["scheduled_at"] == "2026-08-05T10:00"
    assert d["png_path"] and Path(d["png_path"]).exists()
    # md-fila skal ikke bli stående med plassholderen
    md = Path(d["md_path"]).read_text(encoding="utf-8")
    assert "![[" in md and "bilde lages når" not in md


def test_bildefeil_mister_ikke_planleggingen(bunke_client, monkeypatch):
    """Bildekallet er det som kan ryke. Da skal datoen likevel stå, ellers har
    eieren tatt en avgjørelse som systemet glemte."""
    client, _, mpath = bunke_client

    def _sprekk(*a, **k):
        raise RuntimeError("bildetjenesten svarte ikke")
    monkeypatch.setattr("brandpost.render.render_post", _sprekk)

    r = client.post("/some/api/bunke/2026-07-31/1/like",
                    data={"when": "2026-08-05T10:00"})
    assert "bildet feilet" in r.text
    d = json.loads(mpath.read_text(encoding="utf-8"))["drafts"][0]
    assert d["status"] == "planlagt"
    assert d["scheduled_at"] == "2026-08-05T10:00"


def test_vurderte_utkast_forsvinner_fra_bunken(bunke_client, monkeypatch):
    """Bunken skal aldri stoppe: er den tom, står det at flere er på vei, ikke at
    du er ferdig (Oscar 31. juli). De to betyr helt ulike ting."""
    client, tmp_path, mpath = bunke_client
    from web import app as somemod
    monkeypatch.setattr(somemod, "_etterfyll_bunke", lambda brand: True)

    client.post("/some/api/bunke/2026-07-31/1/pass")
    client.post("/some/api/bunke/2026-07-31/2/pass")
    r = client.get("/some/bunke")
    assert store.unjudged_drafts(tmp_path) == []
    assert "Lager flere forslag" in r.text
    assert "Bunken er tom" not in r.text


def test_kalenderen_har_lenke_til_bunken(bunke_client):
    client, _, _ = bunke_client
    r = client.get("/some")
    assert "/some/bunke" in r.text


# ── Etterfyll ────────────────────────────────────────────────────────────────

def test_etterfyll_trigges_naar_bunken_synker_til_terskelen(bunke_client, monkeypatch):
    """Påfyll skal bestilles FØR bunken er tom. Ett bilde tar rundt 21 sekunder,
    så ti nye trenger et par minutter, og eieren skal ikke stå og vente."""
    client, _, _ = bunke_client
    from web import app as somemod

    startet: list[str] = []
    monkeypatch.setattr(somemod, "_etterfyll_bunke", lambda brand: startet.append(brand) or True)
    monkeypatch.setattr(somemod, "BUNKE_MIN", 1)

    # 2 i bunken, terskel 1: første nei tar den til 1 og skal utløse påfyll.
    r = client.post("/some/api/bunke/2026-07-31/1/pass")
    assert startet, "påfyll ble ikke bestilt"
    assert "nye forslag i bakgrunnen" in r.text


def test_etterfyll_venter_naar_det_er_nok_igjen(bunke_client, monkeypatch):
    client, _, _ = bunke_client
    from web import app as somemod
    startet: list[str] = []
    monkeypatch.setattr(somemod, "_etterfyll_bunke", lambda brand: startet.append(brand) or True)
    monkeypatch.setattr(somemod, "BUNKE_MIN", 0)      # aldri påfyll
    client.post("/some/api/bunke/2026-07-31/1/pass")
    assert startet == []


def test_paafyllet_kjorer_riktig_kommando(bunke_client, monkeypatch):
    client, tmp_path, _ = bunke_client
    from web import app as somemod

    kjort: list[list[str]] = []

    class _P:
        pid = 777

    def _fake(cmd, **kw):
        kjort.append(cmd)
        return _P()
    monkeypatch.setattr(somemod.subprocess, "Popen", _fake)

    assert somemod._etterfyll_bunke("demo") is True
    assert "--bunke" in kjort[0]
    assert str(somemod.BUNKE_PAAFYLL) in kjort[0]
    assert "demo" in kjort[0]


def test_doed_laas_foreldes(bunke_client, monkeypatch):
    """En lås fra en krasjet kjøring skal ikke okkupere en plass for alltid."""
    client, tmp_path, _ = bunke_client
    from web import app as somemod

    class _P:
        pid = 4242
    monkeypatch.setattr(somemod.subprocess, "Popen", lambda cmd, **kw: _P())
    monkeypatch.setattr(somemod, "BUNKE_SAMTIDIGE", 1)

    laasdir = store.socials_dir(tmp_path) / ".bunke-paafyll"
    laasdir.mkdir(parents=True, exist_ok=True)
    doed = laasdir / "999.lock"
    doed.write_text("")
    import os as _os
    gammelt = time.time() - (somemod.BUNKE_LAAS_MAKS_S + 60)
    _os.utime(doed, (gammelt, gammelt))

    assert somemod._etterfyll_bunke("demo") is True   # rydder den døde og starter
    assert not doed.exists()


# ── Avviste som mønster, ikke bare sperreliste ───────────────────────────────

def test_rejected_recently_gir_overskrift_og_motiv(tmp_path):
    """blocked_topics gir emnene. Modellen trenger selve forslagene for å se HVA
    SLAGS vinkling som ikke traff."""
    _dag(tmp_path, "2026-07-30", [
        {"headline": "Den som ikke traff", "motif": "grå graf", "emne": "a",
         "pillar": "data-bevis", "verdict": "passed", "verdict_at": "2026-07-30T09:00"},
        {"headline": "For gammel", "emne": "b", "verdict": "passed",
         "verdict_at": "2026-07-01T09:00"},
    ])
    ut = store.rejected_recently(tmp_path, now=NOW)
    assert [x["headline"] for x in ut] == ["Den som ikke traff"]
    assert ut[0]["motif"] == "grå graf"


def test_avvist_block_ber_om_moenster_ikke_bare_tema():
    from brandpost import cli
    blokk = cli._avvist_block([{"headline": "H", "motif": "m", "emne": "e"}])
    assert "mønsteret" in blokk
    assert cli._avvist_block([]) == ""


# ── Retting etter tilbakemelding ─────────────────────────────────────────────
# 31. juli 2026: et utkast påsto «rundt 15,7 milliarder kroner» fra Horisont
# Europa, mens kilden det selv viste til sier 10,6. Generering via `cli run` gjør
# ingen websøk, så tall og kilder kommer fra modellens hukommelse og verifiseres
# ikke. Til den rotårsaken er løst er eierens øye siste skanse, og da må han kunne
# si fra med ord.

def _mock_revise(monkeypatch, ut: dict):
    from brandpost import revise
    monkeypatch.setattr(revise, "structured_call",
                        lambda *a, **k: {"structured_output": ut})


def test_retting_skriver_om_tekst_og_lagrer_rettelsen(bunke_client, monkeypatch):
    client, _, mpath = bunke_client
    _mock_revise(monkeypatch, {
        "headline": "Kontingenten kommer hjem",
        "body": "Norske miljøer har hentet rundt 10,6 milliarder kroner.",
        "why_now": "fordi", "motif": "nytt motiv", "emne": "horisont-retur",
        "kilder": ["10,6 mrd kr → https://innovasjonnorge.no/x"],
        "endret": "Rettet tallet fra 15,7 til 10,6 mrd.",
    })
    monkeypatch.setattr("brandpost.render.render_post",
                        lambda *a, **k: {"png": b"\x89PNG", "how": "mock"})

    r = client.post("/some/api/bunke/2026-07-31/1/rett",
                    data={"note": "tallet er feil, kilden sier 10,6 mrd"})
    assert r.status_code == 200
    assert "Rettet tallet fra 15,7 til 10,6" in r.text

    d = json.loads(mpath.read_text(encoding="utf-8"))["drafts"][0]
    assert "10,6 milliarder" in d["body"]
    assert d["emne"] == "horisont-retur"
    # Rettelsen må huskes, ellers kommer feilen tilbake ved neste forsøk
    assert "tallet er feil, kilden sier 10,6 mrd" in d["spec"]["corrections"]
    # og bildet skal være laget på nytt
    assert d["png_path"] and Path(d["png_path"]).exists()


def test_retting_beholder_utkastet_i_bunken(bunke_client, monkeypatch):
    """En retting er verken ja eller nei: forslaget skal fortsatt vente på dom."""
    client, _, mpath = bunke_client
    _mock_revise(monkeypatch, {"headline": "H", "body": "ny tekst", "endret": "ok"})
    monkeypatch.setattr("brandpost.render.render_post",
                        lambda *a, **k: {"png": b"\x89PNG", "how": "mock"})
    client.post("/some/api/bunke/2026-07-31/1/rett", data={"note": "for skråsikker"})
    d = json.loads(mpath.read_text(encoding="utf-8"))["drafts"][0]
    assert d["status"] == "proposed"
    assert "verdict" not in d


def test_tom_tilbakemelding_avvises(bunke_client):
    client, _, mpath = bunke_client
    r = client.post("/some/api/bunke/2026-07-31/1/rett", data={"note": "   "})
    assert "Skriv hva som er galt" in r.text
    d = json.loads(mpath.read_text(encoding="utf-8"))["drafts"][0]
    assert d["body"] == "brødtekst"          # urørt


def test_bildefeil_beholder_den_rettede_teksten(bunke_client, monkeypatch):
    """Teksten er det viktige. Ryker bildekallet, skal rettingen likevel stå."""
    client, _, mpath = bunke_client
    _mock_revise(monkeypatch, {"headline": "H", "body": "rettet tekst", "endret": "ok"})

    def _sprekk(*a, **k):
        raise RuntimeError("bildetjenesten svarte ikke")
    monkeypatch.setattr("brandpost.render.render_post", _sprekk)

    r = client.post("/some/api/bunke/2026-07-31/1/rett", data={"note": "feil tall"})
    assert "bildet feilet" in r.text
    d = json.loads(mpath.read_text(encoding="utf-8"))["drafts"][0]
    assert d["body"] == "rettet tekst"


def test_rettelser_akkumuleres_og_kappes():
    """Alle tidligere rettelser skal følge med i prompten: et problem eieren har
    påpekt én gang skal ikke komme tilbake i neste forsøk."""
    from brandpost import revise
    sett: dict = {}

    def _fanger(system, user, schema, label=""):
        sett["user"] = user
        return {"structured_output": {"headline": "H", "body": "B", "endret": "e"}}

    import brandpost.revise as rv
    gammel = rv.structured_call
    rv.structured_call = _fanger
    try:
        draft = {"brand": "demo", "headline": "H", "body": "B",
                 "spec": {"corrections": ["første feil", "andre feil"]}}
        rv.revise_draft(draft, "tredje feil")
        assert "første feil" in sett["user"]
        assert "tredje feil" in sett["user"]
        # kappes til de nyeste
        mange = {"brand": "demo", "headline": "H", "body": "B",
                 "spec": {"corrections": [f"feil {i}" for i in range(20)]}}
        res = rv.revise_draft(mange, "ny")
        assert len(res["felter"]["spec"]["corrections"]) <= rv.MAX_RETTELSER
    finally:
        rv.structured_call = gammel


# ── Tall uten kilde ──────────────────────────────────────────────────────────

def test_flagger_tall_som_ikke_finnes_i_kildene():
    from brandpost import cli
    posts = [
        {"headline": "A", "body": "Norge hentet 15,7 milliarder kroner.",
         "kilder": ["returandel 3,23 % → https://x.no"]},
        {"headline": "B", "body": "Returandelen er 3,23 prosent.",
         "kilder": ["returandel 3,23 prosent → https://x.no"]},
        {"headline": "C", "body": "Ingen tall her.", "kilder": []},
    ]
    cli._flagg_udekkede_tall(posts)
    assert posts[0]["tall_uten_kilde"]                 # 15,7 mrd står ikke i kilden
    assert "tall_uten_kilde" not in posts[1]           # dekket
    assert "tall_uten_kilde" not in posts[2]           # ingen tall å dekke


def test_tall_uten_noen_kilder_flagges_med_selve_tallet():
    """Flagget skal si HVILKET tall som mangler dekning, ikke bare at noe gjør
    det: eieren skal kunne se etter akkurat den påstanden i teksten."""
    from brandpost import cli
    posts = [{"headline": "A", "body": "19 prosent av alt.", "kilder": []}]
    cli._flagg_udekkede_tall(posts)
    assert posts[0]["tall_uten_kilde"] == ["19 prosent"]


def test_flagget_sperrer_ikke_utkastet():
    """Advarsel, ikke sperre: å forkaste alt med tall ville tømt bunken, og et
    tall kan være riktig selv om kilde-linja er formulert annerledes."""
    from brandpost import cli
    posts = [{"headline": "A", "body": "15,7 milliarder.", "kilder": [], "emne": "x"}]
    cli._flagg_udekkede_tall(posts)
    beholdt = cli._guard_topics(posts, {"hard": [], "soft": []})
    assert len(beholdt) == 1


def test_kildekravet_sier_at_nettsoek_mangler():
    """Prompten ba før om «URL fra nettsøk» i en kjøring UTEN nettsøk. Den
    motsigelsen er grunnen til at modellen fant på URL-er."""
    from brandpost import cli
    assert "DU HAR IKKE NETTSØK" in cli._RUN_SYSTEM
    assert "Skriv ALDRI en URL du ikke har fått i konteksten" in cli._RUN_SYSTEM


def test_laasen_slippes_ogsaa_naar_genereringen_kaster(tmp_path, monkeypatch):
    """Låsen ble før bare sluppet i suksess-veien, så en ModelError blokkerte alt
    påfyll til 15-minutters foreldelsen slo inn. Det skjedde første gang
    bunke-modus møtte ekte data: ti utkast sprengte modell-timeouten."""
    from brandpost import cli
    monkeypatch.setenv("BRANDPOST_WORKSPACE", str(tmp_path))
    import os as _os
    laasdir = store.socials_dir(tmp_path) / ".bunke-paafyll"
    laasdir.mkdir(parents=True, exist_ok=True)
    laas = laasdir / f"{_os.getpid()}.lock"
    laas.write_text("")

    def _sprekk(args):
        raise RuntimeError("modellen svarte ikke")
    monkeypatch.setattr(cli, "_cmd_run", _sprekk)

    class A:
        bunke = 10
        vault = str(tmp_path)
    with pytest.raises(RuntimeError):
        cli.cmd_run(A())
    assert not laas.exists(), "låsen henger etter en feilet kjøring"


def test_timeouten_skalerer_med_bunkestoerrelsen(monkeypatch, tmp_path):
    """Ett utkast trenger ikke fem minutter; ti trenger mer enn fem."""
    from brandpost import cli
    monkeypatch.setenv("BRANDPOST_WORKSPACE", str(tmp_path))
    sett: dict = {}

    from brandpost import model as loop_model
    def _fanger(system, user, schema, label="", timeout=300, model=None):
        sett["timeout"] = timeout
        return {"structured_output": {"posts": []}}
    monkeypatch.setattr(loop_model, "structured_call", _fanger)

    class A:
        brand = "demo"
        n = 3
        days = 5
        dry_run = True
        bunke = 10
        vault = str(tmp_path)
    cli.cmd_run(A())
    assert sett["timeout"] >= 1200, "ti utkast må få rikelig over standardtimeouten"


# ── Tidsvelger og tavle ──────────────────────────────────────────────────────

def test_ledige_tider_er_publiseringsdager_med_opptatte_merket(tmp_path, monkeypatch):
    """Et fritt datofelt lot to innlegg havne på samme dag uten at det var synlig
    før etterpå. Nedtrekket viser hele bildet mens du velger."""
    monkeypatch.setenv("BRANDPOST_WORKSPACE", str(tmp_path))
    from web import app as somemod
    from brandpost import plan as planmod

    ledige = somemod._ledige_tider(tmp_path)
    assert ledige, "ingen kommende publiseringsdager"
    # Kun faktiske publiseringsdager, aldri helg
    for t in ledige:
        d = datetime.strptime(t["verdi"][:10], "%Y-%m-%d").date()
        assert d.weekday() in planmod.POST_DAYS
        assert d > date.today()
    assert all(not t["opptatt"] for t in ledige)


def test_opptatt_dag_merkes_med_hva_som_ligger_der(tmp_path, monkeypatch):
    monkeypatch.setenv("BRANDPOST_WORKSPACE", str(tmp_path))
    from web import app as somemod
    forste = somemod._ledige_tider(tmp_path)[0]["verdi"][:10]
    _dag(tmp_path, "2026-01-02", [{"headline": "Allerede booket", "status": "planlagt",
                                   "scheduled_at": f"{forste}T10:00"}])
    ledige = somemod._ledige_tider(tmp_path)
    treff = [t for t in ledige if t["verdi"][:10] == forste]
    assert treff and treff[0]["opptatt"]
    assert treff[0]["hva"] == "Allerede booket"
    # og forvalget skal hoppe over den
    assert somemod._neste_postdag(tmp_path) != forste


def test_tavla_deler_i_denne_uka_senere_og_ute(tmp_path, monkeypatch):
    monkeypatch.setenv("BRANDPOST_WORKSPACE", str(tmp_path))
    from web import app as somemod
    idag = date.today()
    senere = idag + timedelta(days=30)
    _dag(tmp_path, "2026-01-02", [
        {"headline": "Ute nå", "status": "published", "brand": "demo",
         "published_at": f"{(idag - timedelta(days=3)).isoformat()}T10:00"},
        {"headline": "Langt fram", "status": "planlagt", "brand": "demo",
         "scheduled_at": f"{senere.isoformat()}T10:00"},
        {"headline": "Bare et forslag", "status": "proposed", "brand": "demo"},
    ])
    ctx = somemod._tavle_ctx(tmp_path, "demo")
    alle = [r["headline"] for k in ctx["kolonner"].values() for r in k]
    assert "Ute nå" in alle
    assert "Langt fram" in alle
    # Forslag hører hjemme i bunken, ikke på tavla
    assert "Bare et forslag" not in alle
    assert [r["headline"] for r in ctx["kolonner"]["senere"]] == ["Langt fram"]


def test_tavla_svarer(bunke_client):
    client, _, _ = bunke_client
    r = client.get("/some/tavle")
    assert r.status_code == 200
    assert "Tavla" in r.text


# ── Datoer i fortiden ────────────────────────────────────────────────────────
# 31. juli 2026 ble et innlegg planlagt til 2025-07-31 (feil år i det frie
# datofeltet). Publisher nektet med rette å legge ut noe tolv måneder på
# etterskudd, så det ble bare liggende, og tavla viste det som «ute».

def test_planlegging_bakover_avvises(bunke_client):
    client, _, mpath = bunke_client
    r = client.post("/some/api/bunke/2026-07-31/1/like",
                    data={"when": "2025-07-31T15:15"})
    assert "tilbake i tid" in r.text
    d = json.loads(mpath.read_text(encoding="utf-8"))["drafts"][0]
    assert d["status"] == "proposed", "utkastet skal ikke ha blitt planlagt"
    assert "scheduled_at" not in d


def test_det_frie_feltet_valideres_ogsaa(bunke_client):
    """Nedtrekket kan ikke gi fortid, men det frie feltet kan. Det var nettopp
    der feilen kom inn."""
    client, _, mpath = bunke_client
    r = client.post("/some/api/bunke/2026-07-31/1/like",
                    data={"when": "2030-01-01T10:00",       # gyldig i nedtrekket
                          "when_egen": "2020-01-01T10:00"})  # men fritt felt vinner
    assert "tilbake i tid" in r.text
    d = json.loads(mpath.read_text(encoding="utf-8"))["drafts"][0]
    assert d["status"] == "proposed"


def test_kalenderens_planlegg_knapp_avviser_ogsaa_fortid(bunke_client):
    """Samme hull fantes i «Aksepter og planlegg» på kalendersiden, og det var
    faktisk den knappen som slapp 2025-datoen gjennom."""
    client, _, mpath = bunke_client
    r = client.post("/some/api/draft/2026-07-31/1/schedule",
                    data={"when": "2025-07-31T15:15"})
    assert "tilbake i tid" in r.text
    d = json.loads(mpath.read_text(encoding="utf-8"))["drafts"][0]
    assert d["status"] == "proposed"


def test_tavla_skiller_forfalt_fra_publisert(tmp_path, monkeypatch):
    """Et planlagt innlegg med passert tidspunkt er strandet, ikke ute. Blandet
    inn i «ute» så det ut som om alt hadde gått fint."""
    monkeypatch.setenv("BRANDPOST_WORKSPACE", str(tmp_path))
    from web import app as somemod
    igaar = (date.today() - timedelta(days=1)).isoformat()
    _dag(tmp_path, "2026-01-02", [
        {"headline": "Strandet", "status": "planlagt", "brand": "demo",
         "scheduled_at": f"{igaar}T10:00"},
        {"headline": "Faktisk ute", "status": "published", "brand": "demo",
         "published_at": f"{igaar}T10:00"},
    ])
    k = somemod._tavle_ctx(tmp_path, "demo")["kolonner"]
    assert [r["headline"] for r in k["forfalt"]] == ["Strandet"]
    assert [r["headline"] for r in k["ute"]] == ["Faktisk ute"]
    assert k["forfalt"][0]["dager_siden"] == 1


def test_ingen_hurtigtaster_i_bunken(bunke_client):
    """Piltastene var raske, men en swipe lagrer en dom du ikke ser igjen, og de
    kolliderte med den naturlige måten å bla i karusell-slidene på: du kunne stå
    og lese side tre og plutselig ha sagt nei til hele innlegget (Oscar 31. juli).
    Hver dom skal kreve et bevisst klikk."""
    client, _, _ = bunke_client
    r = client.get("/some/bunke")
    assert "ArrowLeft" not in r.text
    assert "ArrowRight" not in r.text
    assert "keydown" not in r.text


# ── Flere merker deler ikke karantene ────────────────────────────────────────

def test_karantenen_er_per_merke(tmp_path):
    """To selskaper som skriver om samme fagfelt har hver sine følgere og hver sin
    plan. At det ene har brukt en vinkel er ingen grunn til at det andre ikke kan.

    Karantenen var global til 2. august 2026, og ville sperret Vitandi fra alt
    Tilskudd.ai hadde skrevet om."""
    _dag(tmp_path, "2026-07-28", [
        {"emne": "skattefunn-frist", "brand": "tilskudd", "status": "planlagt",
         "scheduled_at": "2026-07-29T10:00"},
        {"emne": "egen-vinkel", "brand": "vitandi", "status": "planlagt",
         "scheduled_at": "2026-07-29T10:00"},
    ])
    tilskudd = store.blocked_topics(tmp_path, now=NOW, brand_key="tilskudd")
    vitandi = store.blocked_topics(tmp_path, now=NOW, brand_key="vitandi")

    assert tilskudd["hard"] == ["skattefunn-frist"]
    assert vitandi["hard"] == ["egen-vinkel"]
    # uten merke: alt, som før (brukes av verktøy som vil se hele bildet)
    assert set(store.blocked_topics(tmp_path, now=NOW)["hard"]) == {
        "skattefunn-frist", "egen-vinkel"}


def test_avviste_forslag_er_ogsaa_per_merke(tmp_path):
    _dag(tmp_path, "2026-07-30", [
        {"headline": "Tilskudds nei", "brand": "tilskudd", "emne": "a",
         "verdict": "passed", "verdict_at": "2026-07-30T09:00"},
        {"headline": "Vitandis nei", "brand": "vitandi", "emne": "b",
         "verdict": "passed", "verdict_at": "2026-07-30T09:00"},
    ])
    ut = store.rejected_recently(tmp_path, now=NOW, brand_key="vitandi")
    assert [x["headline"] for x in ut] == ["Vitandis nei"]


def test_tidsvelgeren_er_per_merke(tmp_path, monkeypatch):
    """To selskaper har hver sin firmaside og hver sine følgere, så at det ene
    poster mandag er ingen grunn til at det andre ikke kan. Uten merke-filter
    blokkerte Tilskudd.ai alle datoer for Vitandi, og Vitandi kunne ikke
    planlegges i det hele tatt (Oscar 2. august)."""
    monkeypatch.setenv("BRANDPOST_WORKSPACE", str(tmp_path))
    from web import app as somemod

    forste = somemod._ledige_tider(tmp_path)[0]["verdi"][:10]
    _dag(tmp_path, "2026-01-02", [{"headline": "Tilskudds innlegg", "brand": "tilskudd",
                                   "status": "planlagt",
                                   "scheduled_at": f"{forste}T10:00"}])

    tilskudd = somemod._ledige_tider(tmp_path, brand_key="tilskudd")
    vitandi = somemod._ledige_tider(tmp_path, brand_key="vitandi")

    assert [t for t in tilskudd if t["verdi"][:10] == forste][0]["opptatt"] is True
    assert [t for t in vitandi if t["verdi"][:10] == forste][0]["opptatt"] is False
    # forvalget skal hoppe over for tilskudd, men ikke for vitandi
    assert somemod._neste_postdag(tmp_path, "tilskudd") != forste
    assert somemod._neste_postdag(tmp_path, "vitandi") == forste


def test_velgeren_strekker_seg_til_den_finner_ledige_dager(tmp_path, monkeypatch):
    """Er de neste ukene fylt opp, må lista gå lenger fram. 2. august sto eieren
    med elleve valg der alle var grå, og ingen vei videre."""
    monkeypatch.setenv("BRANDPOST_WORKSPACE", str(tmp_path))
    from web import app as somemod

    # Fyll opp alle publiseringsdager de neste seks ukene
    booket = []
    dag = date.today() + timedelta(days=1)
    for _ in range(42):
        from brandpost import plan as planmod
        if dag.weekday() in planmod.POST_DAYS:
            booket.append({"headline": f"Booket {dag}", "brand": "demo",
                           "status": "planlagt", "scheduled_at": f"{dag.isoformat()}T10:00"})
        dag += timedelta(days=1)
    _dag(tmp_path, "2026-01-02", booket)

    ledige = somemod._ledige_tider(tmp_path, antall=3, brand_key="demo")
    frie = [t for t in ledige if not t["opptatt"]]
    assert len(frie) >= 3, "velgeren ga ingen ledige dager selv om det finnes senere"
    # og forvalget skal peke på en av dem
    assert somemod._neste_postdag(tmp_path, "demo") == frie[0]["verdi"][:10]
