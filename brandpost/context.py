"""context — samler ferske temaer og vinklinger til hjernen.

Destillerer det du har matet inn til en kompakt «hva rører seg»-dump som brukes til
å velge innleggsvinkler. Returnerer KUN temaer, overskrifter og endringer, aldri rått
notat-innhold: dette er tenning for kreativ vinkling, ikke en kilde til sitater.

Kilder under arbeidsmappa:
  notes/*.md              det du selv legger inn (møtereferater, innvendinger, tall)
  socials/pulse/*.json    valgfri puls, hvis du kobler på en egen kilde
  socials/engagement.json respons på publiserte innlegg (engagement.py)

ALT er valgfritt. En fersk kloning uten et eneste notat gir tomme felter, og
systemet skriver da ut fra merkevaren og planen alene. Det er med vilje: du skal
kunne se et resultat før du har rigget noe som helst.

Konfidensialitet: dette laget sensurerer IKKE, men eksponerer bevisst bare
overskriftsnivå. Runbooken avgjør hva som faktisk kan brukes offentlig, og dens
regel er enkel: aldri kundenavn, aldri interne tall, aldri upublisert prising.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from pathlib import Path

from . import paths



def _vault(vault: Path | None) -> Path:
    return paths.workspace(vault)


def _system(vault: Path) -> Path:
    """Rota for alt systemet skriver. I opphavet var dette en arbeidsmappe; her er
    det bare arbeidsmappa, og navnet er beholdt for å holde diffen liten."""
    return paths.workspace(vault)


def _notater(vault: Path, days: int, limit: int) -> list[dict]:
    """Ferske notater fra `notes/`, nyeste først.

    Dette er kontekst-inngangen: legg markdown-filer her, så leser hjernen dem når
    den skal finne ut hva den skal skrive om. Et notat kan være hva som helst,
    et møtereferat, en kundeinnvending du hørte, et tall du fant.

    De første linjene brukes som sammendrag, så skriv det viktigste øverst.
    Tom mappe er helt greit: da skriver hjernen ut fra merkevaren og planen alene.
    """
    d = paths.notes_dir(vault)
    if not d.exists():
        return []
    cutoff = datetime.now() - timedelta(days=days)
    rader: list[tuple[float, dict]] = []
    for p in sorted(d.rglob("*.md")):
        try:
            mtime = p.stat().st_mtime
            if datetime.fromtimestamp(mtime) < cutoff:
                continue
            tekst = p.read_text(encoding="utf-8", errors="replace").strip()
        except OSError:
            continue
        if not tekst:
            continue
        linjer = [rad.strip() for rad in tekst.splitlines() if rad.strip()]
        rader.append((mtime, {
            "tittel": linjer[0].lstrip("# ").strip() if linjer else p.stem,
            "sammendrag": " ".join(linjer[1:6])[:600],
            "fil": p.name,
        }))
    rader.sort(key=lambda r: r[0], reverse=True)
    return [rad for _, rad in rader[:limit]]


def _context_titles(vault: Path, days: int, limit: int) -> list[str]:
    """Bare titlene på ferske notater, som tema-hint."""
    d = paths.notes_dir(vault)
    if not d.exists():
        return []
    cutoff = datetime.now() - timedelta(days=days)
    rows: list[tuple[float, str]] = []
    for p in d.glob("*.md"):
        if p.name == "index.md":
            continue
        try:
            mtime = p.stat().st_mtime
        except OSError:
            continue
        if datetime.fromtimestamp(mtime) < cutoff:
            continue
        rows.append((mtime, p.stem))
    rows.sort(reverse=True)
    return [stem for _, stem in rows[:limit]]


def _latest_pulse(vault: Path, max_age_days: int = 3) -> dict:
    """Ferskeste Slack-puls (pulse.py sitt destillat), maks `max_age_days` gammel.
    Eksponerer kun de anonymiserte feltene, aldri interne stier eller problemer."""
    d = _system(vault) / "socials" / "pulse"
    if not d.exists():
        return {}
    cutoff = datetime.now() - timedelta(days=max_age_days)
    for p in sorted(d.glob("*.json"), reverse=True):  # datonavn: nyeste først
        try:
            if datetime.fromtimestamp(p.stat().st_mtime) < cutoff:
                continue
            data = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        out = {k: data[k] for k in
               ("generated", "angles", "wins", "sporsmal_folk_stiller", "produktnytt")
               if data.get(k)}
        if data.get("reason") and not out.get("angles"):
            out["reason"] = data["reason"]
        return out
    return {}


def _engagement_summary(vault: Path, top: int = 5, bottom: int = 3) -> dict:
    """Kompakt respons-bilde fra engagement.json: hva som funket best og dårligst
    (headline + pilar + format + tall), så hjernen kan lære av det sammen med lessons."""
    p = _system(vault) / "socials" / "engagement.json"
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    posts = [q for q in (data.get("posts") or []) if isinstance(q, dict)]
    if not posts:
        return {}

    def _row(q: dict) -> dict:
        return {"headline": q.get("headline", ""), "pillar": q.get("pillar", ""),
                "format": q.get("format", ""), "reactions": q.get("reactions", 0),
                "comments": q.get("comments", 0)}

    posts.sort(key=lambda q: (q.get("reactions", 0) + 2 * q.get("comments", 0)),
               reverse=True)
    out = {"updated": data.get("updated", ""), "topp": [_row(q) for q in posts[:top]]}
    if len(posts) > top:
        out["bunn"] = [_row(q) for q in posts[-bottom:]]
    return out


def gather_context(vault: Path | None = None, *, days: int = 10,
                   enrich_limit: int = 12, insight_limit: int = 6,
                   context_limit: int = 8) -> dict:
    """Kompakt tema-dump til hjernen. ALLE felt er best-effort og kan være tomme:
    systemet skal virke på en fersk kloning uten notater, uten historikk og uten tall."""
    v = _vault(vault)
    return {
        "generated": datetime.now().isoformat(timespec="seconds"),
        "vault": str(v),
        "window_days": days,
        "notes": _notater(v, days, enrich_limit),
        "context_links": _context_titles(v, days * 3, context_limit),
        "slack_pulse": _latest_pulse(v),
        "engagement": _engagement_summary(v),
    }
