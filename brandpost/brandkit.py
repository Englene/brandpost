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
  media/library.toml              godkjente, ekte publiseringsbilder

Prosa-seksjonene er KUN til hjernen (cli.py). Renderer/prompts bruker bare de
maskinlesbare feltene (palett, fonter, logo/media). Fonter deles via assets/fonts/
(ikke merke-spesifikke). Å legge til et selskap = dropp en ny mappe her, ingen
kode-endring. Se brands/README.md.
"""

from __future__ import annotations

import os
import re
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
class MediaAsset:
    """Én eksplisitt godkjent ressurs i merkets egen bildekatalog."""

    id: str
    file_path: Path
    description: str
    pillars: tuple[str, ...]
    alt_text: str
    approved: bool = False

    @property
    def file(self) -> Path:
        """Bakovervennlig kortnavn internt; offentlig kontrakt er file_path."""
        return self.file_path


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
    media_assets: tuple[MediaAsset, ...] = ()  # aldri delt på tvers av merker
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
    linkedin_org_urn: str = ""       # merkets firmaside; tom verdi stopper firmapublisering
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


def _inside(base: Path, candidate: Path, *, what: str) -> Path:
    """Resolve en profilsti og nekt absolutt sti/symlink/``..`` ut av merket."""
    root = base.resolve()
    resolved = candidate.resolve()
    if resolved != root and root not in resolved.parents:
        raise ValueError(f"{what} peker utenfor merkets mappe: {candidate}")
    return resolved


def _brand_file(base: Path, raw: str, *, what: str,
                suffixes: tuple[str, ...] = ()) -> Path:
    rel = Path((raw or "").strip())
    if not raw or rel.is_absolute():
        raise ValueError(f"{what} må være en relativ sti i merkets mappe")
    out = _inside(base, base / rel, what=what)
    if suffixes and out.suffix.lower() not in suffixes:
        raise ValueError(f"{what} har ikke støttet filtype: {out.suffix}")
    if not out.is_file():
        raise ValueError(f"{what} finnes ikke: {out}")
    return out


def _load_media_assets(base: Path, media: dict) -> tuple[MediaAsset, ...]:
    raw_library = str(media.get("library") or "").strip()
    default = base / "media" / "library.toml"
    if not raw_library and not default.is_file():
        return ()
    library = (_brand_file(base, raw_library, what="media.library",
                           suffixes=(".toml",)) if raw_library
               else _inside(base, default, what="media.library"))
    data = tomllib.loads(library.read_text(encoding="utf-8"))
    rows = data.get("asset") or []
    if not isinstance(rows, list):
        raise ValueError(f"{library}: forventet [[asset]]")

    seen: set[str] = set()
    out: list[MediaAsset] = []
    for i, row in enumerate(rows, 1):
        if not isinstance(row, dict):
            raise ValueError(f"{library}: asset {i} må være en tabell")
        asset_id = str(row.get("id") or "").strip()
        if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,63}", asset_id):
            raise ValueError(f"{library}: ugyldig asset-id {asset_id!r}")
        if asset_id in seen:
            raise ValueError(f"{library}: duplikat asset-id {asset_id!r}")
        seen.add(asset_id)
        raw_file = str(row.get("file") or "").strip()
        rel = Path(raw_file)
        if not raw_file or rel.is_absolute():
            raise ValueError(f"{library}: asset {asset_id!r} trenger relativ fil")
        file = _inside(base, library.parent / rel, what=f"asset {asset_id!r}")
        if file.suffix.lower() not in (".png", ".jpg", ".jpeg", ".webp"):
            raise ValueError(f"{library}: ustøttet bildeformat for {asset_id!r}")
        if not file.is_file():
            raise ValueError(f"{library}: bildefila finnes ikke for {asset_id!r}: {file}")
        pillars = row.get("pillars") or []
        if not isinstance(pillars, list) or not all(isinstance(p, str) for p in pillars):
            raise ValueError(f"{library}: pillars for {asset_id!r} må være en liste")
        out.append(MediaAsset(
            id=asset_id,
            file_path=file,
            description=str(row.get("description") or "").strip(),
            pillars=tuple(p.strip() for p in pillars if p.strip()),
            alt_text=str(row.get("alt_text") or "").strip(),
            # Manglende godkjenning er et nei. Bare true kan velges/rendres.
            approved=row.get("approved") is True,
        ))
    return tuple(out)


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
        try:
            p = _inside(d, d / rel, what="mediafil")
        except ValueError:
            raise
        return p if p.exists() else None

    def _font(raw: object, default: str) -> str:
        name = str(raw or default).strip()
        # Bare merke-lokale stier trenger oppløsning her. Rene filnavn går via
        # den delte, OFL-lisensierte fontkatalogen/systemfontene som tidligere.
        if len(Path(name).parts) == 1:
            return name
        return str(_brand_file(d, name, what="font",
                               suffixes=(".ttf", ".otf")))

    refs = tuple(p for r in (media.get("refs") or [])
                 if (p := _mp(str(r))) is not None)
    media_assets = _load_media_assets(d, media)
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
        display_font=_font(fonts.get("display"), "Fraunces.ttf"),
        body_font=_font(fonts.get("body"), "Inter.ttf"),
        logo_path=_mp(media.get("logo")),
        tilda_path=_mp(media.get("tilda")),
        refs=refs,
        media_assets=media_assets,
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


def media_asset(brand: Brand, asset_id: str) -> MediaAsset:
    """Finn en godkjent id KUN i dette merket; ukjent/avslått er en hard feil."""
    wanted = (asset_id or "").strip()
    for asset in brand.media_assets:
        if asset.id == wanted and asset.approved:
            return asset
    raise ValueError(f"media-id {wanted!r} er ikke godkjent for merket {brand.key!r}")


def approved_media_assets(brand: Brand) -> tuple[MediaAsset, ...]:
    return tuple(a for a in brand.media_assets if a.approved)


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
    raw = Path(name)
    if raw.is_absolute():
        try:
            resolved = raw.resolve()
            allowed = any(
                resolved != base.resolve() and base.resolve() in resolved.parents
                for base in brand_dirs() if base.exists()
            )
        except OSError:
            return None
        return resolved if allowed and resolved.is_file() and resolved.suffix.lower() in (".ttf", ".otf") else None
    # En relativ sti skal ha blitt løst og sikkerhetsvalidert av _load_profile.
    # Å slå opp ``../`` her ville åpnet en ny traversal-vei for direkte kall.
    if len(raw.parts) != 1:
        return None
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
