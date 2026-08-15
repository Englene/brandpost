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
    d = _profile(tmp_path, "gamma")
    _quadrants(d / "media" / "kart.png", "PNG")
    _library(d, "kraftkart", "kart.png", approved=False)
    monkeypatch.setenv("BRANDPOST_BRANDS_DIR", str(tmp_path))

    brand = brandkit.load_brand("gamma")
    assert brand.media_assets[0].id == "kraftkart"
    assert brand.media_assets[0].file_path == (d / "media" / "kart.png").resolve()
    assert brandkit.approved_media_assets(brand) == ()
    with pytest.raises(ValueError, match="ikke godkjent"):
        brandkit.media_asset(brand, "kraftkart")


def test_media_id_kan_ikke_krysse_merker(tmp_path, monkeypatch):
    a = _profile(tmp_path, "gamma")
    p = _profile(tmp_path, "delta")
    _quadrants(a / "media" / "a.png", "PNG")
    _quadrants(p / "media" / "p.png", "PNG")
    _library(a, "gamma-kart", "a.png")
    _library(p, "delta-graf", "p.png")
    monkeypatch.setenv("BRANDPOST_BRANDS_DIR", str(tmp_path))

    gamma = brandkit.load_brand("gamma")
    with pytest.raises(ValueError, match="gamma"):
        render.render_post({"bevis_id": "delta-graf", "pillar": "analyse"}, brand=gamma)


@pytest.mark.parametrize(("suffix", "fmt"), [("png", "PNG"), ("jpg", "JPEG")])
def test_png_og_jpeg_dekodes_uten_beskjaering_eller_ai(
        tmp_path, monkeypatch, suffix, fmt):
    d = _profile(tmp_path, "gamma")
    source = d / "media" / f"kart.{suffix}"
    _quadrants(source, fmt)
    _library(d, "kraftkart", source.name)
    monkeypatch.setenv("BRANDPOST_BRANDS_DIR", str(tmp_path))
    monkeypatch.setattr(render, "engine_content",
                        lambda *a, **k: pytest.fail("ekte media skal aldri sendes til KI"))

    out = render.render_post({"bevis_id": "kraftkart", "pillar": "analyse",
                              "orientation": "kvadrat"},
                             brand=brandkit.load_brand("gamma"))
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
    d = _profile(tmp_path, "gamma", library="", display_font="media/fonts/Hanken.ttf")
    fonts = d / "media" / "fonts"
    fonts.mkdir()
    shutil.copy2(brandkit.FONTS_DIR / "Inter.ttf", fonts / "Hanken.ttf")
    monkeypatch.setenv("BRANDPOST_BRANDS_DIR", str(tmp_path))
    brand = brandkit.load_brand("gamma")
    assert brandkit.font_path(brand.display_font) == (fonts / "Hanken.ttf").resolve()

    evil = _profile(tmp_path, "evil", library="", display_font="../utenfor.ttf")
    (tmp_path / "utenfor.ttf").write_bytes(b"ikke en font")
    with pytest.raises(ValueError, match="utenfor merkets mappe"):
        brandkit.load_brand("evil")


def test_library_path_traversal_nektes(tmp_path, monkeypatch):
    _profile(tmp_path, "gamma", library="../stjaalet.toml")
    (tmp_path / "stjaalet.toml").write_text("[[asset]]\n", encoding="utf-8")
    monkeypatch.setenv("BRANDPOST_BRANDS_DIR", str(tmp_path))
    with pytest.raises(ValueError, match="utenfor merkets mappe"):
        brandkit.load_brand("gamma")


def test_refs_mappa_leses_automatisk(tmp_path, monkeypatch):
    """«Slipp en haug med eksempler i media/refs/» er flyten en ny bruker
    forventer, og den dokumentasjonen har lovet hele tiden.

    Koden leste bare en eksplisitt liste i [media].refs. La du femten bilder i
    mappa, så motoren null av dem og ingenting feilet.
    """
    from PIL import Image
    from brandpost import brandkit

    d = tmp_path / "merke"
    (d / "media" / "refs").mkdir(parents=True)
    (d / "profile.toml").write_text(
        'key = "merke"\nname = "Merke"\n'
        '[palette]\nbg="#fff"\nink="#000"\nheadline="#000"\nbrand="#000"\n'
        'shape="#eee"\ndark="#000"\n', encoding="utf-8")
    for navn in ("b.png", "a.jpg", "notat.txt"):
        p = d / "media" / "refs" / navn
        if p.suffix == ".txt":
            p.write_text("ikke et bilde", encoding="utf-8")
        else:
            Image.new("RGB", (8, 8), (1, 2, 3)).save(p)

    monkeypatch.setenv("BRANDPOST_BRANDS_DIR", str(tmp_path))
    refs = brandkit.load_brand("merke").refs

    assert [p.name for p in refs] == ["a.jpg", "b.png"], "sortert, og kun bilder"
    assert all(p.suffix != ".txt" for p in refs)


def test_eksplisitte_refs_gaar_foran_mappa(tmp_path, monkeypatch):
    """Et merke skal kunne prioritere bestemte eksempler. OpenAI-baksiden tar
    bare de fem første, så rekkefølgen avgjør hva som faktisk sendes."""
    from PIL import Image
    from brandpost import brandkit

    d = tmp_path / "merke"
    (d / "media" / "refs").mkdir(parents=True)
    for navn in ("aaa.png", "viktig.png"):
        Image.new("RGB", (8, 8), (1, 2, 3)).save(d / "media" / "refs" / navn)
    (d / "profile.toml").write_text(
        'key = "merke"\nname = "Merke"\n'
        '[media]\nrefs = ["media/refs/viktig.png"]\n'
        '[palette]\nbg="#fff"\nink="#000"\nheadline="#000"\nbrand="#000"\n'
        'shape="#eee"\ndark="#000"\n', encoding="utf-8")

    monkeypatch.setenv("BRANDPOST_BRANDS_DIR", str(tmp_path))
    refs = brandkit.load_brand("merke").refs

    assert refs[0].name == "viktig.png", "eksplisitt valg skal komme først"
    assert len(refs) == 2, "og mappa skal ikke gi duplikat"


def test_bibliotekbilder_sendes_aldri_til_bildemodellen(tmp_path, monkeypatch):
    """Kritisk for PERSONBILDER.

    Bildebiblioteket brukes til ekte bilder man har rett til å publisere, og for
    et selskap er det ofte bilder av navngitte mennesker. De skal brukes NØYAKTIG
    som de er: skalert inn på merkevareflaten, aldri sendt til en bildemodell og
    aldri redigert av en.

    `media/refs/` er det motsatte: de bildene ER stilreferanser og sendes med i
    hvert bildekall. Legger noen et portrett der, sendes et ansikt til
    bildetjenesten som eksempel til etterligning. Denne testen låser skillet.
    """
    from PIL import Image
    from brandpost import brandkit, render

    d = tmp_path / "merke"
    (d / "media").mkdir(parents=True)
    Image.new("RGB", (800, 600), (30, 60, 90)).save(d / "media" / "portrett.jpg")
    (d / "profile.toml").write_text(
        'key = "merke"\nname = "Merke"\n[media]\nlibrary = "media/library.toml"\n'
        '[palette]\nbg="#ffffff"\nink="#000000"\nheadline="#000000"\n'
        'brand="#123456"\nshape="#eeeeee"\ndark="#000000"\n', encoding="utf-8")
    (d / "media" / "library.toml").write_text(
        '[[asset]]\nid = "portrett"\nfile = "portrett.jpg"\n'
        'description = "Portrett av en navngitt person, publisert med samtykke."\n'
        'pillars = []\nalt_text = "Portrett"\napproved = true\n', encoding="utf-8")

    monkeypatch.setenv("BRANDPOST_BRANDS_DIR", str(tmp_path))

    def _forbudt(*a, **k):
        raise AssertionError("et bibliotekbilde ble sendt til en bildemodell")
    monkeypatch.setattr(render, "render_motiv", _forbudt)

    b = brandkit.load_brand("merke")
    r = render.render_post({"media_id": "portrett", "headline": "H"}, brand=b)

    assert r["format"] == "eget-bilde"
    assert r["how"] == "media:portrett"
    assert r["png"][:8] == b"\x89PNG\r\n\x1a\n"
    # Og bildet skal IKKE ha havnet blant stilreferansene.
    assert all("portrett" not in p.name for p in b.refs)


def test_kort_hex_godtas():
    """«#fff» er gyldig CSS, og den som fyller ut en palett første gang skriver
    det like naturlig som «#ffffff». Før dette krasjet hele renderingen med
    «invalid literal for int() with base 16», uten å si hvilket felt det gjaldt."""
    import pytest
    from brandpost.render import _hex

    assert _hex("#fff") == (255, 255, 255)
    assert _hex("#ffffff") == (255, 255, 255)
    assert _hex("#1a2b3c") == (26, 43, 60)
    assert _hex("  #ABC  ") == (170, 187, 204)

    # Og en ekte feil skal si hva som er galt, ikke bare velte.
    with pytest.raises(ValueError, match="ugyldig fargekode"):
        _hex("#12345")
