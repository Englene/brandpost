"""fsutil — atomiske skriv.

tmp-fil + rename, med backoff på transiente låsefeil. Det siste høres overdrevent
ut helt til filene ligger i en synkemappe (iCloud, Dropbox, Syncthing): da holder
synkeklienten fila låst i korte glimt, og et vanlig skriv feiler tilfeldig.
"""

from __future__ import annotations

import errno
import json
import time
from pathlib import Path

# Feil som går over av seg selv: ressursen er opptatt akkurat nå, ikke ødelagt.
_RETRYABLE = {errno.EAGAIN, errno.EBUSY, errno.EDEADLK, errno.EINTR}


def atomic_write_text(path: Path, text: str, *, encoding: str = "utf-8",
                      attempts: int = 5, base_delay: float = 0.3) -> None:
    """Skriv til tmp og bytt inn. Leseren ser enten den gamle eller den nye fila,
    aldri en halvskrevet."""
    path = Path(path)
    tmp = path.with_name(path.name + ".tmp")
    last: OSError | None = None
    for i in range(attempts):
        try:
            tmp.write_text(text, encoding=encoding)
            tmp.replace(path)
            return
        except OSError as e:
            if e.errno not in _RETRYABLE:
                raise
            last = e
            time.sleep(base_delay * (2 ** i))
    raise last if last else OSError(f"fikk ikke skrevet {path}")


def atomic_write_json(path: Path, payload, *, indent: int = 2,
                      attempts: int = 5, base_delay: float = 0.3) -> None:
    atomic_write_text(Path(path),
                      json.dumps(payload, indent=indent, ensure_ascii=False),
                      attempts=attempts, base_delay=base_delay)
