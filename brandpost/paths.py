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
