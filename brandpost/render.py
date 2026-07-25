"""render — lag bildet for ett innlegg.

To akser gir variasjon:
  VARIANT (tekst-struktur, spec['variant']): 'utsagn' | 'tall' | 'sitat'
  TEMA    (visuell skin, roteres for variasjon): sand-høyre, sand-venstre, mørk,
          sentrert, blokk. Styrer bakgrunn, mark-plassering, aksent, justering.

Et kort = en variant tegnet inne i et tema, så to påfølgende kort ser forskjellige
ut selv med samme tekst-struktur. Format: stående 1080×1350 (default) eller
kvadratisk via spec['orientation'].

Redaksjonell sti ('format':'redaksjonelt') går via Gemini (gemini.py) med tekst-
verifisering og trygg mal-fallback.

Spec-felt (alle valgfrie unntatt headline/number):
  format, variant, theme, orientation, headline, subhead, kicker, number,
  image_prompt, concept, brand
"""

from __future__ import annotations

import os
import sys
import time
import re
from dataclasses import dataclass
from io import BytesIO

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from . import brandkit
from .brandkit import Brand

SIZE_SQUARE = (1080, 1080)
SIZE_PORTRAIT = (1080, 1350)


def _hex(c: str) -> tuple[int, int, int]:
    c = c.lstrip("#")
    return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def _pcol(pal, attr: str) -> tuple[int, int, int]:
    return _hex(getattr(pal, attr))


def _cap_text(s: str | None, max_chars: int) -> str:
    """Backstop mot for lang subtekst på typografi-kort: kutt til ~max_chars på
    ordgrense. Utdypningen skal uansett ligge i LinkedIn-teksten (body), ikke på kortet."""
    s = (s or "").strip()
    if len(s) <= max_chars:
        return s
    return s[:max_chars].rsplit(" ", 1)[0].rstrip(",.;:· ") + "."


def resolve_size(spec: dict) -> tuple[int, int]:
    o = (spec.get("orientation") or "staaende").strip().lower()
    return SIZE_SQUARE if o in ("kvadrat", "kvadratisk", "square", "1:1") else SIZE_PORTRAIT


# ───────────────────────────────────────────────────────────
# Temaer (visuelle skins). Fargene er palett-attributt-navn.
# ───────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Theme:
    key: str
    bg: str
    fg: str           # headline-farge
    fg2: str          # subhead/label-farge
    kicker: str
    mark_corner: str | None
    mark_scale: float
    mark_tint: str | None      # palett-attr for ensfarget mark, ellers None (to-tone)
    accent: str                # "dots" | "quarter" | "none"
    accent_corner: str
    accent_col: str
    dot_alpha: int
    align: str                 # "left" | "center"
    wordmark: str              # "tl" | "bottom" | "none"
    band: str | None           # palett-attr for bunn-bånd, ellers None
    text_top: float
    text_bottom: float


THEMES = [
    Theme("sand-hoyre", bg="bg", fg="headline", fg2="brand", kicker="brand",
          mark_corner="br", mark_scale=0.44, mark_tint=None,
          accent="dots", accent_corner="tr", accent_col="brand", dot_alpha=135,
          align="left", wordmark="tl", band=None, text_top=0.24, text_bottom=0.70),
    Theme("sand-venstre", bg="bg", fg="headline", fg2="brand", kicker="brand",
          mark_corner="bl", mark_scale=0.42, mark_tint=None,
          accent="quarter", accent_corner="tr", accent_col="shape", dot_alpha=255,
          align="left", wordmark="tl", band=None, text_top=0.25, text_bottom=0.72),
    Theme("mork", bg="dark", fg="bg", fg2="brand", kicker="brand",
          mark_corner="br", mark_scale=0.44, mark_tint="brand",
          accent="dots", accent_corner="tr", accent_col="brand", dot_alpha=120,
          align="left", wordmark="tl", band=None, text_top=0.24, text_bottom=0.70),
    Theme("sentrert", bg="bg", fg="headline", fg2="brand", kicker="brand",
          mark_corner="br", mark_scale=0.30, mark_tint=None,
          accent="quarter", accent_corner="tl", accent_col="headline", dot_alpha=255,
          align="center", wordmark="bottom", band=None, text_top=0.32, text_bottom=0.74),
    Theme("blokk", bg="bg", fg="headline", fg2="brand", kicker="brand",
          mark_corner="br", mark_scale=0.26, mark_tint="bg",
          accent="dots", accent_corner="tr", accent_col="brand", dot_alpha=130,
          align="left", wordmark="bottom", band="brand", text_top=0.20, text_bottom=0.60),
]
THEME_MAP = {t.key: t for t in THEMES}


def pick_theme(spec: dict, seq: int = 0) -> Theme:
    """Tema fra spec['theme'] hvis satt, ellers rotér for variasjon. 'tall'-varianten
    unngår 'sentrert' (store tall vil venstrestilles)."""
    key = (spec.get("theme") or "").strip().lower()
    if key in THEME_MAP:
        return THEME_MAP[key]
    order = list(THEMES)
    theme = order[seq % len(order)]
    if (spec.get("variant") == "tall") and theme.key == "sentrert":
        theme = THEME_MAP["sand-venstre"]
    return theme


# ───────────────────────────────────────────────────────────
# Font + tekst
# ───────────────────────────────────────────────────────────

def _load_font(name: str, size: int, *, bold: bool = False) -> ImageFont.FreeTypeFont:
    path = brandkit.font_path(name)
    if path is None:
        return ImageFont.load_default()
    try:
        font = ImageFont.truetype(str(path), size)
    except OSError:
        return ImageFont.load_default()
    if bold:
        try:
            font.set_variation_by_axes([850])
        except (OSError, AttributeError, ValueError):
            try:
                font.set_variation_by_name("Black")
            except (OSError, AttributeError, ValueError):
                pass
    return font


def _wrap(draw, text, font, max_w) -> list[str]:
    lines: list[str] = []
    for para in text.split("\n"):
        words = para.split()
        if not words:
            lines.append("")
            continue
        cur = words[0]
        for w in words[1:]:
            trial = f"{cur} {w}"
            if draw.textlength(trial, font=font) <= max_w:
                cur = trial
            else:
                lines.append(cur)
                cur = w
        lines.append(cur)
    return lines


def _fit(draw, text, name, max_w, max_h, *, start=112, min_size=48):
    size = max(min_size, start)
    while size >= min_size:
        font = _load_font(name, size, bold=True)
        lines = _wrap(draw, text, font, max_w)
        line_h = int(size * 1.12)
        if len(lines) * line_h <= max_h and all(
                draw.textlength(ln, font=font) <= max_w for ln in lines):
            return font, lines, line_h
        size -= 6
    font = _load_font(name, min_size, bold=True)
    return font, _wrap(draw, text, font, max_w), int(min_size * 1.12)


def _put_lines(draw, lines, font, y, line_h, color, *, align, margin, w) -> int:
    for ln in lines:
        if align == "center":
            x = int((w - draw.textlength(ln, font=font)) / 2)
        else:
            x = margin
        draw.text((x, y), ln, font=font, fill=color)
        y += line_h
    return y


# ───────────────────────────────────────────────────────────
# Merkevare-primitiver (delt med karusell-slides)
# ───────────────────────────────────────────────────────────

def _recolor(logo: Image.Image, rgb: tuple[int, int, int]) -> Image.Image:
    """Ensfarget versjon av marken (alle synlige piksler -> rgb), alfa beholdt."""
    solid = Image.new("RGBA", logo.size, (*rgb, 0))
    solid.putalpha(logo.split()[3])
    return solid


def _draw_dot_grid(img, rgb, *, alpha=135, corner="tr", cols=6, rows=4) -> None:
    w, h = img.size
    r = max(2, int(w * 0.0055))
    gap = int(w * 0.030)
    span = (cols - 1) * gap
    x0 = w - int(w * 0.078) - span if "r" in corner else int(w * 0.078)
    y0 = int(h * 0.065) if "t" in corner else h - int(h * 0.065) - (rows - 1) * gap
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)
    for i in range(cols):
        for j in range(rows):
            cx, cy = x0 + i * gap, y0 + j * gap
            od.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(*rgb, alpha))
    img.alpha_composite(overlay)


def _draw_quarter(img, rgb, corner="tl") -> None:
    """Fylt kvartsirkel i et hjørne (som referanse-innleggene)."""
    w, h = img.size
    r = int(w * 0.17)
    spans = {
        "tl": ([-r, -r, r, r], 0, 90),
        "tr": ([w - r, -r, w + r, r], 90, 180),
        "bl": ([-r, h - r, r, h + r], 270, 360),
        "br": ([w - r, h - r, w + r, h + r], 180, 270),
    }
    box, a, b = spans.get(corner, spans["tl"])
    ImageDraw.Draw(img).pieslice(box, start=a, end=b, fill=rgb)


def _draw_band(img, rgb) -> int:
    """Fyll et bunn-bånd. Returnerer bånd-toppen (y)."""
    w, h = img.size
    top = h - int(h * 0.24)
    ImageDraw.Draw(img).rectangle([0, top, w, h], fill=rgb)
    return top


def _draw_big_mark(img, brand, *, scale=0.44, corner="br", tint=None) -> None:
    w, h = img.size
    lp = brand.logo_path
    if not (lp and lp.exists()):
        return
    try:
        logo = Image.open(lp).convert("RGBA")
    except (OSError, ValueError):
        return
    size = int(w * scale)
    logo = logo.resize((size, size), Image.LANCZOS)
    if tint is not None:
        logo = _recolor(logo, tint)
    off = {
        "br": (w - int(size * 0.68), h - int(size * 0.66)),
        "bl": (-int(size * 0.34), h - int(size * 0.66)),
        "tr": (w - int(size * 0.68), -int(size * 0.32)),
        "tl": (-int(size * 0.34), -int(size * 0.30)),
    }
    img.alpha_composite(logo, off.get(corner, off["br"]))


def _wordmark_width(brand, mark_h) -> int:
    font = _load_font(brand.body_font, int(mark_h * 0.84), bold=True)
    label = brand.wordmark or brand.name
    tw = ImageDraw.Draw(Image.new("RGB", (10, 10))).textlength(label, font=font)
    return mark_h + int(mark_h * 0.34) + int(tw)


def _draw_wordmark(img, brand, x, y, mark_h, *, text_rgb, tint=None) -> None:
    cx = x
    lp = brand.logo_path
    if lp and lp.exists():
        try:
            logo = Image.open(lp).convert("RGBA")
            logo.thumbnail((mark_h, mark_h), Image.LANCZOS)
            if tint is not None:
                logo = _recolor(logo, tint)
            img.alpha_composite(logo, (cx, y))
            cx += logo.width + int(mark_h * 0.34)
        except (OSError, ValueError):
            pass
    label = brand.wordmark or brand.name
    font = _load_font(brand.body_font, int(mark_h * 0.84), bold=True)
    d = ImageDraw.Draw(img)
    tb = d.textbbox((0, 0), label, font=font)
    ty = y + (mark_h - (tb[3] - tb[1])) // 2 - tb[1]
    d.text((cx, ty), label, font=font, fill=text_rgb)


def _apply_theme(img, brand, theme: Theme) -> None:
    """Tegn bakgrunn + mark + aksent + ordmerke etter tema (før teksten)."""
    pal = brand.palette
    w, h = img.size
    margin = int(w * 0.078)
    ImageDraw.Draw(img).rectangle([0, 0, w, h], fill=_pcol(pal, theme.bg))
    if theme.band:
        band_top = _draw_band(img, _pcol(pal, theme.band))
    if theme.accent == "dots":
        _draw_dot_grid(img, _pcol(pal, theme.accent_col), alpha=theme.dot_alpha,
                       corner=theme.accent_corner)
    elif theme.accent == "quarter":
        _draw_quarter(img, _pcol(pal, theme.accent_col), corner=theme.accent_corner)
    if theme.mark_corner:
        tint = _pcol(pal, theme.mark_tint) if theme.mark_tint else None
        _draw_big_mark(img, brand, scale=theme.mark_scale, corner=theme.mark_corner, tint=tint)
    # Ordmerke
    mark_h = int(w * 0.05)
    if theme.wordmark == "tl":
        wm_text = _pcol(pal, theme.fg)
        wm_tint = _pcol(pal, "bg") if theme.bg == "headline" else None
        _draw_wordmark(img, brand, margin, int(h * 0.058), mark_h, text_rgb=wm_text, tint=wm_tint)
    elif theme.wordmark == "bottom":
        in_band = theme.band is not None
        wm_text = _pcol(pal, "bg") if in_band else _pcol(pal, theme.fg)
        wm_tint = _pcol(pal, "bg") if in_band else None
        total = _wordmark_width(brand, mark_h)
        wx = (w - total) // 2
        wy = h - int(h * 0.145) if in_band else h - int(h * 0.11)
        _draw_wordmark(img, brand, wx, wy, mark_h, text_rgb=wm_text, tint=wm_tint)


def _to_png(img) -> bytes:
    buf = BytesIO()
    img.convert("RGB").save(buf, format="PNG")
    return buf.getvalue()


# ───────────────────────────────────────────────────────────
# Låst ramme oppå et rent Gemini-motiv (headline + ordmerke = Pillow, piksellik)
# ───────────────────────────────────────────────────────────

def _cover_resize(img: Image.Image, size: tuple[int, int]) -> Image.Image:
    """Skalér + midt-beskjær så bildet dekker size nøyaktig.

    Beskjærer FØR nedskalering når kilden er større enn målet: da kastes bare de
    pikslene som uansett skulle bort, i stedet for å bruke dem til å regne ut
    mellomsteg. Etterskjerpes lett, fordi enhver nedskalering myker opp kanter litt,
    og AI-motivet ligger side om side med knivskarp Pillow-tekst."""
    tw, th = size
    w, h = img.size
    scale = max(tw / w, th / h)
    if scale < 1:  # kilden er større enn målet: beskjær først, så skalér ned
        kw, kh = int(round(tw / scale)), int(round(th / scale))
        x, y = max(0, (w - kw) // 2), max(0, (h - kh) // 2)
        img = img.crop((x, y, min(w, x + kw), min(h, y + kh)))
        img = img.resize((tw, th), Image.LANCZOS)
        return img.filter(ImageFilter.UnsharpMask(radius=1.1, percent=55, threshold=3))
    nw, nh = max(tw, int(w * scale)), max(th, int(h * scale))
    img = img.resize((nw, nh), Image.LANCZOS)
    x, y = (nw - tw) // 2, (nh - th) // 2
    return img.crop((x, y, x + tw, y + th))


def _sand_fade(img: Image.Image, brand: Brand, *, top_frac=0.26, bot_frac=0.20) -> None:
    """Mykt sand-fade øverst + nederst så headline/ordmerke alltid ligger på ren sand
    (uten hard kant), uansett hva motivet la i de sonene."""
    w, h = img.size
    sand = _pcol(brand.palette, "bg")
    top_h = max(1, int(h * top_frac))
    col = Image.new("RGBA", (1, top_h))
    for y in range(top_h):
        col.putpixel((0, y), (*sand, int(255 * (1 - y / top_h))))
    img.alpha_composite(col.resize((w, top_h)), (0, 0))
    bot_h = max(1, int(h * bot_frac))
    colb = Image.new("RGBA", (1, bot_h))
    for y in range(bot_h):
        colb.putpixel((0, y), (*sand, int(255 * (y / bot_h))))
    img.alpha_composite(colb.resize((w, bot_h)), (0, h - bot_h))


# Trygge soner for motiv-kortet: headline eier toppen, ordmerket bunnen,
# innholdet skal ligge i midtsonen med ekte luft rundt.
_CONTENT_TOP = 0.27
_CONTENT_BOTTOM = 0.89
_CONTENT_SIDE = 0.05


def _content_mask(img: Image.Image, bg: tuple[int, int, int], tol: int = 26):
    """1-bit maske over piksler som IKKE er bakgrunns-sand (innholdet)."""
    from PIL import ImageChops
    rgb = img.convert("RGB")
    diff = ImageChops.difference(rgb, Image.new("RGB", rgb.size, bg))
    return diff.convert("L").point(lambda p: 255 if p > tol else 0)


def zone_occupancy(img: Image.Image, bg: tuple[int, int, int],
                   *, y0: float, y1: float, tol: int = 26) -> float:
    """Andel ikke-sand-piksler i horisontalbåndet [y0*h, y1*h] (0.0-1.0)."""
    w, h = img.size
    band = _content_mask(img, bg, tol).crop((0, int(h * y0), w, int(h * y1)))
    hist = band.histogram()
    total = band.size[0] * band.size[1]
    return (hist[255] / total) if total else 0.0


def _content_reflow(img: Image.Image, brand: Brand) -> Image.Image:
    """Garantien mot trange kort: finn innholdets faktiske boks; stikker det opp i
    headline-sonen (eller ut i marger/ordmerke-sonen), løftes det ut og limes inn
    på nytt, skalert og sentrert i innholds-sonen med ekte luft. Bakgrunnen tas
    fra bildets eget hjørne så sand-tonen blir sømløs. Uendret når motoren alt
    har fulgt sonene (ingen kvalitetstap i normaltilfellet)."""
    w, h = img.size
    corner = img.convert("RGB").getpixel((6, 6))  # motorens egen sand-tone
    mask = _content_mask(img, corner)
    bbox = mask.getbbox()
    if not bbox:
        return img
    tx0, ty0 = int(w * _CONTENT_SIDE), int(h * _CONTENT_TOP)
    tx1, ty1 = int(w * (1 - _CONTENT_SIDE)), int(h * _CONTENT_BOTTOM)
    slack = int(h * 0.02)
    x0, y0, x1, y1 = bbox
    if (x0 >= tx0 - slack and y0 >= ty0 - slack
            and x1 <= tx1 + slack and y1 <= ty1 + slack):
        return img  # innholdet ligger alt trygt: ikke rør det
    content = img.crop(bbox)
    scale = min((tx1 - tx0) / content.width, (ty1 - ty0) / content.height, 1.0)
    nw, nh = max(1, int(content.width * scale)), max(1, int(content.height * scale))
    content = content.resize((nw, nh), Image.LANCZOS)
    canvas = Image.new("RGBA", (w, h), (*corner, 255))
    canvas.paste(content, (tx0 + (tx1 - tx0 - nw) // 2, ty0 + (ty1 - ty0 - nh) // 2))
    return canvas


def _headline_top(img: Image.Image, brand: Brand, headline: str) -> None:
    if not headline:
        return
    w, h = img.size
    margin = int(w * 0.08)
    draw = ImageDraw.Draw(img)
    hf, lines, lh = _fit(draw, headline, brand.display_font, int(w * 0.84),
                         int(h * 0.185), start=int(w * 0.078), min_size=int(w * 0.044))
    _put_lines(draw, lines, hf, int(h * 0.075), lh, _pcol(brand.palette, "headline"),
               align="center", margin=margin, w=w)


def _wordmark_bottom(img: Image.Image, brand: Brand) -> None:
    w, h = img.size
    mark_h = int(w * 0.052)
    total = _wordmark_width(brand, mark_h)
    _draw_wordmark(img, brand, (w - total) // 2, h - int(h * 0.085), mark_h,
                   text_rgb=_pcol(brand.palette, "headline"))


def _draw_logo_corners(img: Image.Image, brand: Brand, *, alpha: float = 0.5,
                       corners=(("tl", 0.44), ("br", 0.46))) -> None:
    """Store interlock-logo-former i hjørnene som bakgrunn (bleke salvie, halvgjennomsiktig),
    delvis utenfor kanten. Den deterministiske «rammen»: man kjenner igjen logoen i bakgrunnen."""
    w, h = img.size
    lp = brand.logo_path
    if not (lp and lp.exists()):
        return
    try:
        base = Image.open(lp).convert("RGBA")
    except (OSError, ValueError):
        return
    shape = _pcol(brand.palette, "shape")
    for corner, scale in corners:
        s = int(w * scale)
        lg = _recolor(base.resize((s, s), Image.LANCZOS), shape)
        lg.putalpha(lg.split()[3].point(lambda p: int(p * alpha)))
        pos = {
            "tl": (-int(s * 0.42), -int(s * 0.42)),
            "tr": (w - int(s * 0.58), -int(s * 0.42)),
            "bl": (-int(s * 0.42), h - int(s * 0.58)),
            "br": (w - int(s * 0.58), h - int(s * 0.58)),
        }[corner]
        img.alpha_composite(lg, pos)


# ───────────────────────────────────────────────────────────
# Varianter (tekst) — respekterer temaets farger + justering
# ───────────────────────────────────────────────────────────

def _variant_utsagn(img, brand, spec, theme, *, margin, max_w) -> None:
    pal = brand.palette
    w, h = img.size
    draw = ImageDraw.Draw(img)
    y = int(h * theme.text_top)
    max_h = int((theme.text_bottom - theme.text_top) * h)
    kicker = (spec.get("kicker") or "").strip()
    if kicker:
        kf = _load_font(brand.body_font, int(w * 0.027), bold=True)
        _put_lines(draw, [kicker.upper()], kf, y, int(w * 0.052), _pcol(pal, theme.kicker),
                   align=theme.align, margin=margin, w=w)
        y += int(w * 0.052)
    headline = (spec.get("headline") or "").strip()
    hf, lines, lh = _fit(draw, headline, brand.display_font, max_w, int(max_h * 0.62),
                         start=int(w * 0.105), min_size=int(w * 0.05))
    y = _put_lines(draw, lines, hf, y, lh, _pcol(pal, theme.fg), align=theme.align, margin=margin, w=w)
    subhead = (spec.get("subhead") or "").strip()
    if subhead:
        y += int(lh * 0.30)
        sf, sl, slh = _fit(draw, subhead, brand.display_font, max_w, int(max_h * 0.33),
                           start=int(w * 0.052), min_size=26)
        _put_lines(draw, sl, sf, y, slh, _pcol(pal, theme.fg2), align=theme.align, margin=margin, w=w)


def _variant_tall(img, brand, spec, theme, *, margin, max_w) -> None:
    pal = brand.palette
    w, h = img.size
    draw = ImageDraw.Draw(img)
    y = int(h * (theme.text_top - 0.04))
    number = (spec.get("number") or spec.get("headline") or "").strip()
    nf, nlines, nlh = _fit(draw, number, brand.display_font, max_w, int(h * 0.28),
                           start=int(w * 0.26), min_size=int(w * 0.11))
    y = _put_lines(draw, nlines, nf, y, nlh, _pcol(pal, theme.fg), align=theme.align, margin=margin, w=w)
    y += int(h * 0.012)
    label = (spec.get("headline") or "").strip() if spec.get("number") else ""
    if label:
        lf, ll, llh = _fit(draw, label, brand.display_font, max_w, int(h * 0.15),
                           start=int(w * 0.072), min_size=int(w * 0.045))
        y = _put_lines(draw, ll, lf, y, llh, _pcol(pal, theme.fg), align=theme.align, margin=margin, w=w)
    subhead = (spec.get("subhead") or "").strip()
    if subhead:
        y += int(h * 0.015)
        sf, sl, slh = _fit(draw, subhead, brand.display_font, max_w, int(h * 0.15),
                           start=int(w * 0.05), min_size=26)
        _put_lines(draw, sl, sf, y, slh, _pcol(pal, theme.fg2), align=theme.align, margin=margin, w=w)


def _variant_sitat(img, brand, spec, theme, *, margin, max_w) -> None:
    pal = brand.palette
    w, h = img.size
    draw = ImageDraw.Draw(img)
    headline = (spec.get("headline") or "").strip()
    if headline and not headline.startswith("«"):
        headline = f"«{headline}»"
    y = int(h * (theme.text_top + 0.04))
    max_h = int((theme.text_bottom - theme.text_top) * h)
    hf, lines, lh = _fit(draw, headline, brand.display_font, max_w, int(max_h * 0.62),
                         start=int(w * 0.115), min_size=int(w * 0.055))
    y = _put_lines(draw, lines, hf, y, lh, _pcol(pal, theme.fg), align=theme.align, margin=margin, w=w)
    subhead = (spec.get("subhead") or "").strip()
    if subhead:
        y += int(lh * 0.32)
        sf, sl, slh = _fit(draw, subhead, brand.display_font, max_w, int(max_h * 0.33),
                           start=int(w * 0.052), min_size=26)
        _put_lines(draw, sl, sf, y, slh, _pcol(pal, theme.fg2), align=theme.align, margin=margin, w=w)


_VARIANTS = {"utsagn": _variant_utsagn, "tall": _variant_tall, "sitat": _variant_sitat}


def render_template(spec: dict, brand: Brand, size: tuple[int, int] | None = None,
                    *, seq: int = 0) -> bytes:
    """Deterministisk merkevare-kort: velg variant (tekst) + tema (visuell skin)."""
    size = size or resolve_size(spec)
    img = Image.new("RGBA", size, (255, 255, 255, 255))
    w, h = size
    margin = int(w * 0.078)
    theme = pick_theme(spec, seq)
    max_w = int(w * (0.86 if theme.align == "center" else 0.82))
    _apply_theme(img, brand, theme)
    spec = {**spec, "subhead": _cap_text(spec.get("subhead"), 68)}  # kort subtekst, ikke avsnitt
    variant = (spec.get("variant") or "utsagn").strip().lower()
    (_VARIANTS.get(variant) or _variant_utsagn)(img, brand, spec, theme, margin=margin, max_w=max_w)
    return _to_png(img)


def _normalize(s: str) -> str:
    return re.sub(r"[^a-zæøå0-9]", "", (s or "").lower())


_MOTIV_FRAMES = [  # roteres per innlegg (seq): to-tone-mark i ett bunn-hjørne + bleik salvie diagonalt
    {"mark": "br", "soft": "tl"},
    {"mark": "bl", "soft": "tr"},
]


def image_backend(spec: dict) -> str:
    """Velg bildemotor: spec['backend'] eller NOTATER_SOME_IMAGE_BACKEND (default gemini)."""
    b = (spec.get("backend") or os.environ.get("NOTATER_SOME_IMAGE_BACKEND") or "gemini").strip().lower()
    return "openai" if b in ("openai", "gpt", "gpt-image", "gpt-image-2") else "gemini"


MAX_CORRECTIONS = 5


def with_corrections(motif: str, corrections) -> str:
    """Legg Oscars rettelser («ser ut som en penis», «feil grønnfarge») bakerst i
    motiv-prompten. ALLE rettelsene følger med hver gang, ikke bare den nyeste:
    ellers kommer et problem han allerede har påpekt tilbake ved neste forsøk.
    Nyeste sist, og bare de siste få, så prompten ikke drukner i historikk."""
    retter = [str(c).strip() for c in (corrections or []) if str(c).strip()]
    if not motif or not retter:
        return motif
    linjer = "\n".join(f"- {r}" for r in retter[-MAX_CORRECTIONS:])
    return (f"{motif}\n\nRETT OPP. Tidligere forsøk bommet på dette, og det MÅ være "
            f"annerledes nå:\n{linjer}")


def engine_content(spec: dict, brand: Brand, size: tuple[int, int],
                   *, retries: int = 3) -> Image.Image | None:
    """Bildekall: motoren lager KUN innholdet, på merkets bakgrunn, uten tekst og med
    tomme marger. Returnerer None når motivet mangler eller motoren feiler helt.

    Delt av enkeltbildene og karusell-forsiden med vilje: det er denne kontrakten som
    gjør at AI-delen ser typografisk ut, og to kopier ville sklidd fra hverandre.

    Prøver PÅ NYTT ved forbigående feil. Den gamle løkka i render_motiv lovet tre
    forsøk, men brøt ved første unntak, så en 5xx fra motoren ga stille tekst-kort
    (verifisert 25. juli: en OpenAI-500 tømte forsiden uten et eneste spor)."""
    motif = with_corrections((spec.get("motif") or spec.get("image_prompt") or "").strip(),
                             spec.get("corrections"))
    if not motif:
        return None
    if image_backend(spec) == "openai":
        from . import openai_image as engine
    else:
        from . import gemini as engine
    siste = ""
    for forsok in range(max(1, retries)):
        try:
            raw = engine.generate_content(motif, brand=brand, size=size,
                                          concept=spec.get("concept"),
                                          use_tilda=bool(spec.get("tilda")))
            return Image.open(BytesIO(raw)).convert("RGBA")
        except Exception as e:  # noqa: BLE001
            siste = f"{type(e).__name__}: {e}"
            if forsok < retries - 1:
                time.sleep(2 ** forsok)
    # Aldri stille: uten denne linja ser et tomt kort ut som et designvalg.
    print(f"  ⚠️  bildemotoren ga opp etter {retries} forsøk: {siste[:160]}",
          file=sys.stderr)
    return None


def render_motiv(spec: dict, brand: Brand, size: tuple[int, int] | None = None,
                 *, retries: int = 3, seq: int = 0) -> tuple[bytes, str]:
    """Komposisjons-stien: bildemotoren (gpt-image-2 eller Gemini) lager KUN infografikk-
    innholdet på sand med tomme marger/hjørner; Pillow tegner den DETERMINISTISKE rammen
    oppå: store interlock-logo-former i hjørnene (bakgrunn), Fraunces-headline (topp) og
    «demo labs»-ordmerke (bunn). Slik blir rammen alltid riktig og gjenkjennelig, tekst +
    logo piksellik, og innholdet legges sømløst inn (sand på sand, ingen innlimt boks).
    Faller til tekst-kort hvis motoren feiler."""
    size = size or resolve_size(spec)
    motif = with_corrections((spec.get("motif") or spec.get("image_prompt") or "").strip(),
                             spec.get("corrections"))
    headline = (spec.get("headline") or "").strip()
    if not motif:
        return render_template(spec, brand, size, seq=seq), "template-fallback"
    backend = image_backend(spec)
    for _ in range(max(1, retries)):
        content = engine_content(spec, brand, size)
        if content is None:
            break
        img = _cover_resize(content, size)
        img = _content_reflow(img, brand)   # garantert luft: aldri innhold i tittel-sonen
        _sand_fade(img, brand, top_frac=0.20, bot_frac=0.14)   # rene soner for tittel/ordmerke
        # Ren, VARIERT ramme som typografi-kortene: ett bleikt salvie-hjørne + ÉN
        # gjenkjennelig to-tone interlock-mark (rotert per seq). INGEN prikk-matrise oppå
        # motivet: infografikken er alt innholdsrik, så rammen skal holde seg luftig.
        fr = _MOTIV_FRAMES[seq % len(_MOTIV_FRAMES)]
        _draw_logo_corners(img, brand, corners=((fr["soft"], 0.42),), alpha=0.5)
        _draw_big_mark(img, brand, scale=0.24, corner=fr["mark"])   # ÉN diskret to-tone-mark
        _headline_top(img, brand, headline)                    # tittel = Pillow (alltid riktig)
        _wordmark_bottom(img, brand)                           # ordmerke = Pillow
        return _to_png(img), backend
    return render_template(spec, brand, size, seq=seq), "template-fallback"


def render_post(spec: dict, *, brand: Brand | None = None,
                size: tuple[int, int] | None = None, seq: int = 0) -> dict:
    """Rendr ett enkeltbilde. Default = motiv-sti (kreativ) når det finnes et motiv,
    ellers typografi-kort (tekst-mal). seq roterer mal-temaet ved fallback."""
    b = brand or brandkit.load_brand(spec.get("brand", "demo"))
    size = size or resolve_size(spec)
    fmt = (spec.get("format") or ("motiv" if spec.get("motif") else "typografi-kort")).strip()
    if fmt in ("motiv", "redaksjonelt"):
        png, how = render_motiv(spec, b, size, seq=seq)
    else:
        png, how = render_template(spec, b, size, seq=seq), "template"
    return {"png": png, "how": how, "format": fmt, "theme": pick_theme(spec, seq).key}
