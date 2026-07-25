"""engagement — les responsen på publiserte innlegg tilbake inn i lærdommene.

Skanner manifestene i `_system/socials/*/manifest.json` for utkast med status
"published" + linkedin_url, henter reaksjons- og kommentartall via
socialMetadata-endepunktet (Community Management API, scope `r_organization_social`)
og skriver `_system/socials/engagement.json`. context-laget destillerer fila til
et kompakt topp/bunn-bilde som runbooken leser sammen med lessons.md, så
innholdet lærer av hva som faktisk får respons.

Read-only mot LinkedIn. Degraderer pent: mangler creds eller scope beholdes
forrige engagement.json urørt, og `reason`/`problems` forklarer hvorfor.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import quote

import requests

from .fsutil import atomic_write_json
from . import linkedin
from .store import socials_dir

_SCOPE_HINT = ("403 fra socialMetadata: mangler r_organization_social-scope? "
               "Re-autoriser LinkedIn-appen med scopet, så virker `stats`.")


def _post_urn(url: str) -> str:
    """…/feed/update/urn:li:share:123 → urn:li:share:123 ('' hvis ukjent form)."""
    tail = (url or "").rstrip("/").rsplit("/", 1)[-1]
    return tail if tail.startswith("urn:li:") else ""


def _published_drafts(vault: Path | None, days_back: int) -> list[dict]:
    """Publiserte utkast fra dags-manifestene, eldste først."""
    root = socials_dir(vault)
    cutoff = datetime.now() - timedelta(days=days_back)
    rows: list[dict] = []
    for mp in sorted(root.glob("*/manifest.json")):
        day = mp.parent.name  # YYYY-MM-DD
        try:
            if datetime.strptime(day, "%Y-%m-%d") < cutoff:
                continue
        except ValueError:
            continue
        try:
            manifest = json.loads(mp.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for d in manifest.get("drafts") or []:
            if d.get("status") == "published" and d.get("linkedin_url"):
                rows.append({"date": day, **d})
    return rows


def _social_metadata(urn: str, token: str, *, session) -> dict:
    """{'reactions': N, 'comments': M} for ett innlegg. Reiser HTTPError ved feil."""
    r = session.get(f"{linkedin.API}/rest/socialMetadata/{quote(urn, safe='')}",
                    timeout=30, headers=linkedin._headers(token))
    r.raise_for_status()
    data = r.json() if r.content else {}
    reactions = 0
    for v in (data.get("reactionSummaries") or {}).values():
        if isinstance(v, dict):
            reactions += int(v.get("count") or 0)
    cs = data.get("commentSummary") or {}
    comments = int(cs.get("aggregatedTotalComments") or cs.get("count") or 0)
    return {"reactions": reactions, "comments": comments}


def update_stats(vault: Path | None = None, *, days_back: int = 45,
                 cfg: linkedin.LinkedInConfig | None = None, session=None) -> dict:
    """Oppdater engagement.json for alle publiserte innlegg siste `days_back` dager.
    Returnerer payloaden (med `_path` når fila ble skrevet)."""
    cfg = cfg or linkedin.load_linkedin_config()
    rows = _published_drafts(vault, days_back)
    if not rows:
        return {"posts": [], "reason": "ingen publiserte innlegg i manifestene ennå"}
    if not cfg.access_token:
        return {"posts": [], "reason": "LinkedIn ikke konfigurert (LINKEDIN_ACCESS_TOKEN mangler)"}

    sess = session or requests.Session()
    posts: list[dict] = []
    problems: list[str] = []
    for d in rows:
        urn = _post_urn(d.get("linkedin_url", ""))
        if not urn:
            problems.append(f"uforståelig linkedin_url: {d.get('linkedin_url')}")
            continue
        try:
            counts = linkedin._with_token_refresh(
                cfg, sess, lambda t, u=urn: _social_metadata(u, t, session=sess))
        except requests.HTTPError as e:
            st = getattr(getattr(e, "response", None), "status_code", 0)
            if st == 403:
                problems.append(_SCOPE_HINT)
                break  # scope-feil rammer alle innlegg; ikke hamre videre
            problems.append(f"{urn}: HTTP {st}")
            continue
        except Exception as e:
            problems.append(f"{urn}: {e}")
            continue
        posts.append({"date": d.get("date"), "headline": d.get("headline", ""),
                      "pillar": d.get("pillar", ""), "format": d.get("format", ""),
                      "url": d.get("linkedin_url", ""), **counts})

    payload: dict = {"updated": datetime.now().isoformat(timespec="seconds"), "posts": posts}
    if problems:
        payload["problems"] = problems
    out = socials_dir(vault) / "engagement.json"
    if posts or not out.exists():  # aldri klipp over gode tall med en tom feil-kjøring
        atomic_write_json(out, payload)
        payload["_path"] = str(out)
    return payload
