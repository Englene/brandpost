"""Merkeisolert media/library.toml og deterministisk ekte-bilde-rendering."""

from __future__ import annotations

import shutil
from io import BytesIO

import pytest
from PIL import Image

from brandpost import brandkit, render


def _profile(base, key: str, *, library: str = "media/library.toml",
             display_font: str = "Fraunces.ttf"):
    d = base / key
    (d / "media").mkdir(parents=True)
    (d / "profile.toml").write_text(f'''\
key = "{key}"
name = "{key.title()}"
handle = "{key}"
enabled = true

[palette]
bg = "#f1ede4"
ink = "#5a5d66"
headline = "#14161b"
brand = "#152a18"
shape = "#e9e4d8"
dark = "#152a18"

[fonts]
display = "{display_font}"
body = "Inter.ttf"

[media]
library = "{library}"
''', encoding="utf-8")
    return d


def _library(d, asset_id: str, filename: str, *, approved: bool = True):
    (d / "media" / "library.toml").write_text(f'''\
[[asset]]
id = "{asset_id}"
file = "{filename}"
description = "Ekte analysebilde"
pillars = ["analyse"]
alt_text = "Analyse av kraftsystemet"
approved = {str(approved).lower()}
''', encoding="utf-8")


def _quadrants(path, fmt: str):
    im = Image.new("RGB", (400, 100), "white")
    for box, color in [((0, 0, 200, 50), "red"), ((200, 0, 400, 50), "green"),
                       ((0, 50, 200, 100), "blue"), ((200, 50, 400, 100), "yellow")]:
        im.paste(color, box)
    im.save(path, format=fmt)


def test_library_lastes_typet_og_avslaatt_id_avvises(tmp_path, monkeypatch):
    d = _profile(tmp_path, "akser")
    _quadrants(d / "media" / "kart.png", "PNG")
    _library(d, "kraftkart", "kart.png", approved=False)
    monkeypatch.setenv("BRANDPOST_BRANDS_DIR", str(tmp_path))

    brand = brandkit.load_brand("akser")
    assert brand.media_assets[0].id == "kraftkart"
    assert brand.media_assets[0].file_path == (d / "media" / "kart.png").resolve()
    assert brandkit.approved_media_assets(brand) == ()
    with pytest.raises(ValueError, match="ikke godkjent"):
        brandkit.media_asset(brand, "kraftkart")


def test_media_id_kan_ikke_krysse_merker(tmp_path, monkeypatch):
    a = _profile(tmp_path, "akser")
    p = _profile(tmp_path, "pengefix")
    _quadrants(a / "media" / "a.png", "PNG")
    _quadrants(p / "media" / "p.png", "PNG")
    _library(a, "akser-kart", "a.png")
    _library(p, "pengefix-graf", "p.png")
    monkeypatch.setenv("BRANDPOST_BRANDS_DIR", str(tmp_path))

    akser = brandkit.load_brand("akser")
    with pytest.raises(ValueError, match="akser"):
        render.render_post({"bevis_id": "pengefix-graf", "pillar": "analyse"}, brand=akser)


@pytest.mark.parametrize(("suffix", "fmt"), [("png", "PNG"), ("jpg", "JPEG")])
def test_png_og_jpeg_dekodes_uten_beskjaering_eller_ai(
        tmp_path, monkeypatch, suffix, fmt):
    d = _profile(tmp_path, "akser")
    source = d / "media" / f"kart.{suffix}"
    _quadrants(source, fmt)
    _library(d, "kraftkart", source.name)
    monkeypatch.setenv("BRANDPOST_BRANDS_DIR", str(tmp_path))
    monkeypatch.setattr(render, "engine_content",
                        lambda *a, **k: pytest.fail("ekte media skal aldri sendes til KI"))

    out = render.render_post({"bevis_id": "kraftkart", "pillar": "analyse",
                              "orientation": "kvadrat"},
                             brand=brandkit.load_brand("akser"))
    image = Image.open(BytesIO(out["png"])).convert("RGB")
    assert image.size == (1080, 1350)
    assert out["how"] == "media:kraftkart"
    assert out["alt_text"] == "Analyse av kraftsystemet"
    # Alle fire kildehjørner overlever contain-komposisjonen; crop ville mistet minst to.
    colors = image.resize((64, 80)).getdata()
    assert any(r > 170 and g < 100 and b < 100 for r, g, b in colors)
    assert any(b > 120 and r < 130 for r, g, b in colors)
    assert any(r > 160 and g > 140 and b < 130 for r, g, b in colors)


def test_merkelokal_font_virker_og_traversal_nektes(tmp_path, monkeypatch):
    d = _profile(tmp_path, "akser", library="", display_font="media/fonts/Hanken.ttf")
    fonts = d / "media" / "fonts"
    fonts.mkdir()
    shutil.copy2(brandkit.FONTS_DIR / "Inter.ttf", fonts / "Hanken.ttf")
    monkeypatch.setenv("BRANDPOST_BRANDS_DIR", str(tmp_path))
    brand = brandkit.load_brand("akser")
    assert brandkit.font_path(brand.display_font) == (fonts / "Hanken.ttf").resolve()

    evil = _profile(tmp_path, "evil", library="", display_font="../utenfor.ttf")
    (tmp_path / "utenfor.ttf").write_bytes(b"ikke en font")
    with pytest.raises(ValueError, match="utenfor merkets mappe"):
        brandkit.load_brand("evil")


def test_library_path_traversal_nektes(tmp_path, monkeypatch):
    _profile(tmp_path, "akser", library="../stjaalet.toml")
    (tmp_path / "stjaalet.toml").write_text("[[asset]]\n", encoding="utf-8")
    monkeypatch.setenv("BRANDPOST_BRANDS_DIR", str(tmp_path))
    with pytest.raises(ValueError, match="utenfor merkets mappe"):
        brandkit.load_brand("akser")
