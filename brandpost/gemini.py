"""gemini — tynn klient mot Google Gemini bilde-API (Nano Banana Pro).

Bruker den nye samlede SDK-en `google-genai` (import: `from google import genai`).
Modell-id-er drifter, så de er env-styrte:

  NOTATER_SOME_IMAGE_MODEL   default 'gemini-3-pro-image-preview'  (Nano Banana Pro)
  NOTATER_SOME_VISION_MODEL  default 'gemini-2.5-flash'           (tekst-tilbakelesing)
  GEMINI_API_KEY             nøkkel fra https://aistudio.google.com/apikey

generate_image() sender bilde-prompten + merkevare-referansebilder (logo + 1-2 av
egne tidligere innlegg, hvis du legger dem i brands/<merke>/media/refs/) og henter ut
PNG-bytene fra svaret. read_text_back() ber en billig visjonsmodell lese teksten i
et generert bilde, brukt av render.py til å fange feilstavet norsk.
"""

from __future__ import annotations

import os
from io import BytesIO
from pathlib import Path

from .brandkit import Brand


class GeminiError(RuntimeError):
    """Nøkkel mangler, SDK ikke installert, eller API-kall feilet."""


def _client():
    key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not key:
        raise GeminiError("GEMINI_API_KEY mangler i .env")
    try:
        from google import genai  # type: ignore
    except ImportError as e:
        raise GeminiError("google-genai ikke installert (.venv/bin/pip install google-genai)") from e
    return genai.Client(api_key=key)


def image_model() -> str:
    return os.environ.get("NOTATER_SOME_IMAGE_MODEL", "gemini-3-pro-image-preview")


# Motoren returnerte 928x1152 uten dette, mens lerretet er 1080x1350: alt AI-innhold
# ble OPPSKALERT 16 %, og det er dét som gjorde motivene (og teksten i dem) uskarpe
# ved siden av den knivskarpe Pillow-typografien (målt 25. juli 2026).
# 2K gir 1856x2304, altså nedskalering, som er skarpt.
def image_size_hint() -> str:
    return (os.environ.get("NOTATER_SOME_IMAGE_RES") or "2K").strip() or "2K"


def _aspect_ratio(size) -> str:
    """Nærmeste sideforhold Gemini støtter. Uten dette bestemmer motoren selv, og et
    avvikende forhold blir midt-beskåret bort i _cover_resize."""
    w, h = size
    if h > w:
        return "4:5" if abs(w / h - 0.8) < 0.06 else "2:3"
    if w > h:
        return "3:2"
    return "1:1"


def _bilde_config(size):
    """GenerateContentConfig med sideforhold + oppløsning, eller None hvis SDK-en
    er for gammel til å kjenne feltene (da faller vi til motorens standard)."""
    try:
        from google.genai import types  # type: ignore
        return types.GenerateContentConfig(
            image_config=types.ImageConfig(aspect_ratio=_aspect_ratio(size),
                                           image_size=image_size_hint()))
    except Exception:  # noqa: BLE001
        return None


def vision_model() -> str:
    return os.environ.get("NOTATER_SOME_VISION_MODEL", "gemini-2.5-flash")


def _labeled_refs(brand: Brand, *, use_tilda: bool = False) -> list:
    """Merkevare-referanser med tekst-etikett foran hvert bilde, så Gemini vet hva
    hver ref ER: logoen (må gjengis riktig), Tilda (maskoten), og eksempel-innlegg
    som viser ønsket stil. Returnerer en flat contents-liste (label, img, label, …)."""
    from PIL import Image
    out: list = []

    def add(label: str, path):
        try:
            out.append(label)
            out.append(Image.open(path).convert("RGBA"))
        except (OSError, ValueError):
            if out and out[-1] == label:
                out.pop()

    if brand.logo_path and brand.logo_path.exists():
        add("Interlock-logoen (må gjengis nøyaktig slik, ikke forvreng den):", brand.logo_path)
    if use_tilda and brand.tilda_path and brand.tilda_path.exists():
        add("Maskoten Tilda (krem frø-figur med grønn spire, vennlig):", brand.tilda_path)
    for path in brand.refs:
        if path.exists():
            add("Eksempel på ØNSKET stil (rik, informativ infografikk med interlock-marken "
                "gjennomgående, flat grafisk, luftig), etterlign dette nivået:", path)
    return out


def _reference_images(brand: Brand) -> list:  # bakoverkompat: bare bildene
    return [x for x in _labeled_refs(brand) if not isinstance(x, str)]


def _extract_png(response) -> bytes:
    """Plukk første bilde-part ut av et genai-svar og returner PNG-bytes."""
    from PIL import Image
    candidates = getattr(response, "candidates", None) or []
    for cand in candidates:
        content = getattr(cand, "content", None)
        parts = getattr(content, "parts", None) or []
        for part in parts:
            inline = getattr(part, "inline_data", None)
            data = getattr(inline, "data", None) if inline else None
            if data:
                img = Image.open(BytesIO(data)).convert("RGB")
                buf = BytesIO()
                img.save(buf, format="PNG")
                return buf.getvalue()
    raise GeminiError("ingen bilde-part i Gemini-svaret")


def generate_image(motif: str, *, headline: str = "", brand: Brand,
                   size=(1080, 1350), concept: str | None = None,
                   use_tilda: bool = False) -> bytes:
    """Design ETT sammenhengende merkevare-kort (som en grafisk designer, ikke et
    foto limt på en bakgrunn): brandets former + farger + logo integrert, valgfri
    Tilda, og et meningsbærende motiv. Reiser GeminiError ved feil.

    motif: den kreative, MENINGSBÆRENDE visuelle idéen på norsk. DETTE er variasjonen.
    headline: kort headline-tekst (korrekt norsk).
    concept: valgfri stil-arketype. use_tilda: ta med maskoten Tilda i scenen.
    size: kvadrat 1:1 eller stående 4:5."""
    from . import prompts
    client = _client()
    full = prompts.brand_card_prompt(motif, headline=headline, brand=brand, size=size,
                                     concept=concept, use_tilda=use_tilda)
    contents = [full, *_labeled_refs(brand, use_tilda=use_tilda)]
    try:
        resp = client.models.generate_content(model=image_model(), contents=contents,
                                              config=_bilde_config(size))
    except Exception as e:  # SDK reiser ulike typer; normaliser
        raise GeminiError(f"Gemini generate feilet: {e}") from e
    return _extract_png(resp)


def generate_motif_only(motif: str, *, brand: Brand, size=(1080, 1350),
                        concept: str | None = None) -> bytes:
    """Generer KUN det sentrale motivet som illustrasjon: ingen tekst, ingen logo,
    ingen ramme, på ren sand med tomme soner øverst/nederst. Pillow legger deretter
    headline + ordmerke oppå deterministisk (låst ramme, alltid korrekt norsk).
    Sender IKKE merkevare-referansebilder (de inneholder tekst/logo som ville smitte)."""
    from . import prompts
    client = _client()
    pal = brand.palette
    portrait = size[1] > size[0]
    fmt = "stående 4:5 (portrett)" if portrait else "kvadratisk 1:1"
    concept_hint = prompts.CONCEPTS.get((concept or "").strip().lower(), "")
    ch = f"Stil-retning: {concept_hint}. " if concept_hint else ""
    full = (
        f"Lag KUN én enkelt, sentrert, rolig redaksjonell vektor-illustrasjon, {fmt}, "
        f"som illustrerer dette konseptet: {motif}. {ch}"
        f"Ren, varm sand bakgrunn ({pal.bg}). Bruk merkefargene: mørkegrønn "
        f"({pal.headline}), salvie ({pal.shape}) og sand. Skandinavisk minimalisme, "
        f"mye luft, elegant.\n\n"
        f"STRENGT: INGEN tekst, INGEN bokstaver, INGEN tall, INGEN logo, INGEN ordmerke, "
        f"INGEN ramme eller kant. La det ØVERSTE ~25 % og det NEDERSTE ~18 % av bildet "
        f"være HELT TOMT (bare sand) — motivet skal ligge samlet i midten. Ingen "
        f"watermark, ingen emoji, ingen pastellbobler."
    )
    try:
        resp = client.models.generate_content(model=image_model(), contents=[full],
                                              config=_bilde_config(size))
    except Exception as e:
        raise GeminiError(f"Gemini motiv feilet: {e}") from e
    return _extract_png(resp)


def generate_content(motif: str, *, brand: Brand, size=(1080, 1350),
                     concept: str | None = None, use_tilda: bool = False) -> bytes:
    """KUN infografikk-innholdet på sand (rammen tegnes av Pillow etterpå). Sender bare
    logoen (+ evt. Tilda) som ref, ikke frame-eksemplene."""
    from PIL import Image
    from . import prompts
    client = _client()
    full = prompts.content_prompt(motif, brand=brand, size=size, concept=concept,
                                  use_tilda=use_tilda)
    refs = []
    if brand.logo_path and brand.logo_path.exists():
        try:
            refs.append(Image.open(brand.logo_path).convert("RGBA"))
        except (OSError, ValueError):
            pass
    if use_tilda and brand.tilda_path and brand.tilda_path.exists():
        try:
            refs.append(Image.open(brand.tilda_path).convert("RGBA"))
        except (OSError, ValueError):
            pass
    try:
        resp = client.models.generate_content(model=image_model(), contents=[full, *refs],
                                              config=_bilde_config(size))
    except Exception as e:
        raise GeminiError(f"Gemini content feilet: {e}") from e
    return _extract_png(resp)


def read_text_back(png: bytes) -> str:
    """Be en billig visjonsmodell lese all tekst i bildet (til æøå-verifisering)."""
    client = _client()
    try:
        from google.genai import types  # type: ignore
        part = types.Part.from_bytes(data=png, mime_type="image/png")
        resp = client.models.generate_content(
            model=vision_model(),
            contents=["Gjengi ordrett all tekst som står i dette bildet. Kun teksten.", part],
        )
    except Exception as e:
        raise GeminiError(f"Gemini vision feilet: {e}") from e
    return (getattr(resp, "text", "") or "").strip()


def available() -> bool:
    """True hvis nøkkel + SDK finnes (uten å gjøre et betalt kall)."""
    try:
        _client()
        return True
    except GeminiError:
        return False
