"""linkedin_draft — lagre genererte SoMe-utkast som EKTE utkast i LinkedIn.

API-et har ingen utkast (se linkedin.py: «PUBLISHED is the only accepted field»),
så dette er nettleser-automatisering (Playwright) mot en manuelt innlogget økt:
åpne firmasidas komposer, lim inn tekst, legg ved bildet, lukk komposeren og velg
«Lagre som utkast». eieren reviewer, redigerer og publiserer selv i LinkedIn.

Lover og valg:
- Publiserer ALDRI. Verktøyet klikker aldri «Publiser»; eneste stiendring i
  LinkedIn er et lagret utkast. Svarstyrt publisering (linkedin.py) er urørt.
- BRANDPOST_BROWSER_ENABLED=1 kreves for ekte kjøring; alt annet er dry-run som
  bare skriver hva som VILLE blitt lagret.
- Innlogging gjør et menneske ÉN gang med `--setup` (synlig nettleser); koden
  ser aldri passord. Nettleserprofilen bor lokalt (aldri i den synkede vaulten).
- Heads-up (ærlig): LinkedIns brukeravtale liker ikke automatisering. Volumet
  her er 2-3 utkast i uka på egen konto, uten publisering; risikoen er lav,
  men den er eierens informerte valg (22. juli 2026).

Selektorer er norsk/engelsk-tolerante (regex på tilgjengelighetsnavn), for
LinkedIn bytter språk etter kontoinnstilling.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

from . import brandkit
from . import paths
from . import store

LEDGER_NAME = "utkast-ledger.json"

# Tilgjengelighetsnavn, norsk og engelsk. LinkedIn A/B-er tekster; hold rause.
RE_START_POST = re.compile(r"start et innlegg|start a post|opprett( et)? innlegg|create a post", re.I)
RE_CREATE_MENU = re.compile(r"^\+?\s*(opprett|create)\b", re.I)
RE_POST_ITEM = re.compile(r"^(innlegg|post)$", re.I)
RE_ADD_MEDIA = re.compile(r"legg til medier|add media|legg til et bilde|add a photo", re.I)
RE_NEXT = re.compile(r"^(neste|next)$", re.I)
RE_DISMISS = re.compile(r"lukk|dismiss|forkast utkast|avvis", re.I)
RE_SAVE_DRAFT = re.compile(r"lagre som utkast|save as draft|lagre utkast", re.I)
RE_EDITOR = re.compile(r"tekstredigering|text editor|hva vil du snakke om|what do you want to talk about", re.I)


def profile_dir() -> Path:
    raw = (os.environ.get("BRANDPOST_BROWSER_PROFILE") or "").strip()
    return Path(raw).expanduser() if raw else paths.state_dir() / "linkedin-profile"


def page_url() -> str:
    """Firmasidas URL (helst admin-visningen, da komponerer boksen SOM sida)."""
    return (os.environ.get("BRANDPOST_LINKEDIN_PAGE_URL") or "").strip()


# Feeden er komposeren for din EGEN profil. Åpner du den herfra, er avsenderen deg
# som person; åpner du den fra en firmaside, er avsenderen sida.
FEED_URL = "https://www.linkedin.com/feed/"


def _er_person(brand_key: str) -> bool:
    """Skriver dette merket som et menneske?

    Ukjent merke gir False, altså firmaside-oppførsel. Det er den forsiktige
    retningen: tar vi feil den veien, havner utkastet på feil firmaside og blir
    liggende som utkast. Tar vi feil andre veien, havner firmainnhold på Oscars
    personlige profil, og det er en verre feil å oppdage i etterkant.
    """
    if not brand_key:
        return False
    try:
        return brandkit.load_brand(brand_key).voice_mode == "person"
    except (ValueError, KeyError, OSError):
        return False


def maal_url(draft: dict) -> str:
    """Hvor komposeren skal åpnes for dette utkastet.

    Personlige utkast går til feeden, merkevare-utkast til firmasida. Uten dette
    skilte ingenting dem: alle utkast arvet den globale firmaside-URL-en, så et
    personlig innlegg ville blitt lagret som et utkast på Tilskudd.ai.
    """
    if _er_person(draft.get("brand", "")):
        return FEED_URL
    return page_url() or FEED_URL


def enabled() -> bool:
    return os.environ.get("BRANDPOST_BROWSER_ENABLED") == "1"


# ── ledger: hvilke utkast er alt lagret (lokal fil, aldri i vaulten) ──────────

def _ledger_path() -> Path:
    return profile_dir() / LEDGER_NAME


def read_ledger() -> dict:
    try:
        return json.loads(_ledger_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def mark_saved(key: str) -> None:
    led = read_ledger()
    led[key] = datetime.now().isoformat(timespec="seconds")
    p = _ledger_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(led, ensure_ascii=False, indent=2), encoding="utf-8")


# ── utvalg: hvilke utkast fra manifestet skal bli LinkedIn-utkast ─────────────

def pick_drafts(vault: Path, *, date: str | None = None, nr: int | None = None,
                limit: int = 3, only_unsaved: bool = True) -> list[dict]:
    """Velg rendrede bilde-utkast fra dags-manifestet. only_unsaved hopper over
    utkast som alt er behandlet (ligger i ledgeren) — av for planlegging der
    kalleren peker på ett bestemt utkast. Karusell-PDF-er hoppes over i v1."""
    root = store.socials_dir(vault)
    if date is None:
        cands = sorted((p for p in root.glob("*/manifest.json")), reverse=True)
        if not cands:
            return []
        day_dir = cands[0].parent
        date = day_dir.name
    else:
        day_dir = root / date
    try:
        manifest = json.loads((day_dir / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []

    led = read_ledger()
    out: list[dict] = []
    for d in manifest.get("drafts", []):
        if nr is not None and d.get("nr") != nr:
            continue
        key = f"{date}#{d.get('nr')}"
        if only_unsaved and key in led:
            continue
        # Manifestet skriver maskin-spesifikke fulle stier (png_path fra Mini);
        # utled filnavnet og slå opp lokalt i dags-mappa, som some-dashbordet gjør.
        image = Path(d.get("png_path") or d.get("image") or "").name
        if not image:  # karusell (pdf) eller tekstpost: v1 tar kun bilder
            continue
        img_path = day_dir / image
        if not img_path.exists():
            continue
        text = (d.get("body") or d.get("headline") or "").strip()
        if not text:
            continue
        # Merkenøkkelen avgjør HVOR komposeren åpnes (se maal_url), så den må
        # følge utkastet hele veien. brand_name er noe annet: den styrer
        # mention-valget inne i komposeren.
        brand_key = (d.get("brand") or "").strip()
        out.append({"key": key, "nr": d.get("nr"), "date": date,
                    "headline": (d.get("headline") or "")[:60],
                    "brand": brand_key,
                    # Et menneske tagger ikke seg selv. Tom brand_name her slår av
                    # mention-forsøket for personlige utkast.
                    "brand_name": ("" if _er_person(brand_key)
                                   else (d.get("brand_name") or "").strip()),
                    "text": text, "image": img_path})
        if len(out) >= limit:
            break
    return out


# ── playwright-flyten (lazy import: resten av modulen krever ikke playwright) ─

def _launch(*, headless: bool):
    from playwright.sync_api import sync_playwright
    pw = sync_playwright().start()
    ctx = pw.chromium.launch_persistent_context(
        str(profile_dir()), headless=headless, viewport={"width": 1440, "height": 1000},
        args=["--disable-blink-features=AutomationControlled"])
    return pw, ctx


def _is_logged_in(page) -> bool:
    page.goto("https://www.linkedin.com/feed/", wait_until="domcontentloaded")
    page.wait_for_timeout(2500)
    url = page.url
    return ("/login" not in url) and ("checkpoint" not in url) and ("authwall" not in url)


def setup() -> int:
    """Synlig nettleser: mennesket logger inn ÉN gang, profilen huskes lokalt."""
    profile_dir().mkdir(parents=True, exist_ok=True)
    os.chmod(profile_dir(), 0o700)
    pw, ctx = _launch(headless=False)
    try:
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto("https://www.linkedin.com/login", wait_until="domcontentloaded")
        print("Logg inn i vinduet (inkl. eventuell 2FA). Venter i inntil 5 minutter …")
        try:
            page.wait_for_url(re.compile(r".*/feed/.*"), timeout=300_000)
        except Exception:  # noqa: BLE001
            if not _is_logged_in(page):
                print("Kom aldri til feeden. Kjør --setup på nytt.")
                return 1
        print("✅ Innlogget. Profilen er lagret lokalt; --check verifiserer headless.")
        return 0
    finally:
        ctx.close()
        pw.stop()


def check() -> int:
    pw, ctx = _launch(headless=True)
    try:
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        ok = _is_logged_in(page)
        print("✅ innlogget økt" if ok else "❌ ikke innlogget: kjør --setup først")
        return 0 if ok else 1
    finally:
        ctx.close()
        pw.stop()


def _open_composer(page) -> None:
    """To layouter: feed/side har en «Start et innlegg»-boks; admin-dashbordet
    har en «Opprett»-knapp med «Start et innlegg»-lenke i menyen (probet 22.
    juli 2026). NB: Opprett-knappens ARIA-navn avviker fra synlig tekst, så
    tekst-selektorer (:has-text) er riktig verktøy her, ikke get_by_role."""
    direct = page.locator('button:has-text("Start et innlegg"), button:has-text("Start a post")')
    if direct.count() and direct.first.is_visible():
        direct.first.click()
        return
    page.locator('button:has-text("Opprett"), button:has-text("Create")').first.click()
    item = page.locator('a:has-text("Start et innlegg"), a:has-text("Start a post"), '
                        '[role="menuitem"]:has-text("innlegg"), [role="menuitem"]:has-text("post")')
    item.first.wait_for(state="visible", timeout=10_000)
    item.first.click()


# @handle i brødteksten. LinkedIn lager en EKTE tagg bare når man skriver @ og
# velger firmaet fra typeahead-lista; ren innliming blir stående som vanlig tekst.
# Må starte på ordgrense (ellers plukkes «@example.com» ut av en e-postadresse)
# og slutte alfanumerisk (ellers sluker den punktumet etter «@demo-labs.»).
_MENTION_RE = re.compile(r"(?<![\w.@])@[A-Za-z0-9](?:[A-Za-z0-9._\-]*[A-Za-z0-9])?")
_MENTION_OPTS = ('[role="option"], .ql-mention-list-item, [data-test-mention-item]')


def _select_mention(page, expect_name: str) -> bool:
    """Velg merket fra mention-lista. Godtar KUN et toppforslag som faktisk er
    vårt merke: nedtrekket inneholder ofte selskaper med lignende navn, og feil valg
    ville tagget en konkurrent i innlegget ditt."""
    opts = page.locator(_MENTION_OPTS)
    if not opts.count():
        return False
    first = " ".join((opts.first.inner_text() or "").split())
    if not first.lower().startswith(expect_name.lower()):
        return False
    opts.first.click()
    page.wait_for_timeout(500)
    return True


def _type_with_mentions(page, text: str, expect_name: str) -> int:
    """Skriv brødteksten og gjør @handle om til ekte tagger. Vanlig tekst limes
    inn raskt; selve handlen skrives tegn for tegn så typeaheaden fyrer.
    Slår valget feil (ingen liste, eller feil firma øverst), blir taggen stående
    som ren tekst, aldri tagget til feil side. Returnerer antall ekte tagger."""
    tagged, pos = 0, 0
    for m in _MENTION_RE.finditer(text):
        if text[pos:m.start()]:
            page.keyboard.insert_text(text[pos:m.start()])
        for ch in m.group(0):
            page.keyboard.type(ch, delay=80)
        page.wait_for_timeout(1500)
        if _select_mention(page, expect_name):
            tagged += 1
        pos = m.end()
    if text[pos:]:
        page.keyboard.insert_text(text[pos:])
    return tagged


def _prepare_composer(page, draft: dict) -> None:
    """Åpne komposeren og fyll den med utkastets tekst + bilde. Delt av både
    lagre-utkast og planlegg-flyten, så innfyllingen håndteres ett sted."""
    target = maal_url(draft)
    page.goto(target, wait_until="domcontentloaded")
    page.wait_for_timeout(2500)

    _open_composer(page)
    editor = page.get_by_role("textbox", name=RE_EDITOR).first
    editor.wait_for(state="visible", timeout=15_000)
    editor.click()
    # Komposeren kan ha GJENOPPRETTET et tidligere utkast (tekst og/eller
    # bilde); tøm teksten først så vi aldri dobler innhold.
    page.keyboard.press("ControlOrMeta+a")
    page.keyboard.press("Backspace")
    # fill() setter DOM-innhold uten input-events, og LinkedIns React-editor
    # registrerte det aldri (bevist 22. juli: utkastet ble lagret med tomt
    # tekstfelt). insert_text går via tastaturet og fyrer ekte events.
    tagged = _type_with_mentions(page, draft["text"], draft.get("brand_name") or "")
    if tagged:
        print(f"      ({tagged} ekte LinkedIn-tagg{'er' if tagged > 1 else ''})")
    page.wait_for_timeout(800)

    # «Legg til medier» finnes bare når komposeren IKKE alt har et vedlegg
    # (gjenopprettet utkast skjuler knappen). Har den vedlegg, beholder vi det.
    media_btn = page.get_by_role("button", name=RE_ADD_MEDIA)
    if media_btn.count() and media_btn.first.is_visible():
        with page.expect_file_chooser(timeout=15_000) as fc_info:
            media_btn.first.click()
        fc_info.value.set_files(str(draft["image"]))
        # Medievisningen har en Neste-knapp tilbake til komposeren; vent til
        # bildet er lastet opp (knappen aktiveres) før vi går videre.
        nxt = page.get_by_role("button", name=RE_NEXT).first
        nxt.wait_for(state="visible", timeout=30_000)
        nxt.click()
        page.wait_for_timeout(1500)
    else:
        print("      (vedlegg fantes fra gjenopprettet utkast, beholdes)")


def _save_one(page, draft: dict) -> None:
    """Komposer → tekst → bilde → lukk → «Lagre som utkast». Reiser ved avvik."""
    _prepare_composer(page, draft)
    page.get_by_role("button", name=RE_DISMISS).first.click()
    save = page.get_by_role("button", name=RE_SAVE_DRAFT).first
    save.wait_for(state="visible", timeout=10_000)
    save.click()
    page.wait_for_timeout(2000)


# ── Planlegging (native LinkedIn-scheduling via klokke-ikonet) ────────────────
# Fulle norske månedsnavn = kalender-widgetens header og dag-celle-aria
# («juli 2026», «27. juli 2026»). LinkedIns bekreftelses-header forkorter LANGE
# navn («sep.») men ikke korte («juli»), så header-sjekken bruker 3-bokstavers
# prefiks som matcher begge.
_MND_FULL = ["januar", "februar", "mars", "april", "mai", "juni",
             "juli", "august", "september", "oktober", "november", "desember"]
_MND_3 = ["jan", "feb", "mar", "apr", "mai", "jun",
          "jul", "aug", "sep", "okt", "nov", "des"]


def _pick_calendar_date(page, when: datetime) -> None:
    """Sett datoen ved å KLIKKE dagen i kalender-widgeten. Typing oppdaterer bare
    synlig verdi, ikke LinkedIns interne planleggings-tilstand (bevist 22. juli:
    feltet viste 29.7 mens innlegget ble planlagt til default-datoen)."""
    page.locator('input[name="artdeco-date"]').first.click()
    page.wait_for_timeout(700)
    mnd_full = _MND_FULL[when.month - 1]
    target = f"{mnd_full} {when.year}"
    for _ in range(18):  # naviger framover til rett måned (maks 18 mnd fram)
        hdr = page.locator(
            '.artdeco-calendar__month, .artdeco-calendar [aria-live]'
        ).first.inner_text().strip().lower()
        if target in hdr:
            break
        page.locator('button[aria-label="Neste måned"]').first.click()
        page.wait_for_timeout(350)
    else:
        raise RuntimeError(f"fant ikke måneden {target} i kalenderen")
    day = page.get_by_role(
        "button", name=re.compile(rf"\b{when.day}\. {mnd_full} {when.year}\."))
    day.first.click()
    page.wait_for_timeout(500)


def _pick_time(page, when: datetime) -> None:
    """Sett tidspunktet ved å KLIKKE opsjonen i den utvidede tidslista. Typing
    oppdaterer bare synlig verdi (bevist 22. juli). Lista er virtualisert og
    seedes rundt nåtid, så vi scroller til opsjonen dukker opp (opp først, det
    dekker morgen-slots; ned som fallback). Tida må være et 15-min-slot."""
    hhmm = when.strftime("%H:%M")
    page.locator('button[aria-label="Utvid tidsvelger"]').first.click()
    page.wait_for_timeout(600)
    page.mouse.move(720, 400)
    for direction in (-320, 320):  # opp, så ned
        for _ in range(28):
            opt = page.get_by_role("option", name=hhmm, exact=True)
            if opt.count():
                opt.first.click()
                page.wait_for_timeout(400)
                return
            page.mouse.wheel(0, direction)
            page.wait_for_timeout(160)
    raise RuntimeError(f"fant ikke tidspunktet {hhmm} i tidslista "
                       f"(må være et kvarter: 00/15/30/45)")


def _assert_schedule_header(page, when: datetime) -> str:
    """Les LinkedIns egen «<ukedag>. <dag>. <mnd>., <tid> …»-linje i
    planleggings-dialogen og bekreft at den matcher ønsket dato+tid. DETTE er
    fasiten: dør sjekken, planlegges INGENTING (typing-fella over)."""
    body = page.locator('div[role="dialog"]').last.inner_text()
    hhmm = when.strftime("%H:%M")
    dag = f"{when.day}."
    mnd3 = _MND_3[when.month - 1]
    ok = (hhmm in body and dag in body and mnd3 in body.lower())
    if not ok:
        snip = " ".join(body.split())[:160]
        raise RuntimeError(
            f"planleggings-header stemmer ikke med {dag} {mnd3} {hhmm}: «{snip}»")
    m = re.search(r"(man|tir|ons|tor|fre|lør|søn)[^\n]*", body)
    return m.group(0).strip() if m else f"{dag} {mnd3} {hhmm}"


def _schedule_one(page, draft: dict, when: datetime, *, commit: bool) -> str:
    """Komposer → tekst → bilde → «Planlegg innlegg» → dato+tid → FASIT-sjekk →
    (commit ? «Neste»+«Planlegg» : avbryt). Returnerer LinkedIns bekreftede
    tidslinje. commit=False gjør alt UNNTATT selve planleggingen (tørrkjøring)."""
    _prepare_composer(page, draft)
    page.locator('button[aria-label="Planlegg innlegg"]').first.click()
    page.wait_for_timeout(1800)
    _pick_calendar_date(page, when)
    _pick_time(page, when)
    bekreftet = _assert_schedule_header(page, when)  # fasit; reiser ved avvik
    if not commit:
        return bekreftet
    # Lukk evt. åpen popup ved å klikke dialog-overskriften, så «Neste».
    page.get_by_text("Planlegg innlegg", exact=True).first.click()
    page.wait_for_timeout(400)
    page.get_by_role("button", name=re.compile(r"^Neste$")).first.click()
    page.wait_for_timeout(2500)
    plan = page.get_by_role("button", name=re.compile(r"^Planlegg$")).first
    plan.wait_for(state="visible", timeout=10_000)
    plan.click()
    page.wait_for_timeout(4000)
    return bekreftet


def schedule_post(vault: Path, *, date: str, nr: int, when: datetime,
                  headless: bool = True, commit: bool | None = None) -> int:
    """Planlegg ETT utkast som native LinkedIn-planlagt innlegg til `when`.
    commit=None → styres av enabled() (BRANDPOST_BROWSER_ENABLED=1); commit=False
    er alltid tørrkjøring (fasit-sjekk, ingen planlegging)."""
    if commit is None:
        commit = enabled()
    drafts = pick_drafts(vault, date=date, nr=nr, limit=1, only_unsaved=False)
    if not drafts:
        print(f"Fant ikke bilde-utkast {date}#{nr}.")
        return 1
    draft = drafts[0]
    # Se samme sjekk i save_drafts: en personlig profil trenger ingen firmaside.
    if not page_url() and not _er_person(draft.get("brand", "")):
        print("BRANDPOST_LINKEDIN_PAGE_URL mangler (firmasidas URL).")
        return 1
    if not commit:
        print(f"  🧪 tørrkjøring: ville planlagt {draft['key']} «{draft['headline']}» "
              f"til {when:%d.%m %H:%M} (fasit-sjekk kjøres, ingen planlegging)")

    pw, ctx = _launch(headless=headless)
    try:
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        if not _is_logged_in(page):
            print("❌ ikke innlogget: kjør --setup først (synlig nettleser).")
            return 1
        try:
            bekreftet = _schedule_one(page, draft, when, commit=commit)
        except Exception as e:  # noqa: BLE001
            print(f"  ⚠️  {draft['key']}: {type(e).__name__}: {e}")
            shot = profile_dir() / f"feil-plan-{draft['date']}-nr{draft['nr']}.png"
            try:
                page.screenshot(path=str(shot))
                print(f"      skjermbilde: {shot}")
            except Exception:  # noqa: BLE001
                pass
            return 1
        if commit:
            mark_saved(draft["key"])  # samme ledger: hindrer dobbel-planlegging
            # Skriv status=planlagt til manifestet (dashbordet leser det).
            try:
                mpath, manifest = store.load_manifest(vault, draft["date"])
                if manifest:
                    idx, _ = store.select_draft(manifest, str(draft["nr"]))
                    if idx is not None:
                        store.mark_scheduled(mpath, manifest, idx,
                                             when.isoformat(timespec="minutes"),
                                             confirmed=bekreftet)
            except Exception as e:  # noqa: BLE001
                print(f"      (status-skriving hoppet over: {e})")
            print(f"  ✅ planlagt {draft['key']} «{draft['headline']}» — {bekreftet}")
        else:
            print(f"  ✅ tørrkjøring OK: LinkedIn bekreftet «{bekreftet}» "
                  f"(ingenting planlagt)")
        return 0
    finally:
        ctx.close()
        pw.stop()


def save_drafts(vault: Path, *, date: str | None = None, nr: int | None = None,
                limit: int = 3, headless: bool = True) -> int:
    drafts = pick_drafts(vault, date=date, nr=nr, limit=limit)
    if not drafts:
        print("Ingen ulagrede bilde-utkast å ta.")
        return 0
    if not enabled():
        for d in drafts:
            hvor = "personprofilen" if _er_person(d.get("brand", "")) else "firmasida"
            print(f"  🧪 dry-run (BRANDPOST_BROWSER_ENABLED=0): ville lagret utkast "
                  f"{d['key']} «{d['headline']}» + {d['image'].name} → {hvor} "
                  f"({maal_url(d)})")
        return 0
    # Kravet gjelder bare merkevare-utkast. For en personlig profil ER
    # personprofilen målet, og da er en manglende firmaside-URL helt riktig.
    if not page_url() and any(not _er_person(d.get("brand", "")) for d in drafts):
        print("BRANDPOST_LINKEDIN_PAGE_URL mangler (firmasidas URL). Uten den havner "
              "utkastet på personprofilen; sett den i .env.")
        return 1

    pw, ctx = _launch(headless=headless)
    try:
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        if not _is_logged_in(page):
            print("❌ ikke innlogget: kjør --setup først (synlig nettleser).")
            return 1
        ok = 0
        for d in drafts:
            try:
                _save_one(page, d)
                mark_saved(d["key"])
                ok += 1
                print(f"  ✅ lagret LinkedIn-utkast {d['key']} «{d['headline']}»")
            except Exception as e:  # noqa: BLE001
                print(f"  ⚠️  {d['key']}: {type(e).__name__}: {e}")
                shot = profile_dir() / f"feil-{d['date']}-nr{d['nr']}.png"
                try:
                    page.screenshot(path=str(shot))
                    print(f"      skjermbilde: {shot}")
                except Exception:  # noqa: BLE001
                    pass
        print(f"Ferdig: {ok}/{len(drafts)} utkast lagret.")
        return 0 if ok == len(drafts) else 1
    finally:
        ctx.close()
        pw.stop()


# ── Auto-oppdagelse av publiserte innlegg ────────────────────────────────────
# LinkedIn-API-ets socialMetadata krever scope r_organization_social (ikke
# godkjent ennå, se linkedin.py). Med en innlogget økt kan vi i stedet lese
# firmasidas egen innleggsliste: hvert innlegg har data-urn = aktivitets-URN,
# og teksten står i elementet. Da slipper eieren å lime inn URL-er manuelt.

def posts_url() -> str:
    """Firmasidas offentlige innleggsliste, utledet fra admin-URL-en i .env."""
    m = re.search(r"/company/([^/]+)/", page_url() or "")
    return f"https://www.linkedin.com/company/{m.group(1)}/posts/" if m else ""


def _norm(s: str) -> str:
    """Sammenlignbar form: små bokstaver, ett mellomrom, uten spesialtegn som
    LinkedIn og vi skriver ulikt (hermetegn, tankestrek, mention-format)."""
    s = (s or "").lower().replace("«", "").replace("»", "")
    s = re.sub(r"[^\wæøå ]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def fetch_published(limit: int = 20, *, headless: bool = True) -> list[dict]:
    """Les publiserte innlegg fra firmasida: [{urn, url, text}, …], nyeste først.
    Krever innlogget økt; returnerer [] hvis lista ikke kan leses."""
    url = posts_url()
    if not url:
        return []
    pw, ctx = _launch(headless=headless)
    try:
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(url, wait_until="domcontentloaded")
        page.wait_for_timeout(5000)
        for _ in range(3):  # etterlast flere innlegg
            page.mouse.wheel(0, 1800)
            page.wait_for_timeout(1300)
        rows = page.evaluate(
            """() => {
              const out = [];
              document.querySelectorAll('[data-urn], [data-id]').forEach(el => {
                const urn = el.getAttribute('data-urn') || el.getAttribute('data-id') || '';
                if (!/activity/i.test(urn)) return;
                const t = (el.innerText || '').replace(/\\s+/g, ' ').trim();
                if (t) out.push({urn, text: t});
              });
              return out;
            }"""
        )
        seen, out = set(), []
        for r in rows:
            urn = r.get("urn", "")
            if urn in seen:
                continue
            seen.add(urn)
            out.append({"urn": urn, "text": r.get("text", ""),
                        "url": f"https://www.linkedin.com/feed/update/{urn}/"})
            if len(out) >= limit:
                break
        return out
    finally:
        ctx.close()
        pw.stop()


def _match_draft(draft: dict, published: list[dict]) -> dict | None:
    """Finn det publiserte innlegget som svarer til utkastet. Matcher på en
    distinkt bit av brødteksten (LinkedIn-teksten er pakket i header-støy som
    følgertall og synlighet, så vi leter etter vår tekst INNI deres)."""
    for felt in ("body", "headline"):
        bit = _norm(draft.get(felt) or "")[:60]
        if len(bit) < 25:  # for kort til å være entydig
            continue
        for p in published:
            if bit in _norm(p["text"]):
                return p
    return None


def sync_published(vault: Path, *, limit: int = 20, headless: bool = True) -> int:
    """Match publiserte LinkedIn-innlegg mot utkastene og sett status=published
    + linkedin_url automatisk. Returnerer antall nye treff. Rører aldri utkast
    som alt er markert publisert."""
    published = fetch_published(limit, headless=headless)
    if not published:
        print("Fant ingen publiserte innlegg (ikke innlogget, eller tom side).")
        return 0
    print(f"  leste {len(published)} publiserte innlegg fra firmasida")
    root = store.socials_dir(vault)
    n = 0
    for mpath in sorted(root.glob("*/manifest.json"), reverse=True):
        try:
            manifest = json.loads(mpath.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        endret = False
        for idx, d in enumerate(manifest.get("drafts") or []):
            if not isinstance(d, dict) or d.get("status") == "published":
                continue
            hit = _match_draft(d, published)
            if not hit:
                continue
            store.mark_published(mpath, manifest, idx, hit["url"])
            endret = True
            n += 1
            print(f"  ✅ {mpath.parent.name}#{d.get('nr')} «{(d.get('headline') or '')[:44]}» "
                  f"→ publisert ({hit['urn'].split(':')[-1]})")
        if endret:  # mark_published skrev alt; les inn på nytt ved neste runde
            continue
    if not n:
        print("  ingen nye treff (alt er alt bokført)")
    return n


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Lagre SoMe-utkast som LinkedIn-utkast (aldri publisering)")
    ap.add_argument("--vault", default=None)
    ap.add_argument("--setup", action="store_true", help="synlig nettleser for engangs-innlogging")
    ap.add_argument("--check", action="store_true", help="verifiser innlogget økt headless")
    ap.add_argument("--date", default=None, help="dags-manifest (YYYY-MM-DD), default nyeste")
    ap.add_argument("--nr", type=int, default=None, help="kun dette utkast-nummeret")
    ap.add_argument("--limit", type=int, default=3)
    ap.add_argument("--headed", action="store_true", help="vis nettleseren under lagring")
    ap.add_argument("--schedule", metavar="YYYY-MM-DDTHH:MM",
                    help="planlegg utkastet (--date --nr) som native LinkedIn-planlagt "
                         "innlegg til dette tidspunktet (kvarter-slot)")
    ap.add_argument("--dry-run", action="store_true",
                    help="med --schedule: kjør fasit-sjekk uten å faktisk planlegge")
    ap.add_argument("--sync-published", action="store_true",
                    help="les firmasidas innlegg og marker matchende utkast som publisert")
    args = ap.parse_args(argv)

    if args.setup:
        return setup()
    if args.check:
        return check()
    vault = paths.workspace(args.vault)
    if args.sync_published:
        sync_published(vault, headless=not args.headed)
        return 0
    if args.schedule:
        if not args.date or args.nr is None:
            print("--schedule krever --date og --nr (ett bestemt utkast).")
            return 2
        try:
            when = datetime.strptime(args.schedule.replace(" ", "T")[:16], "%Y-%m-%dT%H:%M")
        except ValueError:
            print("Ugyldig --schedule; bruk YYYY-MM-DDTHH:MM (f.eks. 2026-07-29T08:00).")
            return 2
        return schedule_post(vault, date=args.date, nr=args.nr, when=when,
                             headless=not args.headed,
                             commit=False if args.dry_run else None)
    return save_drafts(vault, date=args.date, nr=args.nr, limit=args.limit,
                       headless=not args.headed)


if __name__ == "__main__":
    sys.exit(main())
