"""spot — små håndtegnede skisse-ikoner på karusell-slidene.

Innholds-slidene var ren typografi fram til 15. september 2026: heading, brødtekst,
og en stor tom flate under. Sammenlignet med karusellene folk faktisk stopper på
manglet de et blikkfang per kort. Her hentes det fra vår egen
`tegn/`-generator, ikke fra et bildekall: ikonene er ferdig rendret til PNG i
merkets `media/ikoner/`, så rendringen koster null kroner og null nettverk.

  IKONER              de 26 navnene generatoren kan tegne
  last_ikon(...)      PNG (RGBA, transparent) for ett ikon i et merke, eller None
  velg_ikon(slide)    slidens eget `ikon`-felt, ellers nøkkelord fra teksten

Ikonene TEGNES i meetingnotes/tegn (node + chromium, kun på laptopen) og legges
ferdig-rendret i merkets `media/ikoner/` under BRANDPOST_BRANDS_DIR:

  ~/repos/meetingnotes/.venv/bin/python -m inbox_processor.social.bygg_ikoner \
      --tema <merke> --ut <brands>/<merke>/media/ikoner

Mini har ikke node, så motoren her leser bare filer.
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

from PIL import Image

from .brandkit import Brand

# Speiler IKONER i tegn/ikoner/ikoner.mjs. Test-kontrakt: test_social_ikoner.py
# leser den fila og krever at listene er identiske, så en ny tegning her aldri
# blir hengende igjen som et navn modellen kan be om men ingen kan rendre.
IKONER: tuple[str, ...] = (
    # de 26 første (23. august 2026)
    "dokumentbunke", "lupe", "kartnaal", "haandtrykk", "sjekkliste", "konvolutt",
    "lyspaere", "myntstabel", "kalender", "bygning", "rakett", "graf", "godkjent",
    "avslag", "soknad", "signatur", "mappe", "skjold", "kolbe", "gradshatt",
    "klokke", "maalskive", "trapp", "puslebrikke", "prateboble", "spire",
    # utvidelsen for karusell-slidene (15. september 2026): motivene slidene våre
    # faktisk handler om, flaskehalser, avveininger, terskler og valg
    "trakt", "tannhjul", "veiskille", "vektskaal", "spoersmaalstegn", "floke",
    "kompass", "kikkert", "noekkel", "laas", "timeglass", "kalkulator",
    "mikroskop", "skyvebryter", "termometer", "regneark", "laptop", "database",
    "team", "lovbok", "stempel", "bro", "milepael", "sammenligning",
)

# Nøkkelord -> ikon. Sikkerhetsnett for utkast skrevet før `ikon`-feltet fantes,
# og for de gangene modellen ber om et navn som ikke finnes. Rekkefølgen er
# prioritert: første treff vinner, så det spesifikke står før det generelle.
_NOKKELORD: tuple[tuple[str, tuple[str, ...]], ...] = (
    # Flerords-fraser først: de peker på ett bestemt motiv. Enkeltordene under er
    # bredere og skal bare slå til når ingen frase gjorde det.
    ("sammenligning", ("samme prosjekt", "før og etter", "forskjellen mellom", "to utkast", "sammenlign")),
    ("trakt", ("flaskehals", "køen", "kø ", "propp", "stopper opp", "venter alt annet")),
    ("puslebrikke", ("henger sammen", "variabl", "avhenger av hverandre")),
    ("skyvebryter", ("skrur på", "justerer", "parameter", "innstilling", "vri på")),
    ("vektskaal", ("avveining", "veier tyngst", "veier mer", "prioriter", "verdt prisen")),
    ("laas", ("bindingstid", "bundet", "låst", "oppsigelse", "sperret")),
    ("timeglass", ("fristen går", "tida renner", "siste sjanse", "rekker det", "utsett")),
    ("spoersmaalstegn", ("vet ikke", "uvisst", "ukjent", "hva om", "usikker på")),
    ("veiskille", ("to veier", "valget", "velge mellom", "enten", "alternativ")),
    ("tannhjul", ("mekanisme", "maskineri", "under panseret", "hvordan det virker", "motor")),
    ("kalkulator", ("regne ut", "regnes ut", "regne seg", "beregn", "kalkul", "regnestykk")),
    ("kompass", ("retning", "kurs", "strategi", "peker mot")),
    ("kikkert", ("framover", "langt fram", "utsikt", "neste år", "på sikt")),
    ("mikroskop", ("detalj", "nærmere", "gransk", "forskning", "undersøk")),
    ("regneark", ("timeliste", "timeføring", "regneark", "tabell", "fører timer")),
    ("laptop", ("kode", "utvikler", "programvare", "systemet", "plattform")),
    ("database", ("datasett", "database", "tusenvis av", "lagrer")),
    ("team", ("teamet", "roller", "hvem gjør hva", "de ansatte", "personene")),
    ("lovbok", ("regelverk", "reglene", "forskrift", "ordningen", "vilkår")),
    ("stempel", ("stempel", "formelt godkjent", "attestert")),
    ("bro", ("bygger bro", "overgang", "knytter sammen", "fra idé til")),
    ("milepael", ("milepæl", "etappe", "delmål", "i mål")),
    ("noekkel", ("nøkkel", "åpner opp", "tilgang", "løser opp")),
    ("floke", ("floke", "vrient", "henger fast", "komplisert")),
    ("termometer", ("temperatur", "nivået", "grader", "måler hvor")),
    # Enkeltord (den opprinnelige tabellen, prioritert som før).
    ("klokke", ("venter", "venting", "tid", "timer", "forsinke")),
    ("puslebrikke", ("variabl", "henger sammen", "sammenheng", "kobl", "avheng", "brikke")),
    ("graf", ("terskel", "grense", "kurve", "vokser", "vekst", "måling", "måler", "volum")),
    ("kolbe", ("eksperiment", "prøve", "forsøk", "test", "hypotese", "usikkerhet", "uavklart")),
    ("maalskive", ("ferdig", "mål", "kriterium", "treffe", "resultat", "lykkes")),
    ("prateboble", ("spør", "spørsmål", "svar", "samtale", "møte", "dialog", "si fra")),
    ("lyspaere", ("idé", "ide", "innsikt", "oppdag", "forstå", "løsning")),
    ("sjekkliste", ("sjekk", "krav", "liste", "punkt", "husk", "rekkefølge")),
    ("signatur", ("signatur", "signer", "undertegn")),
    ("soknad", ("søknad", "søke", "søker", "utkast", "formulering")),
    ("godkjent", ("godkjent", "innvilget", "ja fra", "gjennom")),
    ("avslag", ("avslag", "avvist", "nei fra", "stopp")),
    ("myntstabel", ("kroner", "penger", "tilskudd", "fradrag", "honorar", "pris", "kostnad", "budsjett")),
    ("kalender", ("frist", "dato", "kalender", "runde", "året", "uke", "måned")),
    ("bygning", ("bedrift", "selskap", "virksomhet", "organisasjon")),
    ("rakett", ("lanser", "start", "skalere", "fart")),
    ("mappe", ("arkiv", "dokumentasjon", "samle", "orden")),
    ("dokumentbunke", ("dokument", "rapport", "papir", "vedlegg")),
    ("skjold", ("sikker", "personvern", "risiko", "vern", "trygg")),
    ("gradshatt", ("faglig", "kompetanse", "lære", "utdann")),
    ("trapp", ("steg", "trinn", "fase", "prosess", "underveis")),
    ("lupe", ("finn", "leter", "analys", "gjennomgang", "ser etter")),
    ("konvolutt", ("e-post", "epost", "melding", "kontakt", "send")),
    ("haandtrykk", ("avtale", "samarbeid", "partner", "enige")),
    ("kartnaal", ("sted", "region", "kart", "geografi", "fylke", "kommune")),
    ("spire", ("spire", "begynnelsen", "første gang", "tidlig fase")),
)


def ikon_mappe(brand: Brand) -> Path | None:
    """Mappa merkets ferdig-rendrede ikoner ligger i, eller None uten profil."""
    if not brand.profile_dir:
        return None
    return Path(brand.profile_dir) / "media" / "ikoner"


@lru_cache(maxsize=128)
def _les(sti: str, mtime: float) -> Image.Image:
    """Les PNG-en og BESKJÆR den til der det faktisk er strek.

    Ikonene er tegnet i en felles 120-boks, men fyller den ulikt: kalkulatoren
    bruker halve bredden, trakten hele. Uten beskjæring blir de derfor visuelt
    ulikt store på slidene, selv om filene har samme mål. mtime er med i
    cache-nøkkelen så en ny-bygget PNG ikke blir stående igjen.
    """
    im = Image.open(sti).convert("RGBA")
    boks = im.getbbox()                      # None for en helt tom PNG
    return im.crop(boks) if boks else im


def last_ikon(navn: str, brand: Brand) -> Image.Image | None:
    """PNG-en for ett ikon i merkets palett, eller None når den ikke er bygget."""
    navn = (navn or "").strip().lower()
    mappe = ikon_mappe(brand)
    if not navn or navn not in IKONER or not mappe:
        return None
    fil = mappe / f"{navn}.png"
    try:
        return _les(str(fil), fil.stat().st_mtime)
    except (FileNotFoundError, OSError):
        return None


def velg_ikon(slide: dict) -> str | None:
    """Ikonnavnet for en slide: eksplisitt `ikon` først, ellers nøkkelord i teksten.

    Ingen tilfeldig fallback: et ikon som ikke har noe med teksten å gjøre er verre
    enn den tomme flata vi startet med."""
    valgt = (slide.get("ikon") or "").strip().lower()
    if valgt in IKONER:
        return valgt
    tekst = " ".join(str(slide.get(k) or "") for k in ("heading", "body", "kicker")).lower()
    tekst = re.sub(r"\s+", " ", tekst)
    for navn, ord_ in _NOKKELORD:
        if any(o in tekst for o in ord_):
            return navn
    return None
