"""linkedin_draft: utvalg, ledger og dry-run, uten Playwright og uten nett."""

import json

from brandpost import linkedin_draft as ld


def _manifest(day_dir, drafts):
    day_dir.mkdir(parents=True)
    (day_dir / "manifest.json").write_text(
        json.dumps({"drafts": drafts}, ensure_ascii=False), encoding="utf-8")


def _draft(nr, *, image="a.png", body="tekst", headline="Overskrift"):
    return {"nr": nr, "image": image, "body": body, "headline": headline}


def test_pick_velger_nyeste_dag_og_hopper_over_lagrede(tmp_path, monkeypatch):
    monkeypatch.setenv("BRANDPOST_BROWSER_PROFILE", str(tmp_path / "profil"))
    vault = tmp_path / "vault"
    d1 = vault / "socials" / "2026-07-21"
    d2 = vault / "socials" / "2026-07-22"
    _manifest(d1, [_draft(1)])
    _manifest(d2, [_draft(1), _draft(2, image="b.png")])
    (d2 / "a.png").write_bytes(b"png")
    (d2 / "b.png").write_bytes(b"png")

    got = ld.pick_drafts(vault)
    assert [d["key"] for d in got] == ["2026-07-22#1", "2026-07-22#2"]

    ld.mark_saved("2026-07-22#1")
    got = ld.pick_drafts(vault)
    assert [d["key"] for d in got] == ["2026-07-22#2"]


def test_pick_hopper_over_karusell_og_manglende_bilde(tmp_path, monkeypatch):
    monkeypatch.setenv("BRANDPOST_BROWSER_PROFILE", str(tmp_path / "profil"))
    vault = tmp_path / "vault"
    day = vault / "socials" / "2026-07-22"
    _manifest(day, [
        {"nr": 1, "pdf": "k.pdf", "body": "karusell"},   # ingen image: hoppes
        _draft(2, image="finnes-ikke.png"),               # png mangler på disk
        _draft(3, image="ok.png"),
    ])
    (day / "ok.png").write_bytes(b"png")
    got = ld.pick_drafts(vault)
    assert [d["nr"] for d in got] == [3]
    assert got[0]["text"] == "tekst"


def test_pick_respekterer_nr_og_limit(tmp_path, monkeypatch):
    monkeypatch.setenv("BRANDPOST_BROWSER_PROFILE", str(tmp_path / "profil"))
    vault = tmp_path / "vault"
    day = vault / "socials" / "2026-07-22"
    _manifest(day, [_draft(i, image=f"{i}.png") for i in (1, 2, 3)])
    for i in (1, 2, 3):
        (day / f"{i}.png").write_bytes(b"png")
    assert [d["nr"] for d in ld.pick_drafts(vault, nr=2)] == [2]
    assert len(ld.pick_drafts(vault, limit=2)) == 2


def test_dry_run_uten_flagg_lagrer_ingenting(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("BRANDPOST_BROWSER_PROFILE", str(tmp_path / "profil"))
    monkeypatch.delenv("BRANDPOST_BROWSER_ENABLED", raising=False)
    vault = tmp_path / "vault"
    day = vault / "socials" / "2026-07-22"
    _manifest(day, [_draft(1)])
    (day / "a.png").write_bytes(b"png")

    rc = ld.save_drafts(vault)
    out = capsys.readouterr().out
    assert rc == 0
    assert "dry-run" in out
    assert ld.read_ledger() == {}  # ingenting markert som lagret


def test_ekte_kjoring_krever_side_url(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("BRANDPOST_BROWSER_PROFILE", str(tmp_path / "profil"))
    monkeypatch.setenv("BRANDPOST_BROWSER_ENABLED", "1")
    monkeypatch.delenv("BRANDPOST_LINKEDIN_PAGE_URL", raising=False)
    vault = tmp_path / "vault"
    day = vault / "socials" / "2026-07-22"
    _manifest(day, [_draft(1)])
    (day / "a.png").write_bytes(b"png")

    rc = ld.save_drafts(vault)
    assert rc == 1
    assert "BRANDPOST_LINKEDIN_PAGE_URL" in capsys.readouterr().out


def test_pick_utleder_filnavn_fra_maskinfremmed_png_path(tmp_path, monkeypatch):
    """Manifestet skrives på Mini med fulle /Users/brukeren-stier; lokalt teller
    bare filnavnet i dags-mappa (regresjonen 22. juli: alt ble hoppet over)."""
    monkeypatch.setenv("BRANDPOST_BROWSER_PROFILE", str(tmp_path / "profil"))
    vault = tmp_path / "vault"
    day = vault / "socials" / "2026-07-29"
    _manifest(day, [{"nr": 1, "body": "tekst", "headline": "H",
                     "png_path": "/Users/brukeren/Documents/Arbeidsmappa Vault/_system/socials/2026-07-29/post-1.png"}])
    (day / "post-1.png").write_bytes(b"png")
    got = ld.pick_drafts(vault)
    assert [d["nr"] for d in got] == [1]
    assert got[0]["image"] == day / "post-1.png"


def test_ledger_rundtur(tmp_path, monkeypatch):
    monkeypatch.setenv("BRANDPOST_BROWSER_PROFILE", str(tmp_path / "profil"))
    assert ld.read_ledger() == {}
    ld.mark_saved("2026-07-22#1")
    led = ld.read_ledger()
    assert list(led) == ["2026-07-22#1"]


# ── planlegging ───────────────────────────────────────────────────────────────

def test_maanedstabeller_er_komplette():
    assert len(ld._MND_FULL) == 12 and len(ld._MND_3) == 12
    assert ld._MND_FULL[6] == "juli" and ld._MND_3[6] == "jul"
    assert ld._MND_FULL[8] == "september" and ld._MND_3[8] == "sep"


def test_cli_schedule_krever_date_og_nr(capsys):
    # Uten --date/--nr skal den avvise FØR nettleseren startes (returkode 2).
    rc = ld.main(["--schedule", "2026-07-29T08:00"])
    assert rc == 2
    assert "krever --date og --nr" in capsys.readouterr().out


def test_cli_schedule_avviser_ugyldig_tidspunkt(capsys):
    rc = ld.main(["--schedule", "i-morgen", "--date", "2026-07-29", "--nr", "1"])
    assert rc == 2
    assert "Ugyldig --schedule" in capsys.readouterr().out


def test_schedule_post_uten_utkast_feiler(tmp_path, monkeypatch):
    monkeypatch.setenv("BRANDPOST_BROWSER_PROFILE", str(tmp_path / "profil"))
    monkeypatch.setenv("BRANDPOST_LINKEDIN_PAGE_URL", "https://x/company/1/admin/")
    from datetime import datetime
    rc = ld.schedule_post(tmp_path / "vault", date="2026-07-29", nr=99,
                          when=datetime(2026, 7, 29, 8, 0), commit=False)
    assert rc == 1  # fant ikke utkastet, aldri nettleser


# ── auto-oppdagelse av publiserte innlegg + idébank ───────────────────────────

def test_norm_gjor_tekst_sammenlignbar():
    assert ld._norm("Ordet «forskning» skremmer!") == "ordet forskning skremmer"


def test_match_draft_finner_vaar_tekst_inni_linkedin_stoy():
    """LinkedIn-teksten er pakket i header-støy (følgertall, synlighet); vår
    brødtekst skal likevel gjenkjennes."""
    draft = {"body": "Ordet «forskning» skremmer bort halvparten av dem som kvalifiserer."}
    publisert = [{"urn": "urn:li:activity:1", "url": "u1",
                  "text": "Demo Labs 80 følgere 4t Synlig for alle "
                          "Ordet forskning skremmer bort halvparten av dem som kvalifiserer"}]
    assert ld._match_draft(draft, publisert)["urn"] == "urn:li:activity:1"


def test_match_draft_krever_lang_nok_bit():
    """Kort tekst skal ikke gi tilfeldige treff."""
    assert ld._match_draft({"body": "Kort."}, [{"urn": "a", "url": "u", "text": "Kort."}]) is None


def test_posts_url_utledes_fra_admin_url(monkeypatch):
    monkeypatch.setenv("BRANDPOST_LINKEDIN_PAGE_URL",
                       "https://www.linkedin.com/company/99001122/admin/")
    assert ld.posts_url() == "https://www.linkedin.com/company/99001122/posts/"


def test_sync_published_markerer_treff(tmp_path, monkeypatch):
    from brandpost import store
    monkeypatch.setenv("BRANDPOST_BROWSER_PROFILE", str(tmp_path / "profil"))
    day = tmp_path / "socials" / "2026-07-27"
    day.mkdir(parents=True)
    (day / "manifest.json").write_text(json.dumps({"drafts": [
        {"nr": 1, "headline": "H", "body": "Ordet forskning skremmer bort halvparten av dem",
         "status": "proposed"},
        {"nr": 2, "headline": "Annen", "body": "Noe helt annet som ikke er publisert ennaa",
         "status": "proposed"}]}, ensure_ascii=False), encoding="utf-8")

    monkeypatch.setattr(ld, "fetch_published", lambda limit=20, headless=True: [
        {"urn": "urn:li:activity:7", "url": "https://li/7",
         "text": "Demo Labs 80 følgere Ordet forskning skremmer bort halvparten av dem"}])
    n = ld.sync_published(tmp_path)
    assert n == 1
    m = json.loads((day / "manifest.json").read_text())
    assert m["drafts"][0]["status"] == "published"
    assert m["drafts"][0]["linkedin_url"] == "https://li/7"
    assert m["drafts"][1]["status"] == "proposed"   # urørt


def test_used_angles_sperrer_kun_publisert_og_planlagt(tmp_path):
    from brandpost import store
    day = tmp_path / "socials" / "2026-07-27"
    day.mkdir(parents=True)
    (day / "manifest.json").write_text(json.dumps({"drafts": [
        {"nr": 1, "headline": "Ute", "motif": "m1", "status": "published"},
        {"nr": 2, "headline": "Paa vei", "motif": "m2", "status": "planlagt"},
        {"nr": 3, "headline": "Bare foreslaatt", "motif": "m3", "status": "proposed"}]},
        ensure_ascii=False), encoding="utf-8")
    heads = [a["headline"] for a in store.used_angles(tmp_path)]
    assert "Ute" in heads and "Paa vei" in heads
    assert "Bare foreslaatt" not in heads   # skal tilbake i idébanken
