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
import stat
from pathlib import Path

# Repo-rota. Lå som parents[2] i tre moduler, som pekte UT AV repoet: .env ble
# aldri lest, og «cp .env.example .env» i README virket ikke for noen. Én kilde nå.
REPO_ROOT = Path(__file__).resolve().parents[1]


def env_files() -> list[Path]:
    """Den ene miljøfila installasjonen eksplisitt har valgt.

    Det finnes med vilje ingen søkesti og ingen fallback til ``cwd/.env`` eller
    motorrepoets ``.env``. En pip-installert motor kan ellers fylle manglende
    Pengefix-verdier med Oscars LinkedIn-/API-oppsett bare fordi klonen ligger i
    nærheten. ``BRANDPOST_ENV_FILE`` er derfor en obligatorisk peker når en fil
    skal brukes; prosessmiljø uten fil virker fortsatt som før.
    """
    raw = (os.environ.get("BRANDPOST_ENV_FILE") or "").strip()
    return [Path(raw).expanduser()] if raw else []


# Verdier vi selv la inn ved forrige load. De fjernes før en annen eksplisitt
# fil lastes, slik at to installasjoner som testes i samme prosess ikke lekker
# manglende variabler til hverandre. Verdier satt av launchd/skallet eies ikke av
# denne tabellen og vinner alltid.
_LOADED_ENV: dict[str, str] = {}


def load_env() -> list[Path]:
    """Last bare ``BRANDPOST_ENV_FILE`` uten kryssforurensning.

    En plist eller eksplisitt eksport vinner over fila. På POSIX strammes
    filmodusen til ``0600`` når fila lastes; hemmeligheter skal aldri være
    gruppe-/verdenslesbare.
    """
    global _LOADED_ENV
    for key, value in list(_LOADED_ENV.items()):
        if os.environ.get(key) == value:
            os.environ.pop(key, None)
    _LOADED_ENV = {}

    lastet: list[Path] = []
    try:
        from dotenv import dotenv_values
    except ImportError:
        return lastet
    for p in env_files():
        if p.is_file():
            if os.name == "posix":
                try:
                    p.chmod(stat.S_IRUSR | stat.S_IWUSR)
                except OSError:
                    pass
            verdier = dotenv_values(p)
            for key, value in verdier.items():
                if key and value is not None and key not in os.environ:
                    os.environ[key] = value
                    _LOADED_ENV[key] = value
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


def state_dir(override: Path | str | None = None) -> Path:
    """Maskinlokal tilstand: logger, ledgers, låser og nettleserprofil.

    Standard under workspacet gir isolasjon også i en fersk klone. Produksjon
    bør sette ``BRANDPOST_STATE_DIR`` eksplisitt, så release-bytter aldri flytter
    eller deler maskintilstand.
    """
    if override:
        return Path(override).expanduser()
    raw = (os.environ.get("BRANDPOST_STATE_DIR") or "").strip()
    return Path(raw).expanduser() if raw else workspace() / ".brandpost-state"


def state_dir_for_workspace(workspace_override: Path | str | None = None) -> Path:
    """State-root bundet til et eksplisitt workspace når env ikke overstyrer."""
    raw = (os.environ.get("BRANDPOST_STATE_DIR") or "").strip()
    return Path(raw).expanduser() if raw else workspace(workspace_override) / ".brandpost-state"
