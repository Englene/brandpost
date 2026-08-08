"""brandkit: merkevare-profiler lastet fra disk (én mappe per selskap).

Hvert merke er en mappe under `brands/<key>/`:

  profile.toml                    maskin-tokens (palett-hex, fonter, media-stier, pilarer, enabled)
  voice/design.md          visuell stil (til bilde-hjernen)
  voice/writing.md         stemme + regler
  voice/archetype.md       merke-arketype/personlighet
  voice/strategy.md        posisjonering + publikum + innholdspilarene
  company/about.md         om selskapet
  company/products.md      produkt + faktakuler (mates til hjernen som «produktfakta»)
  company/rules.md         miks, kadens, hva vi unngår, HARD-sperrene
  (norske navn merkevare/ og bedrift/ godtas fortsatt)
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
BUNDLED_BRANDS_DIR = Path(__file__).resolve().parent / "brands"


def brand_dirs() -> list[Path]:
    """Hvor merker letes etter, i prioritert rekkefølge.

    BRANDPOST_BRANDS_DIR (kolon-separert, som PATH) legges FØRST, så dine egne
    merker vinner over de innebygde ved navnekollisjon. Det er dette som lar
    merkevaren din, altså strategien, stemmen og logoene, bo i et privat repo
    mens motoren installeres fra dette: du skal ikke måtte legge forretnings-
    materialet ditt i en pakke du oppdaterer.

    Uten variabelen oppfører alt seg som før, med demo/ og minimal/ innebygd.
    """
    ut: list[Path] = []
    raw = os.environ.get("BRANDPOST_BRANDS_DIR", "")
    for del_ in raw.split(os.pathsep):
        d = del_.strip()
        if d:
            ut.append(Path(d).expanduser())
    ut.append(BUNDLED_BRANDS_DIR)
    return ut


def brand_dir(key: str) -> Path | None:
    """Første katalog som faktisk har profilen, eller None."""
    for base in brand_dirs():
        if (base / key / "profile.toml").exists():
            return base / key
    return None


# Bakoverkompatibelt navn: pekte på den innebygde katalogen før eksterne merker
# ble mulige. Bruk brand_dirs()/brand_dir() i ny kode.
BRANDS_DIR = BUNDLED_BRANDS_DIR


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
    # "brand" (et selskap som taler) eller "person" (et menneske som taler).
    # Styrer rolle, taggeregel og konfidensialitetssperre i hjernens systemprompt,
    # se cli._modus_blokker(). Alt annet i profilen virker likt for begge.
    #
    # Uten dette skrev hjernen «vi i <navn>» også for en personlig profil, og la
    # på produktfakta og salgssperrer som ikke gir mening for et menneske. Det er
    # forskjellen mellom et innlegg som leses og en annonse folk scroller forbi.
    voice_mode: str = "brand"
    enabled: bool = True             # med i enabled_brands()/nattkjøringen
    profile_dir: Path | None = None
    linkedin_org_urn: str = ""       # merkets firmaside ([linkedin].org_urn); "" -> global env
    linkedin_handle: str = ""        # @handle som TAGGER firmasida ([linkedin].handle)
    # Kanal for publisert-varselet ([slack].channel); "" -> BRANDPOST_SLACK_CHANNEL.
    # Tom i dag med vilje: firmamerkene deler én kanal. Feltet finnes for at det
    # skal være en konfigurasjonslinje, ikke en kodeendring, den dagen de skal
    # varsle i hver sin kanal.
    slack_channel: str = ""
    # Skal dette merket varsle i Slack i det hele tatt? ([slack].varsle)
    #
    # Standard ja, fordi et firmamerke som publiserer bør være synlig for teamet.
    # Personlige profiler setter den til false: kanalen er et arbeidsverktøy, og
    # hva Oscar legger ut på sin egen profil er ikke teamets sak.
    slack_varsle: bool = True
    # Navnet på miljøvariabelen med tokenet for DETTE merkets workspace
    # ([slack].token_env). Tom betyr BRANDPOST_SLACK_TOKEN. Aldri selve tokenet:
    # profile.toml ligger i git.
    slack_token_env: str = ""
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

def _md(base: Path, *navn: str) -> str:
    """Første fil som finnes, av flere navn. Lar engelske navn være standarden uten
    å brekke profiler som allerede bruker de norske."""
    for n in navn:
        tekst = _read_md(base, n)
        if tekst:
            return tekst
    return ""


def _read_md(base: Path, name: str) -> str:
    p = base / name
    if p.exists():
        try:
            return p.read_text(encoding="utf-8").strip()
        except OSError:
            pass
    return ""


def _load_profile(key: str) -> Brand:
    d = brand_dir(key)
    if d is None:
        avail = ", ".join(available_brands()) or "(ingen)"
        sett = ", ".join(str(p) for p in brand_dirs())
        raise ValueError(
            f"ukjent merke '{key}' (har: {avail}). Lette i: {sett}. "
            f"Ligger merket ditt et annet sted, sett BRANDPOST_BRANDS_DIR.")
    prof = d / "profile.toml"
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
    # Engelske navn er standard; de norske godtas fortsatt, så en profil laget før
    # navnebyttet ikke slutter å virke.
    m = d / "voice" if (d / "voice").is_dir() else d / "merkevare"
    b = d / "company" if (d / "company").is_dir() else d / "bedrift"
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
        slack_channel=str((data.get("slack") or {}).get("channel", "")).strip(),
        slack_varsle=bool((data.get("slack") or {}).get("varsle", True)),
        slack_token_env=str((data.get("slack") or {}).get("token_env", "")).strip(),
        language=str(data.get("language", "no")).strip() or "no",
        # Ukjent verdi faller til "brand": en skrivefeil i profilen skal gi den
        # forsiktige oppførselen, ikke slå av salgssperrene i det stille.
        voice_mode=("person"
                    if str((data.get("voice") or {}).get("mode", "")).strip().lower() == "person"
                    else "brand"),
        voice=_md(m, "writing.md", "skrivestil.md"),
        designstil=_md(m, "design.md", "designstil.md"),
        arketype=_md(m, "archetype.md", "arketype.md"),
        strategi=_md(m, "strategy.md", "strategi.md"),
        om_oss=_md(b, "about.md", "om-oss.md"),
        produkter=_md(b, "products.md", "produkter.md"),
        innholdspreferanser=_md(b, "rules.md", "innholdspreferanser.md"),
        pillars=pillars,
    )


def load_brand(key: str) -> Brand:
    return _load_profile((key or "demo").strip().lower())


def available_brands() -> list[str]:
    """Alle merker med en profil på disk (uansett enabled), på tvers av katalogene."""
    funnet: set[str] = set()
    for base in brand_dirs():
        if not base.exists():
            continue
        funnet |= {p.name for p in base.iterdir() if (p / "profile.toml").exists()}
    return sorted(funnet)


def enabled_brands() -> list[str]:
    """Merker generatoren skal kjøre for. BRANDPOST_BRANDS overstyrer (komma-
    separert); ellers alle profiler med enabled=true. Faller til ['demo']."""
    raw = os.environ.get("BRANDPOST_BRANDS")
    if raw:
        keys = [k.strip().lower() for k in raw.split(",") if k.strip()]
        # brand_dir(), ikke BRANDS_DIR: et merke fra BRANDPOST_BRANDS_DIR skal
        # kunne stå i BRANDPOST_BRANDS. Ellers ble egne merker stille filtrert
        # bort og kjøringen falt til demo.
        return [k for k in keys if brand_dir(k) is not None] or ["demo"]
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
