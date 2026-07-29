"""server — dashbordet som en importerbar ASGI-app.

    uvicorn web.server:app --port 5050

Appen ble bygget i main.py i repo-rota, som virker når du kjører fra en klone,
men ikke når brandpost er pip-installert: da er main.py ikke med i pakken, og
det finnes ingen app å peke uvicorn på. Static-mappa ble dessuten funnet via
repo-rota, som heller ikke stemmer da.

main.py bruker denne nå, så det er én app og én statisk sti.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from . import app as some

WEB_DIR = Path(__file__).resolve().parent

app = FastAPI(title="brandpost")
app.include_router(some.router)

STATIC = WEB_DIR / "static"
STATIC.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")


@app.get("/")
def forside():
    return RedirectResponse("/some")


@app.get("/healthz")
def healthz() -> dict:
    """Liveness for prosess-vakter (launchd KeepAlive, systemd, docker healthcheck).
    Svarer uten å røre disk eller nettverk, så den sier «prosessen lever», ikke
    «alt er bra»."""
    return {"ok": True, "service": "brandpost"}
