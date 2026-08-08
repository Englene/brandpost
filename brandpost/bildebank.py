"""bildebank — egne, ekte bilder som alternativ til generert grafikk.

Motoren tegner normalt bildet sitt selv. For en personlig profil er det feil vei:
en privatperson som poster designet infografikk på hvert innlegg leser som en
kampanje. Det som virker er et bilde av den faktiske tingen.

Denne modulen LESER en bildebank som noen andre har fylt. Den vurderer ingenting
og skanner ingenting: den kjenner bare formatet, og hva som skal til for at et
bilde er godkjent. Selve vurderingen hører hjemme i oppsettet ditt, fordi den
avhenger av hva DU regner som sensitivt.

Formatet er én JSON-fil, `<workspace>/socials/bevis.json`:

    {"oppdatert": "...", "bilder": {"<id>": {
        "sti": "/…/skjermbilde.png",
        "sett": true,          // så noen faktisk på bildet?
        "sensitiv": false,     // inneholder det noe som ikke tåler offentlighet?
        "egnet": true,         // viser det noe som er bygget?
        "beskrivelse": "…",    // det eneste hjernen får se
        "stikkord": ["…"],
        "overstyrt": "godkjent" | "avvist"   // valgfritt, eieren vinner
    }}}

GODKJENNINGEN ER FAIL-CLOSED: et bilde er kandidat bare når alle tre flaggene er
positive. Mangler et felt, er svaret nei. Asymmetrien er hele begrunnelsen: en
falsk positiv legger en kundes navn ut offentlig, en falsk negativ koster ett
bilde av mange.
"""

from __future__ import annotations

import json
from pathlib import Path

from . import paths
from . import store

INDEKS_NAVN = "bevis.json"


def indeks_sti(vault: Path | None = None) -> Path:
    return store.socials_dir(paths.workspace(vault)) / INDEKS_NAVN


def les_indeks(vault: Path | None = None) -> dict:
    """Hele banken. Tom, gyldig struktur når fila mangler eller er ødelagt: en
    manglende bildebank er en normal tilstand, ikke en feil."""
    try:
        data = json.loads(indeks_sti(vault).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"oppdatert": "", "bilder": {}}
    if not isinstance(data, dict) or not isinstance(data.get("bilder"), dict):
        return {"oppdatert": "", "bilder": {}}
    return data


def er_kandidat(post: dict) -> bool:
    """Kan dette bildet foreslås til et innlegg?

    Eierens egen overstyring vinner over vurderingen i begge retninger. Det er
    poenget med den: han har sett bildet selv, og en maskin som overprøver ham på
    hans eget skjermbilde er bare i veien.
    """
    if not isinstance(post, dict):
        return False
    if post.get("overstyrt") == "avvist":
        return False
    if post.get("overstyrt") == "godkjent":
        return True
    return bool(post.get("sett")) and not post.get("sensitiv") and bool(post.get("egnet"))


def kandidater(vault: Path | None = None, limit: int = 40) -> list[dict]:
    """De godkjente bildene, nyeste vurdering først.

    Stien er med, fordi den som velger bildet må kunne kopiere fila. Det er trygt:
    dette går til genereringen, aldri til et innlegg.
    """
    ut = [{"id": n, "sti": p.get("sti", n), "beskrivelse": p.get("beskrivelse", ""),
           "stikkord": p.get("stikkord", []), "vurdert": p.get("vurdert", "")}
          for n, p in les_indeks(vault).get("bilder", {}).items() if er_kandidat(p)]
    ut.sort(key=lambda d: d.get("vurdert", ""), reverse=True)
    return ut[:limit]


def finn(bevis_id: str, vault: Path | None = None) -> Path | None:
    """Stien til ett godkjent bilde, eller None.

    Godkjenningen håndheves PÅ NYTT her, ikke bare når kandidatlista bygges. To
    grunner: hjernen kan finne på en id, og banken kan ha endret seg mellom
    genereringen og bruken. Uten dette ville en id som var godkjent i går kunne
    hente et bilde eieren har avvist siden.
    """
    if not bevis_id:
        return None
    post = les_indeks(vault).get("bilder", {}).get(bevis_id)
    if not post or not er_kandidat(post):
        return None
    sti = Path(post.get("sti", ""))
    return sti if sti.is_file() else None


def kandidat_blokk(vault: Path | None = None, limit: int = 25) -> str:
    """Kandidatene som en blokk til hjernens brukermelding. Tom streng når banken
    er tom, så prompten ikke får en overskrift uten innhold under."""
    kand = kandidater(vault, limit=limit)
    if not kand:
        return ""
    rader = [{"id": k["id"], "viser": k["beskrivelse"]} for k in kand]
    return ("\n\nEGNE BILDER du kan bruke (ekte skjermbilder fra ditt eget arbeid, "
            "allerede sjekket for sensitivt innhold). Passer ett av dem til et "
            "utkast, sett `bevis_id` til id-en. Bildet skal VISE det innlegget "
            "handler om, ikke bare være i nærheten av temaet. Passer ingen, la "
            "`bevis_id` stå tom: ingen bilde er bedre enn feil bilde.\n"
            + json.dumps(rader, ensure_ascii=False))
