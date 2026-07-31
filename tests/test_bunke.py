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
from datetime import datetime
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


def test_forslag_uten_dom_sperrer_ingenting(tmp_path):
    """Et utkast som bare ligger der, verken likt eller avvist, skal ikke stenge
    emnet sitt. Det var nettopp den feilen recent_angles gjorde."""
    _dag(tmp_path, "2026-07-30", [{"emne": "urørt", "status": "proposed"}])
    res = store.blocked_topics(tmp_path, now=NOW)
    assert res == {"hard": [], "soft": []}


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
    # Bildet finnes ikke ennå, så motivet må beskrives i stedet.
    assert "Tenkt bilde" in r.text


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


def test_vurderte_utkast_forsvinner_fra_bunken(bunke_client):
    client, tmp_path, mpath = bunke_client
    client.post("/some/api/bunke/2026-07-31/1/pass")
    client.post("/some/api/bunke/2026-07-31/2/pass")
    r = client.get("/some/bunke")
    assert "Bunken er tom" in r.text
    assert store.unjudged_drafts(tmp_path) == []


def test_kalenderen_har_lenke_til_bunken(bunke_client):
    client, _, _ = bunke_client
    r = client.get("/some")
    assert "/some/bunke" in r.text
