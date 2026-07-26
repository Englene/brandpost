"""store — skriv SoMe-utkast til vaulten + hold dedup-state.

Utkast havner i `<vault>/_system/socials/<dato>/`:
  post-1.png     rendret bilde
  post-1.md      copy + «hvorfor nå» + metadata (frontmatter)

Dedup-state i `<vault>/_system/socials/state.json` husker de siste vinklene/
formatene (samme idé som Dagsbrevets historikk) så generatoren ikke gjentar seg.
"""

from __future__ import annotations

import json
import re
import os
import shutil
from datetime import datetime
from pathlib import Path

from . import paths
from .fsutil import atomic_write_json, atomic_write_text

STATE_KEEP = 40  # antall siste utkast vi husker for dedup


def _vault(vault: Path | None) -> Path:
    """Arbeidsmappa. Beholder navnet `_vault` av historiske grunner; den er nå bare
    en tynn videresending til paths.workspace, som er ENESTE oppløsning i repoet."""
    return paths.workspace(vault)


def socials_dir(vault: Path | None = None) -> Path:
    d = paths.socials_dir(vault)
    d.mkdir(parents=True, exist_ok=True)
    return d


def _state_path(vault: Path) -> Path:
    return paths.socials_dir(vault) / "state.json"


def load_state(vault: Path | None = None) -> dict:
    p = _state_path(_vault(vault))
    if not p.exists():
        return {"version": 1, "posts": []}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(data, dict) and isinstance(data.get("posts"), list):
            return data
    except (OSError, ValueError):
        pass
    return {"version": 1, "posts": []}


def recent_angles(vault: Path | None = None, n: int = 14) -> list[dict]:
    """De n siste (format, headline, motif, pillar)-radene: mates til runbooken for å
    unngå gjentak av BÅDE vinkel og visuelt motiv."""
    posts = load_state(vault).get("posts", [])
    return [
        {"format": p.get("format"), "headline": p.get("headline"),
         "motif": p.get("motif", ""), "pillar": p.get("pillar", "")}
        for p in posts[-n:]
    ]


# Tankestrek-sanering. Bor HER fordi både innleggs-saneringen (cli) og
# plan-motoren trenger den, og store er den laveste modulen begge importerer.
# Duplisert regex to steder er nettopp fella som lot plan-temaene beholde
# tankestrek helt til 22. juli 2026.
_RANGE_DASH_RE = re.compile(r"(?<=\d)\s*[–—]\s*(?=\d)")
_DASH_RE = re.compile(r"\s*[–—]+\s*")


def clean_text(text: str) -> str:
    """Aldri tankestrek: tallspenn får bindestrek, resten blir komma."""
    t = _RANGE_DASH_RE.sub("-", text or "")
    t = _DASH_RE.sub(", ", t)
    return re.sub(r"  +", " ", t).strip()


def used_angles(vault: Path | None = None, n: int = 30) -> list[dict]:
    """Vinkler som faktisk er BRUKT: utkast med status publisert eller planlagt.

    recent_angles() sperrer alt som er GENERERT, som brente gode ideer som aldri
    kom ut (22. juli: 8 sperret, 0 publisert). Idébanken skal bare stenge det som
    er ute eller på vei ut; resten kan gjenbrukes. Nyeste først."""
    root = socials_dir(vault)
    out: list[dict] = []
    for mpath in sorted(root.glob("*/manifest.json"), reverse=True):
        try:
            manifest = json.loads(mpath.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for d in manifest.get("drafts") or []:
            if not isinstance(d, dict):
                continue
            if d.get("status") not in ("published", "planlagt"):
                continue
            out.append({"format": d.get("format"), "headline": d.get("headline"),
                        "motif": (d.get("motif") or "")[:140],
                        "pillar": d.get("pillar", ""),
                        "status": d.get("status")})
            if len(out) >= n:
                return out
    return out


def pillar_coverage(vault: Path | None = None, pillar_ids: list[str] | None = None,
                    window: int = 24) -> dict[str, int]:
    """Tell hvor mange av de siste `window` utkastene som traff hver pilar (0-fylt for
    de oppgitte id-ene). Brukes til å vri hjernen mot de underdekte pilarene, så
    innholdet følger strategien over tid i stedet for å klumpe seg på én vinkel."""
    posts = load_state(vault).get("posts", [])[-window:]
    counts: dict[str, int] = {pid: 0 for pid in (pillar_ids or [])}
    for p in posts:
        pid = (p.get("pillar") or "").strip()
        if pid:
            counts[pid] = counts.get(pid, 0) + 1
    return counts


def read_lessons(vault: Path | None = None, max_chars: int = 2500) -> str:
    """eierens notater om hva som funker (respons/likes) i `_system/socials/lessons.md`.
    Frøet til «analysér responsen»: hjernen leser dette og eksperimenterer videre.
    Tomt hvis fila ikke finnes."""
    p = socials_dir(vault) / "lessons.md"
    if not p.exists():
        return ""
    try:
        return p.read_text(encoding="utf-8")[:max_chars].strip()
    except OSError:
        return ""


def _slug(text: str, maxlen: int = 60) -> str:
    keep = "".join(c if c.isalnum() or c in " -_" else " " for c in (text or ""))
    return "-".join(keep.split())[:maxlen].strip("-").lower() or "post"


def write_draft(vault: Path | None, brand_key: str, spec: dict, png: bytes,
                *, index: int, when: datetime | None = None) -> dict:
    """Skriv ett utkast (png + md). Returnerer metadata inkl. filstier."""
    when = when or datetime.now()
    day_dir = socials_dir(vault) / when.strftime("%Y-%m-%d")
    day_dir.mkdir(parents=True, exist_ok=True)

    stem = f"post-{index}-{brand_key}-{_slug(spec.get('headline', ''))}"
    png_path = day_dir / f"{stem}.png"
    md_path = day_dir / f"{stem}.md"
    png_path.write_bytes(png)

    headline = spec.get("headline", "").strip()
    body = spec.get("body", "").strip()          # LinkedIn-brødteksten (over bildet)
    why = spec.get("why_now", "").strip()
    fmt = spec.get("format", "typografi-kort")
    fm = {
        "type": "some-draft",
        "brand": brand_key,
        "format": fmt,
        "pillar": (spec.get("pillar") or "").strip(),
        "headline": headline,
        "generated": when.isoformat(timespec="seconds"),
        "image": png_path.name,
        "status": "utkast",
    }
    fm_yaml = "\n".join(f"{k}: {json.dumps(v, ensure_ascii=False)}" for k, v in fm.items())
    md = (
        f"---\n{fm_yaml}\n---\n\n"
        f"# {headline}\n\n"
        f"![[{png_path.name}]]\n\n"
        f"## LinkedIn-tekst\n\n{body or '(bilde-kort, ingen brødtekst)'}\n\n"
        f"## Hvorfor nå\n\n{why or '(ikke oppgitt)'}\n"
    )
    atomic_write_text(md_path, md)
    return {
        "brand": brand_key, "format": fmt, "headline": headline,
        "motif": (spec.get("motif") or "").strip(),
        "pillar": (spec.get("pillar") or "").strip(),
        "png_path": str(png_path), "md_path": str(md_path),
        "body": body, "why_now": why,
        "kilder": [k for k in (spec.get("kilder") or []) if isinstance(k, str)],
        "status": "proposed",  # → "published" når eieren publiserer den (godkjenn-hvert)
        # originalspec (uten brand) så dashbordet kan regenerere bildet etter redigering
        "spec": {k: v for k, v in spec.items() if k != "brand"},
    }


def write_carousel(vault: Path | None, brand_key: str, spec: dict, built: dict,
                   *, index: int, when: datetime | None = None) -> dict:
    """Skriv en karusell: PDF + slide-PNG-er + md. `built` = carousel.build_carousel(...).
    Returnerer metadata inkl. pdf-sti (og pdf/cover-bytes for e-posten)."""
    when = when or datetime.now()
    day_dir = socials_dir(vault) / when.strftime("%Y-%m-%d")
    day_dir.mkdir(parents=True, exist_ok=True)

    tittel = built.get("tittel", "Karusell").strip()
    stem = f"karusell-{index}-{brand_key}-{_slug(tittel)}"
    pdf_path = day_dir / f"{stem}.pdf"
    cover_path = day_dir / f"{stem}-forside.png"
    md_path = day_dir / f"{stem}.md"
    pdf_path.write_bytes(built["pdf"])
    cover_path.write_bytes(built["cover"])
    slides_dir = day_dir / stem
    slides_dir.mkdir(exist_ok=True)
    for i, png in enumerate(built.get("slide_pngs", []), 1):
        (slides_dir / f"slide-{i}.png").write_bytes(png)

    body = (spec.get("body") or "").strip()      # LinkedIn-teksten over dokumentet
    why = (spec.get("why_now") or "").strip()
    fm = {
        "type": "some-karusell", "brand": brand_key, "tittel": tittel,
        "slides": built.get("n"), "generated": when.isoformat(timespec="seconds"),
        "pdf": pdf_path.name, "status": "utkast",
    }
    fm_yaml = "\n".join(f"{k}: {json.dumps(v, ensure_ascii=False)}" for k, v in fm.items())
    md = (
        f"---\n{fm_yaml}\n---\n\n"
        f"# {tittel}\n\n"
        f"Karusell ({built.get('n')} slides) — last opp PDF-en `{pdf_path.name}` som "
        f"dokumentpost på LinkedIn.\n\n"
        f"![[{cover_path.name}]]\n\n"
        f"## LinkedIn-tekst\n\n{body or '(ingen brødtekst)'}\n\n"
        f"## Hvorfor nå\n\n{why or '(ikke oppgitt)'}\n"
    )
    atomic_write_text(md_path, md)
    return {
        "type": "karusell", "brand": brand_key, "format": "karusell",
        "pillar": (spec.get("pillar") or "").strip(),
        "headline": tittel, "tittel": tittel, "n": built.get("n"),
        "pdf_path": str(pdf_path), "cover_path": str(cover_path), "md_path": str(md_path),
        "pdf": built["pdf"], "cover": built["cover"], "size_mb": built.get("size_mb"),
        "body": body, "why_now": why,
        "kilder": [k for k in (spec.get("kilder") or []) if isinstance(k, str)],
        "status": "proposed",
        "spec": {k: v for k, v in spec.items() if k != "brand"},
    }


def record(vault: Path | None, drafts: list[dict], *, when: datetime | None = None) -> None:
    """Legg utkastene inn i dedup-state (trimmet til STATE_KEEP)."""
    when = when or datetime.now()
    socials_dir(vault)  # sørg for at _system/socials/ finnes (record kan kjøres frittstående)
    state = load_state(vault)
    for d in drafts:
        state["posts"].append({
            "brand": d.get("brand"), "format": d.get("format"),
            "headline": d.get("headline"), "motif": (d.get("motif") or "")[:140],
            "pillar": d.get("pillar", ""),
            "date": when.strftime("%Y-%m-%d"),
        })
    state["posts"] = state["posts"][-STATE_KEEP:]
    state["updated"] = when.isoformat(timespec="seconds")
    atomic_write_json(_state_path(_vault(vault)), state)


# ── LinkedIn-publisering: manifest-status (godkjenn-hvert) ──────────
# Publisering er menneske-gated: generatoren foreslår (status "proposed"),
# `cli.py publish` sender ÉN valgt post og setter "published" + linkedin_url.
# ETT manifest per dag, FELLES for alle merker: hvert utkast bærer sitt faste
# «publiser: N»-nummer i "nr" (aldri gjenbrukt samme dag), så et svar på en
# eldre epost aldri kan treffe et annet utkast enn det eieren faktisk så.
# ("n" er opptatt: slide-antall på karuseller.)


def merge_manifest(vault: Path | None, *, brand_key: str, brand_name: str,
                   new_drafts: list[dict], when: datetime | None = None) -> tuple[Path, dict]:
    """Slå nyrendrede utkast inn i dags-manifestet i stedet for å overskrive det,
    så to merker samme dag ikke visker ut hverandres utkast:
      - andre merkers utkast består urørt (samme nummer),
      - egne publiserte utkast består (publiseringslogg + engasjement-lesing),
      - egne uposterte utkast erstattes (re-render = nytt forslag),
      - nye utkast nummereres fra dagens teller ("seq"), som aldri teller ned.
    Muterer new_drafts (setter "nr") og returnerer (sti, manifest)."""
    when = when or datetime.now()
    day_dir = socials_dir(vault) / when.strftime("%Y-%m-%d")
    day_dir.mkdir(parents=True, exist_ok=True)
    path = day_dir / "manifest.json"

    old: dict = {}
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                old = data
        except (OSError, ValueError):
            pass  # ugyldig manifest: start dagen på nytt heller enn å stoppe render

    old_drafts = [d for d in (old.get("drafts") or []) if isinstance(d, dict)]
    seq = int(old.get("seq") or 0)
    for i, d in enumerate(old_drafts, 1):
        if not isinstance(d.get("nr"), int):
            d["nr"] = i  # eldre manifest uten nr: posisjonen VAR nummeret i eposten
        seq = max(seq, d["nr"])
    kept = [d for d in old_drafts
            if d.get("brand") != brand_key or d.get("status") == "published"]
    for d in new_drafts:
        seq += 1
        d["nr"] = seq

    manifest = {
        "brand": brand_key, "brand_name": brand_name,  # sist rendrede merke (styrer `send`)
        "generated": when.isoformat(timespec="seconds"),
        "seq": seq,
        "drafts": kept + list(new_drafts),
    }
    atomic_write_json(path, manifest)
    return path, manifest


def load_manifest(vault: Path | None = None,
                  date: str | None = None) -> tuple[Path | None, dict | None]:
    """Returner (sti, manifest) for en gitt dato (YYYY-MM-DD), ellers det NYESTE.
    (sti, None) hvis fila finnes men er ugyldig; (None, None) hvis ingen finnes."""
    root = socials_dir(vault)
    if date:
        p: Path | None = root / date / "manifest.json"
    else:
        cands = sorted(root.glob("*/manifest.json"),
                       key=lambda x: x.stat().st_mtime, reverse=True)
        p = cands[0] if cands else None
    if not p or not p.exists():
        return None, None
    try:
        return p, json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return p, None


def select_draft(manifest: dict, sel) -> tuple[int | None, dict | None]:
    """Finn ETT utkast: nummeret fra eposten (utkastets "nr"; posisjon i eldre
    manifester uten nr), eller en slug/headline-bit (case-insensitiv).
    (None, None) om ingen treff. Håndhever godkjenn-hvert (aldri hele batchen)."""
    drafts = manifest.get("drafts") or []
    s = str(sel or "").strip().lower()
    if not s:
        return None, None
    if s.isdigit():
        want = int(s)
        if any(isinstance(d.get("nr"), int) for d in drafts):
            # nummerert dags-manifest: et foreldet nummer skal bomme, aldri treffe naboen
            for i, d in enumerate(drafts):
                if d.get("nr") == want:
                    return i, d
            return None, None
        i = want - 1
        return (i, drafts[i]) if 0 <= i < len(drafts) else (None, None)
    for i, d in enumerate(drafts):
        hay = f"{d.get('headline', '')} {Path(d.get('png_path', '')).stem}".lower()
        if s in hay:
            return i, d
    return None, None


def mark_published(manifest_path: Path, manifest: dict, idx: int, url: str,
                   *, when: datetime | None = None) -> None:
    """Sett status=published + linkedin_url + published_at på utkast `idx`
    (listeposisjon, ikke "nr"), skriv manifestet tilbake (samme indent=2-form som
    render). Hindrer dobbeltposting."""
    drafts = manifest.get("drafts") or []
    if 0 <= idx < len(drafts):
        drafts[idx]["status"] = "published"
        drafts[idx]["linkedin_url"] = url
        # NÅR det gikk ut, ikke bare AT det gikk ut: dagsmappa sier når utkastet ble
        # LAGET, og et innlegg laget mandag kan gå ut fredag. Uten dette stemmer
        # ikke kalenderen med virkeligheten.
        drafts[idx]["published_at"] = (when or datetime.now()).isoformat(timespec="minutes")
        atomic_write_json(Path(manifest_path), manifest)


def mark_scheduled(manifest_path: Path, manifest: dict, idx: int,
                   scheduled_at: str, confirmed: str = "") -> None:
    """Sett status=planlagt + scheduled_at (ISO) på utkast `idx` etter at det er
    planlagt som native LinkedIn-innlegg. `confirmed` er LinkedIns egen bekreftede
    tidslinje (fasit), lagret for sporbarhet. Hindrer dobbel-planlegging."""
    drafts = manifest.get("drafts") or []
    if 0 <= idx < len(drafts):
        drafts[idx]["status"] = "planlagt"
        drafts[idx]["scheduled_at"] = scheduled_at
        if confirmed:
            drafts[idx]["scheduled_confirmed"] = confirmed
        atomic_write_json(Path(manifest_path), manifest)


def mark_unscheduled(manifest_path: Path, manifest: dict, idx: int) -> None:
    """Avlys en planlegging: tilbake til «proposed», og fjern tidspunktet så
    publisher-jobben ikke plukker den opp. Publiserte utkast røres aldri."""
    drafts = manifest.get("drafts") or []
    if not (0 <= idx < len(drafts)):
        return
    d = drafts[idx]
    if d.get("status") == "published":
        return
    d["status"] = "proposed"
    d.pop("scheduled_at", None)
    d.pop("scheduled_confirmed", None)
    atomic_write_json(Path(manifest_path), manifest)


def _draft_files(manifest_path: Path, draft: dict) -> list[Path]:
    """Filene som hører til ETT utkast: bilde, markdown, PDF, forside, slide-mappe."""
    dag = Path(manifest_path).parent
    ut: list[Path] = []
    for felt in ("png_path", "md_path", "pdf_path", "cover_path"):
        raw = (draft.get(felt) or "").strip()
        if raw:
            ut.append(Path(raw))
    stem = Path(draft.get("pdf_path") or draft.get("png_path") or "").stem
    if stem and (dag / stem).is_dir():
        ut.append(dag / stem)          # slide-mappa til en karusell
    return ut


def trash_draft(manifest_path: Path, manifest: dict, idx: int,
                *, when: datetime | None = None) -> dict:
    """Slett ett utkast: ut av manifestet, filene til papirkurven. Returnerer
    {slettet, headline, kurv} eller {slettet: False, grunn}.

    Filene FLYTTES, ikke fjernes: hvert bilde har kostet et bildekall, og en
    feilklikket sletting skal kunne angres ved å flytte mappa tilbake.
    Publiserte utkast røres aldri: de er dokumentasjon på hva som faktisk gikk ut."""
    drafts = manifest.get("drafts") or []
    if not (0 <= idx < len(drafts)):
        return {"slettet": False, "grunn": "fant ikke utkastet"}
    d = drafts[idx]
    if d.get("status") == "published":
        return {"slettet": False, "grunn": "publisert, røres ikke"}

    mpath = Path(manifest_path)
    stempel = (when or datetime.now()).strftime("%Y%m%dT%H%M%S")
    kurv = mpath.parent.parent / "_slettet" / f"{mpath.parent.name}-nr{d.get('nr', idx + 1)}-{stempel}"
    kurv.mkdir(parents=True, exist_ok=True)
    (kurv / "utkast.json").write_text(json.dumps(d, ensure_ascii=False, indent=2),
                                      encoding="utf-8")
    for p in _draft_files(mpath, d):
        try:
            if p.exists():
                shutil.move(str(p), str(kurv / p.name))
        except OSError:
            pass       # en fil som ikke lot seg flytte skal ikke blokkere slettingen

    drafts.pop(idx)
    atomic_write_json(mpath, manifest)
    return {"slettet": True, "headline": d.get("headline", ""), "kurv": str(kurv)}


def deletable_drafts(vault: Path | None = None) -> list[dict]:
    """Alt som KAN slettes (alt som ikke er publisert), nyeste dag først. Brukes til
    å vise eieren den eksakte lista FØR en masse-sletting, aldri til å slette blindt."""
    ut: list[dict] = []
    for mpath in sorted(socials_dir(vault).glob("*/manifest.json"), reverse=True):
        try:
            manifest = json.loads(mpath.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for i, d in enumerate(manifest.get("drafts") or []):
            if not isinstance(d, dict) or d.get("status") == "published":
                continue
            ut.append({"dag": mpath.parent.name, "idx": i, "nr": d.get("nr", i + 1),
                       "headline": d.get("headline", ""), "brand": d.get("brand", ""),
                       "status": d.get("status", "proposed")})
    return ut


_EDITABLE_FIELDS = ("headline", "body", "why_now", "tittel")


def update_draft_fields(manifest_path: Path, manifest: dict, idx: int,
                        fields: dict) -> dict | None:
    """Oppdater redigerbare felt på utkast `idx` (listeposisjon; dashbordet løser
    «nr» via select_draft) og skriv manifestet tilbake. Returnerer utkastet, None
    ved ugyldig idx. Speiler endringen best-effort inn i utkastets .md
    (manifestet er sannheten for e-post/publisering/dashbord)."""
    drafts = manifest.get("drafts") or []
    if not (0 <= idx < len(drafts)):
        return None
    d = drafts[idx]
    for k in _EDITABLE_FIELDS:
        v = fields.get(k)
        if isinstance(v, str):
            d[k] = v.strip()
    atomic_write_json(Path(manifest_path), manifest)
    _sync_draft_md(d)
    return d


def _sync_draft_md(draft: dict) -> None:
    """Skriv redigert headline/body/hvorfor-nå inn i utkastets .md (best-effort,
    aldri fatal: manifestet er kilden, .md er vault-visningen)."""
    md_path = draft.get("md_path")
    if not md_path:
        return
    p = Path(md_path)
    try:
        text = p.read_text(encoding="utf-8")
        lines = text.splitlines()
        for i, line in enumerate(lines):
            if line.startswith("# "):
                lines[i] = f"# {(draft.get('headline') or draft.get('tittel') or '').strip()}"
                break
        text = "\n".join(lines) + ("\n" if text.endswith("\n") else "")
        head, sep, tail = text.partition("## LinkedIn-tekst")
        if sep:
            parts = tail.split("## Hvorfor nå", 1)
            body = (draft.get("body") or "(ingen brødtekst)").strip()
            why_now = (draft.get("why_now") or "").strip()
            why_block = (f"## Hvorfor nå\n\n{why_now}\n" if why_now
                         else ("## Hvorfor nå" + parts[1] if len(parts) == 2 else ""))
            text = f"{head}## LinkedIn-tekst\n\n{body}\n\n{why_block}"
        p.write_text(text, encoding="utf-8")
    except OSError:
        pass
