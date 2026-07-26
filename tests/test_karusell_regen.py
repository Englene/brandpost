"""Karusell-regenerering: ombygging over eksisterende filer + AI-forside.

Karusellen tegnes lokalt fra maler, så byggingen koster null bildekall. Motoren
mockes der den faktisk slås opp, så ingen test går på nett.
"""

from __future__ import annotations

import json

import pytest
from PIL import Image

from brandpost import brandkit, carousel, render, slides, store


def _spec(n_innhold: int = 2) -> dict:
    s = [{"kind": "forside", "heading": "Fem feil", "body": "Sveip."}]
    s += [{"kind": "innhold", "heading": f"Punkt {i}", "body": f"Forklaring {i}."}
          for i in range(1, n_innhold + 1)]
    s += [{"kind": "cta", "heading": "Klar?", "body": "Prøv oss."}]
    return {"type": "karusell", "tittel": "Fem feil", "brand": "demo", "slides": s}


@pytest.fixture()
def utkast(tmp_path):
    """Ekte karusell på disk, som etter en nattkjøring."""
    b = brandkit.load_brand("demo")
    built = carousel.build_carousel(_spec(2), brand=b)
    meta = store.write_carousel(tmp_path, "demo", _spec(2), built, index=1)
    return {k: v for k, v in meta.items() if k not in ("pdf", "cover")}


# ── ombygging skriver til de samme filene ──────────────────

def test_ombygging_beholder_filnavnene(utkast, tmp_path):
    """write_carousel regner alltid ut nytt filnavn fra tittelen. Skiftet navnet seg,
    ville manifestet, kalender-miniatyren og publiseringsveien pekt på gamle filer."""
    from pathlib import Path
    pdf_foer = Path(utkast["pdf_path"])
    cover_foer = Path(utkast["cover_path"])
    stoerrelse_foer = pdf_foer.stat().st_size

    endret = {**utkast, "spec": {**utkast["spec"],
                                 "slides": _spec(3)["slides"]}}  # én slide mer
    res = carousel.rebuild_carousel(endret)

    assert res["n"] == 5
    assert pdf_foer.exists() and cover_foer.exists(), "samme stier skal fortsatt finnes"
    assert pdf_foer.stat().st_size != stoerrelse_foer, "PDF-en skal faktisk være ny"
    assert len(list((pdf_foer.parent / pdf_foer.stem).glob("slide-*.png"))) == 5


def test_kortere_karusell_rydder_etterlatte_slides(utkast):
    """Visningen globber slide-mappa. Uten opprydding ville slides fra den LENGRE
    utgaven blitt hengende igjen og vist etter en ombygging til færre."""
    from pathlib import Path
    slide_dir = Path(utkast["pdf_path"]).parent / Path(utkast["pdf_path"]).stem
    assert len(list(slide_dir.glob("slide-*.png"))) == 4

    kortere = {**utkast, "spec": {**utkast["spec"], "slides": _spec(1)["slides"]}}
    res = carousel.rebuild_carousel(kortere)

    assert res["n"] == 3
    assert res["ryddet"] == ["slide-4.png"]
    assert sorted(p.name for p in slide_dir.glob("slide-*.png")) == [
        "slide-1.png", "slide-2.png", "slide-3.png"]


def test_ombygging_uten_slides_nekter(utkast):
    tomt = {**utkast, "spec": {"slides": []}}
    with pytest.raises(ValueError):
        carousel.rebuild_carousel(tomt)


# ── AI-forside ─────────────────────────────────────────────

def test_uten_motiv_kostar_ingen_bildekall(monkeypatch):
    """Nattkjøringen skal ikke plutselig begynne å bruke bildekall på karuseller."""
    kalt = []
    monkeypatch.setattr(render, "engine_content",
                        lambda *a, **k: kalt.append(1) or None)
    carousel.build_carousel(_spec(1))
    assert kalt == []


def test_motiv_gir_ett_bildekall_til_forsiden(monkeypatch):
    """Ett kall per karusell, ikke ett per slide: åtte uavhengige bilder leser lett
    som åtte ulike serier, og koster sju til ti ganger et vanlig innlegg."""
    kalt = []
    kunst = Image.new("RGBA", slides.SIZE_PORTRAIT, (10, 120, 60, 255))
    monkeypatch.setattr(render, "engine_content",
                        lambda *a, **k: kalt.append(1) or kunst)

    built = carousel.build_carousel({**_spec(3), "motif": "tre søyler"})

    assert len(kalt) == 1, "ett bildekall totalt, uansett antall slides"
    assert built["n"] == 5


def test_forsiden_beholder_ren_flate_til_typografien(monkeypatch):
    """kravet: AI-delen må se typografisk ut. Toppen der ordmerke og tittel
    tegnes skal være merkets egen flate, ikke motivet."""
    b = brandkit.load_brand("demo")
    kunst = Image.new("RGBA", slides.SIZE_PORTRAIT, (200, 30, 30, 255))  # knallrødt
    med = slides.render_forside({"kind": "forside", "heading": "Test"}, b, 4, art=kunst)

    w, h = med.size
    r, g, bl = med.convert("RGB").getpixel((int(w * 0.04), int(h * 0.03)))
    sand = render._hex(b.palette.bg)
    assert abs(r - sand[0]) < 14 and abs(g - sand[1]) < 14 and abs(bl - sand[2]) < 14, \
        "toppsonen skal være merkets flate, ikke motivet"


def test_motivet_vises_faktisk_i_midtbandet():
    b = brandkit.load_brand("demo")
    kunst = Image.new("RGBA", slides.SIZE_PORTRAIT, (200, 30, 30, 255))
    uten = slides.render_forside({"kind": "forside", "heading": "Test"}, b, 4)
    med = slides.render_forside({"kind": "forside", "heading": "Test"}, b, 4, art=kunst)
    assert uten.tobytes() != med.tobytes(), "motivet skal gi et synlig annet kort"


def test_innholdsslides_far_aldri_motiv():
    """Bare forsiden. Innholdsslidene leses på to sekunder, og der leses ren tekst best."""
    b = brandkit.load_brand("demo")
    kunst = Image.new("RGBA", slides.SIZE_PORTRAIT, (200, 30, 30, 255))
    uten = slides.render_slide({"kind": "innhold", "heading": "P"}, b, pos=1, total=3)
    med = slides.render_slide({"kind": "innhold", "heading": "P"}, b, pos=1, total=3,
                              art=kunst)
    assert uten.tobytes() == med.tobytes()


# ── omskriving av slide-tekst ──────────────────────────────

def test_omskriving_sender_alle_rettelser_med(monkeypatch, utkast):
    """Som for bildene: et problem du har påpekt skal ikke komme tilbake."""
    sett = {}

    def fake_call(system, user, schema, **k):
        # EKTE konvolutt-form: structured_call svarer med et ytre lag, og svaret
        # ligger under "structured_output". Mocker man det indre svaret, tester man
        # en kontrakt som ikke finnes.
        sett["user"] = user
        return {"structured_output": {"tittel": "Ny tittel",
                                      "slides": [{"kind": "forside", "heading": "Ny"},
                                                 {"kind": "cta", "heading": "Klar?"}]},
                "_model": "test"}
    from brandpost import model as loop_model
    monkeypatch.setattr(loop_model, "structured_call", fake_call)

    ut = carousel.omskriv_slides(utkast, brandkit.load_brand("demo"),
                                 rettelser=["for mye tekst", "punkt 3 er svakt"])

    assert ut["tittel"] == "Ny tittel" and len(ut["slides"]) == 2
    assert "for mye tekst" in sett["user"] and "punkt 3 er svakt" in sett["user"]
