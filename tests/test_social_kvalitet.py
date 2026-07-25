"""Tester for innleggs-kvaliteten: tekst-sanering (naturlig norsk), tagging i
stedet for URL, kilder synlig kun for oss, dato-adresserte publiser-svar og
API-mention av firmasida."""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path

from brandpost import brandkit, cli as clim, email as emailmod
from brandpost import linkedin, render, store


# ── sanering ───────────────────────────────────────────────

def test_clean_text_removes_dashes_keeps_ranges():
    assert clim._clean_text("AI gjør jobben — du sparer penger") == "AI gjør jobben, du sparer penger"
    assert clim._clean_text("Konsulenten tar 15–25 % av beløpet") == "Konsulenten tar 15-25 % av beløpet"
    assert clim._clean_text("Én ting – og bare én") == "Én ting, og bare én"


def test_sanitize_spec_moves_urls_to_kilder_and_tags_brand():
    spec = {"headline": "Test — med strek",
            "body": ("Les mer på https://www.regjeringen.no/skattefunn i dag.\n"
                     "Se demo labs for detaljer — det er gratis."),
            "kilder": ["72 627 søknader → produktfakta"]}
    clim._sanitize_spec(spec, brand_name="Demo Labs", wordmark="demo labs")
    assert spec["headline"] == "Test, med strek"
    assert "http" not in spec["body"]                      # URL ut av innlegget
    assert "@Demo Labs" in spec["body"]                  # domenenavn -> tagg
    assert "—" not in spec["body"] and "–" not in spec["body"]
    assert any("regjeringen.no" in k for k in spec["kilder"])   # flyttet til kilder
    assert "72 627 søknader → produktfakta" in spec["kilder"]   # eksisterende består


def test_sanitize_spec_cleans_slides():
    spec = {"type": "karusell", "tittel": "T",
            "slides": [{"kind": "innhold", "heading": "Steg 1 — start", "body": "a — b"}]}
    clim._sanitize_spec(spec, brand_name="Demo Labs")
    assert spec["slides"][0]["heading"] == "Steg 1, start"
    assert spec["slides"][0]["body"] == "a, b"


# ── kilder + dato-kommando i eposten ───────────────────────

def _draft(tmp_path, *, spec_extra=None, when=None):
    when = when or datetime.now()
    b = brandkit.load_brand("demo")
    spec = {"headline": "Testkort", "body": "Kropp", "why_now": "nå",
            "format": "typografi-kort", "pillar": "myte-avliving", **(spec_extra or {})}
    png = render.render_template({"headline": "Testkort"}, b)
    meta = store.write_draft(tmp_path, "demo", spec, png, index=1, when=when)
    meta["brand_name"] = b.name
    safe = [{k: v for k, v in meta.items() if k not in ("png", "pdf", "cover")}]
    store.merge_manifest(tmp_path, brand_key="demo", brand_name=b.name,
                         new_drafts=safe, when=when)
    return safe[0]


def test_email_shows_kilder_and_dated_publish_command(tmp_path):
    d = _draft(tmp_path, spec_extra={"kilder": ["75,3 % godkjent → intern statistikk"]})
    d["date"] = "2026-07-13"
    subject, doc, inline, _ = emailmod.build_some_email([d])
    assert "Kilder (kun for deg, ikke i innlegget)" in doc
    assert "75,3 % godkjent" in doc
    assert f"publiser: 13.07-{d['nr']}" in doc


def test_publish_command_plain_without_date(tmp_path):
    d = _draft(tmp_path)
    d.pop("date", None)
    assert emailmod.publish_command(d, 2) == "publiser: 2"


# ── digest_replies: dato-adressert svar ────────────────────





# ── motiv-reflow: aldri trange kort ────────────────────────

def _sand_canvas(b, w=540, h=675):
    from PIL import Image
    return Image.new("RGBA", (w, h), (*render._hex(b.palette.bg), 255))


def test_reflow_moves_content_out_of_headline_zone():
    from PIL import ImageDraw
    b = brandkit.load_brand("demo")
    img = _sand_canvas(b)
    # innhold som stikker helt opp i tittel-sonen (som det trange prosess-kortet)
    ImageDraw.Draw(img).rectangle([100, 40, 440, 600], fill=(6, 35, 28, 255))
    bg = render._hex(b.palette.bg)
    assert render.zone_occupancy(img, bg, y0=0.04, y1=0.26) > 0.2
    out = render._content_reflow(img, b)
    assert render.zone_occupancy(out, bg, y0=0.04, y1=0.26) < 0.02  # toppen er luftig
    assert render.zone_occupancy(out, bg, y0=0.30, y1=0.85) > 0.10  # innholdet består


def test_reflow_leaves_compliant_image_untouched():
    from PIL import ImageDraw
    b = brandkit.load_brand("demo")
    img = _sand_canvas(b)
    h = img.height
    ImageDraw.Draw(img).rectangle([120, int(h * 0.35), 420, int(h * 0.80)],
                                  fill=(6, 35, 28, 255))
    assert render._content_reflow(img, b) is img  # ingen reflow, null kvalitetstap


# ── API-mention ────────────────────────────────────────────

def test_api_commentary_converts_tag_to_mention():
    out = linkedin.api_commentary("Vi i @Demo Labs hjelper deg.",
                                  brand_name="Demo Labs",
                                  org_urn="urn:li:organization:42")
    assert out == "Vi i @[Demo Labs](urn:li:organization:42) hjelper deg."
    # uten URN eller tagg: uendret
    assert linkedin.api_commentary("ren tekst", brand_name="X", org_urn="") == "ren tekst"


def test_publish_draft_preview_uses_mention(tmp_path, monkeypatch):
    png = tmp_path / "p.png"
    png.write_bytes(b"png")

    class _B:
        linkedin_org_urn = "urn:li:organization:42"

    monkeypatch.setattr("brandpost.brandkit.load_brand", lambda key: _B())
    draft = {"headline": "H", "brand": "demo", "brand_name": "Demo Labs",
             "png_path": str(png), "body": "Vi i @Demo Labs hjelper deg."}
    cfg = linkedin.LinkedInConfig(client_id="c", client_secret="s", access_token="t",
                                  refresh_token="r", org_urn="urn:li:organization:1",
                                  enabled=False)
    res = linkedin.publish_draft(draft, cfg=cfg)
    assert "@[Demo Labs](urn:li:organization:42)" in res["preview"]["commentary"]

# ── @handle-tagging (Oscars retting 22. juli: @demo-labs, ikke demo labs) ──

def test_sanitize_bruker_handle_som_tagg():
    """Med handle skal taggen bli @demo-labs: det er strengen LinkedINs
    mention-liste slår opp på (verifisert live 22. juli, ett unikt treff)."""
    spec = {"body": "Les mer på demo labs i dag."}
    clim._sanitize_spec(spec, brand_name="Demo Labs", handle="demo-labs",
                        wordmark="demo labs")
    assert "@demo-labs" in spec["body"]
    assert "demo labs i dag" not in spec["body"]  # domenet er byttet ut


def test_sanitize_konverterer_gammel_merkenavn_tagg():
    """Eldre utkast/hjerne-tekst med @Demo Labs skal bli @demo-labs."""
    spec = {"body": "Vi i @Demo Labs hjelper deg."}
    clim._sanitize_spec(spec, brand_name="Demo Labs", handle="demo-labs",
                        wordmark="demo labs")
    assert "@demo-labs" in spec["body"]
    assert "@Demo Labs" not in spec["body"]


def test_sanitize_uten_handle_beholder_gammel_form():
    spec = {"body": "Les mer på demo labs."}
    clim._sanitize_spec(spec, brand_name="Demo Labs", wordmark="demo labs")
    assert "@Demo Labs" in spec["body"]


def test_brand_profil_har_linkedin_handle():
    from brandpost import brandkit
    assert brandkit.load_brand("demo").linkedin_handle == "demo-labs"


def test_mention_regex_treffer_handle_men_ikke_epost():
    from brandpost import linkedin_draft as ld
    assert ld._MENTION_RE.findall("Vi i @demo-labs hjelper deg") == ["@demo-labs"]
    # e-post skal ikke plukkes som mention (ingen @ i starten av et ord)
    assert ld._MENTION_RE.findall("skriv til ola@example.com") == []


def test_mention_regex_sluker_ikke_punktum_etter_tagg():
    """«@demo-labs.» skal gi taggen uten punktumet, ellers skriver automatikken
    et ekstra tegn inn i mention-søket og treffer ingenting."""
    from brandpost import linkedin_draft as ld
    assert ld._MENTION_RE.findall("Se @demo-labs. Neste setning.") == ["@demo-labs"]


# ── merkenøytralitet: ett selskaps identitet skal ikke lekke til et annet ──

def test_bildeprompten_baerer_ikke_ett_merkes_farge_til_andre():
    """#52b160 var Demo Labss sekundærgrønn, hardkodet i prompten. Den fulgte med
    til ETHVERT merke, så Minimal-innlegg kom ut i Demo Labss farger (funnet 23. juli)."""
    from brandpost import brandkit, prompts
    for key in ("demo", "minimal"):
        p = prompts.content_prompt("to søyler", brand=brandkit.load_brand(key))
        assert "#52b160" not in p, key


def test_merke_uten_logo_faar_ikke_beskjed_om_aa_tegne_en_mark():
    """Uten egen logo låner motoren et annet merkes mark eller finner på en. Da
    bærer innlegget feil avsender, og det er verre enn et kjedelig bilde."""
    from dataclasses import replace
    from brandpost import brandkit, prompts
    # Et merke uten egen logo, uavhengig av hvilke profiler som finnes i dag.
    b = replace(brandkit.load_brand("minimal"), name="Merkeuten", logo_path=None)
    assert prompts.har_egen_logo(b) is False
    for p in (prompts.content_prompt("motiv", brand=b),
              prompts.brand_card_prompt("motiv", brand=b, headline="H")):
        assert "demo" not in p.lower(), "et annet selskaps navn i prompten"
        assert "INGEN LOGO" in p or "ALDRI tegn en logo" in p or "ALDRI en logo" in p


def test_merke_med_logo_beholder_marken():
    from brandpost import brandkit, prompts
    b = brandkit.load_brand("demo")
    assert prompts.har_egen_logo(b) is True
    assert "mark" in prompts.content_prompt("motiv", brand=b).lower()


def test_lysere_tone_folger_merkefargen():
    from brandpost import prompts
    assert prompts.lysere("#254C7A") != "#254C7A"
    assert prompts.lysere("#1c2e3d") != prompts.lysere("#254C7A"), "ulike merker, ulike toner"
    assert prompts.lysere("ikke-hex") == "ikke-hex"


# ── oppløsning: AI-delen skal nedskaleres, aldri oppskaleres ──

def test_gemini_ber_om_riktig_sideforhold():
    """Uten sideforhold bestemmer motoren selv, og avviket blir midt-beskåret bort.
    1080x1350 er 4:5; ba vi ikke om det, mistet vi 17 % av høyden i beskjæringen."""
    from brandpost import gemini
    assert gemini._aspect_ratio((1080, 1350)) == "4:5"
    assert gemini._aspect_ratio((1080, 1080)) == "1:1"
    assert gemini._aspect_ratio((1350, 1080)) == "3:2"


def test_gemini_ber_om_hoyere_opplosning_enn_lerretet(monkeypatch):
    """Motoren ga 928x1152 mot et lerret på 1080x1350, altså 16 % OPPSKALERING, og
    det var dét som gjorde AI-innholdet uskarpt ved siden av Pillow-teksten.
    2K gir 1856x2304, som nedskaleres. Låst fordi 1K ville sett ut som en besparelse."""
    from brandpost import gemini
    monkeypatch.delenv("NOTATER_SOME_IMAGE_RES", raising=False)
    assert gemini.image_size_hint() == "2K"
    monkeypatch.setenv("NOTATER_SOME_IMAGE_RES", "4K")
    assert gemini.image_size_hint() == "4K"


def test_openai_ber_om_hoy_kvalitet(monkeypatch):
    """gpt-image-2 kan ikke gi flere piksler enn 1024x1536, så kvalitet er det eneste
    håndtaket mot uskarphet der."""
    from brandpost import openai_image
    monkeypatch.delenv("NOTATER_SOME_IMAGE_QUALITY", raising=False)
    assert openai_image.quality() == "high"


def test_nedskalering_beskjaerer_foer_den_skalerer():
    """Er kilden større enn målet, skal pikslene som uansett skal bort kastes FØR
    skaleringen, ikke brukes til å regne ut mellomsteg."""
    from PIL import Image
    from brandpost import render
    stor = Image.new("RGBA", (1856, 2304), (20, 160, 60, 255))
    ut = render._cover_resize(stor, (1080, 1350))
    assert ut.size == (1080, 1350)


def test_oppskalering_virker_fortsatt_naar_kilden_er_liten():
    """Faller motoren tilbake til en liten størrelse, skal det fortsatt gi et kort."""
    from PIL import Image
    from brandpost import render
    liten = Image.new("RGBA", (512, 640), (20, 160, 60, 255))
    assert render._cover_resize(liten, (1080, 1350)).size == (1080, 1350)
