"""Godkjenningsporten: en profil med [approval] kan ikke generere før et menneske
har lest gjennom den.

Problemet porten løser: en ny bruker setter opp merket sitt ved å la modellen fylle
ut profile.toml. Gjettede fakta om eget selskap ser overbevisende ut, og går rett på
en firmaside om ingen leser dem først.

Kontrakten har to halvdeler, og begge testes her:
  1. Profiler UTEN [approval] oppfører seg nøyaktig som før. Den som allerede
     kjører et merke i produksjon skal ikke våkne til en sperre.
  2. Når tabellen først finnes, er alt annet enn et eksplisitt ja et nei, og
     ingen inngang (CLI, dashbord, planlagt jobb) kommer utenom.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

from brandpost import brandkit, cli

MERKE = "delta"  # nøytralt fikstur-navn: repoet er offentlig


def _profile(*, enabled: object = False, approval: bool = True,
             overrides: dict[str, object] | None = None) -> str:
    verdier: dict[str, object] = {
        "facts_approved": True,
        "voice_approved": True,
        "design_approved": True,
        "sources_approved": True,
        "approved_by": "Testeier",
        "approved_at": "2026-08-15T14:00:00+02:00",
    }
    verdier.update(overrides or {})

    def toml_verdi(v: object) -> str:
        return ("true" if v else "false") if isinstance(v, bool) else f'"{v}"'

    linjer = [f'key = "{MERKE}"', 'name = "Delta AS"', f'handle = "{MERKE}"',
              f"enabled = {toml_verdi(enabled)}", ""]
    if approval:
        linjer += ["[approval]"] + [f"{k} = {toml_verdi(v)}"
                                    for k, v in verdier.items()] + [""]
    linjer += ["[palette]", 'bg = "#ffffff"', 'ink = "#111111"',
               'headline = "#111111"', 'brand = "#222222"', 'shape = "#eeeeee"',
               'dark = "#111111"', "", "[fonts]", 'display = "Inter.ttf"',
               'body = "Inter.ttf"']
    return "\n".join(linjer) + "\n"


def _merkerot(tmp_path: Path, monkeypatch, **profil_kw) -> Path:
    rot = tmp_path / "brands"
    mappe = rot / MERKE
    mappe.mkdir(parents=True)
    (mappe / "profile.toml").write_text(_profile(**profil_kw), encoding="utf-8")
    monkeypatch.setenv("BRANDPOST_BRANDS_DIR", str(rot))
    return rot


# ───────────────────────────────────────────────────────────
# Halvdel 1: eksisterende merker merker ingenting
# ───────────────────────────────────────────────────────────

def test_profil_uten_approval_er_helt_uendret(tmp_path, monkeypatch):
    """Den viktigste testen i fila. Tilskudd-, Vitandi- og demo-profilene har
    ingen [approval]-tabell, og skal fortsette å virke selv om de er dvalende."""
    _merkerot(tmp_path, monkeypatch, enabled=False, approval=False)
    brand = brandkit.load_brand(MERKE)
    assert brand.enabled is False
    assert brand.approval is None
    assert brandkit.generation_blockers(brand) == ()
    brandkit.require_generation_ready(brand)      # skal ikke kaste


def test_publisering_gaar_som_foer_for_merke_som_ikke_er_installert(tmp_path, monkeypatch):
    """Et gammelt utkast kan peke på et merke denne maskinen ikke har profilen til.
    Det er ikke det samme som at profilen sier nei, og skal publiseres som før.

    Uten dette skillet ville sperren gjort en manglende profil til en hard feil
    midt i den planlagte utsendelsen."""
    _merkerot(tmp_path, monkeypatch, enabled=True)
    from brandpost import publisher

    monkeypatch.setattr(publisher.linkedin, "publish_draft",
                        lambda d, dry_run=None: {"posted": True, "url": "https://li/1"})
    monkeypatch.setattr(publisher, "_publisert_epost", lambda *a, **k: {"sent": True})
    monkeypatch.setattr(publisher, "_publisert_slack", lambda *a, **k: {"sent": False})
    mpath = tmp_path / "socials" / "2026-08-15" / "manifest.json"
    mpath.parent.mkdir(parents=True)
    utkast = {"nr": 1, "brand": "et-merke-som-ikke-finnes", "headline": "H",
              "body": "b", "status": "proposed"}
    manifest = {"drafts": [utkast]}
    mpath.write_text(json.dumps(manifest), encoding="utf-8")

    res = publisher.publiser_ett(mpath, manifest, 0, utkast, vault=tmp_path)

    assert res["posted"] is True


# ───────────────────────────────────────────────────────────
# Halvdel 2: når tabellen finnes, er alt annet enn ja et nei
# ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("overstyr,forventet", [
    ({"facts_approved": False}, "facts_approved"),
    ({"voice_approved": False}, "voice_approved"),
    ({"design_approved": False}, "design_approved"),
    ({"sources_approved": False}, "sources_approved"),
    ({"approved_by": ""}, "approved_by"),
    ({"approved_at": ""}, "approved_at"),
])
def test_hvert_felt_maa_staa_og_signaturen_maa_vaere_utfylt(
        tmp_path, monkeypatch, overstyr, forventet):
    _merkerot(tmp_path, monkeypatch, enabled=True, overrides=overstyr)
    with pytest.raises(brandkit.GenerationBlocked, match=forventet):
        brandkit.require_generation_ready(brandkit.load_brand(MERKE))


@pytest.mark.parametrize("verdi", ["true", 1])
def test_sannhetslignende_verdier_gir_ikke_myndighet(tmp_path, monkeypatch, verdi):
    """Teksten "true" og tallet 1 er ikke et ja. `bool("false")` er True, så en
    slapp konvertering ville gjort strengen "false" til en godkjenning."""
    _merkerot(tmp_path, monkeypatch, enabled=True,
              overrides={"facts_approved": verdi})
    with pytest.raises(brandkit.GenerationBlocked, match="facts_approved"):
        brandkit.require_generation_ready(brandkit.load_brand(MERKE))


def test_enabled_som_tekst_avvises_i_stedet_for_aa_bli_sann(tmp_path, monkeypatch):
    """`bool("false")` er True. Skrivefeilen ville altså slått merket PÅ."""
    _merkerot(tmp_path, monkeypatch, enabled="false")
    with pytest.raises(ValueError, match="enabled må være true eller false"):
        brandkit.load_brand(MERKE)


def test_env_variabelen_kan_vise_merket_men_ikke_godkjenne_det(tmp_path, monkeypatch):
    """BRANDPOST_BRANDS velger hva installasjonen viser og kjører. Den er et
    utvalgsfilter, ikke en fullmakt."""
    _merkerot(tmp_path, monkeypatch, enabled=False)
    monkeypatch.setenv("BRANDPOST_BRANDS", MERKE)

    assert brandkit.enabled_brands() == [MERKE]
    with pytest.raises(brandkit.GenerationBlocked, match="enabled må være true"):
        brandkit.require_generation_ready(brandkit.load_brand(MERKE))

    from web import app as webapp
    rad = next(r for r in webapp.merker_ctx(MERKE)["valg"] if r["key"] == MERKE)
    assert rad["dvale"] is True, "nedtrekket skal vise at merket ikke er produksjonsklart"


# ───────────────────────────────────────────────────────────
# Ingen inngang kommer utenom
# ───────────────────────────────────────────────────────────

def test_cli_stopper_foer_kontekst_og_modellkall(tmp_path, monkeypatch, capsys):
    """Porten ligger før gather_context, altså før noe koster penger eller
    skriver til vaulten."""
    _merkerot(tmp_path, monkeypatch, enabled=True,
              overrides={"sources_approved": False})
    monkeypatch.setattr(cli.ctxmod, "gather_context",
                        lambda *a, **k: pytest.fail("kontekst hentet før porten"))
    args = argparse.Namespace(vault=str(tmp_path / "workspace"), brand=MERKE,
                              days=10, n=1, bunke=None, dry_run=True)

    assert cli.cmd_run(args) == 2
    assert "generering sperret" in capsys.readouterr().err


def test_publiser_ett_er_fail_closed_ogsaa_ved_direkte_kall(tmp_path, monkeypatch):
    """publiser_ett er felles vei for CLI, planlagt jobb, dashbord og Slack.
    Den er den kanoniske sperren, ikke web-preflighten."""
    _merkerot(tmp_path, monkeypatch, enabled=True,
              overrides={"voice_approved": False})
    from brandpost import publisher

    kalt: list[dict] = []
    monkeypatch.setattr(publisher.linkedin, "publish_draft",
                        lambda d, dry_run=None: kalt.append(d) or {"posted": False})
    utkast = {"brand": MERKE, "headline": "Uferdig", "status": "proposed"}

    with pytest.raises(brandkit.GenerationBlocked, match="voice_approved"):
        publisher.publiser_ett(tmp_path / "manifest.json", {"drafts": [utkast]}, 0,
                               utkast, vault=tmp_path, dry_run=True)
    assert kalt == [], "LinkedIn skal ikke røres, heller ikke i tørrkjøring"


# ───────────────────────────────────────────────────────────
# Dashbordet: sperret skal SES, ikke bare virke
# ───────────────────────────────────────────────────────────

@pytest.fixture()
def sperret_web(tmp_path, monkeypatch):
    # Speiler en fersk profil: satt opp, men ingenting lest gjennom ennå.
    _merkerot(tmp_path, monkeypatch, enabled=False, overrides={
        "facts_approved": False, "voice_approved": False,
        "design_approved": False, "sources_approved": False,
        "approved_by": "", "approved_at": "",
    })
    monkeypatch.setenv("BRANDPOST_BRANDS", MERKE)
    monkeypatch.setenv("BRANDPOST_WORKSPACE", str(tmp_path / "workspace"))
    monkeypatch.setenv("BRANDPOST_STATE_DIR", str(tmp_path / "state"))
    from fastapi.testclient import TestClient
    from main import app
    from web import app as webapp

    startet: list = []
    monkeypatch.setattr(webapp.subprocess, "Popen",
                        lambda cmd, **kw: startet.append(cmd) or
                        pytest.fail("subprosess startet for sperret merke"))
    return TestClient(app, headers={"Origin": "http://testserver"}), startet


def test_bunken_sier_hvorfor_den_er_tom(sperret_web):
    """«Tom bunke» og «sperret» ser like ut om vi ikke sier det. Da tror hun at
    hun er ferdig, ikke at hun mangler et steg."""
    client, startet = sperret_web
    r = client.get(f"/some/bunke?brand={MERKE}")

    assert r.status_code == 200
    assert "Generering er sperret" in r.text
    # Hvert punkt i klartekst, ikke én klump feltnavn: den som sitter her har
    # ofte aldri åpnet en TOML-fil.
    assert "Merket står i dvale (enabled)" in r.text
    assert "Ingen har lest gjennom det som står om selskapet" in r.text
    assert "brands/delta/profile.toml" in r.text, "må si HVOR det rettes"
    assert startet == []


def test_generer_naa_knappen_starter_ingenting(sperret_web):
    client, startet = sperret_web
    r = client.post(f"/some/api/bunke/fyll?brand={MERKE}")

    assert r.status_code == 200
    assert "Generering er sperret" in r.text
    assert startet == []


def test_generate_endepunktet_starter_ingenting(sperret_web):
    client, startet = sperret_web
    r = client.post(f"/some/api/generate?brand={MERKE}")

    assert r.status_code == 200
    assert f"Generering er sperret for {MERKE}" in r.text
    assert startet == []


@pytest.mark.parametrize("linkedin_paa", ["0", "1"])
def test_publiser_knappen_naar_aldri_publisher(tmp_path, monkeypatch, linkedin_paa):
    """Også tørrkjøring er en publiseringshandling: den beviser hvilken avsender
    innlegget ville fått. Sperren ligger før publisher-kallet."""
    _merkerot(tmp_path, monkeypatch, enabled=True,
              overrides={"facts_approved": False})
    workspace = tmp_path / "workspace"
    monkeypatch.setenv("BRANDPOST_WORKSPACE", str(workspace))
    monkeypatch.setenv("BRANDPOST_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("LINKEDIN_ENABLED", linkedin_paa)

    dag = "2026-08-15"
    mappe = workspace / "socials" / dag
    mappe.mkdir(parents=True)
    (mappe / "manifest.json").write_text(json.dumps({"drafts": [{
        "nr": 1, "brand": MERKE, "brand_name": "Delta AS",
        "headline": "Et ugodkjent utkast", "body": "Tekst",
        "status": "proposed", "png_path": "",
    }]}), encoding="utf-8")

    from fastapi.testclient import TestClient
    from main import app
    from web import app as webapp

    kalt: list = []
    monkeypatch.setattr(webapp.pubmod, "publiser_ett",
                        lambda *a, **k: kalt.append(a) or {"posted": True})
    client = TestClient(app, headers={"Origin": "http://testserver"})

    r = client.post(f"/some/api/draft/{dag}/1/publish")

    assert r.status_code == 200
    assert f"Publisering er sperret for {MERKE}" in r.text
    assert "facts_approved" in r.text
    assert kalt == []
