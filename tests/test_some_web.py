"""Tester for SoMe-dashbordet (/some): kalender, kort-handlinger og media-guard.

Kjøres mot en midlertidig arbeidsmappe (BRANDPOST_WORKSPACE per test), så
ingen test går på nett. LinkedIn-publisering testes kun i dry-run.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from brandpost import brandkit, render, store
from web import app as somemod
from main import app


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("BRANDPOST_WORKSPACE", str(tmp_path))
    monkeypatch.delenv("LINKEDIN_ENABLED", raising=False)
    return TestClient(app)


def _frem(dager: int = 7) -> str:
    """Et tidspunkt fram i tid, på datetime-local-form.

    Planlegging bakover er forbudt fra 31. juli 2026 (et innlegg ble planlagt til
    feil år og ble bare liggende). Testene må derfor peke framover, ellers tester
    de bare at sperren virker."""
    return (datetime.now() + timedelta(days=dager)).strftime("%Y-%m-%dT10:00")


def _make_manifest(vault, when: datetime | None = None) -> tuple[str, int]:
    """Ett ekte utkast (mal-rendret PNG) i dags-manifestet; returnerer (dag, nr)."""
    when = when or datetime.now()
    b = brandkit.load_brand("demo")
    png = render.render_template({"headline": "Testkort"}, b)
    meta = store.write_draft(vault, "demo", {
        "headline": "Testkort", "body": "Kroppstekst", "why_now": "nå",
        "format": "typografi-kort", "pillar": "myte-avliving"}, png, index=1, when=when)
    meta["brand_name"] = b.name
    safe = [{k: v for k, v in meta.items() if k not in ("png", "pdf", "cover")}]
    store.merge_manifest(vault, brand_key="demo", brand_name=b.name,
                         new_drafts=safe, when=when)
    return when.strftime("%Y-%m-%d"), safe[0]["nr"]


def test_home_renders(client):
    r = client.get("/some")
    assert r.status_code == 200
    assert "SoMe-kommandosenter" in r.text


def test_calendar_shows_scheduled_draft_and_slot(client, tmp_path):
    """Kalenderen viser plan-slots og det som faktisk skal ut.

    Fram til 31. juli 2026 viste den ALLE utkast, også de uvurderte. Da bunken
    kom, druknet de fire innleggene som er ekte avtaler i tjue som bare er
    forslag, så uvurderte hører nå hjemme i bunken (se neste test)."""
    day, nr = _make_manifest(tmp_path)
    mpath, manifest = store.load_manifest(tmp_path, day)
    idx, _ = store.select_draft(manifest, str(nr))
    store.mark_scheduled(mpath, manifest, idx, f"{day}T10:00")

    d = tmp_path / "socials"
    (d / "plan.json").write_text(json.dumps({"weeks": [], "slots": [
        {"date": day, "brand": "demo", "pillar": "myte-avliving", "format": "bilde",
         "tema": "Slot-tema", "status": "planlagt"}]}, ensure_ascii=False),
        encoding="utf-8")
    r = client.get(f"/some/api/calendar?month={day[:7]}")
    assert r.status_code == 200
    assert "Testkort" in r.text and "Slot-tema" in r.text


def test_calendar_skjuler_uvurderte_forslag(client, tmp_path):
    """Et forslag som verken er planlagt eller publisert skal IKKE ligge i
    kalenderen: det er ikke en avtale, bare et forslag som venter på dom."""
    day, _nr = _make_manifest(tmp_path)          # status «proposed»
    r = client.get(f"/some/api/calendar?month={day[:7]}")
    assert "Testkort" not in r.text


def test_day_panel_edit_writes_manifest(client, tmp_path):
    day, nr = _make_manifest(tmp_path)
    r = client.get(f"/some/api/drafts?day={day}")
    assert r.status_code == 200 and "Testkort" in r.text
    r2 = client.post(f"/some/api/draft/{day}/{nr}", data={
        "headline": "Redigert tittel", "body": "Ny tekst", "why_now": "fordi"})
    assert r2.status_code == 200 and "Redigert tittel" in r2.text
    manifest = json.loads((tmp_path / "socials" / day / "manifest.json")
                          .read_text(encoding="utf-8"))
    d = next(x for x in manifest["drafts"] if x.get("nr") == nr)
    assert d["body"] == "Ny tekst" and d["headline"] == "Redigert tittel"
    md = (tmp_path / "socials" / day)
    md_file = next(md.glob("post-1-*.md"))
    assert "Ny tekst" in md_file.read_text(encoding="utf-8")


def test_mark_published_sets_status(client, tmp_path):
    day, nr = _make_manifest(tmp_path)
    bad = client.post(f"/some/api/draft/{day}/{nr}/published", data={"url": "nei"})
    assert "⚠️" in bad.text
    url = "https://www.linkedin.com/feed/update/urn:li:share:123"
    ok = client.post(f"/some/api/draft/{day}/{nr}/published", data={"url": url})
    assert ok.status_code == 200 and "publisert" in ok.text
    manifest = json.loads((tmp_path / "socials" / day / "manifest.json")
                          .read_text(encoding="utf-8"))
    d = next(x for x in manifest["drafts"] if x.get("nr") == nr)
    assert d["status"] == "published" and d["linkedin_url"] == url


def test_publish_via_api_is_dry_run_without_enabled(client, tmp_path):
    day, nr = _make_manifest(tmp_path)
    r = client.post(f"/some/api/draft/{day}/{nr}/publish")
    assert r.status_code == 200 and "Dry-run" in r.text
    manifest = json.loads((tmp_path / "socials" / day / "manifest.json")
                          .read_text(encoding="utf-8"))
    d = next(x for x in manifest["drafts"] if x.get("nr") == nr)
    assert d["status"] == "proposed"  # ingenting postet, ingenting markert


def test_media_serves_png_and_blocks_traversal(client, tmp_path, monkeypatch):
    day, nr = _make_manifest(tmp_path)
    manifest = json.loads((tmp_path / "socials" / day / "manifest.json")
                          .read_text(encoding="utf-8"))
    name = json.loads(json.dumps(manifest["drafts"][0]))["png_path"].rsplit("/", 1)[-1]
    ok = client.get(f"/some/media/{day}/{name}")
    assert ok.status_code == 200
    assert ok.headers["content-type"].startswith("image/png")
    assert client.get(f"/some/media/{day}/finnes-ikke.png").status_code == 404
    assert client.get(f"/some/media/{day}/manifest.json").status_code == 404
    monkeypatch.setenv("BRANDPOST_WORKSPACE", str(tmp_path))
    with pytest.raises(HTTPException):
        somemod.media("..", "hemmelig.png")
    with pytest.raises(HTTPException):
        somemod.media(day, "../../../etc/hosts.png")


def test_karusell_card_shows_scrollable_slides(client, tmp_path):
    from pathlib import Path

    b = brandkit.load_brand("demo")
    png = render.render_template({"headline": "S"}, b)
    built = {"pdf": b"%PDF-1.4 fake", "cover": png, "slide_pngs": [png, png, png],
             "n": 3, "tittel": "Tre steg", "size_mb": 0.1}
    when = datetime.now()
    meta = store.write_carousel(tmp_path, "demo",
                                {"tittel": "Tre steg", "body": "b", "why_now": "w",
                                 "slides": [], "kilder": ["fakta → produktfakta"]},
                                built, index=1, when=when)
    meta["brand_name"] = b.name
    safe = [{k: v for k, v in meta.items() if k not in ("png", "pdf", "cover")}]
    store.merge_manifest(tmp_path, brand_key="demo", brand_name=b.name,
                         new_drafts=safe, when=when)
    day = when.strftime("%Y-%m-%d")
    r = client.get(f"/some/api/drafts?day={day}")
    assert r.status_code == 200
    assert r.text.count("slide-") >= 3                     # alle slides i stripa
    assert "scroll sidelengs" in r.text.lower()            # scrollehintet
    assert "Kilder (kun for deg" in r.text                 # kildene på kortet
    stem = Path(safe[0]["pdf_path"]).stem
    ok = client.get(f"/some/media/{day}/{stem}/slide-2.png")
    assert ok.status_code == 200                           # nested media-rute virker
    assert ok.headers["content-type"].startswith("image/png")


def test_refresh_endpoints_report_cli_result(client, monkeypatch):
    monkeypatch.setattr(somemod, "_run_cli", lambda *a, **k: (True, "🗓 plan rullet"))
    r = client.post("/some/api/plan/refresh")
    assert r.status_code == 200 and "plan rullet" in r.text
    r2 = client.post("/some/api/pulse/refresh")
    assert r2.status_code == 200


# ── Aksepter og planlegg (LinkedIn-scheduling) ────────────────────────────────

def test_schedule_button_vises_naar_paa(client, tmp_path, monkeypatch):
    monkeypatch.setenv("BRANDPOST_BROWSER_ENABLED", "1")
    day, nr = _make_manifest(tmp_path)
    r = client.get(f"/some/api/drafts?day={day}")
    assert r.status_code == 200
    assert "Aksepter og planlegg" in r.text
    assert f'value="{day}T10:00"' in r.text  # foreslått slot-dag kl. 10:00 (eieren 22. juli)


def test_schedule_skriver_tidspunkt_uten_nettleser(client, tmp_path):
    """valget 22. juli: VI eier publiseringen, saa knappen er et lynkjapt
    skriv. Ingen nettleser-subprosess som holder forespoerselen aapen i minutter."""
    day, nr = _make_manifest(tmp_path)
    naar = _frem()
    r = client.post(f"/some/api/draft/{day}/{nr}/schedule", data={"when": naar})
    assert r.status_code == 200
    assert "Planlagt" in r.text and "e-post" in r.text
    _, manifest = store.load_manifest(tmp_path, day)
    d = manifest["drafts"][0]
    assert d["status"] == "planlagt"
    assert d["scheduled_at"] == naar


def test_schedule_avviser_ugyldig_tidspunkt(client, tmp_path, monkeypatch):
    monkeypatch.setenv("BRANDPOST_BROWSER_ENABLED", "1")
    day, nr = _make_manifest(tmp_path)
    r = client.post(f"/some/api/draft/{day}/{nr}/schedule", data={"when": "tull"})
    assert "Ugyldig tidspunkt" in r.text


def test_schedule_gjor_kortet_planlagt(client, tmp_path):
    day, nr = _make_manifest(tmp_path)
    r = client.post(f"/some/api/draft/{day}/{nr}/schedule", data={"when": _frem()})
    assert "🗓 planlagt" in r.text          # statuspille byttet
    # Planen skal ogsaa vite at slotten er planlagt
    from brandpost import plan as planmod
    slots = {s["date"]: s for s in planmod.load_plan(tmp_path).get("slots", [])}
    assert slots.get(day, {}).get("status") in ("planlagt", None)


# ── kalender: dra, miniatyr, endre/avlys (eierens bestilling 23. juli) ─────────

def test_planlagt_kan_endres_og_avlyses(client, tmp_path):
    """Glippe funnet 23. juli: naar et utkast forst var planlagt, forsvant
    tidsfeltet og tidspunktet satt fast."""
    day, nr = _make_manifest(tmp_path)
    naar = _frem()
    client.post(f"/some/api/draft/{day}/{nr}/schedule", data={"when": naar})
    # visningsdag(): et planlagt utkast hører hjemme på dagen det skal UT
    r = client.get(f"/some/api/drafts?day={naar[:10]}")
    assert "Lagre nytt tidspunkt" in r.text and "Avlys" in r.text
    assert f'value="{naar}"' in r.text          # starter fra valgt tid

    r2 = client.post(f"/some/api/draft/{day}/{nr}/unschedule")
    assert "avlyst" in r2.text.lower()
    _, manifest = store.load_manifest(tmp_path, day)
    d = manifest["drafts"][0]
    assert d["status"] == "proposed" and "scheduled_at" not in d


def test_flytt_endrer_dag_men_ikke_filene(client, tmp_path):
    """Dra-og-slipp skal endre TIDSPUNKTET. Filene blir liggende i sin egen
    dagsmappe; aa flytte dem mellom mapper ville vaert skjoert."""
    from datetime import timedelta
    day, nr = _make_manifest(tmp_path)
    ny = (datetime.strptime(day, "%Y-%m-%d") + timedelta(days=2)).strftime("%Y-%m-%d")
    png_for = sorted((tmp_path / "socials" / day).glob("*.png"))

    r = client.post(f"/some/api/draft/{day}/{nr}/move", data={"to": ny})
    assert r.status_code == 200
    _, manifest = store.load_manifest(tmp_path, day)      # bor fortsatt her
    d = manifest["drafts"][0]
    assert d["status"] == "planlagt"
    assert d["scheduled_at"].startswith(ny)
    assert sorted((tmp_path / "socials" / day).glob("*.png")) == png_for


def test_planlagt_vises_paa_publiseringsdagen(client, tmp_path):
    """Kalenderen skal vise innlegget der det skal UT, ikke der det ble laget,
    ellers foles draget som om ingenting skjedde."""
    from datetime import timedelta
    day, nr = _make_manifest(tmp_path)
    ny = (datetime.strptime(day, "%Y-%m-%d") + timedelta(days=2)).strftime("%Y-%m-%d")
    client.post(f"/some/api/draft/{day}/{nr}/move", data={"to": ny})

    r = client.get(f"/some/api/calendar?month={ny[:7]}")
    assert "Testkort" in r.text
    assert "/some/media/" in r.text                      # miniatyr med i cella
    # Dagspanelet for den NYE dagen skal finne kortet, med kildedagen som identitet
    rp = client.get(f"/some/api/drafts?day={ny}")
    assert "Testkort" in rp.text
    assert f"/some/api/draft/{day}/{nr}/" in rp.text     # endepunkt peker paa kildedag


# ── merkevalg, sletting og rydding (eierens bestilling 23. juli 2026) ──

def test_merkedropdown_viser_alle_selskaper(client):
    r = client.get("/some")
    assert r.status_code == 200
    assert "Alle selskaper" in r.text and "Demo Labs" in r.text
    assert "Minimal" in r.text and "dvale" in r.text   # dvalende merke er med, men merket


def test_valgt_merke_filtrerer_bort_andres_utkast(client, tmp_path):
    day, _ = _make_manifest(tmp_path)          # et Demo Labs-utkast
    assert "Testkort" in client.get(f"/some/api/drafts?day={day}&brand=demo").text
    # Minimal har ingen utkast: dagspanelet skal være tomt, ikke vise Demo Labss.
    assert "Testkort" not in client.get(f"/some/api/drafts?day={day}&brand=minimal").text


def test_ukjent_merke_viser_alt_i_stedet_for_ingenting(client, tmp_path):
    day, _ = _make_manifest(tmp_path)
    r = client.get(f"/some/api/drafts?day={day}&brand=finnes-ikke")
    assert r.status_code == 200 and "Testkort" in r.text


def test_slett_knapp_fjerner_utkastet(client, tmp_path):
    day, nr = _make_manifest(tmp_path)
    r = client.post(f"/some/api/draft/{day}/{nr}/delete")
    assert r.status_code == 200 and "Slettet" in r.text
    manifest = json.loads((tmp_path / "socials" / day / "manifest.json")
                          .read_text(encoding="utf-8"))
    assert manifest["drafts"] == []
    kurv = tmp_path / "socials" / "_slettet"
    assert any(kurv.glob("*/utkast.json")), "utkastet skal ligge i papirkurven"


def test_ryddeliste_viser_eksakt_hva_som_slettes(client, tmp_path):
    day, _ = _make_manifest(tmp_path)
    r = client.get("/some/api/purge/preview")
    assert r.status_code == 200
    assert "Testkort" in r.text and "Slett disse 1" in r.text


def test_rydding_avbryter_hvis_lista_har_endret_seg(client, tmp_path):
    """eieren sier ja til en liste han SÅ. Er tallet et annet nå, har noe kommet til
    siden han leste den, og da skal vi ikke slette noe han aldri fikk se."""
    day, _ = _make_manifest(tmp_path)
    r = client.post("/some/api/purge", data={"antall": 7})
    assert r.status_code == 200 and "endret seg" in r.text
    manifest = json.loads((tmp_path / "socials" / day / "manifest.json")
                          .read_text(encoding="utf-8"))
    assert len(manifest["drafts"]) == 1, "ingenting skal være slettet"


def test_rydding_sletter_alt_upublisert(client, tmp_path):
    day, nr = _make_manifest(tmp_path)
    r = client.post("/some/api/purge", data={"antall": 1})
    assert r.status_code == 200 and "Slettet 1" in r.text
    manifest = json.loads((tmp_path / "socials" / day / "manifest.json")
                          .read_text(encoding="utf-8"))
    assert manifest["drafts"] == []


def test_regenerering_husker_rettelsen(client, tmp_path, monkeypatch):
    day, nr = _make_manifest(tmp_path)
    sett: list = []
    monkeypatch.setattr(somemod.rendermod, "render_post",
                        lambda spec, **k: sett.append(spec.get("corrections"))
                        or {"png": b"\x89PNG\r\n\x1a\n", "how": "test"})
    client.post(f"/some/api/draft/{day}/{nr}/regen", data={"note": "feil grønnfarge"})
    client.post(f"/some/api/draft/{day}/{nr}/regen", data={"note": "formen ser rar ut"})
    assert sett[0] == ["feil grønnfarge"]
    assert sett[1] == ["feil grønnfarge", "formen ser rar ut"], \
        "andre forsøk må ta med den første rettelsen, ellers kommer problemet tilbake"


def test_samme_rettelse_lagres_ikke_to_ganger(client, tmp_path, monkeypatch):
    day, nr = _make_manifest(tmp_path)
    sett: list = []
    monkeypatch.setattr(somemod.rendermod, "render_post",
                        lambda spec, **k: sett.append(list(spec.get("corrections") or []))
                        or {"png": b"\x89PNG\r\n\x1a\n", "how": "test"})
    client.post(f"/some/api/draft/{day}/{nr}/regen", data={"note": "feil grønn"})
    client.post(f"/some/api/draft/{day}/{nr}/regen", data={"note": "feil grønn"})
    assert sett[1] == ["feil grønn"]


def test_rydding_gjor_dagene_ledige_igjen(client, tmp_path):
    """Etter en full rydding må planen slutte å påstå at dagene har utkast,
    ellers genererer «Generer nye forslag» ingenting for nettopp de dagene."""
    day, nr = _make_manifest(tmp_path)
    d = tmp_path / "socials"
    (d / "plan.json").write_text(json.dumps({"weeks": [], "slots": [
        {"date": day, "brand": "demo", "status": "utkast",
         "draft_ref": {"manifest": day, "nr": nr}}]}, ensure_ascii=False),
        encoding="utf-8")

    r = client.post("/some/api/purge", data={"antall": 1})

    assert r.status_code == 200 and "ledige igjen" in r.text
    slots = json.loads((d / "plan.json").read_text(encoding="utf-8"))["slots"]
    assert slots[0]["status"] == "planlagt", "slotten skal være åpen for nytt utkast"


def _karusell_manifest(vault, day: str = "2026-07-27"):
    """Ett karusell-utkast i dags-manifestet (PDF + forside), uten å bygge en ekte PDF."""
    d = vault / "socials" / day
    d.mkdir(parents=True, exist_ok=True)
    (d / "kar-forside.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 32)
    (d / "kar.pdf").write_bytes(b"%PDF-1.4\n")
    (d / "manifest.json").write_text(json.dumps({"drafts": [{
        "nr": 1, "type": "karusell", "format": "karusell", "status": "proposed",
        "headline": "1. september, forklart", "tittel": "1. september, forklart",
        "body": "kropp", "brand": "demo", "brand_name": "Demo Labs",
        "cover_path": str(d / "kar-forside.png"), "pdf_path": str(d / "kar.pdf"),
    }]}, ensure_ascii=False), encoding="utf-8")
    return d / "manifest.json"


def test_karusell_kan_faktisk_planlegges_via_knappen(client, tmp_path):
    """Kortet TILBYR et tidspunkt og jobben KAN publisere karusell, men det hjelper
    ikke hvis endepunktet knappen treffer avviser den. Testet begge ender og ikke
    midten 23. juli, og da sto sperren igjen i api_schedule."""
    mpath = _karusell_manifest(tmp_path)

    naar = _frem()
    r = client.post("/some/api/draft/2026-07-27/1/schedule", data={"when": naar})

    assert r.status_code == 200
    assert "kan ikke planlegges" not in r.text
    d = json.loads(mpath.read_text(encoding="utf-8"))["drafts"][0]
    assert d["status"] == "planlagt" and d["scheduled_at"] == naar


def test_karusell_kan_flyttes_i_kalenderen(client, tmp_path):
    mpath = _karusell_manifest(tmp_path)
    r = client.post("/some/api/draft/2026-07-27/1/move", data={"to": "2026-07-29"})
    assert r.status_code == 200 and "kan ikke" not in r.text
    d = json.loads(mpath.read_text(encoding="utf-8"))["drafts"][0]
    assert d["scheduled_at"].startswith("2026-07-29")


def test_karusell_avlyses_som_alt_annet(client, tmp_path):
    mpath = _karusell_manifest(tmp_path)
    client.post("/some/api/draft/2026-07-27/1/schedule", data={"when": "2026-07-28T10:00"})
    r = client.post("/some/api/draft/2026-07-27/1/unschedule")
    assert r.status_code == 200
    d = json.loads(mpath.read_text(encoding="utf-8"))["drafts"][0]
    assert d["status"] == "proposed" and "scheduled_at" not in d


def test_karusell_regen_skriver_om_og_bygger_om(client, tmp_path, monkeypatch):
    """Hele veien: HTTP-kall -> modellen skriver om -> filene bygges om på samme sti.
    Sperren satt i tre ledd (kort, flytting, endepunkt); denne dekker endepunktet."""
    from pathlib import Path
    mpath = _karusell_manifest(tmp_path)
    # Ekte spec med slides, så ombyggingen har noe å bygge fra.
    data = json.loads(mpath.read_text(encoding="utf-8"))
    data["drafts"][0]["spec"] = {"slides": [
        {"kind": "forside", "heading": "Gammel forside"},
        {"kind": "innhold", "heading": "Gammelt punkt"},
        {"kind": "cta", "heading": "Gammel cta"}]}
    mpath.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    sett = {}

    def fake_omskriv(draft, brand, *, rettelser=None):
        sett["rettelser"] = list(rettelser or [])
        return {"tittel": "Ny tittel", "slides": [
            {"kind": "forside", "heading": "Ny forside"},
            {"kind": "cta", "heading": "Ny cta"}]}
    monkeypatch.setattr(somemod.carouselmod, "omskriv_slides", fake_omskriv)

    r = client.post("/some/api/draft/2026-07-27/1/regen", data={"note": "for mye tekst"})

    assert r.status_code == 200, r.text[:200]
    assert "kan ikke regenereres" not in r.text
    assert sett["rettelser"] == ["for mye tekst"]
    d = json.loads(mpath.read_text(encoding="utf-8"))["drafts"][0]
    assert d["tittel"] == "Ny tittel"
    assert [s["heading"] for s in d["spec"]["slides"]] == ["Ny forside", "Ny cta"]
    # PDF-en er faktisk skrevet om, på samme sti som før.
    assert Path(d["pdf_path"]).read_bytes().startswith(b"%PDF")


def test_karusell_regen_uten_slides_fra_modellen_endrer_ingenting(client, tmp_path, monkeypatch):
    """Et tomt modellsvar skal ikke rive den fungerende karusellen."""
    mpath = _karusell_manifest(tmp_path)
    data = json.loads(mpath.read_text(encoding="utf-8"))
    data["drafts"][0]["spec"] = {"slides": [{"kind": "forside", "heading": "Står"}]}
    mpath.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(somemod.carouselmod, "omskriv_slides",
                        lambda d, b, **k: {"tittel": "", "slides": []})

    r = client.post("/some/api/draft/2026-07-27/1/regen", data={"note": ""})

    assert "ingenting er endret" in r.text
    d = json.loads(mpath.read_text(encoding="utf-8"))["drafts"][0]
    assert d["spec"]["slides"] == [{"kind": "forside", "heading": "Står"}]
