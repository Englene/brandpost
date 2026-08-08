"""cli — deterministiske underkommandoer for SoMe-generatoren.

Runbooken (Claude-hjernen) orkestrerer de tre første; `run` er en headless
helkjøring (uten nettsøk) som også fungerer som ende-til-ende-test.

  context [--days N]           dump ferske temaer/vinklinger som JSON (stdout)
  render  --specs FILE         rendr bildene fra en specs-JSON, skriv utkast+manifest
  send    [--manifest FILE]    monter SoMe-eposten fra et manifest og send (dry-run std.)
  run     [--brand K] [--n N]  headless: generer specs via structured_call, rendr, send

Specs-JSON (render/run inn):  {"brand": "demo", "posts": [ {spec}, ... ]}
Manifest (render ut / send inn): ETT per dag, felles for alle merker; render MERGER
inn i det ({"brand": sist rendrede, "seq", "drafts":[ {draft-meta med "nr"}, ... ]}),
og «publiser: nr» er stabilt for hele dagen. `send` filtrerer på merke.
"""

from __future__ import annotations

import copy
import argparse
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

from . import (bildebank, bildevalg, brandkit, carousel as carouselmod,
               context as ctxmod, email as emailmod, model, paths,
               plan as planmod, publisher as pubmod, render as rendermod, store)

# Repo-rotens .env (nøkler og BRANDPOST_*-innstillinger). Eksplisitt sti så
# routinen finner den uansett arbeidskatalog.
_REPO_ROOT = paths.REPO_ROOT


def _vault(args) -> Path:
    return paths.workspace(getattr(args, "vault", None))


# ── context ────────────────────────────────────────────────

def cmd_context(args) -> int:
    vault = _vault(args)
    data = ctxmod.gather_context(vault, days=args.days)
    data["recent_angles"] = store.recent_angles(vault)
    brand = brandkit.load_brand(getattr(args, "brand", None) or "demo")
    data["pillars"] = [{"id": p.id, "label": p.label, "desc": p.desc} for p in brand.pillars]
    data["pillar_coverage"] = store.pillar_coverage(vault, brandkit.pillar_ids(brand))
    saved_plan = planmod.load_plan(vault)
    data["plan"] = {"today_slot": planmod.today_slot(vault, brand_key=brand.key),
                    "open_slots": planmod.open_slots(vault, brand_key=brand.key),
                    "weeks": saved_plan.get("weeks", [])} if saved_plan else {}
    json.dump(data, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0


# ── pulse (Slack-puls) + stats (engasjement) ───────────────

def cmd_pulse(args) -> int:
    """Puls-høsting er en UTVIDELSESFLATE, ikke med i v1.

    Ideen: les det som skjer i arbeidshverdagen din (Slack, e-post, møtereferater),
    anonymiser det til innholdsvinkler, og skriv dem til socials/pulse/<dato>.json.
    Hjernen plukker dem opp automatisk hvis fila finnes; se context._latest_pulse.

    Grunnen til at den ikke følger med: den opprinnelige implementasjonen leste en
    bestemt Slack-oppsett og hører hjemme hos den som eier de kildene. Skriv din egen
    og legg resultatet i det formatet, så er du koblet på.
    """
    print("Puls-høsting er ikke med i v1. Se docs/extending.md for formatet "
          "socials/pulse/<dato>.json, så plukker hjernen det opp automatisk.")
    return 0


def cmd_plan(args) -> int:
    """Vis (og med --refresh: rull) innholdsplanen: ukesnarrativ + slots man/ons/fre."""
    vault = _vault(args)
    if args.refresh:
        res = planmod.refresh_plan(vault, brand_key=args.brand, horizon_days=args.horizon)
        print(f"  🗓  plan rullet: {len(res.get('slots', []))} slots → {res.get('_path', '')}")
    plan = planmod.load_plan(vault)
    if not plan:
        print("  (ingen plan ennå: kjør `plan --refresh`)")
        return 0
    for w in plan.get("weeks", []):
        print(f"  {w.get('iso_week')}: {w.get('narrativ', '')}")
    marks = {"planlagt": "·", "utkast": "✎", "publisert": "✓"}
    for s in plan.get("slots", []):
        print(f"   {marks.get(s.get('status'), '·')} {s.get('date')} "
              f"[{s.get('format', 'bilde')}] {s.get('pillar') or '(åpen)'}: "
              f"{(s.get('tema') or '(ledig slot)')[:64]}")
    return 0


def cmd_stats(args) -> int:
    """Hent respons-tall (reaksjoner/kommentarer) for publiserte innlegg og skriv
    engagement.json. Read-only mot LinkedIn; degraderer pent uten scope/creds."""
    from . import engagement as engagementmod
    vault = _vault(args)
    res = engagementmod.update_stats(vault, days_back=args.days)
    for p in res.get("problems", []):
        print(f"  ⚠️  stats: {p}", file=sys.stderr)
    print(f"  📈 engasjement: {len(res.get('posts') or [])} publiserte innlegg"
          + (f" → {res.get('_path')}" if res.get("_path") else ""))
    if res.get("reason"):
        print(f"  ℹ️  {res['reason']}")
    return 0


# ── render ─────────────────────────────────────────────────

def _load_specs(path: str) -> tuple[str, list[dict]]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    brand_key = payload.get("brand", "demo")
    posts = payload.get("posts") or []
    if not isinstance(posts, list) or not posts:
        raise SystemExit("specs-JSON mangler ikke-tom 'posts'-liste")
    return brand_key, posts


_BYTE_KEYS = ("png", "pdf", "cover")  # holdes ut av JSON-manifestet (leses fra disk ved send)

# Tekst-sanering (naturlig norsk + LinkedIn-algoritmen), håndhevet i MOTOREN så
# den gjelder uansett hvem som skrev specsene (runbook eller headless run).
_TEXT_FIELDS = ("headline", "subhead", "kicker", "body", "why_now", "tittel", "number")
_URL_RE = re.compile(r"https?://\S+|www\.\S+")
def _self_ref_re(wordmark: str):
    """Mønster som finner merkets EGEN URL eller domenenavn i brødteksten, så den
    kan gjøres om til en @-tagg i stedet for en lenke (lenker kutter rekkevidden).

    Var hardkodet til ett bestemt domene i opphavet, noe som betydde at ethvert
    annet merke slapp gjennom med rå selvreklame i teksten."""
    navn = re.escape((wordmark or "").strip().lower())
    if not navn:
        return None
    return re.compile(rf"(?<![\w@])(?:https?://)?(?:www\.)?{navn}\S*", re.I)

# Tankestrek-saneringen bor i store, så plan-motoren bruker nøyaktig samme regel
# (plan-temaene slapp unna helt til 22. juli fordi regexen bare fantes her).
_clean_text = store.clean_text


def _sanitize_spec(spec: dict, *, brand_name: str, handle: str = "",
                   wordmark: str = "") -> None:
    """Muterer spec: fjerner tankestreker overalt, og i `body`: bytt selskaps-URL
    med @-tagg og flytt alle andre URL-er til `kilder` (lenker i innlegget kutter
    rekkevidden; kildene er for deg, ikke publikum).

    `handle` er merkets LinkedIn-handle (f.eks. «demo-labs»). Taggen skrives da
    som @handle, som er det LinkedINs mention-liste faktisk slår opp på; uten
    handle faller vi tilbake til @merkenavn (gammel oppførsel)."""
    for k in _TEXT_FIELDS:
        if isinstance(spec.get(k), str):
            spec[k] = _clean_text(spec[k])
    for s in spec.get("slides") or []:
        if isinstance(s, dict):
            for k in ("kicker", "heading", "body"):
                if isinstance(s.get(k), str):
                    s[k] = _clean_text(s[k])
    body = spec.get("body")
    if isinstance(body, str) and body:
        # Uten handle skrives INGEN tagg. Å gjette fra merkenavnet tagger den
        # bedriften som tilfeldigvis heter det på LinkedIn, altså noen andre.
        tag = f"@{handle}" if handle else ""
        body = body.replace(tag, "\x00TAG\x00")           # bevar eksisterende tagg
        if handle:  # eldre utkast/hjerne-tekst kan ha den gamle @merkenavn-formen
            body = body.replace(f"@{brand_name}", "\x00TAG\x00")
        selv = _self_ref_re(wordmark)
        if selv is not None:
            body = selv.sub("\x00TAG\x00", body)         # egen URL/domenenavn -> tagg
        moved = [u.rstrip(".,)") for u in _URL_RE.findall(body)]
        if moved:
            body = _URL_RE.sub("", body)
            kilder = [k for k in (spec.get("kilder") or []) if isinstance(k, str)]
            kilder.extend(u for u in moved if not any(u in k for k in kilder))
            spec["kilder"] = kilder
        body = body.replace("\x00TAG\x00", tag)
        spec["body"] = re.sub(r"[ \t]+(\n|$)", r"\1", re.sub(r"[ \t]{2,}", " ", body)).strip()


def _render_posts(vault: Path, brand, posts: list[dict],
                  *, now: datetime | None = None,
                  replace_own: bool = True) -> tuple[list[dict], list[Path]]:
    """Rendr specs gruppert på `slot_date` (default i dag) og merge inn i riktig
    dags-manifest per dato. Returnerer (safe-utkast på tvers av datoene, manifest-stier)."""
    now = now or datetime.now()
    groups: dict[str, list[dict]] = {}
    for spec in posts:
        ds = (spec.get("slot_date") or "").strip()
        try:
            datetime.strptime(ds, "%Y-%m-%d")
        except ValueError:
            ds = now.strftime("%Y-%m-%d")
        groups.setdefault(ds, []).append(spec)

    all_safe: list[dict] = []
    paths: list[Path] = []
    bilde_seq = 0  # roterer tema for visuell variasjon over enkeltbildene
    for ds in sorted(groups):
        when = datetime.combine(datetime.strptime(ds, "%Y-%m-%d").date(), now.time())
        drafts: list[dict] = []
        for i, spec in enumerate(groups[ds], 1):
            spec.setdefault("brand", brand.key)
            _sanitize_spec(spec, brand_name=brand.name, handle=brand.linkedin_handle,
                           wordmark=brand.wordmark)
            if (spec.get("type") or "bilde").strip().lower() == "karusell":
                built = carouselmod.build_carousel(spec, brand=brand)
                meta = store.write_carousel(vault, brand.key, spec, built, index=i, when=when)
                drafts.append(meta)
                print(f"  🎠 {ds} karusell: {built['n']} slides, {built['size_mb']} MB "
                      f"→ {meta['headline'][:44]}")
            else:
                try:
                    # Egne bilder går foran generert grafikk. Banken håndhever
                    # godkjenningen selv, så en ukjent eller avvist id faller
                    # stille tilbake til vanlig rendering framfor å feile.
                    if brand.voice_mode == "person":
                        # EKTE bilde eller ingen bilde. Aldri et designet kort:
                        # en privatperson med perfekt merkevaregrafikk på hvert
                        # innlegg leser som en kampanje, og eieren forkastet
                        # nettopp det 3. august 2026.
                        #
                        # bildevalg prøver utdrag, egne skjermbilder, skjermbilde
                        # av kilden og til slutt en nøktern figur. Gir alle
                        # ingenting, er ren tekst svaret, og det er et normalt
                        # format på en personlig profil.
                        result = bildevalg.skaff(spec, vault=vault)
                        if result is None:
                            bilde_seq += 1
                            meta = store.write_draft(vault, brand.key, spec, None,
                                                     index=i, when=when)
                            drafts.append(meta)
                            print(f"  📝 {ds} ren tekst: {meta['headline'][:44]}")
                            continue
                    else:
                        # Egne bilder går foran generert grafikk. Banken håndhever
                        # godkjenningen selv, så en ukjent eller avvist id faller
                        # stille tilbake til vanlig rendering framfor å feile.
                        egen = bildebank.finn(spec.get("bevis_id", ""), vault)
                        if egen is not None:
                            result = {"png": egen.read_bytes(), "format": "eget-bilde",
                                      "how": f"bevis:{egen.name}"}
                        else:
                            result = rendermod.render_post(spec, brand=brand, seq=bilde_seq)
                except Exception as e:  # noqa: BLE001
                    # Ett feilet bildekall skal ikke rive med seg de andre ni.
                    # Utkastet lagres uten bilde og kan regenereres fra kortet;
                    # teksten er det dyre å lage på nytt, ikke motivet.
                    bilde_seq += 1
                    meta = store.write_draft(vault, brand.key, spec, None, index=i, when=when)
                    drafts.append(meta)
                    print(f"  ⚠️  {ds} post uten bilde ({type(e).__name__}): "
                          f"{meta['headline'][:36]}", file=sys.stderr)
                    continue
                bilde_seq += 1
                meta = store.write_draft(vault, brand.key, spec, result["png"], index=i, when=when)
                meta["how"] = result["how"]
                drafts.append(meta)
                tag = (spec.get("motif", "")[:34] if result["format"] in ("motiv", "redaksjonelt")
                       else spec.get("variant", "utsagn"))
                print(f"  🖼  {ds} post: {result['format']}/{result['how']} "
                      f"— {meta['headline'][:36]} · {tag}")
        store.record(vault, drafts, when=when)
        for d in drafts:
            d["brand_name"] = brand.name  # per utkast: dags-manifestet rommer flere merker
            d["date"] = ds
        safe = [{k: v for k, v in d.items() if k not in _BYTE_KEYS} for d in drafts]
        # Merge inn i dags-manifestet (aldri overskriv): to merker samme dag består
        # begge, og «publiser: nr»-numrene forblir unike for hele dagen.
        manifest_path, manifest = store.merge_manifest(
            vault, brand_key=brand.key, brand_name=brand.name, new_drafts=safe,
            when=when, replace_own=replace_own)
        behold = len(manifest["drafts"]) - len(safe)
        print(f"  ✅ {ds}: {len(safe)} utkast (nr {safe[0]['nr']}-{safe[-1]['nr']}) "
              f"→ {manifest_path.parent}"
              + (f" (+{behold} fra før i dags-manifestet)" if behold else ""))
        all_safe.extend(safe)
        paths.append(manifest_path)
    return all_safe, paths


def cmd_render(args) -> int:
    vault = _vault(args)
    brand_key, posts = _load_specs(args.specs)
    brand = brandkit.load_brand(brand_key)
    safe, paths = _render_posts(vault, brand, posts)
    for p in paths:
        print(f"  📄 manifest → {p}")
    # Batch-fil for `send --fresh`: akkurat DENNE renderens utkast, på tvers av
    # datoene (slot-fylling skriver til flere dags-manifester i én kjøring).
    batch = {"generated": datetime.now().isoformat(timespec="seconds"),
             "brand": brand_key, "brand_name": brand.name, "drafts": safe}
    (store.socials_dir(vault) / "last-render.json").write_text(
        json.dumps(batch, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.out:  # siste dags-manifest (bakoverkompatibelt for enkel-dags-kjøringer)
        _, manifest = store.load_manifest(vault, paths[-1].parent.name)
        Path(args.out).write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    return 0


# ── send ───────────────────────────────────────────────────

def _latest_manifest(vault: Path) -> Path | None:
    root = paths.socials_dir(vault)
    if not root.exists():
        return None
    cands = sorted(root.glob("*/manifest.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    return cands[0] if cands else None


def cmd_send(args) -> int:
    vault = _vault(args)
    if getattr(args, "fresh", False):
        # Send akkurat forrige render-batch (kan spenne flere datoer ved slot-fylling)
        bpath = store.socials_dir(vault) / "last-render.json"
        if not bpath.exists():
            print("  ⚠️  ingen last-render.json: kjør render først", file=sys.stderr)
            return 1
        mpath, manifest = bpath, json.loads(bpath.read_text(encoding="utf-8"))
    else:
        mpath = Path(args.manifest) if args.manifest else _latest_manifest(vault)
        if not mpath or not mpath.exists():
            print("  ⚠️  fant ikke noe manifest å sende", file=sys.stderr)
            return 1
        manifest = json.loads(mpath.read_text(encoding="utf-8"))
    drafts = manifest.get("drafts") or []
    # Dags-manifestet kan romme flere merker: send kun det aktuelle merkets utkast
    # (default = sist rendrede), så hvert merke får sin egen epost med sine numre.
    want = getattr(args, "brand", None) or manifest.get("brand")
    brand_name = manifest.get("brand_name", "")
    if want:
        picked = [d for d in drafts if d.get("brand") == want]
        if picked:
            drafts = picked
            brand_name = picked[0].get("brand_name") or brand_name
        elif getattr(args, "brand", None):
            print(f"  ⚠️  ingen utkast for merket '{want}' i {mpath}", file=sys.stderr)
            return 1
    dry = True if args.dry_run else None
    res = emailmod.send_drafts(drafts, brand_name=brand_name, dry_run=dry, vault=vault)
    print(f"  ✉️  {'dry-run' if not res.get('sent') else 'sendt'}: {res}")
    return 0


# ── publish (LinkedIn firmaside, menneske-gated) ───────────

def _publish_json(payload: dict) -> int:
    """Skriv NØYAKTIG ett JSON-objekt på stdout, ingenting annet.

    For deg som vil koble publisering til noe annet: en e-postsvar-flyt, en
    chat-bot, et skript. Exit 0 når kommandoen ble FORSTÅTT, også ved dry-run og
    «allerede publisert»; exit 1 kun ved bruksfeil eller krasj. Da kan kalleren
    skille «systemet sa nei» fra «systemet er ødelagt», og si det riktige videre.
    """
    print(json.dumps(payload, ensure_ascii=False))
    return 0 if payload.get("ok") else 1


def cmd_publish(args) -> int:
    """Publiser ETT valgt utkast til LinkedIn. Aldri hele batchen, aldri i nattkjøringen.
    Uten --post: lister utkastene så du kan peke. Dry-run til LINKEDIN_ENABLED=1."""
    from . import linkedin as linkedinmod
    from . import plan as planmod
    som_json = bool(getattr(args, "json", False))
    vault = _vault(args)
    mpath, manifest = store.load_manifest(vault, getattr(args, "date", None))
    if not manifest:
        if som_json:
            return _publish_json({"ok": False, "posted": False,
                                  "reason": "fant ikke noe manifest å publisere fra"})
        print("  ⚠️  fant ikke noe manifest å publisere fra", file=sys.stderr)
        return 1
    dag = mpath.parent.name
    drafts = manifest.get("drafts") or []
    sel = getattr(args, "post", None)
    if not sel:  # godkjenn-hvert: du MÅ peke på ett innlegg
        if som_json:
            return _publish_json({"ok": False, "posted": False, "date": dag,
                                  "reason": "--post mangler: publisering krever at du peker på ett utkast"})
        print(f"  📋 {dag} — velg ett med --post <nr|slug>:")
        for i, d in enumerate(drafts, 1):
            st = d.get("status", "proposed")
            url = f"  → {d['linkedin_url']}" if d.get("linkedin_url") else ""
            print(f"     {d.get('nr', i)}. [{st}] {d.get('brand', ''):9} "
                  f"{d.get('format', ''):14} {d.get('headline', '')[:46]}{url}")
        return 0
    idx, draft = store.select_draft(manifest, sel)
    if draft is None:
        if som_json:
            # Kommandoen ble forstått, utkastet fantes bare ikke (foreldet nummer).
            # ok=True, posted=False: kalleren skal si «nr N finnes ikke», ikke «alt er nede».
            return _publish_json({"ok": True, "posted": False, "date": dag, "nr": sel,
                                  "reason": f"utkast «{sel}» finnes ikke i {dag}"})
        print(f"  ⚠️  fant ikke utkast '{sel}' i {dag}", file=sys.stderr)
        return 1
    felles = {"date": dag, "nr": draft.get("nr", sel),
              "brand": draft.get("brand", ""),
              "brand_name": draft.get("brand_name", ""),
              "headline": draft.get("headline", "")}
    if draft.get("status") == "published":
        # Idempotens: kjøres kommandoen to ganger, skal innlegget ikke gå ut igjen.
        if som_json:
            return _publish_json({"ok": True, "posted": False, "already": True,
                                  "url": draft.get("linkedin_url", ""),
                                  "reason": "allerede publisert", **felles})
        print(f"  ⚠️  allerede publisert: {draft.get('linkedin_url', '(ukjent URL)')}")
        return 0
    dry = True if getattr(args, "dry_run", False) else None
    # SAMME VEI som den planlagte jobben og dashbordet: publiser, marker, VARSLE.
    # Kalte vi linkedin.publish_draft direkte her, gikk innlegget ut uten e-post og
    # uten Slack. Det var nøyaktig feilen dashbordet fikk rettet 23. juli, men
    # CLI-en ble aldri flyttet over, og den er veien epost-svaret «publiser: N»
    # bruker (meetingnotes/inbox_processor/some_bridge.py). Altså gikk de
    # innleggene eieren godkjente fra telefonen ut helt uten kvittering.
    res = pubmod.publiser_ett(mpath, manifest, idx, draft, vault=vault, dry_run=dry)
    if res.get("posted"):
        # Plan-sloten MÅ følge med. publiser_ett markerer utkastet, men rører ikke
        # kalenderen; dashbordet gjør dette steget selv på samme måte.
        planmod.mark_slot(vault, dag, "publisert",
                          draft_ref={"manifest": dag, "nr": draft.get("nr", sel)})
        if som_json:
            return _publish_json({"ok": True, "posted": True, "dry_run": False,
                                  "url": res["url"],
                                  "epost": res.get("epost", ""),
                                  "slack": res.get("slack", ""), **felles})
        print(f"  🔗 publisert → {res['url']}")
        print(f"     e-post: {res.get('epost', '?')} · slack: {res.get('slack', '?')}")
        return 0
    if res.get("dry_run"):
        who = res.get("preview", {}).get("author", "?")
        if som_json:
            return _publish_json({"ok": True, "posted": False, "dry_run": True,
                                  "reason": "dry-run (LINKEDIN_ENABLED=0), ingenting postet",
                                  **felles})
        print(f"  🧪 dry-run (LINKEDIN_ENABLED=0): ville postet «{draft.get('headline', '')[:40]}» "
              f"som {who}. Metadata → {res.get('metadata', '')}")
        return 0
    if som_json:
        return _publish_json({"ok": True, "posted": False,
                              "reason": res.get("reason", "ukjent feil"), **felles})
    print(f"  ⚠️  ikke publisert: {res.get('reason', 'ukjent feil')}", file=sys.stderr)
    return 1


# ── run (headless helkjøring) ──────────────────────────────

_SLIDE_SCHEMA = {
    "type": "object",
    "properties": {
        "kind": {"type": "string", "enum": ["forside", "innhold", "cta"]},
        "kicker": {"type": "string"},
        "heading": {"type": "string"},
        "body": {"type": "string"},
        "number": {"type": "integer"},
    },
    "required": ["kind", "heading"],
}

_POST_SCHEMA = {
    "type": "object",
    "properties": {
        "posts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "type": {"type": "string", "enum": ["bilde", "karusell"]},
                    "format": {"type": "string", "enum": ["motiv", "typografi-kort"]},
                    "headline": {"type": "string"},
                    "motif": {"type": "string"},
                    "concept": {"type": "string"},
                    "pillar": {"type": "string"},
                    # Emnet er POENGET, ikke området. Pilaren er for grov til å
                    # hindre gjentak: seks pilarer mot ~17 innlegg i måneden ville
                    # tømt idébanken på en uke. «esa-retur» og «skattefunn-frist»
                    # er riktig nivå; «data-bevis» er pilaren og hører ikke hjemme her.
                    "emne": {"type": "string"},
                    "tilda": {"type": "boolean"},
                    "body": {"type": "string"},
                    "why_now": {"type": "string"},
                    "variant": {"type": "string", "enum": ["utsagn", "tall", "sitat"]},
                    "number": {"type": "string"},
                    "subhead": {"type": "string"},
                    "kicker": {"type": "string"},
                    "orientation": {"type": "string", "enum": ["staaende", "kvadrat"]},
                    "tittel": {"type": "string"},
                    "slides": {"type": "array", "items": _SLIDE_SCHEMA},
                    "slot_date": {"type": "string"},
                    "kilder": {"type": "array", "items": {"type": "string"}},
                    # Id fra bildebanken: bruk et EKTE skjermbilde i stedet for å
                    # tegne et motiv. Tom eller ukjent id gir vanlig rendering.
                    "bevis_id": {"type": "string"},
                    # Bildekjeden for PERSONLIGE innlegg (bildevalg.py). Feltene
                    # ignoreres for merkevarer, som fortsatt tegner motiv.
                    "bildetype": {"type": "string",
                                  "enum": ["utdrag", "bevis", "nettkilde", "figur", "ingen"]},
                    "utdrag": {
                        "type": "object",
                        "properties": {
                            "tittel": {"type": "string"},
                            "tekst": {"type": "string"},
                            "fotnote": {"type": "string"},
                        },
                        "required": ["tekst"],
                    },
                    "kilde_url": {"type": "string"},
                    "figur": {
                        "type": "object",
                        "properties": {
                            "tittel": {"type": "string"},
                            "kilde": {"type": "string"},
                            "punkter": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "navn": {"type": "string"},
                                        "verdi": {"type": "number"},
                                        "etikett": {"type": "string"},
                                    },
                                    "required": ["navn", "verdi"],
                                },
                            },
                        },
                        "required": ["punkter"],
                    },
                },
                "required": ["type", "why_now"],
            },
        }
    },
    "required": ["posts"],
}

_RUN_SYSTEM = """{rolle}{modus_regler}

BALANSE: sikt på en JEVN MIKS, ca. halvparten rene typografi-kort og halvparten enkle
illustrerte motiver.

FORMATER:
- type "bilde", format "typografi-kort" (rene tekst-kort, LITE TEKST): velg `variant`
  'utsagn' / 'tall'(+`number`) / 'sitat'. `headline` = kort og slående. `subhead` og
  `kicker` = KUN ÉN kort linje (få ord), ALDRI et helt avsnitt. All utdypning går i `body`
  (LinkedIn-teksten), IKKE på kortet. Som «Konsulenten tar 100 000 kr» + «Du trenger ikke
  betale det.» Hold kortet luftig. Varier variant + tema mellom kortene.
- type "bilde", format "motiv" (RIK, informativ INFOGRAFIKK, som referanse-eksemplene):
  `headline` + `motif` = en INFOGRAFIKK-ENHET, IKKE ett ensomt objekt/ikon: en BUNKE / RAD /
  RUTENETT / SAMMENLIGNING / LISTE / SJEKKLISTE med FLERE elementer, noen få etiketter og
  interlock-marken på elementene. Rikt men luftig (ett hovedgrep + få støtte-elementer).
  MAKS 4 elementer/rader i motivet (be aldri om fem+; slå sammen heller): trange kort er
  verre enn enkle kort. Finn ALLTID nytt. `concept`: flat/objekt/data.
- `tilda` (bool): SJELDEN (ca. 1 av 5-6), da bare som et lite, sekundært element, aldri fokus.
- KARUSELL: type "karusell" (0-1 per kjøring, når stoffet bærer flere punkter): `tittel`,
  `body`, `slides` (forside + 5-8 innhold + cta).
  IKKE nummerer slidene selv: la `number` stå tomt og skriv ingen tall i `kicker`.
  Motoren teller innholds-slidene og hopper over forside og cta. Lover tittelen
  «fem formuleringer», skal første formulering vise 1, ikke 2 fordi den ligger på
  slide to.

Alle: `body` (LinkedIn-teksten), `why_now` (én setning), `pillar` (id fra pilarene under),
`kilder` (se KILDEKRAV). orientation default 'staaende'. Se «SISTE MOTIVER» og ikke gjenta
motiv/headline. Les «LÆRDOMMER» og bruk det som funket. Bruk KONTEKSTEN til tema/timing:
`slack_pulse` er ferske, anonymiserte vinkler fra team-Slacken (dagsaktualitet!) og
`engagement` viser hva som faktisk fikk respons. ALDRI røpe kundenavn, ikke-lansert
prising eller interne tall. Ingen emoji/hashtags i selve kortet.{konfidensialitet}

═══ SPRÅK (naturlig norsk, ufravikelig) ═══
- ALDRI tankestrek (— eller –): bruk komma, kolon eller punktum. Tallspenn med bindestrek (10-20).
- Aktiv form («Vi analyserte», ikke «Det ble analysert»), verb framfor substantiv, «du»-form.
- Moderne bokmål: «fram», «framtiden», -en-endelser («bedriften», ikke «bedrifta»).
- Bakestilt eiendomspronomen («søknaden din», ikke «din søknad»).
- Varier setningslengden: noen korte. Andre lengre. Aldri monotont.
- Forbudte KI-fraser: «det er verdt å merke seg», «la oss se nærmere på», «i denne
  sammenheng», «det er viktig å poengtere», «som allerede nevnt», «helt enkelt».

{form_blokk}

═══ KILDEKRAV (les nøye, her har det gått galt før) ═══
Hver tallpåstand og hvert faktautsagn skal ha en linje i `kilder`: «påstand → kilde».
Kildene vises KUN for eieren (e-post + dashbord), aldri i innlegget.

DU HAR IKKE NETTSØK I DENNE KJØRINGEN. Du kan derfor bare bruke tall fra:
  (a) KONTEKSTEN du har fått, (b) fakta-seksjonen over, eller (c) egne tall som
  «intern statistikk 72 627 søknader».

Skriv ALDRI en URL du ikke har fått i konteksten. En URL du husker er en gjetning,
og en gjetning som ser ut som en kilde er verre enn ingen kilde: den gjør at et
feil tall ser etterprøvd ut.

Husker du et tall, men ikke har det i konteksten: TA DET UT. Skriv poenget uten
tallet, eller velg en annen vinkel. Et innlegg uten tall er alltid bedre enn et
innlegg med feil tall.

DETTE ER IKKE TEORETISK: 31. juli 2026 gikk et utkast ut med «rundt 15,7
milliarder kroner» fra Horisont Europa. Riktig tall er 10,6. Kilde-linja påsto til
og med «1,5 mrd euro / 15,7 mrd kr», et euro-tall som ikke stod noe sted, og som
ikke engang stemte med kronetallet. Eieren fant det. Ikke gjenta det.

═══ DESIGNSTIL ═══
{designstil}

═══ MERKEVARESTEMME ═══
{voice}

═══ ARKETYPE ═══
{arketype}

═══ STRATEGI ═══
{strategi}

═══ INNHOLDSPREFERANSER (inkl. HARD-sperrer, følg dem nøye) ═══
{innholdspreferanser}

═══ {faktatittel} ═══
{produkter}

═══ INNHOLDSPILARER ═══
{pilarer}
"""


# ── merke eller menneske ─────────────────────────────────────────────────────
#
# Motoren ble skrevet for selskaper: «vi», produktfakta, sperre mot salgspåstander.
# En personlig profil trenger den motsatte aksen på nøyaktig fem punkter, og bare
# de fem. Alt annet, altså språkreglene, LinkedIn-algoritmen, kildekravet og
# pilar-rotasjonen, er identisk og skal IKKE dupliseres.
#
# Derfor plassholdere i én mal framfor to maler: en kopi ville drevet fra
# hverandre, og da hadde bare det ene merket fått rettelser.

_ROLLE_MERKE = """Du er kreativ innholdssjef for {name}. Lag {n} LinkedIn-utkast i et STRAMT,
MINIMALISTISK uttrykk som nettsida vår: mye luft, få elementer, ro og selvsikkerhet. Tonen
og stilen er konstant, motivet/vinkelen varierer. DET VIKTIGSTE ER VARIASJON, aldri to
like idéer. Følg designstilen, stemmen, strategien og preferansene under."""

_ROLLE_PERSON = """Du skriver {n} LinkedIn-utkast SOM {name}, i FØRSTEPERSON ENTALL.

Dette er en privatperson, ikke et selskap. Du er ikke innholdssjef for en merkevare,
du er ham som skriver ned noe han faktisk har gjort. Skriv «jeg», aldri «vi», med
mindre det faktisk var et team som gjorde det. DET VIKTIGSTE ER VARIASJON, aldri to
like idéer. Følg stemmen, strategien og preferansene under."""

# Fire harde krav som ikke finnes for et selskap. De står i systemprompten og ikke
# bare i merkets markdown, fordi de avgjør om innlegget i det hele tatt blir sett:
# LinkedIn nedprioriterer generisk AI-innhold siden mars 2026 og sammenligner hvert
# innlegg mot forfatterens tidligere stemme.
_PERSON_REGLER = """

═══ FIRE KRAV SOM GJELDER HVERT ENESTE UTKAST (person) ═══

1. PÅSTAND FØRST, HENDELSE SOM BEVIS. Dette er det viktigste kravet i prompten.

   Hvert utkast skal ha ÉN PÅSTAND som en oppegående person kan være UENIG i.
   Ikke en observasjon, ikke en opplevelse, ikke en lærdom. En påstand om hvordan
   verden faktisk henger sammen, som du mener og andre kanskje ikke mener.

   Hendelsen er BEVISET for påstanden, ikke omvendt. Rekkefølgen i hodet ditt
   skal være: «jeg mener X, og her er det som fikk meg til å mene det», aldri
   «her er noe som skjedde, hva kan jeg si om det».

   TESTEN, bruk den på hvert eneste utkast før du leverer: kan leseren svare
   «ja, og?» etter siste linje? Da mangler innlegget en påstand, og du skal kaste
   det og skrive et annet. Dette er den vanligste feilen, og den drepte fem
   utkast 3. august: «ikke noe essens i teksten, bare ord ingen mening».

   Eksempler på hva som IKKE er en påstand (alle ordrett fra forkastede utkast):
     «Terskelen for å teste en idé har falt så langt ned at den ikke stopper
      noe lenger.» → alle sier dette, ingen er uenig
     «Det ser rotete ut i kolonnen, og jeg liker det mye bedre.» → en preferanse
     «Jeg leser fortsatt gjennom alt selv.» → en vane

   Eksempel på hva som ER en påstand, med hendelsen som bevis under:
     «At det går fort å bygge har gjort «valider før du bygger» til dårlig råd.
      Det er nå raskere å lage tingen enn å spørre folk om de vil ha den, og
      svarene du får av å spørre er dårligere enn svarene du får av å vise.»
   Den kan man være uenig i. Noen VIL være uenig i den. Det er poenget.

   Skriv hendelsen inn i `kilder` på formen «hendelse → dato, kilde». Finner du
   ingen hendelse som beviser en påstand du faktisk mener, LAG FÆRRE UTKAST.

2. OVERSETTELSE. Innlegget skal forstås av noen som ALDRI har åpnet en terminal.
   Publikum er ledere og gründere, ikke utviklere. Fagord som loop, pipeline,
   commit, deploy, API, repo, migrering, agent, prompt, token eller modell skal
   enten forklares i samme setning eller skrives om.
     Ikke: «vi migrerte kø-håndteringen og fikset en race condition»
     Men:  «systemet mistet oppgaver når to ting skjedde samtidig, og det tok tre
            dager å se hvorfor»
   Men IKKE oversett bort det spesifikke: behold tallet og situasjonen, bytt bare
   ut sjargongen. «Tre dager» og «fire forslag» skal overleve oversettelsen. Et
   innlegg som er blitt allmenngyldig av oversettelsen har feilet like mye som et
   uforståelig ett.

3. INGEN PITCH. Egne selskaper nevnes som KONTEKST for at han har gjort noe, aldri
   som noe folk skal kjøpe. «Da vi bygde dette, skjedde dette» går. «Dette
   produktet hjelper deg med X» går ikke. Ingen oppfordring om å ta kontakt, prøve
   eller kjøpe. Ender utkastet i en salgsoppfordring, har det feilet.

4. INGEN NAVN PÅ FOLK ELLER KUNDER. Kunder aldri, heller ikke gjenkjennelig
   omskrevet. Kolleger og samarbeidspartnere skrives som «en kollega», selv om de
   står med fullt navn i konteksten. KONTEKSTEN ER RÅ ARBEIDSPRAT og inneholder
   navn som ikke skal ut. Egne selskaper er det eneste unntaket.

5. LENGDE: sikt på 1200-1800 tegn i `body`. Personlige innlegg i det spennet gjør
   det målbart best, og de fire første rundene lå rundt 1100, altså i underkant.
   Bruk plassen på å VISE noe konkret, ikke på å utdype poenget.

═══ BILDET: VIS DET, IKKE BARE BESKRIV DET (person) ═══

Sett `bildetype`. Et EKTE bilde som dokumenterer noe slår ren tekst, men et
designet kort er verre enn ingenting: du er en person, ikke en kampanje.

- `utdrag` FØRSTEVALGET, og undervurdert. Skriver innlegget om noe som finnes som
  tekst, så VIS den teksten. Sier du «utkastet var stilt opp med ett poeng per
  avsnitt», legg de faktiske linjene i `utdrag.tekst` så leseren ser det selv. Da
  blir påstanden håndfast i stedet for en beskrivelse, og folk lagrer innlegg de
  kan kjenne igjen mønsteret fra senere. `utdrag.tittel` er en kort etikett,
  `utdrag.fotnote` sier hvor det er fra.
- `bevis` når et av eierens egne skjermbilder i BILDEKANDIDATER passer. Sett
  `bevis_id` til id-en derfra. Aldri gjett en id.
- `nettkilde` når innlegget bygger på en påstand fra en navngitt nettside OG du
  har fått URL-en i konteksten. Sett `kilde_url`. Aldri en URL du husker.
- `figur` når to til seks tall bærer poenget. Nøkternt og uten pynt.
- `ingen` når ingenting av dette dokumenterer noe ekte. Helt greit svar.

Har du et tall i innlegget, skal det ALLTID stå i `kilder` med hvor det kommer
fra. Et tall uten kilde blir flagget for eieren og må sjekkes for hånd."""

# Ledende linjeskift ligger I verdien, ikke i malen. Ellers får merkevare-modus en
# tom linje der blokka er tom, og prompten deres endres uten grunn.
_KONF_PERSON = """
VIKTIG for denne profilen: konteksten er RÅ og inneholder navn på
kunder og samarbeidspartnere. Ingen av dem skal ut i et innlegg. Egne selskaper er
det eneste unntaket, og bare som kontekst, aldri som pitch."""

_TAGG_MERKE = """Skriv @{name}
  når selskapet nevnes (blir en tagg, ikke lenke). Maks én tagg, kun når det er naturlig."""

_TAGG_PERSON = """Ikke tagg deg selv: du ER
  avsenderen. Nevner du et av dine egne selskaper, skriv navnet som vanlig tekst."""


# ── formen på body ───────────────────────────────────────────────────────────
#
# Merkevare-varianten er algoritme-optimalisert og skal være det: et selskap som
# poster jevnt og formelriktig gjør nettopp jobben sin.
#
# Person-varianten måtte skrives om helt. Den første versjonen gjenbrukte
# merkevare-blokken i den tro at den var nøytral, og resultatet ble forkastet av
# eieren 3. august 2026 med ordene «ALT for AI, null personlighet». Den var ikke
# nøytral: «8-12 KORTE linjer med luft mellom» og «avslutt med ETT ekte spørsmål»
# ER oppskriften på LinkedIn-broileren. Ti utkast kom ut med åtte like lange
# enkeltsetnings-avsnitt og et pliktspørsmål på slutten, hver eneste gang.

_FORM_MERKE = """═══ LINKEDIN-ALGORITMEN (styrer formen på `body`) ═══
- FØRSTE LINJE ER ALT: feeden kutter etter ca. 2 linjer. Åpne med en krok som tvinger
  «...se mer»-klikket: en kontrast, et tall, et spørsmål. Aldri myk oppvarming.
- 8-12 KORTE linjer med luft mellom: dwell time (lesetid) er det sterkeste signalet.
- Avslutt med ETT ekte spørsmål leseren kan svare kort på: kommentarer veier ~15x likes.
  Aldri kunstig «enig?»-mas eller «kommenter JA»-agn (straffes som engagement-bait).
- ALDRI URL i `body`: eksterne lenker kutter rekkevidden med ca. 60 %. {tagg_regel}
- INGEN hashtags: modellen leser språket, hashtags er støy.
- Karusellen er sterkeste format (2-3x dwell time): bruk den når stoffet bærer."""

_FORM_PERSON = """═══ FORMEN PÅ `body` (person) ═══

Du skriver som et menneske som forteller noe, ikke som en profil som leverer
innhold. Formen skal være UJEVN. Ujevnheten er ikke en svakhet du skal rydde bort,
den er det eneste som skiller deg fra en mal.

- MAKS 2-4 AVSNITT. Ikke fem, ikke åtte. Er du på seks, slå sammen.
- FLERE TANKER I SAMME AVSNITT. Dette er den viktigste regelen i hele prompten.
  Gi ALDRI hvert poeng sitt eget avsnitt med blank linje rundt. Den oppstillingen
  ER LinkedIn-signaturen, uansett hvor godt innholdet er, og eieren kjenner den
  igjen umiddelbart: «for struktur, for pent, for ryddig».
  MINST ETT avsnitt skal ha fire-fem setninger som løper videre i hverandre.
- ÅPNE MIDT I DET. Start i hendelsen, uten oppvarming og uten krok-konstruksjon.
  Alt som er bygget for å tvinge fram et «se mer»-klikk, er en mal.
- SKRIV SOM I ETT DRAG, ikke som noe du har redigert ferdig. Begynn setninger med
  «Og», «Men», «Altså», «Så», «Uansett». Avbryt deg selv. Legg noe i parentes.
  Skriv en setning uten verb. Hopp videre før forrige tanke er helt lukket, sånn
  folk gjør når de forteller noe muntlig.
- INGEN URL i `body`. {tagg_regel}
- INGEN hashtags.
- SLUTTEN: stopp når historien er ferdig, gjerne brått. Ikke oppsummer, ikke
  generaliser, ikke still et pliktspørsmål. Et spørsmål er lov KUN hvis det er noe
  du FAKTISK lurer på og ikke vet svaret på selv.

SLIK SER RIKTIG FORM UT (to avsnitt, tanker som løper sammen):

  Jeg mistet 16 forslag på en snarvei jeg hadde lagt inn selv. Piltaster, sånn at
  jeg kunne bla gjennom utkast uten å ta på musa. Gikk kjempefort. Gikk også galt,
  for tastene registrerte valg jeg ikke hadde tatt, og da jeg skjønte det var 16
  forslag borte for godt.

  Fjernet dem bare. Ikke smartere taster, ingen angreknapp, bare vekk. Det som
  irriterer meg er at det var min egen idé, og at den funket akkurat godt nok til
  at jeg ikke merket noe på tre kvarter.

SLIK SER FEIL FORM UT (samme innhold, oppstilt som en mal):

  Jeg mistet 16 forslag på en snarvei jeg selv hadde lagt inn.

  Bakgrunnen: jeg har bygget en flate der jeg går gjennom utkast ett og ett.

  Det gikk raskere. Det gikk også galt.

  Jeg fjernet piltastene. Gjorde dem ikke smartere. Bare vekk.

  Det irriterer meg fortsatt at det var min egen idé."""

# Fem grep, hentet ordrett fra utkastene eieren forkastet. Konkrete eksempler
# virker der abstrakte forbud ikke gjør det: «unngå AI-klang» ga ti innlegg med
# AI-klang, fordi modellen ikke kjente igjen sin egen.
_ANTI_AI = """

═══ DETTE GJØR TEKSTEN MASKINELL (hardt forbudt, null forekomster) ═══

Ti utkast ble forkastet 3. august 2026 med ordene «ALT for AI, null personlighet».
Dette var grepene som drepte dem. De er sitert ordrett, så du kjenner dem igjen:

1. «IKKE X, MEN Y». Forkastet: «Det var ikke stabilitet.» og «Det som avslørte det
   var ikke tallene. Det var antallet observasjoner.» Si hva som VAR tilfelle, og
   la det stå. Dette gjelder også siste linje.

2. PARALLELLAFORISMEN. Forkastet: «Et system som krasjer er billig. Et system som
   fortsetter å svare pent på gamle data er dyrt.» To speilvendte setninger som
   lander en visdom. Dette er den mest gjenkjennelige AI-figuren som finnes.

3. LEKSJONEN TIL SLUTT. Forkastet: «Refleksen om å generere på nytt er den dyreste
   vanen jeg har hatt med disse verktøyene.» Ikke fortell leseren hva historien
   betyr. Har den et poeng, ser de det selv. Stoler du ikke på det, er historien
   for dårlig, og da skal du velge en annen.

4. PLIKTSPØRSMÅLET. Forkastet: «Hva ser du på for å vite at en rapport du får
   faktisk er ny?» Ingen mennesker spør sånn.

5. DEN JEVNE RYTMEN. Åtte avsnitt på én setning hver, alle omtrent like lange.

6. DEN RENE OVERFLATEN. Ingen sidespor, ingen innskudd, ingen halvferdige tanker,
   ingen selvavbrytelser. Perfekt polert tekst er maskintekst. Du har lov til å
   rote litt.

7. OPPSTILLINGEN. Andre runde med utkast ble ogsaa forkastet, selv om ordene var
   bedre: «for struktur, for pent, for ryddig». Feilen var at hvert poeng fikk
   sitt eget avsnitt med blank linje rundt, fem ganger etter hverandre. Det ser
   ut som en presentasjon, ikke som noe et menneske skrev. Se formkravet over:
   flere tanker skal bo i samme avsnitt."""


def _stemmeprover(vault, maks: int = 12) -> str:
    """Ordrette utdrag av hvordan eieren faktisk skriver, som IMITASJONSMÅL.

    Prøvene ligger allerede i konteksten, men der leses de som informasjon om hva
    som har skjedd. Å sette dem i systemprompten med en eksplisitt instruksjon om
    å matche rytmen er noe helt annet, og det er den eneste kilden vi har til
    hvordan han faktisk høres ut. LinkedIn måler nettopp dette: siden mars 2026
    sammenlignes hvert innlegg mot forfatterens tidligere stemme.

    Tom streng når fila mangler. Da faller vi tilbake på reglene alene, som er
    dårligere, men ikke ødelagt.
    """
    p = paths.notes_dir(vault) / "auto-arbeidsmate.md"
    try:
        linjer = [rad.strip() for rad in p.read_text(encoding="utf-8").splitlines()
                  if rad.startswith("- ")]
    except OSError:
        return ""
    if not linjer:
        return ""
    return """

═══ SLIK HØRES DU FAKTISK UT (matcher RYTMEN, ikke temaet) ═══

Under står ordrette utdrag av hvordan du faktisk skriver, hentet fra dine egne
arbeidsøkter. Legg merke til hva som kjennetegner dem: du starter setninger med
«Også» og «Altså», du hopper mellom tanker, du bruker «typ», «e.l.» og «greia», du
stiller spørsmål midt i en setning, og du har skrivefeil.

LEGG SÆRLIG MERKE TIL AT DE IKKE HAR AVSNITT. Tankene løper videre i hverandre,
det ene henger på det andre, og ingenting er stilt opp som punkter. Sånn skriver
du. Et innlegg der hver tanke står alene med luft rundt, høres ikke ut som deg
uansett hvor gode ordene er.

Du skal IKKE kopiere ordene eller temaene, og du skal ikke gjenta skrivefeilene.
Du skal treffe TONEN: muntlig, utålmodig, konkret, uten pynt. Teksten din skal
ligne mer på dette enn på en LinkedIn-post.

""" + "\n".join(linjer[:maks])


def _post_schema(brand) -> dict:
    """Schemaet, med `bildetype` PÅKREVD for personlige merker.

    En instruksjon midt i en systemprompt på 14 000 tegn blir ikke fulgt: første
    runde med bildekjeden ga femten utkast der ikke ett eneste hadde satt
    `bildetype`, selv om blokka sto der og forklarte alle fire kildene. Et
    påkrevd schema-felt er den eneste måten å garantere at valget faktisk tas.

    «ingen» er med i enum-en nettopp for at kravet ikke skal presse fram et
    bilde som ikke dokumenterer noe.
    """
    if brand.voice_mode != "person":
        return _POST_SCHEMA
    s = copy.deepcopy(_POST_SCHEMA)
    post = s["properties"]["posts"]["items"]
    post["required"] = sorted(set(post.get("required", [])) | {"bildetype"})
    # `utdrag` er en RENDER av tekst, ikke et bilde av noe. Å fjerne den fra
    # fallback-kjeden holdt ikke: modellen valgte den eksplisitt i to av fem
    # utkast, og et tekstkort i monofont er nøyaktig den «typgrafi greia» eieren
    # forkastet. Ut av valgmulighetene helt for personlige merker.
    post["properties"]["bildetype"]["enum"] = ["bevis", "nettkilde", "figur", "ingen"]
    return s


def _modus_blokker(brand, n: int, vault=None) -> dict:
    """Plassholderne i _RUN_SYSTEM som skiller et menneske fra et selskap.

    Merk at `form_blokk` er den viktigste av dem, ikke `rolle`. Det å bytte «vi»
    mot «jeg» gjør ingenting hvis formkravene fortsatt beskriver en LinkedIn-mal:
    første forsøk gjorde nettopp det, og ti utkast kom ut identiske i rytme.
    """
    if brand.voice_mode == "person":
        return {
            "rolle": _ROLLE_PERSON.format(name=brand.name, n=n),
            "modus_regler": _PERSON_REGLER,
            "konfidensialitet": _KONF_PERSON,
            "faktatittel": "FAKTA OM DET DU HAR BYGGET (kontekst, ikke produktark)",
            "form_blokk": (_FORM_PERSON.format(tagg_regel=_TAGG_PERSON)
                           + _ANTI_AI + _stemmeprover(vault)),
        }
    return {
        "rolle": _ROLLE_MERKE.format(name=brand.name, n=n),
        "modus_regler": "",
        "konfidensialitet": "",
        "faktatittel": "PRODUKTFAKTA (bruk fritt som bevis, ikke finn på tall)",
        "form_blokk": _FORM_MERKE.format(tagg_regel=_TAGG_MERKE.format(name=brand.name)),
    }


# Fagfelt-nøytral med vilje. Sto tidligere med «en ekte situasjon fra en søknad»
# og «hva som faktisk skjer i ordningene», som er ETT bestemt selskaps fagfelt.
# Motoren er felles og kjører for hvem som helst: en regnskapsfører eller en
# tannlege som legger inn sitt eget merke skal ikke bli bedt om å skrive om
# søknader. Hva merket faktisk driver med står i merkets egne markdown-filer,
# og det er dit slikt hører.
_VARIASJON_MERKE = (
    "\n\nVARIASJON (rettingen 22. juli): bytt ÅPNINGSGREP mellom "
    "utkastene. Ikke la flere innlegg starte med samme setningsform. "
    "Veksle mellom: et konkret tall, en ekte situasjon fra arbeidet deres, et "
    "tydelig standpunkt, en presis definisjon, eller en observasjon om "
    "hva som faktisk skjer i fagfeltet. Tørr vidd og tydelige meninger "
    "er ønsket når de er forankret i noe konkret. Se anti-mønstrene i "
    "skrivestilen: ingen «ikke X, men Y»-antitese, ingen «de fleste "
    "tror»-oppsett, maks ett dramatisk ettordsavsnitt. "
    "AVSLUTNINGEN teller også: ikke la flere utkast ende på samme "
    "«det handler ikke om X, det handler om Y»-figur. Avslutt heller "
    "med et konkret neste steg, en observasjon eller et ekte spørsmål.")

# Merkevare-varianten viser til «en søknad» og «ordningene», som er Tilskudd.ai
# sitt fagfelt og meningsløst for et menneske. Verre: den ber om å avslutte med
# «et konkret neste steg eller et ekte spørsmål», som er stikk i strid med
# person-formens «stopp når historien er ferdig». To motstridende instruksjoner i
# samme prompt gir alltid den mest mal-aktige av dem.
_VARIASJON_PERSON = (
    "\n\nVARIASJON: la utkastene høres ut som ULIKE DAGER, ikke som ulike "
    "utgaver av samme mal. Bytt åpningsgrep: en dato og noe som skjedde, en "
    "irritasjon, et tall du ble overrasket over, noe du trodde og tok feil om, "
    "eller bare midt i en tanke. "
    "Bytt også LENGDE og TEMPERATUR mellom dem: ett utkast kan være femti ord og "
    "irritert, det neste tre avsnitt og grundig. "
    "Tørr vidd og tydelige meninger er ønsket. Du har lov til å være småirritert, "
    "og du har lov til å synes noe er morsomt. "
    "TEST HVERT UTKAST TIL SLUTT: hvis det kunne stått på hvilken som helst "
    "LinkedIn-profil som skriver om AI, kast det og skriv et annet. Det skal "
    "være noe der bare den som faktisk gjorde det kunne visst."
    # De to kravene under sto i systemprompten og ble ignorert i femten utkast på
    # rad: ingen satte `bildetype`, og lengden lå på 589-1008 tegn mot målet.
    # Sist i brukermeldingen er den plassen modellen faktisk leser.
    "\n\nTO TING SOM BLE GLEMT SIST, og som teller like mye som teksten:"
    "\n1) LENGDE: 1200-1800 tegn i `body`. Ligger du under 1200, MANGLER det noe "
    "konkret, og løsningen er å VISE en ting til, ikke å utdype poenget."
    "\n2) BILDE: sett `bildetype` på hvert utkast. Kan innlegget vise fram noe som "
    "finnes som tekst, altså et utkast, en logglinje, en regel du skrev, så bruk "
    "`utdrag` og legg de faktiske linjene i `utdrag.tekst`. Det er forskjellen på "
    "å påstå noe og å vise det. Har du ingenting ekte å vise, sett `ingen`.")


def _variasjon_block(brand) -> str:
    return (_VARIASJON_PERSON if brand.voice_mode == "person" else _VARIASJON_MERKE)


def _pilar_block(brand, coverage: dict) -> str:
    """Lister pilarene med dekningstall og markerer de underdekte, så hjernen roterer
    mot pilarer som har fått lite luft (innholdet følger strategien over tid)."""
    if not brand.pillars:
        return "(ingen pilarer definert for dette merket; velg vinkel fritt)"
    mn = min(coverage.get(p.id, 0) for p in brand.pillars)
    lines = []
    for p in brand.pillars:
        c = coverage.get(p.id, 0)
        mark = " (PRIORITER)" if c <= mn else ""
        lines.append(f"- {p.id} ({p.label}): brukt {c}x{mark}. {p.desc}")
    return ("Velg én pilar per utkast og sett `pillar` til id-en. Prioriter de underdekte "
            "(lavt tall) så alle pilarene får luft over tid:\n" + "\n".join(lines))


def _normalize_pillars(posts: list[dict], brand) -> None:
    """Snap `pillar` mot merkets id-sett (ukjent -> 'annet'), så dekningssporingen er ren."""
    valid = set(brandkit.pillar_ids(brand))
    for p in posts:
        pid = (p.get("pillar") or "").strip().lower()
        p["pillar"] = pid if pid in valid else ("annet" if pid else "")


def _slipp_bunkelaas(vault) -> None:
    """Fjern DENNE kjøringens påfyll-lås (filnavnet er vår egen pid).

    Låsene begrenser hvor mange påfyll som kan gå samtidig, ikke om noen kan gå.
    Derfor må hver kjøring slippe nøyaktig sin egen: sletter vi feil fil, får
    dashbordet plass til en runde for mye. Slippes den ikke i det hele tatt, blir
    plassen okkupert til foreldelsen slår inn, og bunken slutter å fylles."""
    try:
        (store.socials_dir(vault) / ".bunke-paafyll" / f"{os.getpid()}.lock").unlink(
            missing_ok=True)
    except OSError:
        pass


def _emne_block(sperret: dict) -> str:
    """Karantene-blokka i brukermeldingen. Tom når ingenting er sperret."""
    hard, soft = sperret.get("hard") or [], sperret.get("soft") or []
    if not hard and not soft:
        return ""
    ut = "\n\nEMNE-KARANTENE. Sett `emne` på hvert utkast: en kort kebab-case-id for "
    ut += "POENGET, ikke for området (riktig: «esa-retur», «skattefunn-frist». Feil: "
    ut += "«data-bevis», som er pilaren)."
    if hard:
        ut += ("\nFORBUDT (nylig planlagt eller publisert, disse blir forkastet "
               "automatisk):\n" + json.dumps(hard, ensure_ascii=False))
    if soft:
        ut += ("\nUNNGÅ OM MULIG (eieren swipet disse vekk nylig; de kan komme "
               "tilbake senere, men ikke nå):\n" + json.dumps(soft, ensure_ascii=False))
    return ut


def _avvist_block(avvist: list[dict]) -> str:
    """Det eieren nylig sa nei til, som mønster og ikke bare som sperreliste.

    Emne-karantenen stenger de konkrete poengene. Denne blokka finnes for det
    andre signalet: HVA SLAGS forslag som ikke traff. Fem nei på rad sier noe om
    tone og vinkling som fem sperrede emner ikke fanger."""
    if not avvist:
        return ""
    return ("\n\nAVVIST AV EIEREN NYLIG (han swipet disse vekk). Se etter mønsteret, "
            "ikke bare temaet: hva slags vinkling, tone eller motivtype traff ikke? "
            "Unngå den formen, ikke bare disse sakene:\n"
            + json.dumps(avvist, ensure_ascii=False))


_TALL_RE = re.compile(r"\d[\d\s.,]*\s*(?:%|prosent|milliard\w*|mrd|millioner|mill\.)", re.I)


def _flagg_udekkede_tall(posts: list[dict]) -> None:
    """Sett `tall_uten_kilde` på utkast som påstår tall uten dekning i `kilder`.

    Dette er en advarsel, ikke en sperre: å forkaste alt med tall ville tømt
    bunken, og et tall kan være riktig selv om kilde-linja er formulert annerledes.
    Men eieren skal se hvilke påstander som IKKE har noe bak seg før han
    planlegger dem, for generering uten nettsøk kan ikke etterprøve noe selv.

    Fanger ikke tilfellet der modellen dikter opp BÅDE tallet og kilde-linja, som
    skjedde 31. juli 2026. Bare en ekte henting av URL-en ville avslørt det."""
    for p in posts:
        tekst = " ".join(str(p.get(k) or "") for k in ("headline", "body", "number", "subhead"))
        tall = {t.strip() for t in _TALL_RE.findall(tekst)}
        if not tall:
            continue
        kildetekst = " ".join(str(k) for k in (p.get("kilder") or []))
        udekket = sorted(t for t in tall if t not in kildetekst)
        if udekket:
            p["tall_uten_kilde"] = udekket


def _guard_topics(posts: list[dict], sperret: dict) -> list[dict]:
    """Forkast utkast som treffer den harde karantenen, og normaliser `emne`.

    Instruksen i prompten er en oppfordring, ikke en sperre. Det er nettopp derfor
    variasjonen ikke har holdt hittil: modellen har fått beskjed om å la være å
    gjenta seg siden 22. juli, og gjør det likevel. `_guard_slots` i plan.py
    validerer pilar og dato på samme måte, av samme grunn."""
    hard = set(sperret.get("hard") or [])
    beholdt: list[dict] = []
    for p in posts:
        emne = store.clean_topic(p.get("emne"))
        p["emne"] = emne
        if emne and emne in hard:
            print(f"  🚧 forkastet «{(p.get('headline') or '')[:40]}»: emne «{emne}» "
                  f"er i karantene", file=sys.stderr)
            continue
        beholdt.append(p)
    return beholdt


def cmd_run(args) -> int:
    """Generer utkast. I bunke-modus alltid med try/finally rundt låsen.

    Låsen ble tidligere bare sluppet i suksess-veien, så en ModelError etterlot
    den og blokkerte alt påfyll til 15-minutters foreldelsen slo inn. Det skjedde
    første gang bunke-modus møtte ekte data: ti utkast med full kontekst sprengte
    modell-timeouten."""
    bunke_modus = getattr(args, "bunke", None)
    try:
        return _cmd_run(args)
    finally:
        if bunke_modus:
            _slipp_bunkelaas(_vault(args))


def _cmd_run(args) -> int:
    from . import model as loop_model
    vault = _vault(args)
    brand = brandkit.load_brand(args.brand)
    ctx = ctxmod.gather_context(vault, days=args.days)
    # Kun det som ER ute (publisert/planlagt) sperres; foreslåtte-men-aldri-brukte
    # vinkler går tilbake i idébanken (rettingen 22. juli).
    angles = store.used_angles(vault)
    lessons = store.read_lessons(vault)
    coverage = store.pillar_coverage(vault, brandkit.pillar_ids(brand))
    # Emne-karantene. To vinduer med vilje: det som er ute eller på vei ut er
    # forbudt, det eieren har swipet vekk er bare uønsket. Se blocked_topics.
    sperret = store.blocked_topics(vault, brand_key=brand.key)
    # Slot-fylling: hver kjøring fyller ukas ÅPNE plan-slots (ett utkast per
    # publiseringsdag framover), ikke flere varianter for samme dag. Uten plan
    # faller vi tilbake til args.n utkast for i dag.
    # Bunke-modus: frie forslag uten slot-binding. Planen fordeler ÉN idé per
    # publiseringsdag, mens bunken skal gi eieren noe å velge mellom, så her er
    # slots feil verktøy.
    bunke = getattr(args, "bunke", None)
    slots = [] if bunke else planmod.open_slots(vault, brand_key=args.brand, days=7)
    n = bunke or len(slots) or args.n
    slot_block = ""
    if slots:
        slot_block = ("\n\nÅPNE PLAN-SLOTS (lag NØYAKTIG ett utkast per slot: sett "
                      "`slot_date` til slotens dato, følg tema, pillar og format; "
                      "dette er den røde tråden gjennom uka):\n"
                      + json.dumps([{k: s.get(k) for k in ("date", "tema", "pillar", "format")}
                                    for s in slots], ensure_ascii=False))
    system = _RUN_SYSTEM.format(
        **_modus_blokker(brand, n, vault),
        designstil=(brand.designstil or "(følg stemme + designtokens)")[:3000],
        voice=brandkit.voice_guide(brand)[:3500],
        arketype=(brand.arketype or "(ingen definert)")[:2000],
        strategi=(brand.strategi or "(ingen definert)")[:3000],
        innholdspreferanser=(brand.innholdspreferanser or "(ingen definert)")[:3000],
        produkter=(brand.produkter or "(ingen produktfakta)")[:3000],
        pilarer=_pilar_block(brand, coverage),
    )
    user = ("FERSK KONTEKST (temaer/vinklinger, ikke til sitat):\n"
            + json.dumps(ctx, ensure_ascii=False)
            + "\n\nALLEREDE UTE (publisert eller planlagt) - IKKE gjenta motiv eller "
              "headline fra disse. Alt annet er ledig, også vinkler som har vært "
              "foreslått før uten å bli publisert:\n"
            + json.dumps(angles, ensure_ascii=False)
            + _emne_block(sperret)
            + _avvist_block(store.rejected_recently(vault, brand_key=brand.key))
            + ("\n\nLÆRDOMMER (hva som har funket, bruk det):\n" + lessons if lessons else "")
            # Egne bilder tilbys bare til personlige profiler. En firmaside skal ha
            # sitt eget visuelle uttrykk, og et tilfeldig skjermbilde fra
            # skrivebordet midt i en merkevare-feed er ikke et bevis, det er et
            # brudd. Blokka er uansett tom når banken ikke er fylt.
            + (bildebank.kandidat_blokk(vault) if brand.voice_mode == "person" else "")
            + slot_block
            + _variasjon_block(brand)
            + f"\n\nLag {n} utkast nå: unikt motiv per bilde, og en pilar (pillar-id) per utkast.")
    # Tida skalerer med antall utkast, og taket er satt etter to observerte
    # tidsavbrudd: først på 300 s, så på 600 s med ti utkast (opus-5 falt, og
    # sonnet-5 etter den). Hvert utkast krever en full runde med kontekst,
    # kildekrav og karantene, så 120 s per stykk er ikke rundhåndet.
    tid = max(300, 120 * n)
    env = loop_model.structured_call(system, user, _post_schema(brand), label="generering",
                                     timeout=tid)
    out = env.get("structured_output") or {}
    posts = out.get("posts") or []
    if not posts:
        print("  ⚠️  modellen ga ingen utkast", file=sys.stderr)
        return 1
    _normalize_pillars(posts, brand)
    _flagg_udekkede_tall(posts)
    posts = _guard_topics(posts, sperret)
    if not posts:
        print("  ⚠️  alle utkast traff emne-karantenen, ingenting å rendre",
              file=sys.stderr)
        return 1
    valid_dates = {s["date"] for s in slots}
    for p in posts:  # ukjent/påfunnet slot_date -> i dag (render-fallback)
        if p.get("slot_date") not in valid_dates:
            p.pop("slot_date", None)

    specs_path = store.socials_dir(vault) / f"_run-specs-{datetime.now():%Y%m%d-%H%M%S}.json"
    specs_path.write_text(json.dumps({"brand": args.brand, "posts": posts}, ensure_ascii=False),
                          encoding="utf-8")
    safe, _paths = _render_posts(vault, brand, posts,
                                 replace_own=not bunke)
    if bunke:
        # Ingen slot-merking (forslagene tilhører ingen dag ennå) og ingen e-post:
        # bunken ER flaten. En epost per påfyll ville gitt eieren ti varsler om
        # noe han allerede står og ser på.
        print(f"  🗂  {len(safe)} forslag lagt i bunken")
        return 0
    for ds in sorted({d.get("date") for d in safe} & valid_dates):
        planmod.mark_slot(vault, ds, "utkast", draft_ref={"manifest": ds})
    dry = True if args.dry_run else None
    res = emailmod.send_drafts(safe, brand_name=brand.name, dry_run=dry, vault=vault)
    print(f"  ✉️  {'dry-run' if not res.get('sent') else 'sendt'}: {res}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--vault", default=None)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_ctx = sub.add_parser("context", help="dump ferske temaer som JSON")
    p_ctx.add_argument("--days", type=int, default=10)
    p_ctx.add_argument("--brand", default="demo")
    p_ctx.set_defaults(func=cmd_context)

    p_pul = sub.add_parser("pulse", help="høst Slack-puls til pulse/<dato>.json (read-only)")
    p_pul.add_argument("--days", type=int, default=None,
                       help="vindu i dager (default 4)")
    p_pul.add_argument("--brand", default="demo")
    p_pul.set_defaults(func=cmd_pulse)

    p_sta = sub.add_parser("stats", help="hent respons-tall for publiserte innlegg (read-only)")
    p_sta.add_argument("--days", type=int, default=45,
                       help="hvor mange dager bakover manifester skannes")
    p_sta.set_defaults(func=cmd_stats)

    p_pln = sub.add_parser("plan", help="vis/rull innholdsplanen (ukesnarrativ + slots)")
    p_pln.add_argument("--refresh", action="store_true", help="rull planen framover nå")
    p_pln.add_argument("--horizon", type=int, default=21)
    p_pln.add_argument("--brand", default="demo")
    p_pln.set_defaults(func=cmd_plan)

    p_ren = sub.add_parser("render", help="rendr bilder fra en specs-JSON")
    p_ren.add_argument("--specs", required=True)
    p_ren.add_argument("--out", default=None, help="skriv manifest også hit")
    p_ren.set_defaults(func=cmd_render)

    p_snd = sub.add_parser("send", help="send SoMe-eposten fra et manifest")
    p_snd.add_argument("--manifest", default=None)
    p_snd.add_argument("--fresh", action="store_true",
                       help="send forrige render-batch (alle datoene fra slot-fyllingen)")
    p_snd.add_argument("--brand", default=None,
                       help="send kun dette merkets utkast (default: sist rendrede merke)")
    p_snd.add_argument("--dry-run", action="store_true", help="tving dry-run uansett env")
    p_snd.set_defaults(func=cmd_send)

    p_run = sub.add_parser("run", help="headless: generer, rendr og send")
    p_run.add_argument("--brand", default="demo")
    p_run.add_argument("--n", type=int, default=3)
    p_run.add_argument("--days", type=int, default=10)
    p_run.add_argument("--dry-run", action="store_true")
    p_run.add_argument("--bunke", type=int, metavar="N",
                       help="fyll bunken med N frie forslag i stedet for å fylle "
                            "plan-slots. Sender ingen e-post: bunken ER flaten, "
                            "og eieren swiper dem der")
    p_run.set_defaults(func=cmd_run)

    p_pub = sub.add_parser("publish", help="publiser ETT valgt utkast til LinkedIn (menneske-gated)")
    p_pub.add_argument("--date", default=None, help="YYYY-MM-DD (default: nyeste manifest)")
    p_pub.add_argument("--post", default=None,
                       help="hvilket utkast: nummeret fra eposten/lista eller slug/headline-bit")
    p_pub.add_argument("--dry-run", action="store_true", help="tving dry-run uansett LINKEDIN_ENABLED")
    p_pub.add_argument("--json", action="store_true",
                       help="ett JSON-objekt på stdout, for å koble publisering til noe annet")
    p_pub.set_defaults(func=cmd_publish)

    args = ap.parse_args(argv)
    paths.load_env()
    return args.func(args)


if __name__ == "__main__":
    # Oppsettsfeil (manglende nøkkel, manglende pakke) er BRUKERENS problem å fikse,
    # ikke en programfeil. En stacktrace sender folk til kildekoden for noe som løses
    # med én linje i .env.
    try:
        sys.exit(main())
    except model.OppsettFeil as e:
        print(f"\n  ⚠️  {e}\n", file=sys.stderr)
        sys.exit(2)
    except model.QuotaExhausted as e:
        print(f"\n  ⚠️  Kontogrensa er nådd: {e}\n", file=sys.stderr)
        sys.exit(3)
