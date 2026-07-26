"""openai_image — gpt-image-2-backend (alternativ til Gemini) for SoMe-kortene.

Bruker samme brand-brief (prompts.brand_card_prompt) og de samme merkevare-
referansebildene (logo, Tilda, eksempler) via images.edit, så en sammenligning
mot Gemini blir rettferdig. Faller til ren images.generate hvis edit ikke tar refs.

Nøkkel: OPENAI_API_KEY i .env. Modell: BRANDPOST_OPENAI_MODEL (default gpt-image-2).
"""

from __future__ import annotations

import base64
import os

from . import prompts
from .brandkit import Brand


class OpenAIImageError(RuntimeError):
    """Nøkkel mangler, pakke ikke installert, eller API-kall feilet."""


def model() -> str:
    return os.environ.get("BRANDPOST_OPENAI_MODEL", "gpt-image-2")


def _size(size) -> str:
    # gpt-image-2 støtter 1024x1024, 1536x1024, 1024x1536.
    return "1024x1536" if size[1] > size[0] else "1024x1024"


def quality() -> str:
    """Detaljnivå. Motoren kan ikke gi flere piksler enn 1024x1536, så kvalitet er
    det eneste håndtaket vi har mot uskarphet her (Gemini kan derimot gi 2K)."""
    return (os.environ.get("BRANDPOST_IMAGE_QUALITY") or "high").strip() or "high"


def available() -> bool:
    if not os.environ.get("OPENAI_API_KEY"):
        return False
    try:
        import openai  # noqa: F401
        return True
    except ImportError:
        return False


def _ref_paths(brand: Brand, use_tilda: bool) -> list:
    """Merkevare-referanser fra profilen: logo (+ evt. Tilda) + stil-eksemplene."""
    paths = []
    if brand.logo_path and brand.logo_path.exists():
        paths.append(brand.logo_path)
    if use_tilda and brand.tilda_path and brand.tilda_path.exists():
        paths.append(brand.tilda_path)
    paths.extend(p for p in brand.refs if p.exists())
    return paths[:5]


def generate_image(motif: str, *, headline: str = "", brand: Brand,
                   size=(1080, 1350), concept: str | None = None,
                   use_tilda: bool = False) -> bytes:
    """Design ett sammenhengende brand-kort via gpt-image-2. Reiser OpenAIImageError."""
    try:
        import openai
    except ImportError as e:
        raise OpenAIImageError("openai ikke installert (.venv/bin/pip install openai)") from e
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        raise OpenAIImageError("OPENAI_API_KEY mangler i .env")
    client = openai.OpenAI(api_key=key)
    prompt = prompts.brand_card_prompt(motif, headline=headline, brand=brand, size=size,
                                       concept=concept, use_tilda=use_tilda)
    sz = _size(size)
    files = [open(p, "rb") for p in _ref_paths(brand, use_tilda)]
    try:
        try:
            resp = client.images.edit(model=model(), image=files, prompt=prompt, size=sz)
        except Exception:  # edit tok ikke refs -> ren generering
            resp = client.images.generate(model=model(), prompt=prompt, size=sz,
                                          quality=quality())
    except Exception as e:
        raise OpenAIImageError(f"OpenAI generate feilet: {e}") from e
    finally:
        for f in files:
            try:
                f.close()
            except OSError:
                pass
    b64 = getattr(resp.data[0], "b64_json", None) if getattr(resp, "data", None) else None
    if not b64:
        raise OpenAIImageError("ingen bilde-data i OpenAI-svaret")
    return base64.b64decode(b64)


def generate_content(motif: str, *, brand: Brand, size=(1080, 1350),
                     concept: str | None = None, use_tilda: bool = False) -> bytes:
    """KUN infografikk-innholdet på sand (rammen tegnes av Pillow etterpå). Sender bare
    logoen (+ evt. Tilda) som ref, IKKE frame-eksemplene (de har ramme)."""
    try:
        import openai
    except ImportError as e:
        raise OpenAIImageError("openai ikke installert") from e
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        raise OpenAIImageError("OPENAI_API_KEY mangler i .env")
    client = openai.OpenAI(api_key=key)
    prompt = prompts.content_prompt(motif, brand=brand, size=size, concept=concept,
                                    use_tilda=use_tilda)
    paths = []
    if brand.logo_path and brand.logo_path.exists():
        paths.append(brand.logo_path)
    if use_tilda and brand.tilda_path and brand.tilda_path.exists():
        paths.append(brand.tilda_path)
    files = [open(p, "rb") for p in paths]
    try:
        try:
            resp = client.images.edit(model=model(), image=files, prompt=prompt, size=_size(size))
        except Exception:
            resp = client.images.generate(model=model(), prompt=prompt,
                                          size=_size(size), quality=quality())
    except Exception as e:
        raise OpenAIImageError(f"OpenAI content feilet: {e}") from e
    finally:
        for f in files:
            try:
                f.close()
            except OSError:
                pass
    b64 = getattr(resp.data[0], "b64_json", None) if getattr(resp, "data", None) else None
    if not b64:
        raise OpenAIImageError("ingen bilde-data i OpenAI-svaret")
    return base64.b64decode(b64)
