"""To utvidelsesflater: `publish --json` og eksterne merkekataloger.

Begge finnes for det samme: at brandpost skal kunne være motoren i et større
oppsett uten at oppsettet må ligge i dette repoet.

  --json                  koble publisering til noe annet (e-postsvar, bot, skript)
  BRANDPOST_BRANDS_DIR    la merkevaren din bo et privat sted, mens motoren
                          installeres herfra
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
from datetime import date

import pytest

from brandpost import brandkit, cli as clim, plan as planmod, store


# ── publish --json ─────────────────────────────────────────

def _oppsett(tmp_path, *, status="proposed", nr=1):
    b = brandkit.load_brand("demo")
    dag = date.today().isoformat()
    png = tmp_path / "post.png"
    png.write_bytes(b"png")
    utkast = {"headline": "Testkort", "body": "brød", "png_path": str(png),
              "status": status, "nr": nr, "format": "typografi-kort"}
    if status == "published":
        utkast["linkedin_url"] = "https://www.linkedin.com/feed/update/urn:li:share:1"
    store.merge_manifest(tmp_path, brand_key="demo", brand_name=b.name,
                         new_drafts=[utkast])
    planmod.atomic_write_json(planmod.plan_path(tmp_path), {
        "slots": [{"date": dag, "status": "utkast", "tema": "t", "pillar": "p"}]})
    return dag


def _kjor(tmp_path, monkeypatch, *, post="1", svar=None):
    if svar is not None:
        monkeypatch.setattr("brandpost.linkedin.publish_draft", lambda d, **k: svar)
    args = argparse.Namespace(vault=str(tmp_path), date=None, post=post,
                              dry_run=False, json=True)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        kode = clim.cmd_publish(args)
    return kode, buf.getvalue()


def test_stdout_er_noyaktig_ett_json_objekt(tmp_path, monkeypatch):
    """Kalleren parser stdout. Ekstra prosalinjer ville knekt den."""
    _oppsett(tmp_path)
    kode, ut = _kjor(tmp_path, monkeypatch, svar={"posted": True, "url": "https://li/1"})
    linjer = [linje for linje in ut.strip().splitlines() if linje.strip()]
    assert len(linjer) == 1, f"forventet én linje, fikk {len(linjer)}: {linjer}"
    assert json.loads(linjer[0])["ok"] is True and kode == 0


def test_publisering_oppdaterer_bade_manifest_og_plan(tmp_path, monkeypatch):
    """REGRESJONSVAKT.

    cmd_publish oppdaterte manifestet, mens dashbordet i tillegg satte
    plan-sloten. Publiserte du fra kommandolinja, ble kalenderen stående på
    «utkast» for et innlegg som var ute. De to veiene skal si det samme.
    """
    dag = _oppsett(tmp_path)
    kode, ut = _kjor(tmp_path, monkeypatch, svar={"posted": True, "url": "https://li/7"})
    assert kode == 0 and json.loads(ut)["posted"] is True

    _, manifest = store.load_manifest(tmp_path, dag)
    assert manifest["drafts"][0]["status"] == "published"
    slot = next(s for s in planmod.load_plan(tmp_path)["slots"] if s["date"] == dag)
    assert slot["status"] == "publisert", "plan.json fulgte ikke med publiseringen"


def test_dry_run_er_forstatt_ikke_feil(tmp_path, monkeypatch):
    """LINKEDIN_ENABLED=0 betyr «mottatt, men ikke postet», ikke «ødelagt»."""
    _oppsett(tmp_path)
    kode, ut = _kjor(tmp_path, monkeypatch,
                     svar={"posted": False, "dry_run": True, "preview": {}})
    d = json.loads(ut)
    assert kode == 0 and d["ok"] is True and d["dry_run"] is True


def test_allerede_publisert_poster_ikke_pa_nytt(tmp_path, monkeypatch):
    """Idempotens: kjøres kommandoen to ganger, går innlegget ikke ut igjen."""
    _oppsett(tmp_path, status="published")
    monkeypatch.setattr("brandpost.linkedin.publish_draft",
                        lambda *a, **k: pytest.fail("skulle ikke publisert på nytt"))
    kode, ut = _kjor(tmp_path, monkeypatch)
    d = json.loads(ut)
    assert kode == 0 and d["ok"] is True and d["already"] is True


def test_ukjent_nummer_er_nei_ikke_krasj(tmp_path, monkeypatch):
    """Foreldet nummer skal gi «finnes ikke», aldri treffe naboen."""
    _oppsett(tmp_path, nr=3)
    monkeypatch.setattr("brandpost.linkedin.publish_draft",
                        lambda *a, **k: pytest.fail("skulle ikke publisert"))
    kode, ut = _kjor(tmp_path, monkeypatch, post="99")
    d = json.loads(ut)
    assert kode == 0 and d["posted"] is False and "finnes ikke" in d["reason"]


def test_uten_post_publiseres_ingenting(tmp_path, monkeypatch):
    """Menneske-gaten: publisering krever at du peker på ETT utkast."""
    _oppsett(tmp_path)
    monkeypatch.setattr("brandpost.linkedin.publish_draft",
                        lambda *a, **k: pytest.fail("skulle ikke publisert"))
    kode, ut = _kjor(tmp_path, monkeypatch, post=None)
    assert kode == 1 and json.loads(ut)["ok"] is False


# ── eksterne merkekataloger ────────────────────────────────

def _lag_merke(base, key, navn):
    """Minste gyldige merke, modellert på brands/minimal/profile.toml."""
    d = base / key
    (d / "media").mkdir(parents=True)
    (d / "profile.toml").write_text(f"""\
key = "{key}"
name = "{navn}"
handle = "{key}"
enabled = true
wordmark = "{navn}"

[palette]
bg = "#FAFAF8"
ink = "#5B6472"
headline = "#22303F"
brand = "#7A5C3E"
shape = "#EDE7DE"
dark = "#22303F"

[fonts]
display = "Fraunces.ttf"
body = "Inter.ttf"
""", encoding="utf-8")
    return d


def test_eget_merke_utenfor_pakken_blir_funnet(tmp_path, monkeypatch):
    """Kjernen i splittet: merkevaren din, altså strategi, stemme og logoer, skal
    kunne bo i et privat repo mens motoren installeres herfra."""
    _lag_merke(tmp_path, "mittfirma", "Mitt Firma")
    monkeypatch.setenv("BRANDPOST_BRANDS_DIR", str(tmp_path))
    assert "mittfirma" in brandkit.available_brands()
    assert brandkit.load_brand("mittfirma").name == "Mitt Firma"


def test_innebygde_merker_overlever(tmp_path, monkeypatch):
    """En ekstern katalog skal LEGGE TIL, ikke erstatte. Ellers slutter demo å
    virke i det øyeblikket du peker på dine egne merker."""
    _lag_merke(tmp_path, "mittfirma", "Mitt Firma")
    monkeypatch.setenv("BRANDPOST_BRANDS_DIR", str(tmp_path))
    tilgjengelig = brandkit.available_brands()
    assert "demo" in tilgjengelig and "mittfirma" in tilgjengelig


def test_egen_katalog_vinner_ved_navnekollisjon(tmp_path, monkeypatch):
    """Din versjon av «demo» skal overstyre den innebygde, ikke omvendt."""
    _lag_merke(tmp_path, "demo", "Min egen demo")
    monkeypatch.setenv("BRANDPOST_BRANDS_DIR", str(tmp_path))
    assert brandkit.load_brand("demo").name == "Min egen demo"


def test_flere_kataloger_med_kolon(tmp_path, monkeypatch):
    """Som PATH: flere kilder, første treff vinner."""
    a, b = tmp_path / "a", tmp_path / "b"
    _lag_merke(a, "en", "Første")
    _lag_merke(b, "to", "Andre")
    monkeypatch.setenv("BRANDPOST_BRANDS_DIR", f"{a}{os.pathsep}{b}")
    assert {"en", "to"} <= set(brandkit.available_brands())


def test_eget_merke_kan_staa_i_enabled_brands(tmp_path, monkeypatch):
    """BRANDPOST_BRANDS filtrerte mot bare den innebygde katalogen, så egne
    merker ble stille kastet og kjøringen falt tilbake til demo."""
    _lag_merke(tmp_path, "mittfirma", "Mitt Firma")
    monkeypatch.setenv("BRANDPOST_BRANDS_DIR", str(tmp_path))
    monkeypatch.setenv("BRANDPOST_BRANDS", "mittfirma")
    assert brandkit.enabled_brands() == ["mittfirma"]


def test_ukjent_merke_sier_hvor_det_ble_lett(tmp_path, monkeypatch):
    """Feilmeldingen skal peke på løsningen, ikke bare på problemet."""
    monkeypatch.setenv("BRANDPOST_BRANDS_DIR", str(tmp_path))
    with pytest.raises(ValueError) as ei:
        brandkit.load_brand("finnesikke")
    assert "BRANDPOST_BRANDS_DIR" in str(ei.value) and str(tmp_path) in str(ei.value)


def test_uten_env_er_alt_som_for(monkeypatch):
    """Bakoverkompatibilitet: en fersk kloning skal virke uten å konfigureres."""
    monkeypatch.delenv("BRANDPOST_BRANDS_DIR", raising=False)
    assert brandkit.brand_dirs() == [brandkit.BUNDLED_BRANDS_DIR]
    assert "demo" in brandkit.available_brands()
