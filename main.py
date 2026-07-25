"""main — start dashbordet.

    python main.py            # http://localhost:5050/some
    PORT=8000 python main.py

Dashbordet er stedet du godkjenner innhold. Ingenting publiseres uten et klikk her
(eller en eksplisitt kommando), og publiseringen er avslått til du selv skrur den på.
"""

from __future__ import annotations

import os
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from web import app as some

ROT = Path(__file__).parent

app = FastAPI(title="brandpost")
app.include_router(some.router)

STATIC = ROT / "web" / "static"
STATIC.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")


@app.get("/")
def forside():
    return RedirectResponse("/some")


if __name__ == "__main__":
    uvicorn.run(app, host=os.environ.get("HOST", "127.0.0.1"),
                port=int(os.environ.get("PORT") or "5050"))
