"""Dashbord v2: sletting, rydding, rettelser i regenerering og merkevalg.

eierens bestilling 23. juli 2026. Ingen nett: bildemotoren og LinkedIn mockes.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from brandpost import publisher, render, store


def _manifest(tmp_path: Path, drafts: list[dict], day: str = "2026-07-23") -> Path:
    d = tmp_path / "socials" / day
    d.mkdir(parents=True)
    (d / "manifest.json").write_text(json.dumps({"drafts": drafts}, ensure_ascii=False),
                                     encoding="utf-8")
    return d / "manifest.json"


# ── sletting ────────────────────────────────────────────────

def test_sletting_flytter_filene_til_papirkurven(tmp_path):
    mpath = _manifest(tmp_path, [{"nr": 1, "headline": "H", "status": "proposed"}])
    png = mpath.parent / "post-1.png"
    png.write_bytes(b"bilde")
    manifest = json.loads(mpath.read_text())
    manifest["drafts"][0]["png_path"] = str(png)

    res = store.trash_draft(mpath, manifest, 0, when=datetime(2026, 7, 23, 12, 0))

    assert res["slettet"] is True
    assert not png.exists(), "fila skal være flyttet ut av dagsmappa"
    kurv = Path(res["kurv"])
    assert (kurv / "post-1.png").read_bytes() == b"bilde", "bildet skal kunne hentes tilbake"
    assert json.loads((kurv / "utkast.json").read_text())["headline"] == "H"
    assert json.loads(mpath.read_text())["drafts"] == []


def test_publisert_utkast_slettes_aldri(tmp_path):
    mpath = _manifest(tmp_path, [{"nr": 1, "headline": "ute", "status": "published",
                                  "linkedin_url": "https://li/1"}])
    manifest = json.loads(mpath.read_text())

    res = store.trash_draft(mpath, manifest, 0)

    assert res["slettet"] is False
    assert json.loads(mpath.read_text())["drafts"][0]["status"] == "published"


def test_slettbare_utelater_publiserte(tmp_path):
    _manifest(tmp_path, [
        {"nr": 1, "headline": "utkast", "status": "proposed", "brand": "demo"},
        {"nr": 2, "headline": "planlagt", "status": "planlagt", "brand": "demo"},
        {"nr": 3, "headline": "ute", "status": "published", "brand": "demo"},
    ])
    rader = store.deletable_drafts(tmp_path)
    assert [r["nr"] for r in rader] == [1, 2]


# ── rettelser i bilde-prompten ──────────────────────────────

def test_rettelser_havner_i_motiv_prompten():
    ut = render.with_corrections("to søyler på sand", ["feil grønnfarge", "formen ser rar ut"])
    assert "to søyler på sand" in ut
    assert "feil grønnfarge" in ut and "formen ser rar ut" in ut


def test_alle_rettelser_folger_med_ikke_bare_den_nyeste():
    # Et problem du har påpekt én gang skal ikke komme tilbake ved neste forsøk.
    ut = render.with_corrections("motiv", ["ikke bruk kapsel-form", "feil grønn"])
    assert "ikke bruk kapsel-form" in ut


def test_rettelser_kappes_saa_prompten_ikke_drukner():
    mange = [f"rettelse {i}" for i in range(12)]
    ut = render.with_corrections("motiv", mange)
    assert ut.count("- rettelse") == render.MAX_CORRECTIONS
    assert "rettelse 11" in ut and "rettelse 0" not in ut   # nyeste beholdes


def test_uten_rettelser_er_motivet_urort():
    assert render.with_corrections("bare motiv", []) == "bare motiv"
    assert render.with_corrections("bare motiv", None) == "bare motiv"


# ── publisering varsler ALLTID, uansett hvem som ba om den ──

def test_publiser_ett_sender_epost_og_markerer(tmp_path, monkeypatch):
    """Dashbordets Publiser-knapp postet uten å varsle (eieren fikk ingen e-post
    23. juli). Begge veiene går nå gjennom denne ene funksjonen."""
    mpath = _manifest(tmp_path, [{"nr": 1, "headline": "H", "status": "proposed"}])
    manifest = json.loads(mpath.read_text())
    monkeypatch.setattr(publisher.linkedin, "publish_draft",
                        lambda d, dry_run=None: {"posted": True, "url": "https://li/7"})
    sendt: dict = {}
    monkeypatch.setattr(publisher, "_publisert_epost",
                        lambda d, url, **k: sendt.update(url=url) or {"sent": True})

    res = publisher.publiser_ett(mpath, manifest, 0, manifest["drafts"][0], vault=tmp_path)

    assert res["posted"] and res["epost"] == "sendt"
    assert sendt == {"url": "https://li/7"}
    assert json.loads(mpath.read_text())["drafts"][0]["status"] == "published"


def test_epostfeil_velter_ikke_en_vellykket_publisering(tmp_path, monkeypatch):
    mpath = _manifest(tmp_path, [{"nr": 1, "headline": "H", "status": "proposed"}])
    manifest = json.loads(mpath.read_text())
    monkeypatch.setattr(publisher.linkedin, "publish_draft",
                        lambda d, dry_run=None: {"posted": True, "url": "https://li/7"})

    def _sprekk(*a, **k):
        raise RuntimeError("SMTP nede")
    monkeypatch.setattr(publisher, "_publisert_epost", _sprekk)

    res = publisher.publiser_ett(mpath, manifest, 0, manifest["drafts"][0], vault=tmp_path)

    assert res["posted"] is True, "innlegget ER ute, e-posten skal ikke rulle det tilbake"
    assert "feilet" in res["epost"]
    assert json.loads(mpath.read_text())["drafts"][0]["status"] == "published"


# ── planen skal ikke lyve etter sletting ────────────────────

def test_slettet_utkast_frigjor_dagen_i_planen(tmp_path):
    """En slot merkes «utkast» når den er fylt. Slettes utkastet, må slotten bli
    åpen igjen, ellers ser dagen fylt ut, generatoren hopper over den, og dagen
    forblir tom uten at noe feiler."""
    from brandpost import plan as planmod
    d = tmp_path / "socials"
    d.mkdir(parents=True)
    (d / "plan.json").write_text(json.dumps({"weeks": [], "slots": [
        {"date": "2026-07-28", "brand": "demo", "status": "utkast",
         "draft_ref": {"manifest": "2026-07-28", "nr": 1}},
        {"date": "2026-07-29", "brand": "demo", "status": "publisert",
         "draft_ref": {"manifest": "2026-07-29", "nr": 1}},
    ]}, ensure_ascii=False), encoding="utf-8")

    frigjort = planmod.reconcile_slots(tmp_path)   # ingen manifester finnes

    assert frigjort == ["2026-07-28"]
    slots = json.loads((d / "plan.json").read_text())["slots"]
    assert slots[0]["status"] == "planlagt" and "draft_ref" not in slots[0]
    assert slots[1]["status"] == "publisert", "publiserte dager røres aldri"


def test_slot_med_levende_utkast_rores_ikke(tmp_path):
    from brandpost import plan as planmod
    _manifest(tmp_path, [{"nr": 1, "headline": "lever", "status": "proposed"}],
              day="2026-07-28")
    (tmp_path / "socials" / "plan.json").write_text(json.dumps(
        {"weeks": [], "slots": [{"date": "2026-07-28", "brand": "demo",
                                 "status": "utkast",
                                 "draft_ref": {"manifest": "2026-07-28", "nr": 1}}]},
        ensure_ascii=False), encoding="utf-8")

    assert planmod.reconcile_slots(tmp_path) == []


# ── publiserte hører hjemme på dagen de faktisk gikk ut ─────

def test_publisert_vises_paa_publiseringsdagen(tmp_path):
    from web import app as somemod
    # Laget 24. juli, gikk ut 23. juli (eieren trykte publiser dagen før mappa tilsier).
    d = {"status": "published", "published_at": "2026-07-23T09:44"}
    assert somemod.visningsdag(d, "2026-07-24") == "2026-07-23"


def test_publisert_uten_tidspunkt_faller_til_dagsmappa(tmp_path):
    from web import app as somemod
    # Vi skriver ALDRI en dato vi ikke vet: da er dagsmappa det ærligste vi har.
    assert somemod.visningsdag({"status": "published"}, "2026-07-24") == "2026-07-24"


def test_planlagt_vises_fortsatt_paa_utsendelsesdagen(tmp_path):
    from web import app as somemod
    d = {"status": "planlagt", "scheduled_at": "2026-07-28T10:00"}
    assert somemod.visningsdag(d, "2026-07-23") == "2026-07-28"


def test_mark_published_lagrer_tidspunktet(tmp_path):
    mpath = _manifest(tmp_path, [{"nr": 1, "headline": "H", "status": "proposed"}])
    manifest = json.loads(mpath.read_text())
    store.mark_published(mpath, manifest, 0, "https://li/1",
                         when=datetime(2026, 7, 23, 9, 44))
    d = json.loads(mpath.read_text())["drafts"][0]
    assert d["published_at"] == "2026-07-23T09:44"


def test_backfill_henter_tidspunkt_fra_linkedin(tmp_path):
    """Innlegg publisert før vi begynte å lagre tidspunktet: fasit hentes fra
    LinkedIn, ikke gjettes ut fra hvilken dagsmappe utkastet lå i."""
    _manifest(tmp_path, [
        {"nr": 1, "headline": "ute", "status": "published",
         "linkedin_url": "https://www.linkedin.com/feed/update/urn:li:activity:7485660656504070144/"},
        {"nr": 2, "headline": "utkast", "status": "proposed"},
    ], day="2026-07-27")
    # LinkedIn kaller det samme innlegget ugcPost, vi lagret activity: samme tall.
    hentet = [{"id": "urn:li:ugcPost:7485660656504070144",
               "publishedAt": int(datetime(2026, 7, 22, 13, 42).timestamp() * 1000)}]

    fylt = publisher.backfill_published_at(tmp_path, hentet=hentet)

    assert fylt == ["2026-07-27#1"]
    drafts = json.loads((tmp_path / "socials" / "2026-07-27" /
                         "manifest.json").read_text())["drafts"]
    assert drafts[0]["published_at"] == "2026-07-22T13:42"
    assert "published_at" not in drafts[1], "upubliserte skal ikke få tidspunkt"


def test_backfill_gjetter_aldri_naar_linkedin_ikke_kjenner_innlegget(tmp_path):
    mpath = _manifest(tmp_path, [{"nr": 1, "headline": "ute", "status": "published",
                                  "linkedin_url": "https://li/urn:li:share:999"}])
    assert publisher.backfill_published_at(tmp_path, hentet=[]) == []
    assert "published_at" not in json.loads(mpath.read_text())["drafts"][0]


def test_backfill_matcher_paa_tekst_naar_id_ene_er_ulike(tmp_path):
    """LinkedIn gir SAMME innlegg ulike ID-er: vi lagret urn:li:activity:… mens
    API-et svarer urn:li:share:… med et helt annet tall. Da må teksten avgjøre."""
    _manifest(tmp_path, [{"nr": 1, "headline": "ute", "status": "published",
                          "body": "Ordet «forskning» skremmer bort halvparten av dem som kvalifiserer.",
                          "linkedin_url": "https://li/urn:li:activity:7485660656504070144"}],
              day="2026-07-27")
    hentet = [{"id": "urn:li:share:7485639979361198080",
               "commentary": "Ordet «forskning» skremmer bort halvparten av dem som kvalifiserer.",
               "publishedAt": int(datetime(2026, 7, 22, 13, 42).timestamp() * 1000)}]

    assert publisher.backfill_published_at(tmp_path, hentet=hentet) == ["2026-07-27#1"]
    d = json.loads((tmp_path / "socials" / "2026-07-27" /
                    "manifest.json").read_text())["drafts"][0]
    assert d["published_at"] == "2026-07-22T13:42"


def test_backfill_velger_ikke_naar_teksten_passer_paa_flere(tmp_path):
    """To innlegg som starter likt: da vet vi ikke hvilket det er, og skal la være."""
    mpath = _manifest(tmp_path, [{"nr": 1, "headline": "ute", "status": "published",
                                  "body": "Samme åpning på begge to.",
                                  "linkedin_url": "https://li/ukjent"}])
    naa = int(datetime(2026, 7, 22, 13, 42).timestamp() * 1000)
    hentet = [{"id": "urn:li:share:1", "commentary": "Samme åpning på begge to.",
               "publishedAt": naa},
              {"id": "urn:li:share:2", "commentary": "Samme åpning på begge to.",
               "publishedAt": naa}]

    assert publisher.backfill_published_at(tmp_path, hentet=hentet) == []
    assert "published_at" not in json.loads(mpath.read_text())["drafts"][0]


# ── karusell kan planlegges som alt annet ───────────────────

def test_karusell_kan_planlegges(tmp_path):
    """Karusell ble utelatt fra planlegging da LinkedIn eide utsendelsen og
    nettleser-composeren ikke kunne lage dokumentinnlegg. Nå publiserer vi selv,
    og PDF-veien har ligget der hele tiden."""
    from web import app as somemod
    dag = tmp_path / "socials" / "2026-07-27"
    dag.mkdir(parents=True)
    (dag / "forside.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    d = {"nr": 4, "headline": "1. september, forklart", "type": "karusell",
         "status": "proposed", "cover_path": str(dag / "forside.png"),
         "pdf_path": str(dag / "karusell.pdf")}

    ctx = somemod._card_ctx(tmp_path, "2026-07-27", d)

    assert ctx["is_karusell"] is True
    assert ctx["can_schedule"] is True, "karusell skal kunne få et tidspunkt"


def test_publisert_karusell_kan_ikke_planlegges(tmp_path):
    from web import app as somemod
    dag = tmp_path / "socials" / "2026-07-27"
    dag.mkdir(parents=True)
    (dag / "forside.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    d = {"nr": 4, "headline": "ute", "type": "karusell", "status": "published",
         "cover_path": str(dag / "forside.png")}

    assert somemod._card_ctx(tmp_path, "2026-07-27", d)["can_schedule"] is False


def test_planlagt_karusell_publiseres_av_jobben(tmp_path, monkeypatch):
    """Hele poenget med å tillate planlegging: jobben må faktisk legge den ut."""
    kar = {"nr": 1, "headline": "K", "body": "kropp", "type": "karusell",
           "status": "planlagt", "scheduled_at": "2026-07-23T10:00",
           "pdf_path": str(tmp_path / "k.pdf"), "brand": "demo"}
    mpath = _manifest(tmp_path, [kar])
    sett: list = []
    monkeypatch.setattr(publisher.linkedin, "publish_draft",
                        lambda d, dry_run=None: sett.append(d.get("type"))
                        or {"posted": True, "url": "https://li/doc"})
    monkeypatch.setattr(publisher, "_publisert_epost", lambda d, url, **k: {"sent": True})

    tall = publisher.publish_due(tmp_path, now=datetime(2026, 7, 23, 11, 0))

    assert tall["publisert"] == 1 and sett == ["karusell"]
    assert json.loads(mpath.read_text())["drafts"][0]["status"] == "published"
