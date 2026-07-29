"""paths — hvor ting bor på disk.

Alt systemet lager havner under ÉN arbeidsmappe:

    <workspace>/socials/<dato>/     genererte utkast (png, md, manifest.json)
    <workspace>/socials/plan.json   innholdsplanen
    <workspace>/socials/_slettet/   papirkurv
    <workspace>/notes/*.md          det du mater inn som kontekst

Sett BRANDPOST_WORKSPACE for å legge den et annet sted. Standard er `./workspace`
i mappa du kjører fra, slik at en fersk kloning virker uten å konfigureres.

Denne fila finnes fordi opphavet hadde FIRE kopier av den samme oppløsningen, i
fire moduler. De var like helt til de ikke var det.
"""

from __future__ import annotations

import os
from pathlib import Path

# Repo-rota. Lå som parents[2] i tre moduler, som pekte UT AV repoet: .env ble
# aldri lest, og «cp .env.example .env» i README virket ikke for noen. Én kilde nå.
REPO_ROOT = Path(__file__).resolve().parents[1]


def env_files() -> list[Path]:
    """Hvor .env letes etter, i prioritert rekkefølge.

    Arbeidskatalogen FØRST, pakkens egen rot etterpå. Kloner du repoet og kjører
    derfra, er de to den samme, og alt er som før.

    Forskjellen dukker opp når brandpost er pip-installert i et annet prosjekt:
    da ligger pakken i site-packages eller i en annen klone, og en .env ved siden
    av pakken er ikke DIN. Uten dette leses oppsettet ditt aldri, og feilen ser
    ut som «ukjent merke» i stedet for «fant ikke .env».
    """
    cwd = Path.cwd() / ".env"
    ut = [cwd]
    pakke = REPO_ROOT / ".env"
    if pakke != cwd:
        ut.append(pakke)
    return ut


def load_env() -> list[Path]:
    """Last .env fra env_files(), første treff vinner per variabel.

    load_dotenv overstyrer aldri noe som alt er satt i miljøet, så en plist eller
    en eksplisitt eksport vinner over begge filene.
    """
    lastet: list[Path] = []
    try:
        from dotenv import load_dotenv
    except ImportError:
        return lastet
    for p in env_files():
        if p.is_file():
            load_dotenv(p)
            lastet.append(p)
    return lastet

DEFAULT_WORKSPACE = Path.cwd() / "workspace"


def workspace(override: Path | str | None = None) -> Path:
    if override:
        return Path(override)
    env = os.environ.get("BRANDPOST_WORKSPACE")
    return Path(env) if env else DEFAULT_WORKSPACE


def socials_dir(override: Path | str | None = None) -> Path:
    return workspace(override) / "socials"


def notes_dir(override: Path | str | None = None) -> Path:
    """Mappa du legger notater i. Alt av `.md` her blir kontekst for hjernen."""
    return workspace(override) / "notes"
