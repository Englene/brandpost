"""slides — stående karusell-slides (1080×1350) i merkevaren.

Tre slide-typer, alle bygd på de samme primitivene som enkeltbildene
(brandpost/render): sand bakgrunn, interlock-mark, «demo labs»-
ordmerke, prikk-matrise, Fraunces-display. Returnerer PIL-Image (RGB) så
carousel.py kan montere dem til én PDF.

  render_forside(slide, brand, total)      hook-tittel + swipe-hint (slide 1)
  render_innhold(slide, brand, i, total)   nummer + heading + brødtekst + fremdrift
  render_cta(slide, brand)                 oppfordring + stor mark + ordmerke
"""

from __future__ import annotations

from PIL import Image, ImageDraw

from .brandkit import Brand
from .render import (
    SIZE_PORTRAIT, _cover_resize, _draw_big_mark, _draw_dot_grid, _draw_wordmark,
    _fit, _hex, _load_font, _wrap,
)

# Båndet et forside-motiv får lov å vises i, som andel av høyden. Et BÅND, ikke en
# uttonet bakgrunn: en lang gradient lar motivet skinne gjennom bak tittelen, og da
# kolliderer strek og tekst (verifisert 25. juli). Over båndet eier Pillow flaten
# (ordmerke, kicker, tittel), under bor sveip-hintet.
ART_TOP_FRAC = 0.42
ART_BOT_FRAC = 0.86
# Hvor stor del av båndhøyden som tones inn og ut i hver ende, så motivet smelter
# inn i flaten i stedet for å se ut som et innlimt bilde.
ART_FEATHER = 0.14


def _canvas(brand: Brand) -> Image.Image:
    return Image.new("RGBA", SIZE_PORTRAIT, (*_hex(brand.palette.bg), 255))


def _draw_body(draw, text, font, x, y, max_w, fill, *, line_gap: float = 1.42) -> int:
    """Tegn ombrutt brødtekst; returner y etter siste linje."""
    lh = int(font.size * line_gap)
    for ln in _wrap(draw, text, font, max_w):
        draw.text((x, y), ln, font=font, fill=fill)
        y += lh
    return y


def _progress(img: Image.Image, brand: Brand, index: int, total: int) -> None:
    """Fremdrifts-prikker nederst: nåværende slide fylt, resten svake."""
    if total <= 1:
        return
    w, h = img.size
    pal = brand.palette
    d = ImageDraw.Draw(img)
    r = int(w * 0.008)
    gap = int(w * 0.032)
    span = (total - 1) * gap
    x0 = (w - span) // 2
    y = h - int(h * 0.06)
    for i in range(total):
        cx = x0 + i * gap
        fill = _hex(pal.brand) if i == index else _hex(pal.shape)
        d.ellipse([cx - r, y - r, cx + r, y + r], fill=fill)


def _lim_inn_motiv(img: Image.Image, art: Image.Image) -> None:
    """Legg motivet inn i sitt bånd, med mykt tonede kanter."""
    w, h = img.size
    y0, y1 = int(h * ART_TOP_FRAC), int(h * ART_BOT_FRAC)
    band_h = max(1, y1 - y0)
    band = _cover_resize(art.convert("RGBA"), (w, band_h))
    maske = Image.new("L", (1, band_h), 255)
    fjaer = max(1, int(band_h * ART_FEATHER))
    for y in range(fjaer):
        v = int(255 * y / fjaer)
        maske.putpixel((0, y), v)
        maske.putpixel((0, band_h - 1 - y), v)
    img.paste(band, (0, y0), maske.resize((w, band_h)))


def render_forside(slide: dict, brand: Brand, total: int,
                   *, art: Image.Image | None = None) -> Image.Image:
    """Forside: stor hook-tittel + ordmerke + swipe-hint, valgfritt over et motiv."""
    img = _canvas(brand)
    pal = brand.palette
    w, h = img.size
    margin = int(w * 0.082)
    # Uten motiv bærer marken kortet visuelt. Med motiv ville de to kjempet om
    # samme flate, så marken vikér.
    if art is None:
        _draw_big_mark(img, brand, scale=0.46, corner="br")
    _draw_dot_grid(img, _hex(pal.brand))
    _draw_wordmark(img, brand, margin, int(h * 0.07), int(w * 0.052),
                   text_rgb=_hex(pal.headline))

    draw = ImageDraw.Draw(img)
    kicker = (slide.get("kicker") or "").strip()
    y = int(h * 0.27)
    if kicker:
        kf = _load_font(brand.body_font, int(w * 0.028), bold=True)
        draw.text((margin, y), kicker.upper(), font=kf, fill=_hex(pal.brand))
        y += int(w * 0.055)
    title = (slide.get("heading") or slide.get("tittel") or "").strip()
    tittel_hoyde = int(h * (0.19 if art is not None else 0.40))
    tf, lines, lh = _fit(draw, title, brand.display_font, int(w * 0.84), tittel_hoyde,
                         start=int(w * 0.115), min_size=int(w * 0.06))
    for ln in lines:
        draw.text((margin, y), ln, font=tf, fill=_hex(pal.headline))
        y += lh
    sub = (slide.get("body") or "").strip()
    if sub:
        y += int(lh * 0.3)
        bf = _load_font(brand.body_font, int(w * 0.032))
        _draw_body(draw, sub, bf, margin, y, int(w * 0.78), _hex(pal.ink))
    if art is not None:
        _lim_inn_motiv(img, art)
    # Swipe-hint nede-venstre
    hint = _load_font(brand.body_font, int(w * 0.03), bold=True)
    draw.text((margin, h - int(h * 0.11)), "Sveip  →", font=hint, fill=_hex(pal.brand))
    return img.convert("RGB")


def render_innhold(slide: dict, brand: Brand, *, pos: int, total: int,
                   number: int | None = None) -> Image.Image:
    """Innholds-slide: stort nummer + heading + brødtekst + fremdrift.

    pos = slidens absolutte posisjon (0-basert, for fremdrifts-prikkene).
    number = punktets nummer (1,2,3 …), forside/cta teller ikke."""
    img = _canvas(brand)
    pal = brand.palette
    w, h = img.size
    margin = int(w * 0.082)
    _draw_dot_grid(img, _hex(pal.brand), cols=5, rows=3)
    _draw_wordmark(img, brand, margin, int(h * 0.07), int(w * 0.044),
                   text_rgb=_hex(pal.headline))

    draw = ImageDraw.Draw(img)
    # Stort nummer (punktets nummer i rekka, forside teller ikke).
    #
    # Det BEREGNEDE nummeret vinner over modellens eget felt. Motoren teller
    # innholds-slides deterministisk i carousel.build_carousel; modellen teller
    # slide-posisjoner og bommer systematisk med forsiden: i «Fem formuleringer
    # som svekker en søknad» fikk første formulering tallet 2, siden den lå på
    # slide to. `pos + 1` er siste utvei og har samme feil, så den brukes bare
    # når ingen har talt for oss.
    num = str(number or slide.get("number") or (pos + 1))
    nf = _load_font(brand.display_font, int(w * 0.16), bold=True)
    draw.text((margin, int(h * 0.16)), num, font=nf, fill=_hex(pal.shape))

    y = int(h * 0.34)
    heading = (slide.get("heading") or "").strip()
    if heading:
        hf, hl, hlh = _fit(draw, heading, brand.display_font, int(w * 0.82), int(h * 0.22),
                           start=int(w * 0.075), min_size=int(w * 0.045))
        for ln in hl:
            draw.text((margin, y), ln, font=hf, fill=_hex(pal.headline))
            y += hlh
        y += int(hlh * 0.35)
    body = (slide.get("body") or "").strip()
    if body:
        bf = _load_font(brand.body_font, int(w * 0.034))
        _draw_body(draw, body, bf, margin, y, int(w * 0.80), _hex(pal.ink))
    _progress(img, brand, pos, total)
    return img.convert("RGB")


def render_cta(slide: dict, brand: Brand) -> Image.Image:
    """Avslutnings-slide: oppfordring + stor mark + ordmerke."""
    img = _canvas(brand)
    pal = brand.palette
    w, h = img.size
    margin = int(w * 0.082)
    _draw_big_mark(img, brand, scale=0.52, corner="br")
    _draw_dot_grid(img, _hex(pal.brand))

    draw = ImageDraw.Draw(img)
    y = int(h * 0.24)
    heading = (slide.get("heading") or "Klar til å prøve?").strip()
    hf, lines, lh = _fit(draw, heading, brand.display_font, int(w * 0.82), int(h * 0.30),
                         start=int(w * 0.10), min_size=int(w * 0.055))
    for ln in lines:
        draw.text((margin, y), ln, font=hf, fill=_hex(pal.headline))
        y += lh
    body = (slide.get("body") or "").strip()
    if body:
        y += int(lh * 0.3)
        bf = _load_font(brand.body_font, int(w * 0.036))
        y = _draw_body(draw, body, bf, margin, y, int(w * 0.74), _hex(pal.ink))
    # Ordmerke stort nede-venstre
    _draw_wordmark(img, brand, margin, h - int(h * 0.13), int(w * 0.06),
                   text_rgb=_hex(pal.headline))
    return img.convert("RGB")


def render_slide(slide: dict, brand: Brand, *, pos: int, total: int,
                 number: int | None = None,
                 art: Image.Image | None = None) -> Image.Image:
    """Rendr én slide etter 'kind' (forside | innhold | cta). `art` gjelder KUN
    forsiden: innholdsslidene skal leses på to sekunder, og der leses ren tekst best."""
    kind = (slide.get("kind") or "innhold").strip().lower()
    if kind == "forside":
        return render_forside(slide, brand, total, art=art)
    if kind == "cta":
        return render_cta(slide, brand)
    return render_innhold(slide, brand, pos=pos, total=total, number=number)
