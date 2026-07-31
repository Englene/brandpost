"""revise — rett opp et utkast etter eierens tilbakemelding.

Dashbordets `regen` lager nytt BILDE fra samme tekst. Denne gjør det andre: den
skriver om selve innlegget når det er innholdet som er galt.

Behovet kom av en ekte feil 31. juli 2026. Et utkast påsto at norske miljøer har
hentet «rundt 15,7 milliarder kroner» fra Horisont Europa, mens kilden det selv
viste til sier 10,6. Kilde-strengen påsto til og med «1,5 mrd euro / 15,7 mrd kr»,
et euro-tall som ikke står på siden, og som ikke engang stemmer med kronetallet.

Generering via `cli run` gjør ingen websøk: modellen skriver kilder og tall fra
hukommelsen, og ingenting verifiserer dem. Til den rotårsaken er løst, er eierens
øye siste skanse, og da må han kunne si fra med ord og få et nytt utkast.

Rettelsen lagres på utkastet og følger med i HVER senere prompt for det, så et
problem han har påpekt én gang ikke kommer tilbake i neste forsøk.
"""
from __future__ import annotations

import json

from . import brandkit, store
from .model import structured_call

MAX_RETTELSER = 8

_REVISE_SCHEMA = {
    "type": "object",
    "properties": {
        "headline": {"type": "string"},
        "body": {"type": "string"},
        "why_now": {"type": "string"},
        "motif": {"type": "string"},
        "emne": {"type": "string"},
        "kilder": {"type": "array", "items": {"type": "string"}},
        "endret": {"type": "string",
                   "description": "én setning om hva som faktisk ble rettet"},
    },
    "required": ["headline", "body", "endret"],
}

_REVISE_SYSTEM = """Du retter opp ETT LinkedIn-utkast for {name} etter eierens tilbakemelding.

Du skal IKKE lage et nytt innlegg om noe annet. Behold vinkelen og poenget, med
mindre tilbakemeldingen ber om noe annet. Rett det han peker på, og la resten stå.

TALL OG KILDER, VIKTIGST AV ALT:
- Er tilbakemeldingen at et tall er feil, skal du bruke tallet HAN oppgir, ikke
  ditt eget. Han har sett kilden.
- Skriv aldri et tall du ikke kan feste til en kilde i `kilder`-lista.
- Er du usikker på et tall, ta det ut av teksten framfor å gjette. Et innlegg uten
  tall er bedre enn et innlegg med feil tall.
- `kilder` er «påstand → URL». Påstanden må være det kilden FAKTISK sier.

SKRIVESTIL:
{voice}

MERKEVARESTEMME OG PRODUKTFAKTA:
{produkter}
"""


def revise_draft(draft: dict, note: str, *, brand_key: str = "") -> dict:
    """Skriv om utkastet etter `note`. Returnerer felter å oppdatere.

    Kaster ModelError hvis modellen ikke svarer. Kallet krever Keychain, altså
    gui-kontekst: over ren ssh feiler det med 401 uansett PATH."""
    brand = brandkit.load_brand(brand_key or draft.get("brand") or "demo")
    spec = dict(draft.get("spec") or {})

    rettelser = [str(c) for c in (spec.get("corrections") or []) if str(c).strip()]
    ny = (note or "").strip()
    if ny and ny not in rettelser:
        rettelser.append(ny)
    rettelser = rettelser[-MAX_RETTELSER:]

    system = _REVISE_SYSTEM.format(
        name=brand.name,
        voice=brandkit.voice_guide(brand)[:3000],
        produkter=(brand.produkter or "(ingen produktfakta)")[:2000],
    )
    naa = {
        "headline": draft.get("headline", ""),
        "body": draft.get("body", ""),
        "why_now": draft.get("why_now", ""),
        "motif": draft.get("motif", ""),
        "emne": draft.get("emne", ""),
        "kilder": [k for k in (draft.get("kilder") or []) if isinstance(k, str)],
    }
    user = ("UTKASTET SLIK DET ER NÅ:\n" + json.dumps(naa, ensure_ascii=False)
            + "\n\nEIERENS TILBAKEMELDING (nyeste sist, alle gjelder fortsatt):\n"
            + "\n".join(f"- {r}" for r in rettelser)
            + "\n\nSkriv om utkastet slik at tilbakemeldingene er innfridd. "
              "Behold det som ikke er påpekt.")

    env = structured_call(system, user, _REVISE_SCHEMA, label="retting")
    ut = env.get("structured_output") or {}
    if not ut.get("body"):
        raise ValueError("modellen ga ingen tekst tilbake")

    spec["corrections"] = rettelser
    for felt in ("headline", "body", "why_now", "motif"):
        if ut.get(felt):
            spec[felt] = store.clean_text(str(ut[felt]))

    felter = {
        "headline": store.clean_text(str(ut.get("headline") or draft.get("headline", ""))),
        "body": store.clean_text(str(ut["body"])),
        "why_now": store.clean_text(str(ut.get("why_now") or draft.get("why_now", ""))),
        "motif": store.clean_text(str(ut.get("motif") or draft.get("motif", ""))),
        "emne": store.clean_topic(ut.get("emne") or draft.get("emne", "")),
        "spec": spec,
    }
    if ut.get("kilder"):
        felter["kilder"] = [store.clean_text(str(k)) for k in ut["kilder"] if str(k).strip()]
    return {"felter": felter, "endret": str(ut.get("endret") or "").strip()}
