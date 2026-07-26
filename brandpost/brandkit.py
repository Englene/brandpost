"""brandkit: merkevare-profiler lastet fra disk (én mappe per selskap).

Hvert merke er en mappe under `brands/<key>/`:

  profile.toml                    maskin-tokens (palett-hex, fonter, media-stier, pilarer, enabled)
  merkevare/designstil.md         designstil-prosa (til bilde-hjernen)
  merkevare/skrivestil.md         stemme + regler
  merkevare/arketype.md           merke-arketype/personlighet
  merkevare/strategi.md           posisjonering + publikum + innholdspilarene (rik prosa)
  bedrift/om-oss.md               om selskapet
  bedrift/produkter.md            produkt + faktakuler (mates til hjernen som «produktfakta»)
  bedrift/innholdspreferanser.md  miks, kadens, hva vi unngår, HARD-sperrene
  media/logo.png tilda.png refs/  merke-spesifikke bilder

Prosa-seksjonene er KUN til hjernen (cli.py). Renderer/prompts bruker bare de
maskinlesbare feltene (palett, fonter, logo/media). Fonter deles via assets/fonts/
(ikke merke-spesifikke). Å legge til et selskap = dropp en ny mappe her, ingen
kode-endring. Se brands/README.md.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

ASSETS = Path(__file__).resolve().parent / "assets"
FONTS_DIR = ASSETS / "fonts"
BRANDS_DIR = Path(__file__).resolve().parent / "brands"


# ───────────────────────────────────────────────────────────
# Tokens. Kortene = sand bakgrunn + mørkegrønn Fraunces-headline, salvie-grønne
# organiske former, grønn interlock-logo. bg_alt/shape_soft/accent er lite brukt
# (accent = oransje kun på nett), så de har defaults; profiler oppgir de 6 brukte.
# ───────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Palette:
    bg: str            # kort-bakgrunn (sand)
    ink: str           # brødtekst-mørk
    headline: str      # display-headline (mørkegrønn, høy kontrast)
    brand: str         # primær/aksent-grønn (logo/kicker/subhead) = nettsidas --amber-500 #24a03d
    shape: str         # salvie-grønn organisk form
    dark: str          # mørkt panel-bakgrunn (mørk-tema) = nettsidas #2B2B2B
    bg_alt: str = "#f7f3ea"       # sekundær flate (lite brukt)
    shape_soft: str = "#e4eee8"   # lysere form/linje (lite brukt)
    accent: str = "#f95f10"       # oransje, sparsom, kun på nett


@dataclass(frozen=True)
class Pillar:
    id: str            # stabil id for rotasjons-sporing (settes på hvert utkast)
    label: str         # kort menneskelig navn
    desc: str = ""     # én linje til hjernen


@dataclass(frozen=True)
class Brand:
    key: str
    name: str          # hvordan merket skrives (Demo Labs)
    handle: str        # kort variant til filnavn
    palette: Palette
    display_font: str  # filnavn i assets/fonts
    body_font: str
    logo_path: Path | None = None
    tilda_path: Path | None = None
    refs: tuple[Path, ...] = ()      # stil-eksempler sendt til bilde-API-et
    wordmark: str = ""               # ordmerke-tekst på kortet ("" -> bruk name)
    # Språket innleggene skrives på. Var hardkodet norsk i opphavet, helt ned i
    # bildepromptene, så et engelsk merke fikk norske etiketter i illustrasjonen.
    language: str = "no"
    enabled: bool = True             # med i enabled_brands()/nattkjøringen
    profile_dir: Path | None = None
    linkedin_org_urn: str = ""       # merkets firmaside ([linkedin].org_urn); "" -> global env
    linkedin_handle: str = ""        # @handle som TAGGER firmasida ([linkedin].handle)
    # prosa-seksjoner (markdown, KUN til hjernen):
    voice: str = ""
    designstil: str = ""
    arketype: str = ""
    strategi: str = ""
    om_oss: str = ""
    produkter: str = ""
    innholdspreferanser: str = ""
    pillars: tuple[Pillar, ...] = ()


# ───────────────────────────────────────────────────────────
# Profil-lasting
# ───────────────────────────────────────────────────────────

def _read_md(base: Path, name: str) -> str:
    p = base / name
    if p.exists():
        try:
            return p.read_text(encoding="utf-8").strip()
        except OSError:
            pass
    return ""


def _load_profile(key: str) -> Brand:
    d = BRANDS_DIR / key
    prof = d / "profile.toml"
    if not prof.exists():
        avail = ", ".join(available_brands()) or "(ingen)"
        raise ValueError(f"ukjent merke '{key}' (mangler {prof}; har: {avail})")
    data = tomllib.loads(prof.read_text(encoding="utf-8"))

    pal = Palette(**(data.get("palette") or {}))
    fonts = data.get("fonts") or {}
    media = data.get("media") or {}

    def _mp(rel: str | None) -> Path | None:
        if not rel:
            return None
        p = d / rel
        return p if p.exists() else None

    refs = tuple(p for r in (media.get("refs") or []) if (p := d / r).exists())
    pillars = tuple(
        Pillar(id=str(p["id"]), label=str(p.get("label", p["id"])), desc=str(p.get("desc", "")))
        for p in (data.get("pillar") or []) if p.get("id")
    )
    m, b = d / "merkevare", d / "bedrift"
    return Brand(
        key=str(data.get("key", key)),
        name=str(data["name"]),
        handle=str(data.get("handle", key)),
        palette=pal,
        display_font=str(fonts.get("display", "Fraunces.ttf")),
        body_font=str(fonts.get("body", "Inter.ttf")),
        logo_path=_mp(media.get("logo")),
        tilda_path=_mp(media.get("tilda")),
        refs=refs,
        wordmark=str(data.get("wordmark", "")),
        enabled=bool(data.get("enabled", True)),
        profile_dir=d,
        linkedin_org_urn=str((data.get("linkedin") or {}).get("org_urn", "")).strip(),
        linkedin_handle=str((data.get("linkedin") or {}).get("handle", "")).strip().lstrip("@"),
        language=str(data.get("language", "no")).strip() or "no",
        voice=_read_md(m, "skrivestil.md"),
        designstil=_read_md(m, "designstil.md"),
        arketype=_read_md(m, "arketype.md"),
        strategi=_read_md(m, "strategi.md"),
        om_oss=_read_md(b, "om-oss.md"),
        produkter=_read_md(b, "produkter.md"),
        innholdspreferanser=_read_md(b, "innholdspreferanser.md"),
        pillars=pillars,
    )


def load_brand(key: str) -> Brand:
    return _load_profile((key or "demo").strip().lower())


def available_brands() -> list[str]:
    """Alle merker med en profil på disk (uansett enabled)."""
    if not BRANDS_DIR.exists():
        return []
    return sorted(p.name for p in BRANDS_DIR.iterdir() if (p / "profile.toml").exists())


def enabled_brands() -> list[str]:
    """Merker generatoren skal kjøre for. BRANDPOST_BRANDS overstyrer (komma-
    separert); ellers alle profiler med enabled=true. Faller til ['demo']."""
    raw = os.environ.get("BRANDPOST_BRANDS")
    if raw:
        keys = [k.strip().lower() for k in raw.split(",") if k.strip()]
        return [k for k in keys if (BRANDS_DIR / k / "profile.toml").exists()] or ["demo"]
    out: list[str] = []
    for key in available_brands():
        try:
            if _load_profile(key).enabled:
                out.append(key)
        except (ValueError, KeyError, OSError):
            pass
    return out or ["demo"]


def pillar_ids(brand: Brand) -> list[str]:
    return [p.id for p in brand.pillars]


# ───────────────────────────────────────────────────────────
# Stemme + fonter (best-effort, med innbakt fallback)
# ───────────────────────────────────────────────────────────

_VOICE_FALLBACK = """\
Merkevarestemme (sammendrag): erfaren rådgiver som forklarer komplekst enkelt.
Datadrevet, direkte, praktisk, tilgjengelig, selvsikker. Konkrete tall som bevis.
Korte setninger, aktiv form, «du». Ingen emoji og ingen hashtags i selve kortet.
"""


def voice_guide(brand: Brand, max_chars: int = 6000) -> str:
    """Stemme-guiden (skrivestil.md via brand.voice), med innbakt fallback."""
    return (brand.voice or _VOICE_FALLBACK)[:max_chars]


def font_path(name: str) -> Path | None:
    """Løs en font: assets/fonts/ først, så vanlige system-plasseringer. None om ingen."""
    cand = FONTS_DIR / name
    if cand.exists():
        return cand
    stem = Path(name).stem.split("[")[0]
    search = [
        FONTS_DIR,
        Path.home() / "Library" / "Fonts",
        Path("/Library/Fonts"),
        Path("/System/Library/Fonts"),
        Path("/usr/share/fonts"),
    ]
    for d in search:
        if not d.exists():
            continue
        for ext in (".ttf", ".otf"):
            hit = d / f"{stem}{ext}"
            if hit.exists():
                return hit
        matches = sorted(d.glob(f"{stem}*.ttf")) + sorted(d.glob(f"{stem}*.otf"))
        if matches:
            return matches[0]
    return None
