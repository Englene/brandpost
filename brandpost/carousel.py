"""carousel — bygg en LinkedIn-karusell (flersides PDF) fra en slide-spec.

En karusell-spec:
  {"type": "karusell", "tittel": "...", "brand": "demo",
   "slides": [ {"kind": "forside", "heading": "...", "kicker": "...", "body": "..."},
               {"kind": "innhold", "heading": "...", "body": "...", "number": 1},
               ...,
               {"kind": "cta", "heading": "Klar til å prøve?", "body": "..."} ]}

Slidene rendres stående (1080×1350) via slides.py og montres til PDF med Pillow
(ingen ny avhengighet). LinkedIn viser PDF-en som en swipe-bar dokumentpost.
"""

from __future__ import annotations

import json
from io import BytesIO
from pathlib import Path

from PIL import Image

from . import brandkit, render, slides
from .brandkit import Brand


def _img_png(img: Image.Image) -> bytes:
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def forside_motiv(spec: dict, brand: Brand):
    """Ett bildekall til forsiden, eller None når spec-en ikke har et motiv.

    Bevisst kun forsiden: den stopper scrollen, mens åtte uavhengig genererte bilder
    lett leser som åtte ulike serier. Samme motor og samme kontrakt som postene, så
    AI-delen ser typografisk ut (Oscars krav 25. juli 2026)."""
    if not (spec.get("motif") or spec.get("image_prompt")):
        return None
    return render.engine_content(spec, brand, slides.SIZE_PORTRAIT)


def build_carousel(spec: dict, *, brand: Brand | None = None, art=None) -> dict:
    """Rendr alle slides og montér til én PDF. Returnerer
    {pdf, slide_pngs, cover, n, tittel, size_mb}.

    `art` er et ferdig forside-motiv. Uten det hentes ett fra spec-ens `motif`;
    har spec-en heller ikke motiv, koster karusellen null bildekall som før."""
    b = brand or brandkit.load_brand(spec.get("brand", "demo"))
    slide_specs = spec.get("slides") or []
    if not slide_specs:
        raise ValueError("karusell-spec mangler ikke-tom 'slides'")
    total = len(slide_specs)
    if art is None:
        art = forside_motiv(spec, b)

    images: list[Image.Image] = []
    point = 0  # nummerering av innholds-slides (forside/cta teller ikke)
    for pos, s in enumerate(slide_specs):
        number = None
        if (s.get("kind") or "innhold").strip().lower() == "innhold":
            point += 1
            number = point
        images.append(slides.render_slide(s, b, pos=pos, total=total, number=number,
                                          art=art))

    buf = BytesIO()
    images[0].save(buf, format="PDF", save_all=True, append_images=images[1:],
                   resolution=72.0)
    pdf = buf.getvalue()
    slide_pngs = [_img_png(im) for im in images]
    return {
        "pdf": pdf,
        "slide_pngs": slide_pngs,
        "cover": slide_pngs[0],
        "n": total,
        "tittel": (spec.get("tittel") or spec.get("headline") or "Karusell").strip(),
        "size_mb": round(len(pdf) / (1024 * 1024), 2),
    }


def rebuild_carousel(draft: dict, *, brand: Brand | None = None, art=None) -> dict:
    """Bygg en EKSISTERENDE karusell på nytt og skriv over filene den alt har.

    Dette er det `write_carousel` ikke kan: den regner alltid ut et nytt filnavn fra
    tittelen, så det fantes ingen overskrivingsvei, og «Regenerer» var derfor sperret.
    Her beholdes pdf_path, cover_path og slide-mappa, slik at manifestet, kalenderens
    miniatyr og publiseringsveien peker på det samme etterpå.

    Returnerer {n, ryddet, slides}. `ryddet` er slides som ble liggende igjen fra en
    lengre utgave: visningen globber mappa, så uten opprydding ville gamle slides
    fortsatt blitt vist etter en ombygging til færre.
    """
    spec = dict(draft.get("spec") or {})
    if not (spec.get("slides") or []):
        raise ValueError("utkastet har ingen slides å bygge om")
    b = brand or brandkit.load_brand(draft.get("brand") or "demo")

    pdf_path = Path(draft.get("pdf_path") or "")
    cover_path = Path(draft.get("cover_path") or "")
    if not pdf_path.name or not cover_path.name:
        raise ValueError("utkastet mangler pdf_path/cover_path")

    built = build_carousel({**spec, "tittel": draft.get("tittel") or spec.get("tittel", "")},
                           brand=b, art=art)

    pdf_path.write_bytes(built["pdf"])
    cover_path.write_bytes(built["cover"])
    slide_dir = pdf_path.parent / pdf_path.stem
    slide_dir.mkdir(exist_ok=True)
    for i, png in enumerate(built["slide_pngs"], 1):
        (slide_dir / f"slide-{i}.png").write_bytes(png)

    ryddet = []
    for gammel in slide_dir.glob("slide-*.png"):
        try:
            nr = int(gammel.stem.split("-")[-1])
        except ValueError:
            continue
        if nr > built["n"]:
            gammel.unlink(missing_ok=True)
            ryddet.append(gammel.name)
    return {"n": built["n"], "ryddet": sorted(ryddet), "slides": len(built["slide_pngs"])}


_OMSKRIV_SCHEMA = {
    "type": "object",
    "properties": {
        "tittel": {"type": "string"},
        "slides": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "kind": {"type": "string", "enum": ["forside", "innhold", "cta"]},
                    "kicker": {"type": "string"},
                    "heading": {"type": "string"},
                    "body": {"type": "string"},
                },
                "required": ["kind", "heading"],
            },
        },
    },
    "required": ["slides"],
}

_OMSKRIV_SYSTEM = (
    "Du skriver om en LinkedIn-karusell for {name}. Behold antall slides og samme "
    "rekkefølge av typer (forside, innhold, cta), men skriv teksten på nytt så den blir "
    "skarpere. Slidene leses på to sekunder hver: korte overskrifter, få ord i brødteksten. "
    "Skriv naturlig norsk bokmål. ALDRI tankestrek, bruk komma, kolon eller punktum.\n\n"
    "MERKESTEMME:\n{voice}"
)


def omskriv_slides(draft: dict, brand: Brand, *, rettelser: list[str] | None = None) -> dict:
    """Be modellen skrive slide-tekstene på nytt. Returnerer ny spec-del
    {tittel, slides}. Ett tekstkall, null bildekall.

    Rettelsene sendes med i sin helhet hver gang, ikke bare den nyeste, av samme
    grunn som for bildene: et problem Oscar har påpekt skal ikke komme tilbake."""
    from . import model as loop_model
    from . import brandkit as bk

    retter = [str(r).strip() for r in (rettelser or []) if str(r).strip()]
    spec = draft.get("spec") or {}
    user = (
        f"DAGENS KARUSELL (behold antall og typer):\n"
        + json.dumps({"tittel": draft.get("tittel") or spec.get("tittel", ""),
                      "slides": spec.get("slides") or []}, ensure_ascii=False, indent=2)
        + f"\n\nINNLEGGSTEKSTEN SOM FØLGER KARUSELLEN (kontekst):\n{draft.get('body', '')}"
        + ("\n\nRETT OPP. Dette bommet forrige forsøk på, og MÅ være annerledes nå:\n"
           + "\n".join(f"- {r}" for r in retter) if retter else "")
        + "\n\nSkriv slidene på nytt nå."
    )
    env = loop_model.structured_call(
        _OMSKRIV_SYSTEM.format(name=brand.name, voice=bk.voice_guide(brand)[:2500]),
        user, _OMSKRIV_SCHEMA, label="karusell-omskriv")
    # structured_call returnerer en KONVOLUTT; svaret ligger under "structured_output",
    # slik alle de andre kallstedene leser det (plan.py, cli.py, pulse.py). Sto feil
    # nøkkel her, og testen mocket det indre svaret, så feilen var usynlig: i drift ble
    # slides alltid tom og regenerering svarte «ingenting er endret».
    ut = env.get("structured_output") or {}
    return {"tittel": (ut.get("tittel") or "").strip(),
            "slides": [s for s in (ut.get("slides") or []) if isinstance(s, dict)]}
