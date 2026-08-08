"""app — SoMe-kommandosenteret: kalender, plan, og utkast-kort med godkjenning.

En FastAPI-router montert under /some. Den leser og skriver de samme filene som
motoren (dags-manifester, plan.json, engagement.json) og gjenbruker store, plan og
linkedin direkte: dashbordet er et skall rundt motoren, ikke en ny sannhetskilde.

Alt er menneske-gated. Ingenting publiseres uten et klikk, og API-publiseringen
respekterer LINKEDIN_ENABLED, som står av til du bevisst skrur den på.
"""

from __future__ import annotations

import calendar as calmod
import json
import re
import subprocess
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).parent.parent
if str(ROOT) not in sys.path:  # speiler server.py: gjør brandpost importerbar
    sys.path.insert(0, str(ROOT))

import os  # noqa: E402

# Web-tjenesten (launchd) starter uten repoets .env i miljøet, så env-gatede
# handlinger som LinkedIn-planlegging (BRANDPOST_BROWSER_ENABLED/PAGE_URL) ikke ville
# se flaggene. Last .env her; overstyrer ALDRI variabler som alt er satt, og
# planlegg-subprosessen arver miljøet.
try:
    from brandpost import paths as _paths  # noqa: E402
    _paths.load_env()
except Exception:  # noqa: BLE001
    pass

from fastapi import APIRouter, Depends, Form, HTTPException, Request  # noqa: E402
from fastapi.responses import FileResponse, HTMLResponse  # noqa: E402
from fastapi.templating import Jinja2Templates  # noqa: E402

from brandpost import brandkit, linkedin, paths  # noqa: E402
from brandpost import carousel as carouselmod  # noqa: E402
from brandpost import plan as planmod  # noqa: E402
from brandpost import publisher as pubmod  # noqa: E402
from brandpost import render as rendermod  # noqa: E402
from brandpost import revise as revisemod  # noqa: E402
from brandpost import store  # noqa: E402
from brandpost.context import _engagement_summary, _latest_pulse  # noqa: E402

WEB_DIR = Path(__file__).parent


def _origin(value: str) -> tuple[str, str]:
    parsed = urlsplit(value)
    return parsed.scheme.lower(), parsed.netloc.lower()


async def _same_origin_mutation(request: Request) -> None:
    """Nekt alle POST-er som ikke beviselig kommer fra dette dashbordet.

    ``Origin`` er nettleserens CSRF-signal. Den kreves også når klienten ikke er
    en nettleser; eksplisitte integrasjoner kan enkelt sende sin lokale origin,
    mens et ondsinnet nettsted aldri kan forfalske headeren fra en nettleser.
    """
    if request.method != "POST":
        return
    supplied = (request.headers.get("origin") or "").strip()
    expected = _origin(str(request.base_url))
    if not supplied or _origin(supplied) != expected:
        raise HTTPException(status_code=403, detail="POST krever samme Origin som dashbordet")


router = APIRouter(prefix="/some", dependencies=[Depends(_same_origin_mutation)])
templates = Jinja2Templates(directory=str(WEB_DIR / "templates"))

_NO_MONTHS = ("januar", "februar", "mars", "april", "mai", "juni", "juli",
              "august", "september", "oktober", "november", "desember")

# Foreslått publiseringstidspunkt i «Aksepter og planlegg» (valget 22. juli:
# kl. 10:00). Må være et kvarter, siden LinkedIns tidsvelger bare tilbyr de.
_DEFAULT_POST_TIME = "10:00"


def _suggest_time() -> str:
    t = (os.environ.get("BRANDPOST_POST_TIME") or _DEFAULT_POST_TIME).strip()
    return t if re.fullmatch(r"\d{2}:(00|15|30|45)", t) else _DEFAULT_POST_TIME


def vault_path() -> Path:
    return paths.workspace()


def _err(msg: str) -> HTMLResponse:
    """Feil som htmx kan vise i target uten å rive siden."""
    return HTMLResponse(f"<div class='text-red-400 text-sm p-2'>⚠️ {msg}</div>")


# ───────────────────────────────────────────────────────────
# Datainnsamling til kalender + kort
# ───────────────────────────────────────────────────────────

ALLE_MERKER = "alle"


def merke_valg(brand: str | None) -> str:
    """Normaliser merke-parameteren. Ukjent merke faller til «alle» i stedet for å
    vise en tom side: et skrivefeil i URL-en skal ikke se ut som at alt er borte."""
    key = (brand or "").strip().lower()
    return key if key in brandkit.available_brands() else ALLE_MERKER


def merker_ctx(valgt: str) -> dict:
    """Nedtrekket oppe til høyre: hvert selskap med egen merkevareprofil. Dvalende
    merker er med (de skal kunne åpnes og fylles), men merkes, så det er tydelig
    hvorfor de er tomme."""
    aktive = set(brandkit.enabled_brands())
    valg = [{"key": ALLE_MERKER, "navn": "Alle selskaper", "dvale": False}]
    for k in brandkit.available_brands():
        try:
            navn = brandkit.load_brand(k).name or k
        except Exception:  # noqa: BLE001
            navn = k
        valg.append({"key": k, "navn": navn, "dvale": k not in aktive})
    return {"valgt": valgt, "valg": valg,
            "navn": next((m["navn"] for m in valg if m["key"] == valgt), "Alle selskaper")}


def _matcher_merke(draft: dict, valgt: str) -> bool:
    return valgt == ALLE_MERKER or (draft.get("brand") or "") == valgt


def visningsdag(draft: dict, kildedag: str) -> str:
    """Hvilken dato utkastet skal VISES på i kalenderen.

    Tre lag, i denne rekkefølgen: er det publisert, hører det hjemme på dagen det
    faktisk gikk ut; er det planlagt, på dagen det skal ut; ellers på dagen det ble
    laget. Dagsmappa sier bare når utkastet ble LAGET, og et innlegg laget mandag
    kan gå ut fredag. Én funksjon, fordi kalendercellene og dagspanelet må være
    enige om dette: to kopier av regelen ville før eller siden sprikt."""
    if draft.get("status") == "published":
        naar = (draft.get("published_at") or "")[:10]
        if naar:
            return naar
    return (draft.get("scheduled_at") or "")[:10] or kildedag


def _thumb_url(day: str, draft: dict) -> str:
    """Miniatyr-URL for kalendercella. Karusell viser forsiden."""
    p = (draft.get("cover_path") if draft.get("type") == "karusell"
         else draft.get("png_path"))
    return f"/some/media/{day}/{Path(p).name}" if p else ""


def _manifest_drafts_by_day(v: Path, year: int, month: int,
                            merke: str = ALLE_MERKER) -> dict[str, list[dict]]:
    """Kompakte utkast-rader per dato i måneden (til kalendercellene).

    Et PLANLAGT utkast vises på dagen det skal PUBLISERES, ikke dagen det ble
    laget. Det er dét dra-og-slipp endrer: tidspunktet, ikke hvor filen bor
    (filflytting mellom dagsmapper ville vært skjørt og unødvendig)."""
    out: dict[str, list[dict]] = {}
    root = store.socials_dir(v)
    pre = f"{year:04d}-{month:02d}"
    # Les ALLE dager, ikke bare månedens: et utkast laget i forrige måned kan
    # være planlagt inn i denne.
    for mp in sorted(root.glob("*/manifest.json")):
        kildedag = mp.parent.name
        try:
            manifest = json.loads(mp.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for pos, d in enumerate(manifest.get("drafts") or [], 1):
            if not isinstance(d, dict) or not _matcher_merke(d, merke):
                continue
            # Kalenderen viser KUN det som faktisk skal ut, altså planlagt eller
            # publisert (Oscar 31. juli). Uvurderte forslag hører hjemme i bunken;
            # lå de i kalenderen også, druknet de fire innleggene som er ekte
            # avtaler i tjue som bare er forslag.
            if d.get("status") not in ("planlagt", "published"):
                continue
            vises = visningsdag(d, kildedag)
            if not vises.startswith(pre):
                continue
            out.setdefault(vises, []).append({
                "nr": d.get("nr") if isinstance(d.get("nr"), int) else pos,
                "headline": d.get("headline") or d.get("tittel", ""),
                "status": d.get("status", "proposed"), "format": d.get("format", ""),
                "brand": d.get("brand", ""),
                "thumb": _thumb_url(kildedag, d),
                "kildedag": kildedag,          # dra-og-slipp trenger å vite hvor den bor
                "tid": ((d.get("published_at") if d.get("status") == "published"
                         else d.get("scheduled_at")) or "")[11:16],
            })
    return out


def _events_by_day(days_ahead: int = 45) -> dict[str, list[dict]]:
    """Møter og frister i kalendercellene. Utvidelsesflate: koble på din egen
    kalender ved å returnere {"YYYY-MM-DD": [{"tid": "09:00", "hva": "..."}]}."""
    return {}


def calendar_ctx(v: Path, year: int, month: int, merke: str = ALLE_MERKER) -> dict:
    """Månedsgrid som merger plan-slots, manifest-utkast og kalenderhendelser."""
    plan = planmod.load_plan(v)
    slots = {s["date"]: s for s in plan.get("slots", [])
             if isinstance(s, dict) and s.get("date")}
    drafts = _manifest_drafts_by_day(v, year, month, merke)
    events = _events_by_day()
    today = date.today().isoformat()
    weeks = []
    for wk in calmod.Calendar().monthdatescalendar(year, month):
        row = []
        for d in wk:
            ds = d.isoformat()
            row.append({"date": ds, "day": d.day, "in_month": d.month == month,
                        "is_today": ds == today,
                        "is_postday": d.weekday() in planmod.POST_DAYS,
                        "slot": slots.get(ds), "drafts": drafts.get(ds, []),
                        "events": events.get(ds, [])})
        weeks.append(row)
    prev_y, prev_m = (year - 1, 12) if month == 1 else (year, month - 1)
    next_y, next_m = (year + 1, 1) if month == 12 else (year, month + 1)
    return {"year": year, "month": month, "weeks": weeks, "merke": merke,
            "label": f"{_NO_MONTHS[month - 1]} {year}",
            "prev": f"{prev_y:04d}-{prev_m:02d}", "next": f"{next_y:04d}-{next_m:02d}"}


def _card_ctx(v: Path, day: str, draft: dict) -> dict:
    """Template-kontekst for ett utkast-kort. Stiene i manifestet er absolutte og
    MASKIN-spesifikke (Mini-manifester bærer /Users/brukeren/…), så alt utledes
    lokalt fra vault + dato + filNAVN. Karuseller får alle slide-PNG-ene som
    scrollbar stripe, ikke bare forsiden."""
    day_dir = store.socials_dir(v) / day
    is_karusell = draft.get("type") == "karusell"

    def _media(name_or_path: str | Path | None, sub: str = "") -> str:
        if not name_or_path:
            return ""
        name = Path(name_or_path).name
        local = (day_dir / sub / name) if sub else (day_dir / name)
        try:
            bust = int(local.stat().st_mtime)
        except OSError:
            bust = 0
        rel = f"{sub}/{name}" if sub else name
        return f"/some/media/{day}/{rel}?v={bust}"

    img = draft.get("cover_path") if is_karusell else draft.get("png_path")
    slides: list[str] = []
    if is_karusell and draft.get("pdf_path"):
        stem = Path(draft["pdf_path"]).stem
        sdir = day_dir / stem
        if sdir.is_dir():
            files = sorted(sdir.glob("slide-*.png"),
                           key=lambda q: int(q.stem.split("-")[-1]))
            slides = [_media(q.name, sub=stem) for q in files]

    # Foreslått planleggings-tidspunkt: slot-datoen kl. 10:00 (valget 22. juli),
    # på datetime-local-form for input-feltet. Redigerbart i kortet.
    # Er den alt planlagt, skal feltet vise det VALGTE tidspunktet, ikke forslaget,
    # så «endre» starter fra der du er.
    suggest_dt = (draft.get("scheduled_at") or "")[:16] or f"{day}T{_suggest_time()}"
    # Alt som ikke alt er publisert kan planlegges, KARUSELL INKLUDERT: den ble
    # utelatt da LinkedIn eide utsendelsen og nettleser-composeren ikke kunne lage
    # dokumentinnlegg. Nå publiserer vi selv, og publish_draft har hatt PDF-veien
    # (publish_document_post) hele tiden. Et PLANLAGT utkast skal fortsatt kunne
    # endres: uten det satt tidspunktet fast så snart man hadde trykket én gang.
    can_schedule = bool(img) and draft.get("status") != "published"
    er_planlagt = draft.get("status") == "planlagt"
    return {"d": draft, "day": day, "media": _media(img), "slides": slides,
            "pdf": _media(draft.get("pdf_path")),
            "is_karusell": is_karusell,
            "kilder": [k for k in (draft.get("kilder") or []) if isinstance(k, str)],
            "linkedin_enabled": linkedin.load_linkedin_config().enabled,
            "rettelser": [str(c) for c in ((draft.get("spec") or {}).get("corrections") or [])
                          if str(c).strip()][-rendermod.MAX_CORRECTIONS:],
            "suggest_dt": suggest_dt, "can_schedule": can_schedule,
            "er_planlagt": er_planlagt,
            # Planlegging er alltid mulig (det er bare et skriv). Det som kan
            # være av, er selve API-publiseringen som skjer til avtalt tid.
            "schedule_enabled": linkedin.load_linkedin_config().enabled}


def _drafts_for_display_day(v: Path, day: str,
                            merke: str = ALLE_MERKER) -> list[tuple[str, dict]]:
    """(kildedag, utkast) for alt som skal VISES på `day`: enten planlagt dit,
    eller laget den dagen uten planlegging. Kildedagen følger med fordi den er
    utkastets identitet (kort-endepunktene slår opp på dag + nr), mens visnings-
    dagen bare er presentasjon."""
    ut: list[tuple[str, dict]] = []
    for mp in sorted(store.socials_dir(v).glob("*/manifest.json")):
        kildedag = mp.parent.name
        try:
            manifest = json.loads(mp.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for pos, d in enumerate(manifest.get("drafts") or [], 1):
            if not isinstance(d, dict) or not _matcher_merke(d, merke):
                continue
            if visningsdag(d, kildedag) != day:
                continue
            if not isinstance(d.get("nr"), int):
                d = {**d, "nr": pos}
            ut.append((kildedag, d))
    return ut


def day_ctx(v: Path, day: str, merke: str = ALLE_MERKER) -> dict:
    """Dagspanelet: alt som vises på datoen + evt. plan-slot. Eldre manifester uten
    "nr" får posisjonen som nummer, samme tolkning som select_draft bruker."""
    plan = planmod.load_plan(v)
    slot = next((s for s in plan.get("slots", []) if s.get("date") == day), None)
    cards = [_card_ctx(v, kildedag, d)
             for kildedag, d in _drafts_for_display_day(v, day, merke)]
    return {"day": day, "slot": slot, "cards": cards, "merke": merke}


def _resolve(v: Path, day: str, nr: int):
    """(mpath, manifest, idx, draft) for utkast «nr» i dags-manifestet, ellers 404."""
    mpath, manifest = store.load_manifest(v, day)
    if not manifest:
        raise HTTPException(404, f"ingen manifest for {day}")
    idx, draft = store.select_draft(manifest, str(nr))
    if draft is None:
        raise HTTPException(404, f"utkast nr {nr} finnes ikke for {day}")
    return mpath, manifest, idx, draft


# ───────────────────────────────────────────────────────────
# Sider + partials
# ───────────────────────────────────────────────────────────

@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
def some_home(request: Request, month: str | None = None, day: str | None = None,
              brand: str | None = None):
    v = vault_path()
    today = date.today()
    try:
        y, m = (int(month[:4]), int(month[5:7])) if month else (today.year, today.month)
    except ValueError:
        y, m = today.year, today.month
    plan = planmod.load_plan(v)
    merke = merke_valg(brand)
    return templates.TemplateResponse(request, "some/index.html", {
        "cal": calendar_ctx(v, y, m, merke),
        "daypanel": day_ctx(v, day or today.isoformat(), merke),
        "pulse": _latest_pulse(v),
        "engagement": _engagement_summary(v),
        "plan": plan,
        "today": today.isoformat(),
        "merker": merker_ctx(merke),
    })


@router.get("/api/calendar", response_class=HTMLResponse)
def api_calendar(request: Request, month: str, brand: str | None = None):
    v = vault_path()
    try:
        y, m = int(month[:4]), int(month[5:7])
    except (ValueError, IndexError):
        raise HTTPException(400, "month må være YYYY-MM")
    return templates.TemplateResponse(request, "some/calendar.html",
                                      {"cal": calendar_ctx(v, y, m, merke_valg(brand))})


@router.get("/api/drafts", response_class=HTMLResponse)
def api_drafts(request: Request, day: str, brand: str | None = None):
    return templates.TemplateResponse(
        request, "some/drafts_day.html",
        {"daypanel": day_ctx(vault_path(), day, merke_valg(brand))})


@router.get("/api/plan", response_class=HTMLResponse)
def api_plan(request: Request):
    return templates.TemplateResponse(request, "some/plan.html",
                                      {"plan": planmod.load_plan(vault_path())})


@router.get("/api/pulse", response_class=HTMLResponse)
def api_pulse(request: Request):
    v = vault_path()
    return templates.TemplateResponse(request, "some/pulse.html",
                                      {"pulse": _latest_pulse(v),
                                       "engagement": _engagement_summary(v)})


# ───────────────────────────────────────────────────────────
# Handlinger på ett utkast (alle menneske-utløst fra dashbordet)
# ───────────────────────────────────────────────────────────

def _card_response(request: Request, day: str, draft: dict, note: str = ""):
    ctx = _card_ctx(vault_path(), day, draft)
    ctx["note"] = note
    return templates.TemplateResponse(request, "some/draft_card.html", {"c": ctx})


@router.post("/api/draft/{day}/{nr}", response_class=HTMLResponse)
def api_edit_draft(request: Request, day: str, nr: int,
                   headline: str = Form(""), body: str = Form(""),
                   why_now: str = Form("")):
    v = vault_path()
    mpath, manifest, idx, draft = _resolve(v, day, nr)
    fields = {"headline": headline, "body": body, "why_now": why_now}
    if draft.get("type") == "karusell":
        fields["tittel"] = headline
    updated = store.update_draft_fields(mpath, manifest, idx, fields)
    return _card_response(request, day, updated, note="Lagret.")


@router.post("/api/draft/{day}/{nr}/published", response_class=HTMLResponse)
def api_mark_published(request: Request, day: str, nr: int, url: str = Form(...)):
    v = vault_path()
    u = url.strip()
    if not u.startswith("https://www.linkedin.com/"):
        return _err("Limen inn hele LinkedIn-URL-en (https://www.linkedin.com/…).")
    mpath, manifest, idx, draft = _resolve(v, day, nr)
    store.mark_published(mpath, manifest, idx, u)
    planmod.mark_slot(v, day, "publisert", draft_ref={"manifest": day, "nr": nr})
    return _card_response(request, day, draft, note="Markert publisert.")


@router.post("/api/draft/{day}/{nr}/schedule", response_class=HTMLResponse)
def api_schedule(request: Request, day: str, nr: int, when: str = Form(...)):
    """«Aksepter og planlegg»: planlegg utkastet som native LinkedIn-planlagt
    innlegg til `when` (datetime-local «YYYY-MM-DDTHH:MM»). Kjøres på maskinen som
    hoster dashbordet (Mini-en: der bor både vault og LinkedIn-innloggingen).
    Skriver status=planlagt i manifestet ved suksess; leser LinkedIns fasit-linje
    i planleggeren og avbryter hvis dato/tid ikke stemmer."""
    v = vault_path()
    mpath, manifest, idx, draft = _resolve(v, day, nr)
    when = (when or "").strip()[:16]
    try:
        naar = datetime.strptime(when, "%Y-%m-%dT%H:%M")
    except ValueError:
        return _err("Ugyldig tidspunkt; velg dato og tid på nytt.")
    if naar < datetime.now():
        return _err(f"{naar:%d.%m.%Y kl. %H:%M} er tilbake i tid. Publisher nekter "
                    f"å legge ut noe som er mer enn noen timer på etterskudd, så "
                    f"innlegget ville bare blitt liggende.")
    # valget 22. juli: VI eier publiseringen. Knappen lagrer bare tidspunktet;
    # publisher-jobben legger ut via API akkurat da og sender e-post i samme
    # øyeblikk. Derfor er dette et lynkjapt skriv, ikke en nettleser-kjøring som
    # holder forespørselen åpen i minutter (det sultet trådene og hang dashbordet).
    store.mark_scheduled(mpath, manifest, idx, when)
    _, _, _, draft2 = _resolve(v, day, nr)
    planmod.mark_slot(v, day, "planlagt", draft_ref={"manifest": day, "nr": nr})
    naar = f"{when[8:10]}.{when[5:7]} kl. {when[11:16]}"
    return _card_response(request, day, draft2,
                          note=f"Planlagt {naar}. Publiseres automatisk, "
                               f"og du får e-post i samme øyeblikk.")


@router.post("/api/draft/{day}/{nr}/move", response_class=HTMLResponse)
def api_move(request: Request, day: str, nr: int, to: str = Form(...),
             brand: str | None = None):
    """Dra-og-slipp i kalenderen: flytt utkastet til en annen DAG ved å endre
    tidspunktet. Filene blir liggende i sin egen dagsmappe (å flytte dem mellom
    mapper og renummerere ville vært skjørt og gir ingen gevinst). Beholder
    klokkeslettet hvis det alt var planlagt, ellers brukes forslaget."""
    v = vault_path()
    mpath, manifest, idx, draft = _resolve(v, day, nr)
    try:
        datetime.strptime(to, "%Y-%m-%d")
    except ValueError:
        return _err("Ugyldig dato.")
    if draft.get("status") == "published":
        return _err("Publiserte innlegg kan ikke flyttes.")
    klokke = (draft.get("scheduled_at") or "")[11:16] or _suggest_time()
    store.mark_scheduled(mpath, manifest, idx, f"{to}T{klokke}")
    planmod.mark_slot(v, to, "planlagt", draft_ref={"manifest": day, "nr": nr})
    return templates.TemplateResponse(
        request, "some/calendar.html",
        {"cal": calendar_ctx(v, int(to[:4]), int(to[5:7]), merke_valg(brand)),
         "flash": f"Flyttet til {to[8:10]}.{to[5:7]} kl. {klokke}"})


@router.post("/api/draft/{day}/{nr}/unschedule", response_class=HTMLResponse)
def api_unschedule(request: Request, day: str, nr: int):
    """Avlys en planlegging: tilbake til utkast, ingenting publiseres.
    Uten denne satt tidspunktet fast så snart man hadde trykket én gang."""
    v = vault_path()
    mpath, manifest, idx, draft = _resolve(v, day, nr)
    if draft.get("status") == "published":
        return _err("Innlegget er alt publisert og kan ikke avlyses herfra.")
    if draft.get("status") != "planlagt":
        return _card_response(request, day, draft, note="Var ikke planlagt.")
    store.mark_unscheduled(mpath, manifest, idx)
    _, _, _, draft2 = _resolve(v, day, nr)
    planmod.mark_slot(v, day, "utkast", draft_ref={"manifest": day, "nr": nr})
    return _card_response(request, day, draft2,
                          note="Planleggingen er avlyst. Innlegget publiseres ikke.")


@router.post("/api/draft/{day}/{nr}/regen", response_class=HTMLResponse)
def api_regen_image(request: Request, day: str, nr: int, note: str = Form("")):
    """Regenerer bildet. `note` er eierens rettelse («ser ut som en penis», «feil
    grønnfarge»), som lagres på utkastet og følger med i prompten HVER gang etterpå:
    et problem han har påpekt én gang skal ikke komme tilbake i neste forsøk."""
    v = vault_path()
    mpath, manifest, idx, draft = _resolve(v, day, nr)
    spec = dict(draft.get("spec") or {})
    if not spec:  # eldre utkast uten lagret spec: regenerer fra kortets felter
        spec = {"format": draft.get("format", "typografi-kort"),
                "motif": draft.get("motif", "")}
    spec["headline"] = draft.get("headline", spec.get("headline", ""))

    retter = [str(c) for c in (spec.get("corrections") or []) if str(c).strip()]
    ny = (note or "").strip()
    if ny and ny not in retter:
        retter.append(ny)
    spec["corrections"] = retter

    if draft.get("type") == "karusell":
        return _regen_karusell(request, day, mpath, manifest, idx, draft, spec, retter)

    try:
        brand = brandkit.load_brand(draft.get("brand") or "demo")
        result = rendermod.render_post(spec, brand=brand)
        Path(draft["png_path"]).write_bytes(result["png"])
        draft["how"] = result.get("how", draft.get("how", ""))
        draft["alt_text"] = (result.get("alt_text") or draft.get("alt_text")
                             or draft.get("headline", ""))
        draft["spec"] = spec          # rettelsene skal overleve til neste forsøk
        store.update_draft_fields(mpath, manifest, idx, {})  # persist how + mtime-bust
        hale = f" Rettelser med: {len(retter)}." if retter else ""
        return _card_response(request, day, draft,
                              note=f"Nytt bilde ({result.get('how', '')}).{hale}")
    except Exception as e:
        return _err(f"Regenerering feilet: {e}")


def _regen_karusell(request: Request, day: str, mpath, manifest, idx: int,
                    draft: dict, spec: dict, retter: list[str]):
    """Regenerer en karusell: modellen skriver slidene på nytt, så bygges de om over
    de EKSISTERENDE filene. Ett tekstkall, og ett bildekall bare hvis forsiden har
    motiv, altså billigere enn å regenerere et vanlig bilde."""
    try:
        brand = brandkit.load_brand(draft.get("brand") or "demo")
        ny_tekst = carouselmod.omskriv_slides(draft, brand, rettelser=retter)
    except Exception as e:  # noqa: BLE001
        return _err(f"Fikk ikke skrevet om slidene: {e}")
    if not ny_tekst.get("slides"):
        return _err("Modellen svarte uten slides; ingenting er endret.")

    spec["slides"] = ny_tekst["slides"]
    tittel = ny_tekst.get("tittel") or draft.get("tittel") or draft.get("headline", "")
    oppdatert = {**draft, "spec": spec, "tittel": tittel}
    try:
        res = carouselmod.rebuild_carousel(oppdatert, brand=brand)
    except Exception as e:  # noqa: BLE001
        return _err(f"Ombygging feilet: {e}")

    draft["spec"] = spec
    draft["tittel"] = tittel
    draft["headline"] = tittel
    draft["n"] = res["n"]
    store.update_draft_fields(mpath, manifest, idx, {"tittel": tittel, "headline": tittel})
    hale = f" Ryddet {len(res['ryddet'])} gamle slides." if res["ryddet"] else ""
    return _card_response(request, day, draft,
                          note=f"Skrev om {res['n']} slides og bygde karusellen på nytt."
                               f"{hale}")


@router.post("/api/draft/{day}/{nr}/delete", response_class=HTMLResponse)
def api_delete_draft(request: Request, day: str, nr: int):
    """Slett ett utkast. Filene flyttes til papirkurven, ikke bort: se store.trash_draft."""
    v = vault_path()
    mpath, manifest, idx, draft = _resolve(v, day, nr)
    res = store.trash_draft(mpath, manifest, idx)
    if not res.get("slettet"):
        return _err(f"Ikke slettet: {res.get('grunn', 'ukjent')}")
    planmod.reconcile_slots(v)      # dagen skal bli ledig igjen, ikke se fylt ut
    return HTMLResponse(
        f"<div class='text-xs text-paper/50 border border-ink-700 rounded-xl p-3'>"
        f"🗑 Slettet «{res.get('headline', '')[:60]}». Filene ligger i papirkurven "
        f"(_system/socials/_slettet/), så det kan angres.</div>")


@router.post("/api/draft/{day}/{nr}/publish", response_class=HTMLResponse)
def api_publish(request: Request, day: str, nr: int):
    v = vault_path()
    mpath, manifest, idx, draft = _resolve(v, day, nr)
    if draft.get("status") == "published":
        return _card_response(request, day, draft, note="Allerede publisert.")
    try:
        # Samme vei som den planlagte utsendelsen: publiser, marker, VARSLE. Kalte vi
        # linkedin.publish_draft direkte her, gikk innlegget ut uten e-post (feilen
        # eieren fant 23. juli).
        res = pubmod.publiser_ett(mpath, manifest, idx, draft, vault=v)
    except Exception as e:
        return _err(f"Publisering feilet: {e}")
    if res.get("posted"):
        planmod.mark_slot(v, day, "publisert", draft_ref={"manifest": day, "nr": nr})
        return _card_response(
            request, day, draft,
            note=f"Publisert på firmasida. E-post: {res.get('epost', '?')} · "
                 f"Slack: {res.get('slack', '?')}.")
    if res.get("dry_run") and "preview" in res:
        return _card_response(request, day, draft,
                              note="Dry-run (LINKEDIN_ENABLED=0): ingenting postet.")
    return _err(f"Ikke publisert: {res.get('reason', 'ukjent feil')}")


# ───────────────────────────────────────────────────────────
# Motor-kjøringer fra dashbordet (subprocess mot CLI-en)
# ───────────────────────────────────────────────────────────

def _run_cli(*args: str, timeout: int = 420) -> tuple[bool, str]:
    cmd = [sys.executable, "-m", "brandpost.cli", *args]
    try:
        r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return False, f"tidsavbrudd etter {timeout}s"
    tail = (r.stdout or r.stderr or "").strip().splitlines()
    return r.returncode == 0, (tail[-1] if tail else f"exit {r.returncode}")


@router.post("/api/pulse/refresh", response_class=HTMLResponse)
def api_pulse_refresh(request: Request):
    ok, msg = _run_cli("pulse")
    v = vault_path()
    return templates.TemplateResponse(request, "some/pulse.html",
                                      {"pulse": _latest_pulse(v),
                                       "engagement": _engagement_summary(v),
                                       "note": msg if ok else f"⚠️ {msg}"})


@router.post("/api/plan/refresh", response_class=HTMLResponse)
def api_plan_refresh(request: Request):
    ok, msg = _run_cli("plan", "--refresh")
    return templates.TemplateResponse(request, "some/plan.html",
                                      {"plan": planmod.load_plan(vault_path()),
                                       "note": msg if ok else f"⚠️ {msg}"})


# ───────────────────────────────────────────────────────────
# Rydd bordet: slett alt upublisert, generer på nytt
# ───────────────────────────────────────────────────────────

def _slettbare(merke: str) -> list[dict]:
    rader = store.deletable_drafts(vault_path())
    return [r for r in rader if merke == ALLE_MERKER or r["brand"] == merke]


@router.get("/api/purge/preview", response_class=HTMLResponse)
def api_purge_preview(request: Request, brand: str | None = None):
    """Vis den EKSAKTE lista over hva som ville blitt slettet, før noe skjer.
    Masse-sletting uten liste er ikke lov: eieren skal se hva han sier ja til."""
    merke = merke_valg(brand)
    return templates.TemplateResponse(request, "some/purge.html",
                                      {"rader": _slettbare(merke), "merke": merke,
                                       "merkenavn": merker_ctx(merke)["navn"]})


@router.post("/api/purge", response_class=HTMLResponse)
def api_purge(request: Request, brand: str | None = None, antall: int = Form(...)):
    """Slett alt upublisert (for valgt selskap). `antall` er tallet eieren SÅ i lista;
    stemmer det ikke lenger, har noe endret seg siden han leste den, og vi avbryter
    heller enn å slette noe han aldri fikk se."""
    merke = merke_valg(brand)
    rader = _slettbare(merke)
    if antall != len(rader):
        return _err(f"Lista har endret seg ({antall} → {len(rader)}). "
                    f"Åpne den på nytt og se over før du sletter.")
    v = vault_path()
    slettet, nektet = 0, 0
    # Bakerst først: hver sletting flytter indeksene etter seg i samme manifest.
    for r in sorted(rader, key=lambda x: (x["dag"], x["idx"]), reverse=True):
        mpath, manifest = store.load_manifest(v, r["dag"])
        if not manifest:
            continue
        res = store.trash_draft(mpath, manifest, r["idx"])
        slettet += 1 if res.get("slettet") else 0
        nektet += 0 if res.get("slettet") else 1
    frigjort = planmod.reconcile_slots(v)
    hale = f", {nektet} rørt ikke" if nektet else ""
    hale += f". {len(frigjort)} dager er ledige igjen" if frigjort else ""
    return HTMLResponse(
        f"<div class='text-sm text-paper/70 p-2'>🗑 Slettet {slettet} utkast{hale}. "
        f"Filene ligger i _system/socials/_slettet/ og kan hentes tilbake. "
        f"<button hx-post='/some/api/generate?brand={merke}' hx-target='#ryddeboks' "
        f"class='ml-2 px-2 py-1 rounded bg-green-700 hover:bg-green-600 text-xs'>"
        f"Generer nye nå</button></div>")


@router.post("/api/generate", response_class=HTMLResponse)
def api_generate(request: Request, brand: str | None = None):
    """Start en ny generering. Kjøres i BAKGRUNNEN: en full kjøring tar minutter, og
    ville ellers holdt en av web-tjenestens tråder opptatt så lenge (det var dét som
    hang dashbordet 22. juli)."""
    merke = merke_valg(brand)
    key = "demo" if merke == ALLE_MERKER else merke
    logg = paths.state_dir() / "logs" / "some-generering.log"
    try:
        logg.parent.mkdir(parents=True, exist_ok=True)
        f = open(logg, "a", encoding="utf-8")     # noqa: SIM115 (eies av subprosessen)
        subprocess.Popen([sys.executable, "-m", "brandpost.cli",
                          "run", "--brand", key],
                         cwd=ROOT, stdout=f, stderr=subprocess.STDOUT, start_new_session=True)
    except Exception as e:  # noqa: BLE001
        return _err(f"Fikk ikke startet generering: {e}")
    return HTMLResponse(
        f"<div class='text-sm text-paper/70 p-2'>▶️ Generering startet for {key}. "
        f"Den tar noen minutter og bruker bildekall. Last siden på nytt etterpå. "
        f"Logg: {logg}</div>")


# ───────────────────────────────────────────────────────────
# Bunken: ett forslag om gangen, ja eller nei
# ───────────────────────────────────────────────────────────
# Kalenderen viser utkast der de tilfeldigvis havnet. Bunken gir deg dem én av
# gangen. Et ja krever en dato med det samme, for et innlegg uten dato er en
# intensjon og ikke en plan, og det er datoen som setter emnet i karantene.

def _bunke_ctx(v: Path, brand: str | None) -> dict:
    merke = merke_valg(brand)
    # ALLE_MERKER betyr «ikke filtrer», så det skal ikke sendes som brand_key.
    kort = store.unjudged_drafts(v, brand_key="" if merke == ALLE_MERKER else merke)
    igjen = len(kort)
    d = kort[0] if kort else None
    ctx: dict = {"igjen": igjen, "brand": merke, "d": None}
    if d:
        # Utkastet sendes flatt, IKKE gjennom _card_ctx: den pakker utkastet inne i
        # sin egen «d»-nøkkel til draft_card.html, og bunken trenger uansett ikke
        # media-URL-ene, siden bildet ikke er laget ennå.
        ctx["d"] = d
        ctx["kilder"] = [k for k in (d.get("kilder") or []) if isinstance(k, str)]
        mk = "" if merke == ALLE_MERKER else merke
        ctx["suggest_dt"] = f"{_neste_postdag(v, mk)}T{_suggest_time()}"
        ctx["ledige"] = _ledige_tider(v, brand_key=mk)
        # Media-URL utledes lokalt fra filNAVN: stiene i manifestet er absolutte
        # og maskinspesifikke, så et utkast generert på en annen maskin ville
        # pekt på en sti som ikke finnes her.
        ctx["media"] = _bunke_media(v, d)
        ctx["slides"] = _bunke_slides(v, d)
    return ctx


def _bunke_media(v: Path, d: dict) -> str:
    """Bilde-URL for et bunke-kort, tom streng hvis bildekallet feilet."""
    navn = d.get("cover_path") if d.get("type") == "karusell" else d.get("png_path")
    if not navn:
        return ""
    day = d.get("day", "")
    fil = (store.socials_dir(v) / day / Path(navn).name)
    if not fil.is_file():
        return ""
    return f"/some/media/{day}/{Path(navn).name}?v={int(fil.stat().st_mtime)}"


def _bunke_slides(v: Path, d: dict) -> list[str]:
    """Alle slides i en karusell, i rekkefølge.

    En karusell kan ikke vurderes på forsiden alene: poenget bygges opp over
    slidene, og en svak side tre er en grunn til å si nei. Kalenderkortet har vist
    hele stripa hele tiden; bunken viste bare forsiden."""
    if d.get("type") != "karusell" or not d.get("pdf_path"):
        return []
    day = d.get("day", "")
    stem = Path(d["pdf_path"]).stem
    sdir = store.socials_dir(v) / day / stem
    if not sdir.is_dir():
        return []
    filer = sorted(sdir.glob("slide-*.png"),
                   key=lambda q: int(q.stem.split("-")[-1]))
    return [f"/some/media/{day}/{stem}/{q.name}?v={int(q.stat().st_mtime)}"
            for q in filer]


_NO_DAYS = ("mandag", "tirsdag", "onsdag", "torsdag", "fredag", "lørdag", "søndag")


def _opptatte_dager(v: Path, brand_key: str = "") -> dict[str, str]:
    """Dato → overskriften som alt ligger der (planlagt eller publisert).

    Avgrenses til ett merke. To selskaper har hver sin firmaside og hver sine
    følgere, så at Tilskudd.ai poster mandag er ingen grunn til at Vitandi ikke
    kan. Uten dette blokkerte det ene merket alle datoer for det andre."""
    ut: dict[str, str] = {}
    for mpath in store.socials_dir(v).glob("*/manifest.json"):
        try:
            manifest = json.loads(mpath.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for d in manifest.get("drafts") or []:
            if not isinstance(d, dict):
                continue
            if brand_key and d.get("brand") != brand_key:
                continue
            naar = d.get("published_at") or d.get("scheduled_at")
            if naar:
                ut[str(naar)[:10]] = (d.get("headline") or "")[:40]
    return ut


def _ledige_tider(v: Path, antall: int = 12, brand_key: str = "") -> list[dict]:
    """Kommende publiseringsdager som valg, med opptatte tydelig merket.

    Et fritt datofelt lot eieren legge to innlegg på samme dag uten å merke det
    før etterpå. Her ser han hele bildet mens han velger: hvilke dager som er
    ledige, og hva som allerede ligger på de som ikke er det."""
    opptatt = _opptatte_dager(v, brand_key)
    tid = _suggest_time()
    ut: list[dict] = []
    ledige = 0
    dag = date.today() + timedelta(days=1)
    # Vi teller LEDIGE dager, ikke dager totalt. Er de neste ukene fylt opp, må
    # lista strekke seg lenger fram; ellers står eieren med et nedtrekk der alt er
    # grått og ingen vei videre. Det skjedde 2. august: elleve valg, alle opptatt.
    for _ in range(400):
        if ledige >= antall:
            break
        if dag.weekday() in planmod.POST_DAYS:
            iso = dag.isoformat()
            er_opptatt = iso in opptatt
            ut.append({
                "verdi": f"{iso}T{tid}",
                "tekst": f"{_NO_DAYS[dag.weekday()]} {dag.day}. {_NO_MONTHS[dag.month - 1]}",
                "opptatt": er_opptatt,
                "hva": opptatt.get(iso, ""),
            })
            if not er_opptatt:
                ledige += 1
        dag += timedelta(days=1)
    return ut


def _neste_postdag(v: Path, brand_key: str = "") -> str:
    """Første ledige publiseringsdag fram i tid, som forvalg i velgeren."""
    for t in _ledige_tider(v, brand_key=brand_key):
        if not t["opptatt"]:
            return t["verdi"][:10]
    return (date.today() + timedelta(days=1)).isoformat()


# Bunken skal aldri stoppe. Tallene er satt etter hvor lang tid et påfyll faktisk
# tar: modellkallet dominerer og en runde på ti bruker fem til ti minutter, mens
# eieren swiper gjennom ti forslag på langt mindre. En terskel på fem var derfor
# for lav, og bunken gikk tom midt i økta.
#
# Nå bestilles påfyll allerede ved femten igjen, og opptil to runder kan lages
# samtidig. Da fylles det raskere enn det tømmes, og han kan planlegge langt fram
# i én økt uten å vente.
BUNKE_MIN = int(os.environ.get("BRANDPOST_BUNKE_MIN", "15"))
# FEM og ikke ti per runde: ti utkast med full kontekst sprengte modell-timeouten
# to ganger (opus-5 brukte over 600 s og falt til sonnet, som også falt). Mindre
# batcher kommer raskere fram, feiler sjeldnere, og to samtidige gir uansett ti.
BUNKE_PAAFYLL = int(os.environ.get("BRANDPOST_BUNKE_PAAFYLL", "5"))
BUNKE_SAMTIDIGE = int(os.environ.get("BRANDPOST_BUNKE_SAMTIDIGE", "2"))
# En lås eldre enn dette er en krasjet kjøring, ikke en pågående.
BUNKE_LAAS_MAKS_S = 20 * 60


def _etterfyll_bunke(brand: str) -> bool:
    """Bestill nye forslag i bakgrunnen. Returnerer True hvis en kjøring ble startet.

    Kjøres detached (start_new_session) fordi den tar minutter: holdt vi
    forespørselen åpen, ville swipen fryse midt i økta. En lås hindrer at to
    påfyll kjører samtidig og lager tjue forslag i stedet for ti.

    NB: dette virker bare når web-tjenesten kjører som launchd-agent i
    gui-domenet. Modellkallet trenger Keychain, og over ren ssh feiler det med
    401 uansett hvor riktig PATH-en er (se «modellfri over ssh» i
    meetingnotes/looper/DEPLOY.md). Skal du teste påfyllet manuelt, gjør det
    gjennom dashbordet, ikke fra en ssh-økt."""
    merke = brand if brand and brand != ALLE_MERKER else (brandkit.enabled_brands() or ["demo"])[0]
    laasdir = paths.state_dir() / "bunke-paafyll"
    laasdir.mkdir(parents=True, exist_ok=True)

    # Rydd døde låser først: en krasjet kjøring skal ikke okkupere en plass for
    # alltid. Deretter: er det ledig kapasitet?
    aktive = 0
    for f in laasdir.glob("*.lock"):
        try:
            if time.time() - f.stat().st_mtime > BUNKE_LAAS_MAKS_S:
                f.unlink(missing_ok=True)
            else:
                aktive += 1
        except OSError:
            pass
    if aktive >= BUNKE_SAMTIDIGE:
        return False

    logg = paths.state_dir() / "logs" / "some-bunke.log"
    logg.parent.mkdir(parents=True, exist_ok=True)
    with open(logg, "ab") as f:
        f.write(f"\n--- påfyll {datetime.now():%F %T} merke={merke} "
                f"({aktive + 1}/{BUNKE_SAMTIDIGE} samtidige) ---\n".encode())
        p = subprocess.Popen(
            [sys.executable, "-m", "brandpost.cli", "run",
             "--brand", merke, "--bunke", str(BUNKE_PAAFYLL)],
            stdout=f, stderr=subprocess.STDOUT, start_new_session=True,
            cwd=str(Path.cwd()),
        )
    # Låsen bærer pid-en, så cli-en kan slippe nøyaktig sin egen og ikke en annen
    # kjørings. En binær lås gjorde at to runder aldri kunne gå samtidig, og da
    # tømtes bunken raskere enn den fyltes.
    (laasdir / f"{p.pid}.lock").touch()
    return True


def _paafyll_kjorer() -> bool:
    """Er det et påfyll i gang akkurat nå?

    Brukes til å skille «bunken er ferdig» fra «bunken venter på flere». De to
    ser like ut for eieren, men betyr helt ulike ting."""
    laasdir = paths.state_dir() / "bunke-paafyll"
    if not laasdir.is_dir():
        return False
    for f in laasdir.glob("*.lock"):
        try:
            if time.time() - f.stat().st_mtime <= BUNKE_LAAS_MAKS_S:
                return True
        except OSError:
            pass
    return False


def _samtidige_for(brand: str) -> int:
    """Hvor mange påfyll som kan gå samtidig for dette merket.

    Person-merker får ÉN. To runder som starter samtidig ser ikke hverandres
    resultater, for dedup leser manifestet og begge leste det før noen skrev.
    For et firma går det stort sett bra: fagfeltet er bredt nok til at to runder
    finner ulike vinkler.

    For et menneske gjør det ikke det. Kilden er én persons uke, og 3. august ga
    to samtidige runder to par nesten identiske innlegg av ti: samme historie om
    å slutte å regenerere teksten, og samme historie om steg null i veiledningen.
    Halve bunken var duplikater.
    """
    try:
        if brandkit.load_brand(brand).voice_mode == "person":
            return 1
    except (ValueError, KeyError, OSError):
        pass
    return BUNKE_SAMTIDIGE


def _kanskje_etterfyll(igjen: int, brand: str) -> int:
    """Bestill så mange runder som trengs, og returner hvor mange som startet.

    Én runde av gangen holdt ikke da bunken var nesten tom: eieren swiper fortere
    enn modellen skriver, og han skal kunne planlegge langt fram i én økt uten å
    møte en tom skjerm."""
    if igjen > BUNKE_MIN:
        return 0
    mangler = max(1, -(-(BUNKE_MIN + BUNKE_PAAFYLL - igjen) // BUNKE_PAAFYLL))
    startet = 0
    for _ in range(min(mangler, _samtidige_for(brand))):
        if not _etterfyll_bunke(brand):
            break                      # ingen ledig kapasitet
        startet += 1
    return startet


def _tavle_ctx(v: Path, brand: str | None) -> dict:
    """Kanban over det som faktisk skal ut: publisert, denne uka, senere.

    Kalenderen viser en måned av gangen og krever at du leser rutenettet.
    Tavla svarer på det ene spørsmålet «hva ligger til publisering, og når»
    uten at du må lete."""
    merke = merke_valg(brand)
    idag = date.today()
    uke_slutt = idag + timedelta(days=(6 - idag.weekday()))
    # «forfalt» er en egen kolonne, ikke en variant av «ute». Et planlagt innlegg
    # med passert tidspunkt er IKKE publisert, det er strandet: publisher nekter
    # alt som er mer enn noen timer på etterskudd. Blandet inn i «ute» så det ut
    # som om det hadde gått fint, og en feil dato kunne ligge upåaktet.
    kolonner: dict[str, list[dict]] = {"forfalt": [], "denne_uka": [],
                                       "senere": [], "ute": []}

    for mpath in sorted(store.socials_dir(v).glob("*/manifest.json")):
        kildedag = mpath.parent.name
        try:
            manifest = json.loads(mpath.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for pos, d in enumerate(manifest.get("drafts") or [], 1):
            if not isinstance(d, dict) or not _matcher_merke(d, merke):
                continue
            if d.get("status") not in ("planlagt", "published"):
                continue
            naar = str(d.get("published_at") or d.get("scheduled_at") or "")
            if not naar:
                continue
            dagen = naar[:10]
            rad = {
                "dato": dagen, "tid": naar[11:16],
                "headline": d.get("headline") or d.get("tittel", ""),
                "status": d.get("status"), "brand": d.get("brand", ""),
                "emne": d.get("emne", ""),
                "thumb": _thumb_url(kildedag, d),
                "nr": d.get("nr") if isinstance(d.get("nr"), int) else pos,
                "kildedag": kildedag,
                "url": d.get("linkedin_url", ""),
            }
            try:
                dd = datetime.strptime(dagen, "%Y-%m-%d").date()
            except ValueError:
                continue
            rad["ukedag"] = _NO_DAYS[dd.weekday()]
            rad["vises"] = f"{dd.day}. {_NO_MONTHS[dd.month - 1]}"
            if d.get("status") == "published":
                kolonner["ute"].append(rad)
            elif naar < datetime.now().isoformat(timespec="minutes"):
                rad["dager_siden"] = (idag - dd).days
                kolonner["forfalt"].append(rad)
            elif dd <= uke_slutt:
                kolonner["denne_uka"].append(rad)
            else:
                kolonner["senere"].append(rad)

    kolonner["ute"].sort(key=lambda r: r["dato"], reverse=True)   # nyeste først
    kolonner["forfalt"].sort(key=lambda r: r["dato"])
    kolonner["denne_uka"].sort(key=lambda r: (r["dato"], r["tid"]))
    kolonner["senere"].sort(key=lambda r: (r["dato"], r["tid"]))
    kolonner["ute"] = kolonner["ute"][:12]        # historikken er ikke poenget
    mk = "" if merke == ALLE_MERKER else merke
    return {"kolonner": kolonner, "brand": merke,
            "tomme_dager": [t for t in _ledige_tider(v, brand_key=mk)
                            if not t["opptatt"]][:6]}


@router.get("/tavle", response_class=HTMLResponse)
def tavle(request: Request, brand: str | None = None):
    ctx = _tavle_ctx(vault_path(), brand)
    ctx["merker"] = merker_ctx(ctx["brand"])
    return templates.TemplateResponse(request, "some/tavle.html", ctx)


@router.get("/bunke", response_class=HTMLResponse)
def bunke(request: Request, brand: str | None = None):
    ctx = _bunke_ctx(vault_path(), brand)
    ctx["merker"] = merker_ctx(ctx["brand"])
    # GET skal være read-only. En fremmed nettside kan navigere nettleseren til
    # localhost, så et sidebesøk må aldri starte betalte modellkall. Tom bunke
    # får en eksplisitt POST-knapp, beskyttet av Origin-kontrollen.
    ctx["fyller"] = _paafyll_kjorer()
    return templates.TemplateResponse(request, "some/bunke.html", ctx)


@router.get("/api/bunke/neste", response_class=HTMLResponse)
def api_bunke_neste(request: Request, brand: str | None = None):
    """Read-only polling mens et eksplisitt bestilt påfyll kjører."""
    ctx = _bunke_ctx(vault_path(), brand)
    ctx["fyller"] = _paafyll_kjorer()
    return templates.TemplateResponse(request, "some/bunke_kort.html", ctx)


@router.post("/api/bunke/fyll", response_class=HTMLResponse)
def api_bunke_fyll(request: Request, brand: str | None = None):
    """«Generer nå» for tom bunke; eksplisitt menneskehandling, aldri GET-sideeffekt."""
    ctx = _bunke_ctx(vault_path(), brand)
    n = _kanskje_etterfyll(ctx["igjen"], ctx["brand"])
    if n:
        ctx["flash"] = f"Henter {n * BUNKE_PAAFYLL} nye forslag i bakgrunnen."
    ctx["fyller"] = bool(n) or _paafyll_kjorer()
    return templates.TemplateResponse(request, "some/bunke_kort.html", ctx)


@router.post("/api/bunke/{day}/{nr}/pass", response_class=HTMLResponse)
def api_bunke_pass(request: Request, day: str, nr: int, brand: str | None = None):
    """Nei: lagre dommen og gå videre. Emnet får kort karantene, ikke evig sperre."""
    v = vault_path()
    mpath, manifest, idx, _ = _resolve(v, day, nr)
    store.mark_verdict(mpath, manifest, idx, "passed")
    ctx = _bunke_ctx(v, brand)
    n = _kanskje_etterfyll(ctx["igjen"], ctx["brand"])
    if n:
        ctx["flash"] = f"Henter {n * BUNKE_PAAFYLL} nye forslag i bakgrunnen."
    ctx["fyller"] = bool(n) or _paafyll_kjorer()
    return templates.TemplateResponse(request, "some/bunke_kort.html", ctx)


@router.post("/api/bunke/{day}/{nr}/rediger", response_class=HTMLResponse)
def api_bunke_rediger(request: Request, day: str, nr: int,
                      headline: str = Form(""), body: str = Form(""),
                      brand: str | None = None):
    """Rett teksten selv, uten modellkall.

    De fleste innvendingene er små: en setning for mye, et ord som skurrer. Å be
    modellen skrive om alt for det er både tregt og risikabelt, siden den gjerne
    endrer mer enn du ba om. Her endrer du nøyaktig det du vil.

    Bildet røres ikke: teksten kan være rettet uten at motivet er feil. Trenger du
    nytt bilde, ligger knappen ved siden av."""
    v = vault_path()
    mpath, manifest, idx, draft = _resolve(v, day, nr)
    if not (body or "").strip():
        return _err("Teksten kan ikke være tom.")

    felter = {"body": store.clean_text(body)}
    if (headline or "").strip():
        felter["headline"] = store.clean_text(headline)
    # Spec-en er kilden når bildet senere regenereres, så den må følge teksten.
    spec = dict(draft.get("spec") or {})
    spec.update({k: v2 for k, v2 in felter.items()})
    felter["spec"] = spec
    oppdatert = store.update_draft_fields(mpath, manifest, idx, felter)

    ctx = _bunke_ctx(v, brand)
    ctx["d"] = oppdatert
    ctx["d"]["day"] = day
    ctx["kilder"] = [k for k in (oppdatert.get("kilder") or []) if isinstance(k, str)]
    ctx["media"] = _bunke_media(v, {**oppdatert, "day": day})
    ctx["slides"] = _bunke_slides(v, {**oppdatert, "day": day})
    ctx["flash"] = "Lagret."
    return templates.TemplateResponse(request, "some/bunke_kort.html", ctx)


@router.post("/api/bunke/{day}/{nr}/nytt-bilde", response_class=HTMLResponse)
def api_bunke_nytt_bilde(request: Request, day: str, nr: int,
                         brand: str | None = None):
    """Bare nytt bilde, samme tekst. For når teksten sitter men motivet bommer."""
    v = vault_path()
    mpath, manifest, idx, draft = _resolve(v, day, nr)
    if draft.get("type") == "karusell":
        return _err("Karuseller bygges om fra kalenderen, ikke herfra.")
    try:
        merke = brandkit.load_brand(draft.get("brand") or "demo")
        spec = dict(draft.get("spec") or {})
        spec.setdefault("headline", draft.get("headline", ""))
        result = rendermod.render_post(spec, brand=merke)
        store.attach_image(mpath, manifest, idx, result["png"],
                           alt_text=result.get("alt_text", ""))
    except Exception as e:  # noqa: BLE001
        return _err(f"Bildet feilet: {e}")

    _, _, _, ferdig = _resolve(v, day, nr)
    ctx = _bunke_ctx(v, brand)
    ctx["d"] = ferdig
    ctx["d"]["day"] = day
    ctx["kilder"] = [k for k in (ferdig.get("kilder") or []) if isinstance(k, str)]
    ctx["media"] = _bunke_media(v, {**ferdig, "day": day})
    ctx["flash"] = "Nytt bilde."
    return templates.TemplateResponse(request, "some/bunke_kort.html", ctx)


@router.post("/api/bunke/{day}/{nr}/rett", response_class=HTMLResponse)
def api_bunke_rett(request: Request, day: str, nr: int, note: str = Form(...),
                   brand: str | None = None):
    """Si hva som er galt, og få både tekst og bilde på nytt.

    Dashbordets vanlige regen lager nytt bilde fra samme tekst. Denne finnes for
    når det er INNHOLDET som er feil: et tall som ikke stemmer med kilden, en
    påstand som er for sterk, en vinkel som bommer. Både tekst og bilde lages på
    nytt, for et nytt poeng fortjener sjelden det gamle motivet.

    Tar tid (ett modellkall pluss ett bildekall, rundt 30-40 sekunder) og kjøres
    derfor synkront med spinner: eieren står og venter på nettopp dette svaret,
    i motsetning til påfyllet som skal skje i bakgrunnen."""
    v = vault_path()
    mpath, manifest, idx, draft = _resolve(v, day, nr)
    if not (note or "").strip():
        return _err("Skriv hva som er galt, så retter den det.")

    try:
        res = revisemod.revise_draft(draft, note, brand_key=draft.get("brand", ""))
    except Exception as e:  # noqa: BLE001
        return _err(f"Rettingen feilet: {e}")

    oppdatert = store.update_draft_fields(mpath, manifest, idx, res["felter"])

    # Nytt bilde: teksten er endret, og et nytt poeng fortjener sjelden det gamle
    # motivet. Feiler bildekallet, står teksten likevel rettet.
    bilde_note = ""
    if oppdatert.get("type") != "karusell":
        try:
            merke = brandkit.load_brand(oppdatert.get("brand") or "demo")
            result = rendermod.render_post(dict(oppdatert.get("spec") or {}), brand=merke)
            store.attach_image(mpath, manifest, idx, result["png"],
                               alt_text=result.get("alt_text", ""))
        except Exception as e:  # noqa: BLE001
            bilde_note = f" Teksten er rettet, men bildet feilet: {e}"

    _, _, _, ferdig = _resolve(v, day, nr)
    ctx = _bunke_ctx(v, brand)
    ctx["d"] = ferdig
    ctx["d"]["day"] = day
    ctx["kilder"] = [k for k in (ferdig.get("kilder") or []) if isinstance(k, str)]
    ctx["media"] = _bunke_media(v, {**ferdig, "day": day})
    ctx["slides"] = _bunke_slides(v, {**ferdig, "day": day})
    ctx["flash"] = (res["endret"] or "Rettet.") + bilde_note
    return templates.TemplateResponse(request, "some/bunke_kort.html", ctx)


@router.post("/api/bunke/{day}/{nr}/like", response_class=HTMLResponse)
def api_bunke_like(request: Request, day: str, nr: int, when: str = Form(""),
                   when_egen: str = Form(""), brand: str | None = None):
    """Ja: krever dato. Planlegger, rendrer bildet, og går videre til neste kort.

    `when` er valget fra nedtrekket med ledige publiseringsdager; `when_egen` er
    det frie feltet bak «annen dato eller tid» og vinner når det er fylt ut."""
    v = vault_path()
    mpath, manifest, idx, draft = _resolve(v, day, nr)
    when = ((when_egen or "").strip() or (when or "").strip())[:16]
    try:
        naar = datetime.strptime(when, "%Y-%m-%dT%H:%M")
    except ValueError:
        return _err("Ugyldig tidspunkt; velg dato og tid på nytt.")
    # Ingen planlegging bakover. 31. juli 2026 ble et innlegg planlagt til
    # 2025-07-31 (feil år i det frie datofeltet). Publisher nektet med rette å
    # legge ut noe tolv måneder på etterskudd, så innlegget ble bare liggende,
    # og ingenting sa fra. En dato i fortiden er alltid en feil, aldri en vilje.
    if naar < datetime.now():
        return _err(f"{naar:%d.%m.%Y kl. %H:%M} er tilbake i tid. "
                    f"Velg et tidspunkt fram i tid, ellers blir innlegget "
                    f"aldri publisert.")

    store.mark_verdict(mpath, manifest, idx, "liked")
    # Bildet ble ikke laget da forslaget kom, nettopp for å slippe å betale for
    # det som forkastes. Nå er det bestilt.
    if not (draft.get("png_path") or "").strip() and draft.get("type") != "karusell":
        try:
            merke = brandkit.load_brand(draft.get("brand") or "demo")
            spec = dict(draft.get("spec") or {})
            spec.setdefault("headline", draft.get("headline", ""))
            result = rendermod.render_post(spec, brand=merke)
            store.attach_image(mpath, manifest, idx, result["png"],
                               alt_text=result.get("alt_text", ""))
        except Exception as e:
            # Planleggingen skal ikke ryke fordi bildekallet gjorde det. Utkastet
            # får dato, og bildet kan regenereres fra kortet i kalenderen.
            store.mark_scheduled(mpath, manifest, idx, when)
            return _err(f"Planlagt, men bildet feilet: {e}. Regenerer fra kalenderen.")

    store.mark_scheduled(mpath, manifest, idx, when)
    planmod.mark_slot(v, day, "planlagt", draft_ref={"manifest": day, "nr": nr})
    ctx = _bunke_ctx(v, brand)
    naar = f"{when[8:10]}.{when[5:7]} kl. {when[11:16]}"
    ctx["flash"] = f"Planlagt {naar}."
    n = _kanskje_etterfyll(ctx["igjen"], ctx["brand"])
    if n:
        ctx["flash"] += f" Henter {n * BUNKE_PAAFYLL} nye i bakgrunnen."
    ctx["fyller"] = bool(n) or _paafyll_kjorer()
    return templates.TemplateResponse(request, "some/bunke_kort.html", ctx)


# ───────────────────────────────────────────────────────────
# Media (PNG/PDF fra vaulten, med streng path-guard)
# ───────────────────────────────────────────────────────────

@router.get("/media/{day}/{filename:path}")
def media(day: str, filename: str):
    """PNG/PDF fra dags-mappa, inkl. karusell-slides i undermappa (day/stem/slide-N.png).
    Streng guard: verken dag- eller fil-segmentet får rømme fra dagens mappe."""
    if filename.rsplit(".", 1)[-1].lower() not in ("png", "pdf"):
        raise HTTPException(404)
    root = store.socials_dir(vault_path()).resolve()
    base = (root / day).resolve()
    p = (base / filename).resolve()
    try:
        base.relative_to(root)
        p.relative_to(base)
    except ValueError:
        raise HTTPException(404)
    if not p.is_file():
        raise HTTPException(404)
    return FileResponse(p)
