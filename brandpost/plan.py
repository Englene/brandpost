"""plan — rullerende innholdsplan med rød tråd (ukesnarrativ + slots).

Modellen foreslår, koden eier kalenderen: hjernen lager ukesnarrativ (den røde
tråden) og tema per slot, mens deterministiske guardrails bestemmer HVILKE dager
som fylles (kun publiseringsdagene publiseringsdagene), én slot per dag, gyldige
pilar-id-er, og at slots som alt har utkast eller er publisert aldri røres.
Dashbordet viser planen; generatoren følger dagens slot, så innleggene bygger
en fortbrukeren over ukene i stedet for å være løsrevne enkeltidéer.

`_system/socials/plan.json`:
  {"generated", "horizon_days", "brand",
   "weeks": [{"iso_week": "2026-W29", "narrativ": "..."}],
   "slots": [{"date": "2026-07-13", "brand": "demo", "pillar": "pris-myte",
              "format": "bilde"|"karusell", "tema": "...",
              "status": "planlagt"|"utkast"|"publisert", "draft_ref": {...}}]}
"""

from __future__ import annotations

import json
import os
from datetime import date, datetime, timedelta
from pathlib import Path

from . import model as loop_model
from .fsutil import atomic_write_json
from . import brandkit, store
from .context import _engagement_summary, _latest_pulse
from .store import socials_dir

def _post_days() -> tuple[int, ...]:
    """Publiseringsdagene (date.weekday(): 0=mandag). Default man/tir/ons/tor.

    Research 22. juli 2026: 2-4 innlegg i uka er referansen for FIRMASIDER, og
    oftere kannibaliserer rekkevidden per innlegg (ett selskap som postet 3x
    sjeldnere fikk 2,2x flere kvalifiserte leads). Fredag er ute: svakest dag
    for B2B. Overstyr med BRANDPOST_POST_DAYS=0,1,2,3,4 for å prøve daglig."""
    raw = (os.environ.get("BRANDPOST_POST_DAYS") or "").strip()
    if raw:
        try:
            dager = tuple(sorted({int(x) for x in raw.split(",") if x.strip()}))
            if dager and all(0 <= d <= 6 for d in dager):
                return dager
        except ValueError:
            pass
    return (0, 1, 2, 3)


POST_DAYS = _post_days()  # man/tir/ons/tor; ÉN kilde, morning_run importerer denne
DEFAULT_HORIZON = 21      # dager framover planen fyller


def plan_path(vault: Path | None = None) -> Path:
    return socials_dir(vault) / "plan.json"


def load_plan(vault: Path | None = None) -> dict:
    p = plan_path(vault)
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _post_dates(start: date, horizon_days: int) -> list[date]:
    """Publiseringsdagene (publiseringsdagene) fra og med `start`, innen horisonten."""
    return [start + timedelta(days=i) for i in range(horizon_days)
            if (start + timedelta(days=i)).weekday() in POST_DAYS]


def _iso_week(d: date) -> str:
    y, w, _ = d.isocalendar()
    return f"{y}-W{w:02d}"


# ── generering (én structured_call, guardrails i kode) ─────

_PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "weeks": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "iso_week": {"type": "string"},
                    "narrativ": {"type": "string"},
                },
                "required": ["iso_week", "narrativ"],
            },
        },
        "slots": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "date": {"type": "string"},
                    "pillar": {"type": "string"},
                    "format": {"type": "string", "enum": ["bilde", "karusell"]},
                    "tema": {"type": "string"},
                },
                "required": ["date", "tema"],
            },
        },
    },
    "required": ["weeks", "slots"],
}

_PLAN_SYSTEM = """Du er innholdssjef for {name} og legger en rullerende LinkedIn-plan.
Du får strategien, pilarene med dekning, ferske puls-vinkler fra teamets hverdag,
engasjement på tidligere innlegg, og datoene som SKAL fylles.

Lever:
- weeks: ETT ukesnarrativ per ISO-uke i horisonten: den røde tråden, ett overordnet
  tema uka bygger mot. Narrativene skal henge sammen fra uke til uke (en fortbrukeren
  som utvikler seg, ikke tilfeldige hopp).
- slots: ETT forslag per oppgitt dato. `tema` er én konkret setning om hva innlegget
  skal si (ikke ferdig tekst), `pillar` er en pilar-id fra listen, `format` er
  'karusell' maks én gang per uke (når temaet bærer flere punkter), ellers 'bilde'.

Regler:
- Bruk KUN datoene i listen, aldri andre.
- Prioriter underdekte pilarer, men la narrativet styre rekkefølgen.
- Slots som alt er fylt (vist som låst) er kontekst: bygg videre på dem, ikke gjenta.
- Konfidensialitet: aldri kundenavn, interne tall eller upublisert prising i temaene."""


def _guard_slots(raw_slots: list, *, to_fill: list[date], brand) -> list[dict]:
    """Snap modell-forslagene mot kalenderen: kun tillatte datoer, én per dato,
    gyldig pilar, karusell maks én per uke. Datoer modellen hoppet over fylles
    med en åpen slot på den mest underdekte pilaren."""
    valid = {d.isoformat(): d for d in to_fill}
    pillars = set(brandkit.pillar_ids(brand))
    by_date: dict[str, dict] = {}
    car_weeks: set[str] = set()
    for s in raw_slots or []:
        if not isinstance(s, dict):
            continue
        ds = str(s.get("date") or "").strip()
        if ds not in valid or ds in by_date:
            continue
        pid = str(s.get("pillar") or "").strip().lower()
        fmt = s.get("format") if s.get("format") in ("bilde", "karusell") else "bilde"
        week = _iso_week(valid[ds])
        if fmt == "karusell":
            if week in car_weeks:
                fmt = "bilde"
            else:
                car_weeks.add(week)
        by_date[ds] = {
            "date": ds, "brand": brand.key,
            "pillar": pid if pid in pillars else "",
            # Saner temaet som alt annet: det mater hjernen, så tankestrek her
            # smitter over i publisert tekst (11 av 13 slots hadde det 22. juli).
            "format": fmt, "tema": store.clean_text(str(s.get("tema") or "")),
            "status": "planlagt",
        }
    for ds in valid:  # tomme datoer får en åpen slot (dashbordet viser dem som ledige)
        if ds not in by_date:
            by_date[ds] = {"date": ds, "brand": brand.key, "pillar": "",
                           "format": "bilde", "tema": "", "status": "planlagt"}
    return [by_date[ds] for ds in sorted(by_date)]


def refresh_plan(vault: Path | None = None, *, brand_key: str = "demo",
                 horizon_days: int = DEFAULT_HORIZON, when: date | None = None) -> dict:
    """Rull planen: behold slots med utkast/publisert (og fortiden), fyll resten av
    horisonten på nytt med modellens forslag bak guardrails. Skriver plan.json."""
    today = when or date.today()
    brand = brandkit.load_brand(brand_key)
    existing = load_plan(vault)
    old_slots = [s for s in existing.get("slots", []) if isinstance(s, dict) and s.get("date")]

    kept = [s for s in old_slots
            if s.get("status") in ("utkast", "publisert") or s["date"] < today.isoformat()]
    # Bevarte slots beholder tema og status, men saneres for tankestrek: de ble
    # skrevet før saneringen fantes, og temaet mates fortsatt til hjernen. Ellers
    # ville de gamle slotsene bære regelbruddet videre i det uendelige.
    for s in kept:
        if isinstance(s.get("tema"), str):
            s["tema"] = store.clean_text(s["tema"])
    kept_dates = {s["date"] for s in kept}
    to_fill = [d for d in _post_dates(today, horizon_days)
               if d.isoformat() not in kept_dates]

    coverage = store.pillar_coverage(vault, brandkit.pillar_ids(brand))
    pillar_lines = "\n".join(
        f"- {p.id} ({p.label}): brukt {coverage.get(p.id, 0)}x. {p.desc}"
        for p in brand.pillars) or "(ingen pilarer definert)"
    v = store._vault(vault)
    user = (
        f"DATOER SOM SKAL FYLLES (én slot per dato):\n"
        + "\n".join(d.isoformat() + f" ({_iso_week(d)})" for d in to_fill)
        + "\n\nPILARER MED DEKNING:\n" + pillar_lines
        + "\n\nSTRATEGI:\n" + (brand.strategi or "(ingen)")[:2500]
        + "\n\nFERSK PULS (anonymiserte vinkler fra teamets hverdag):\n"
        + json.dumps(_latest_pulse(v), ensure_ascii=False)
        + "\n\nENGASJEMENT (hva som funket):\n"
        + json.dumps(_engagement_summary(v), ensure_ascii=False)
        + "\n\nLÅSTE SLOTS (alt fylt, kun kontekst):\n"
        + json.dumps([{k: s.get(k) for k in ("date", "pillar", "tema", "status")}
                      for s in kept], ensure_ascii=False)
        + ("\n\nFORRIGE UKESNARRATIV (bygg videre):\n"
           + json.dumps(existing.get("weeks", []), ensure_ascii=False)
           if existing.get("weeks") else "")
        + "\n\nLag ukesnarrativ + slots nå.")

    weeks: list[dict] = []
    new_slots: list[dict] = []
    if to_fill:
        env = loop_model.structured_call(
            _PLAN_SYSTEM.format(name=brand.name), user, _PLAN_SCHEMA, label="some-plan")
        out = env.get("structured_output") or {}
        new_slots = _guard_slots(out.get("slots"), to_fill=to_fill, brand=brand)
        valid_weeks = {_iso_week(d) for d in _post_dates(today, horizon_days)}
        seen_w: set[str] = set()
        for w in out.get("weeks") or []:
            iw = str(w.get("iso_week") or "").strip()
            if iw in valid_weeks and iw not in seen_w and w.get("narrativ"):
                seen_w.add(iw)
                weeks.append({"iso_week": iw, "narrativ": str(w["narrativ"]).strip()})
        for w in existing.get("weeks", []):  # behold gamle uker som fortsatt er relevante
            if isinstance(w, dict) and w.get("iso_week") in valid_weeks \
                    and w["iso_week"] not in seen_w:
                weeks.append(w)
        weeks.sort(key=lambda w: w["iso_week"])

    payload = {
        "generated": datetime.now().isoformat(timespec="seconds"),
        "horizon_days": horizon_days, "brand": brand_key,
        "weeks": weeks or existing.get("weeks", []),
        "slots": sorted([*kept, *new_slots], key=lambda s: s["date"]),
    }
    atomic_write_json(plan_path(vault), payload)
    payload["_path"] = str(plan_path(vault))
    return payload


# ── oppslag + status ───────────────────────────────────────

def open_slots(vault: Path | None = None, *, brand_key: str | None = None,
               days: int = 7, when: date | None = None) -> list[dict]:
    """Slots med status planlagt fra og med i dag, innen `days` dager: det
    generatoren skal fylle (én per publiseringsdag, dagens inkludert)."""
    start = (when or date.today()).isoformat()
    end = ((when or date.today()) + timedelta(days=days)).isoformat()
    out = [s for s in load_plan(vault).get("slots", [])
           if s.get("status") == "planlagt" and start <= s.get("date", "") <= end
           and (brand_key is None or s.get("brand") == brand_key)]
    return sorted(out, key=lambda s: s["date"])


def today_slot(vault: Path | None = None, *, brand_key: str | None = None,
               when: date | None = None) -> dict | None:
    """Dagens slot (for generatoren), None når dagen ikke har noen."""
    ds = (when or date.today()).isoformat()
    for s in load_plan(vault).get("slots", []):
        if s.get("date") == ds and (brand_key is None or s.get("brand") == brand_key):
            return s
    return None


def reconcile_slots(vault: Path | None = None) -> list[str]:
    """Åpne slots som PÅSTÅR at de har et utkast, men der utkastet er borte.

    En slot merkes «utkast» når generatoren har fylt den. Slettes utkastet etterpå,
    blir slotten stående og lyver: dagen ser fylt ut, generatoren hopper over den,
    og dagen forblir tom uten at noe feiler. Kjøres etter sletting og rydding.
    Returnerer datoene som ble frigjort. Publiserte slots røres aldri."""
    from . import store            # sen import: store importerer ikke plan
    plan = load_plan(vault)
    frigjort: list[str] = []
    for s in plan.get("slots", []):
        if s.get("status") != "utkast":
            continue
        ref = s.get("draft_ref") or {}
        dag, nr = str(ref.get("manifest") or ""), ref.get("nr")
        finnes = False
        if dag:
            _, manifest = store.load_manifest(vault, dag)
            if manifest:
                idx, _ = store.select_draft(manifest, str(nr))
                finnes = idx is not None
        if not finnes:
            s["status"] = "planlagt"      # «planlagt» = åpen slot, klar for nytt utkast
            s.pop("draft_ref", None)
            frigjort.append(s.get("date", ""))
    if frigjort:
        atomic_write_json(plan_path(vault), plan)
    return frigjort


def mark_slot(vault: Path | None, date_iso: str, status: str,
              *, draft_ref: dict | None = None) -> bool:
    """Sett status (planlagt/utkast/publisert) + evt. draft_ref på slotten for datoen."""
    plan = load_plan(vault)
    hit = False
    for s in plan.get("slots", []):
        if s.get("date") == date_iso:
            s["status"] = status
            if draft_ref is not None:
                s["draft_ref"] = draft_ref
            hit = True
    if hit:
        atomic_write_json(plan_path(vault), plan)
    return hit
