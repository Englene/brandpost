"""Enhetstester for SoMe-generatoren (brandpost).

Dekker den deterministiske motoren: merkevare-lasting, typografi-kort-rendering
(inkl. æøå), kontekst-samling fra vaulten, utkast-lagring + dedup, og e-post-
montering med inline-bilder. Gemini-stien testes ikke her (krever nøkkel + kall);
render_editorial faller uansett trygt til mal-kortet uten nøkkel.
"""

from __future__ import annotations

import json
from io import BytesIO

from PIL import Image

from brandpost import (brandkit, carousel, context as ctxmod,
                                    email as emailmod, render, store)


def _png_image(png: bytes) -> Image.Image:
    return Image.open(BytesIO(png))


def test_brand_loads_and_font_resolves():
    b = brandkit.load_brand("demo")
    assert b.name == "Demo Labs"
    assert brandkit.font_path(b.display_font) is not None  # Fraunces vendret i assets/
    assert brandkit.enabled_brands() == ["demo"]


def test_render_template_is_square_rgb_on_sand():
    spec = {"format": "typografi-kort", "orientation": "kvadrat",
            "headline": "Konsulenten tar 100 000 kr."}
    out = render.render_post(spec, brand=brandkit.load_brand("demo"))
    assert out["how"] == "template"
    im = _png_image(out["png"]).convert("RGB")
    assert im.size == render.SIZE_SQUARE
    # venstre kant, midt på, skal være sand (#F5F3EF) = (243, 236, 219)
    r, g, bl = im.getpixel((8, 540))
    assert (abs(r - 243), abs(g - 236), abs(bl - 219)) < (12, 12, 12)


def test_render_handles_norwegian_chars():
    spec = {"format": "typografi-kort", "kicker": "Søknad på 30 minutter",
            "headline": "Én søknad. Samme Forskningsråd.", "subhead": "Færre kroner, større sjanse."}
    out = render.render_post(spec, brand=brandkit.load_brand("demo"))
    assert len(out["png"]) > 1000  # rendret uten å kaste på æøå
    assert _png_image(out["png"]).size == render.SIZE_PORTRAIT  # default stående


def test_render_editorial_falls_back_to_template_without_key(monkeypatch):
    # Ingen GEMINI_API_KEY -> generate_image kaster -> trygg mal-fallback.
    # Rydder også OpenAI-miljøet: enkelte testfiler (log_recon/morning_gate) laster
    # repoets .env ved import, og uten dette gjorde testen EKTE gpt-image-2-kall.
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("NOTATER_SOME_IMAGE_BACKEND", raising=False)
    spec = {"format": "redaksjonelt", "headline": "Test", "image_prompt": "noe"}
    out = render.render_post(spec, brand=brandkit.load_brand("demo"))
    assert out["how"] == "template-fallback"
    assert _png_image(out["png"]).size == render.SIZE_PORTRAIT


def test_motiv_is_default_when_motif_present(monkeypatch):
    # Et motiv -> format 'motiv' automatisk; uten nøkkel faller den trygt til tekst-kort.
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("NOTATER_SOME_IMAGE_BACKEND", raising=False)
    b = brandkit.load_brand("demo")
    out = render.render_post({"headline": "Test", "motif": "en tom pidestall i grønt"}, brand=b)
    assert out["format"] == "motiv"
    assert out["how"] == "template-fallback"
    assert _png_image(out["png"]).size == render.SIZE_PORTRAIT


def test_recent_angles_include_motif(tmp_path):
    spec = {"headline": "H", "motif": "et fjell av fakturaer", "body": "b", "why_now": "w"}
    png = render.render_template({"headline": "H"}, brandkit.load_brand("demo"))
    meta = store.write_draft(tmp_path, "demo", spec, png, index=1)
    assert meta["motif"] == "et fjell av fakturaer"
    store.record(tmp_path, [meta])
    assert store.recent_angles(tmp_path)[-1]["motif"] == "et fjell av fakturaer"


def test_tom_arbeidsmappe_er_trygg(tmp_path):
    """En fersk kloning har ingen notater. Da skal alt være tomt, ikke feile:
    du skal kunne se et resultat før du har rigget noe som helst."""
    data = ctxmod.gather_context(tmp_path, days=10)
    assert data["notes"] == []
    assert data["context_links"] == []
    assert "generated" in data


def test_context_leser_notatmappa(tmp_path):
    """notes/ er hele kontekst-inngangen: legg markdown der, så leser hjernen det.
    Første linje er tittelen, resten blir sammendrag."""
    notes = tmp_path / "notes"
    notes.mkdir(parents=True)
    (notes / "moete.md").write_text(
        "# Kunden spurte om fristen igjen\n\nTre av fem tok det opp uoppfordret.\n",
        encoding="utf-8")

    data = ctxmod.gather_context(tmp_path, days=30)

    assert len(data["notes"]) == 1
    rad = data["notes"][0]
    assert rad["tittel"] == "Kunden spurte om fristen igjen"
    assert "Tre av fem" in rad["sammendrag"]
    assert data["context_links"] == ["moete"]


def test_store_write_draft_and_dedup(tmp_path):
    spec = {"format": "typografi-kort", "headline": "Overskrift", "body": "brød", "why_now": "fordi"}
    png = render.render_post(spec, brand=brandkit.load_brand("demo"))["png"]
    meta = store.write_draft(tmp_path, "demo", spec, png, index=1)
    assert meta["headline"] == "Overskrift"
    assert (tmp_path / "socials").exists()
    assert meta["png_path"].endswith(".png")
    store.record(tmp_path, [meta])
    angles = store.recent_angles(tmp_path)
    assert angles and angles[-1]["headline"] == "Overskrift"


def test_email_build_has_inline_images(tmp_path):
    spec = {"format": "typografi-kort", "headline": "H", "body": "b", "why_now": "w"}
    png = render.render_post(spec, brand=brandkit.load_brand("demo"))["png"]
    drafts = [
        {"format": "typografi-kort", "headline": "En", "body": "b1", "why_now": "w1", "png": png},
        {"format": "typografi-kort", "headline": "To", "body": "b2", "why_now": "w2", "png": png},
    ]
    subject, html, inline, attachments = emailmod.build_some_email(drafts)
    assert "Demo Labs" in subject
    assert attachments == []  # ingen karusell -> ingen vedlegg
    assert len(inline) == 2
    for cid in inline:
        assert f"cid:{cid}" in html  # HTML refererer hvert bilde
    assert "Hvorfor nå" in html


def test_resolve_size_orientation():
    assert render.resolve_size({"orientation": "kvadrat"}) == render.SIZE_SQUARE
    assert render.resolve_size({"orientation": "staaende"}) == render.SIZE_PORTRAIT
    assert render.resolve_size({}) == render.SIZE_PORTRAIT  # default stående


def test_themes_rotate_and_differ_visually():
    b = brandkit.load_brand("demo")
    spec = {"variant": "utsagn", "headline": "Test", "subhead": "under"}
    # seq roterer gjennom alle temaene
    keys = {render.pick_theme(spec, i).key for i in range(len(render.THEMES))}
    assert len(keys) == len(render.THEMES)
    # mørkt tema har mørk bakgrunn (ikke sand) -> ekte visuell forskjell
    dark = render.render_template({**spec, "theme": "mork", "orientation": "kvadrat"}, b)
    r, g, bl = _png_image(dark).convert("RGB").getpixel((8, 8))
    assert r < 60 and g < 80  # mørkegrønt hjørne
    # eksplisitt tema overstyrer rotasjon
    assert render.pick_theme({"theme": "blokk"}, 0).key == "blokk"


def test_variants_render_square_and_portrait():
    b = brandkit.load_brand("demo")
    specs = {
        "utsagn": {"variant": "utsagn", "headline": "Gamle metoder er dyre."},
        "tall": {"variant": "tall", "number": "90 %", "headline": "lavere kostnad."},
        "sitat": {"variant": "sitat", "headline": "Vi er for små."},
    }
    for variant, spec in specs.items():
        for size in (render.SIZE_SQUARE, render.SIZE_PORTRAIT):
            png = render.render_template(spec, b, size)
            assert _png_image(png).size == size, f"{variant} {size}"


def _carousel_spec():
    return {
        "type": "karusell", "tittel": "5 feil", "brand": "demo",
        "slides": [
            {"kind": "forside", "heading": "5 feil som stopper søknaden", "body": "Sveip."},
            {"kind": "innhold", "heading": "Punkt én", "body": "Forklaring én."},
            {"kind": "innhold", "heading": "Punkt to", "body": "Forklaring to."},
            {"kind": "cta", "heading": "Klar?", "body": "Prøv Demo Labs."},
        ],
    }


def test_carousel_builds_valid_multipage_pdf():
    built = carousel.build_carousel(_carousel_spec(), brand=brandkit.load_brand("demo"))
    assert built["n"] == 4
    assert built["pdf"][:4] == b"%PDF"           # gyldig PDF-header
    assert len(built["slide_pngs"]) == 4
    assert _png_image(built["cover"]).size == render.SIZE_PORTRAIT
    from pypdf import PdfReader
    reader = PdfReader(BytesIO(built["pdf"]))
    assert len(reader.pages) == 4                # én side per slide
    assert built["size_mb"] < 10                 # under LinkedIn-grensa


def test_carousel_store_and_email_attachment(tmp_path):
    b = brandkit.load_brand("demo")
    spec = {**_carousel_spec(), "body": "brød", "why_now": "fordi"}
    built = carousel.build_carousel(spec, brand=b)
    meta = store.write_carousel(tmp_path, "demo", spec, built, index=1)
    assert meta["type"] == "karusell" and meta["pdf_path"].endswith(".pdf")
    subject, html, inline, attachments = emailmod.build_some_email([meta])
    assert "karusell" in subject
    assert len(inline) == 1                       # forside-thumbnail inline
    assert len(attachments) == 1                  # PDF vedlagt
    assert attachments[0]["mime"] == "application/pdf"
    assert attachments[0]["data"][:4] == b"%PDF"


# ── merkevare-profil (data-drevet fra brands/<key>/) ────────



def test_minimal_profile_degrades_gracefully():
    # Minimal fikk ekte logo, palett og font fra minimal.no 23. juli. Det som fortsatt
    # mangler er redaksjonelt (pilarer, prosa), og loaderen skal tåle nettopp det.
    b = brandkit.load_brand("minimal")
    assert b.enabled is False                # dvalende -> ikke i enabled_brands()
    assert "minimal" not in brandkit.enabled_brands()
    assert b.pillars == ()                   # pilarer er valget, ikke motorens
    assert brandkit.voice_guide(b)           # faller til innbakt fallback, ikke tom
    assert "minimal" in brandkit.available_brands()


def test_merke_uten_media_degraderer_fortsatt():
    """Degraderingen må testes på et merke UTEN media, ikke på Minimal som nå har det."""
    from dataclasses import replace
    b = replace(brandkit.load_brand("minimal"), logo_path=None, refs=())
    assert b.logo_path is None and b.refs == ()
    assert brandkit.voice_guide(b)


def test_unknown_brand_raises():
    import pytest
    with pytest.raises(ValueError):
        brandkit.load_brand("finnesikke")


def test_pillar_coverage_tracks_and_rotates(tmp_path):
    ids = ["a", "b", "c"]
    drafts = [{"brand": "x", "format": "typografi-kort", "headline": f"h{i}",
               "motif": "", "pillar": "a"} for i in range(3)]
    drafts.append({"brand": "x", "format": "motiv", "headline": "hb", "motif": "", "pillar": "b"})
    store.record(tmp_path, drafts)
    cov = store.pillar_coverage(tmp_path, ids)
    assert cov == {"a": 3, "b": 1, "c": 0}   # 0-fylt for uberørte pilarer
    assert min(cov, key=cov.get) == "c"      # rotasjon skal prioritere den underdekte


def test_write_draft_records_pillar(tmp_path):
    spec = {"format": "typografi-kort", "headline": "H", "pillar": "myte-avliving",
            "body": "b", "why_now": "w"}
    png = render.render_template({"headline": "H"}, brandkit.load_brand("demo"))
    meta = store.write_draft(tmp_path, "demo", spec, png, index=1)
    assert meta["pillar"] == "myte-avliving"
    store.record(tmp_path, [meta])
    assert store.recent_angles(tmp_path)[-1]["pillar"] == "myte-avliving"
