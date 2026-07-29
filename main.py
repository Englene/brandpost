"""main — start dashbordet.

    python main.py            # http://localhost:5050/some
    PORT=8000 python main.py

Dashbordet er stedet du godkjenner innhold. Ingenting publiseres uten et klikk her
(eller en eksplisitt kommando), og publiseringen er avslått til du selv skrur den på.

Selve appen bor i web/server.py, så den også kan startes direkte når brandpost er
installert som pakke, der denne fila ikke er med:

    uvicorn web.server:app --port 5050
"""

from __future__ import annotations

import os

import uvicorn

from web.server import app  # noqa: F401  (eksponert for `uvicorn main:app`)

if __name__ == "__main__":
    uvicorn.run(app, host=os.environ.get("HOST", "127.0.0.1"),
                port=int(os.environ.get("PORT") or "5050"))
