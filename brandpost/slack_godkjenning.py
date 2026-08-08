"""slack_godkjenning — la en kollega styre et merke fra Slack.

Bakgrunnen (6. august 2026): et merke kan eies av noen andre enn den som drifter
maskinen. De skal kunne godkjenne innlegg uten tilgang til dashbordet, uten VPN og
uten å se de andre merkenes utkast.

Flyten er to steg, med Slack som eneste grensesnitt:

    1. `post_forslag()`  → nummererte forslag som ÉN melding i merkets kanal
    2. `les_og_publiser()` → leser svar i TRÅDEN og publiserer det som er godkjent

Svar tolkes som «publiser 2» eller bare «2, 4». Speiler e-postflyten som allerede
virker, og med vilje samme døde syntaks: ett tall eller en liste med tall. Ikke
naturlig språk, for da må noen gjette hva som ble ment, og gjetting som publiserer
er en dårlig idé.

TRÅDSVAR og ikke kanalmeldinger. Da kan flere merker dele en kanal, og «2» er
entydig fordi tråden sier hvilke to. Det er også hvordan folk faktisk svarer.

IDEMPOTENS er hele risikoen her. Et svar som leses to ganger må ikke publisere to
ganger, og `publiser_ett` sjekker ikke selv. Derfor lagres hver behandlede
svar-`ts` i ``BRANDPOST_STATE_DIR/slack-godkjent.json``, og et innlegg som alt har status
`published` hoppes over uansett.
"""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

from . import brandkit, paths, publisher, store
from . import slack as slackmod
from .fsutil import atomic_write_text

LEDGER = "slack-godkjent.json"

# «publiser 2», «publiser: 2 og 4», «2, 4», «Publiser 3.»
# Tallene hentes ut for seg; ordet «publiser» er valgfritt, fordi et bart tall i
# en tråd om nummererte forslag ikke kan bety noe annet.
_SVAR = re.compile(r"\b(?:publiser|publish|ja)\b|^\s*\d+(?:\s*[,ogx&+]\s*\d+)*\s*$", re.I)
_TALL = re.compile(r"\d+")


def _ledger_sti(vault: Path | None = None) -> Path:
    return paths.state_dir_for_workspace(vault) / LEDGER


def les_ledger(vault: Path | None = None) -> dict:
    try:
        return json.loads(_ledger_sti(vault).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def skriv_ledger(data: dict, vault: Path | None = None) -> None:
    p = _ledger_sti(vault)
    p.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(p, json.dumps(data, ensure_ascii=False, indent=1) + "\n")


def _token_env(brand) -> str:
    """Navnet på miljøvariabelen med tokenet for merkets workspace.

    getattr med fallback: et merke lastet fra en eldre profil har ikke feltet, og
    da er svaret det globale tokenet, ikke en feil."""
    return getattr(brand, "slack_token_env", "") or ""


def _kanal(brand) -> str:
    return getattr(brand, "slack_channel", "") or ""


def tolk_svar(tekst: str) -> list[int]:
    """Hvilke forslagsnumre ble godkjent i denne meldingen?

    Tom liste betyr «ingenting å gjøre», og det er det normale: de fleste
    meldinger i en kanal er ikke godkjenninger. Å tolke for villig her er
    farligere enn å tolke for strengt, siden utfallet er en publisering.
    """
    t = (tekst or "").strip()
    if not t or not _SVAR.search(t):
        return []
    # Maks tre tall: et svar med tolv tall er noen som limte inn noe annet.
    return [int(n) for n in _TALL.findall(t)[:3] if 0 < int(n) < 1000]


def post_forslag(brand_key: str, *, vault: Path | None = None, dag: str = "",
                 maks: int = 5, dry_run: bool | None = None) -> dict:
    """Post dagens uvurderte forslag som én melding i merkets kanal.

    Returnerer {"sendt": bool, "ts": str, "antall": int, ...}. `ts` er trådens
    rot, og den lagres i ledgeren: uten den vet ikke steg 2 hvor det skal lete.
    """
    v = paths.workspace(vault)
    brand = brandkit.load_brand(brand_key)
    kanal, token_env = _kanal(brand), _token_env(brand)
    if not kanal:
        return {"sendt": False, "reason": f"{brand_key} har ingen [slack].channel"}

    dag = dag or date.today().isoformat()
    try:
        mpath, manifest = store.load_manifest(v, dag)
    except Exception:  # noqa: BLE001
        return {"sendt": False, "reason": f"fant ikke manifest for {dag}"}
    if not manifest:
        return {"sendt": False, "reason": f"tomt manifest for {dag}"}

    kandidater = [d for d in (manifest.get("drafts") or [])
                  if d.get("brand") == brand_key
                  and d.get("status") == "proposed"
                  and not d.get("verdict")][:maks]
    if not kandidater:
        return {"sendt": False, "reason": "ingen uvurderte forslag"}

    linjer = [f"*{brand.name}* har {len(kandidater)} forslag til LinkedIn "
              f"({dag}).", ""]
    for d in kandidater:
        nr = d.get("nr")
        kropp = " ".join((d.get("body") or "").split())
        linjer.append(f"*{nr}. {d.get('headline', '(uten overskrift)')}*")
        linjer.append(f"{kropp[:400]}{'…' if len(kropp) > 400 else ''}")
        if d.get("why_now"):
            linjer.append(f"_Hvorfor nå: {d['why_now']}_")
        linjer.append("")
    linjer.append("Svar i tråden med nummeret på det som skal ut, "
                  "for eksempel «publiser 2» eller «2, 4». "
                  "Svarer du ingenting, går ingenting ut.")

    r = slackmod.send_message("\n".join(linjer), channel=kanal,
                              token_env=token_env, dry_run=dry_run)
    if not r.get("sent"):
        return {"sendt": False, "antall": len(kandidater),
                "reason": r.get("reason", "tørrkjørt" if r.get("dry_run") else "ukjent"),
                "dry_run": r.get("dry_run", False), "text": r.get("text", "")}

    led = les_ledger(vault)
    traader = led.setdefault("traader", {})
    traader[r["ts"]] = {"brand": brand_key, "dag": dag, "kanal": kanal,
                        "nr": [d.get("nr") for d in kandidater]}
    skriv_ledger(led, vault)
    return {"sendt": True, "ts": r["ts"], "antall": len(kandidater), "kanal": kanal}


def les_og_publiser(*, vault: Path | None = None, dry_run: bool | None = None) -> dict:
    """Gå gjennom åpne tråder, les svar, og publiser det som er godkjent."""
    v = paths.workspace(vault)
    led = les_ledger(vault)
    traader = led.get("traader") or {}
    behandlet = set(led.get("behandlede_svar") or [])
    ut = {"publisert": 0, "hoppet": 0, "feilet": 0, "svar": 0}

    for ts, info in list(traader.items()):
        brand_key = info.get("brand", "")
        try:
            brand = brandkit.load_brand(brand_key)
        except Exception:  # noqa: BLE001
            continue
        token_env = _token_env(brand)
        for melding in slackmod.read_replies(info.get("kanal", ""), ts,
                                             token_env=token_env):
            svar_ts = melding.get("ts", "")
            if not svar_ts or svar_ts in behandlet:
                continue
            numre = tolk_svar(melding.get("text", ""))
            if not numre:
                continue
            ut["svar"] += 1
            # Merk som behandlet FØR publisering. Krasjer vi midt i, er risikoen
            # et innlegg som ikke gikk ut, ikke ett som gikk ut to ganger.
            behandlet.add(svar_ts)
            for nr in numre:
                res = _publiser_nr(v, info.get("dag", ""), brand_key, nr,
                                   dry_run=dry_run)
                if res.get("posted"):
                    ut["publisert"] += 1
                elif res.get("already"):
                    ut["hoppet"] += 1
                else:
                    ut["feilet"] += 1
                    print(f"  ⚠️  nr {nr} ikke publisert: "
                          f"{res.get('reason', 'ukjent')}")

    led["behandlede_svar"] = sorted(behandlet)[-500:]  # nok til å hindre gjentak
    skriv_ledger(led, vault)
    return ut


def _publiser_nr(v: Path, dag: str, brand_key: str, nr: int, *,
                 dry_run: bool | None = None) -> dict:
    """Publiser ett nummer fra en dag, via den ene felles veien."""
    try:
        mpath, manifest = store.load_manifest(v, dag)
    except Exception as e:  # noqa: BLE001
        return {"posted": False, "reason": f"manifest: {e}"}
    if not manifest:
        return {"posted": False, "reason": f"tomt manifest for {dag}"}
    for idx, d in enumerate(manifest.get("drafts") or []):
        if d.get("nr") != nr or d.get("brand") != brand_key:
            continue
        if d.get("status") == "published":
            # Andre sperre mot dobbeltpublisering, uavhengig av ledgeren.
            return {"posted": False, "already": True, "reason": "allerede publisert"}
        return publisher.publiser_ett(mpath, manifest, idx, d, vault=v,
                                      dry_run=dry_run)
    return {"posted": False, "reason": f"fant ikke nr {nr} for {brand_key} i {dag}"}


def main(argv: list[str] | None = None) -> int:
    """To kommandoer, én per steg. Kjøres som to launchd-jobber med ulik takt:
    forslagene én gang om dagen, lesingen ofte nok til at et svar føles besvart.

        python -m brandpost.slack_godkjenning --post akser
        python -m brandpost.slack_godkjenning --les
    """
    import argparse

    ap = argparse.ArgumentParser(
        description="Slack-styrt godkjenning: post forslag, les svar, publiser")
    ap.add_argument("--post", metavar="MERKE",
                    help="steg 1: post dagens forslag i merkets kanal")
    ap.add_argument("--les", action="store_true",
                    help="steg 2: les svar i åpne tråder og publiser")
    ap.add_argument("--vault", default=None)
    ap.add_argument("--dag", default="", help="YYYY-MM-DD, default i dag")
    ap.add_argument("--maks", type=int, default=5)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    paths.load_env()
    v = paths.workspace(args.vault)
    dry = True if args.dry_run else None

    if args.post:
        r = post_forslag(args.post, vault=v, dag=args.dag, maks=args.maks, dry_run=dry)
        if r.get("sendt"):
            print(f"  💬 {r['antall']} forslag → {r['kanal']} (tråd {r['ts']})")
            return 0
        if r.get("dry_run"):
            print(f"  🧪 tørrkjørt, {r.get('antall', 0)} forslag ville gått ut:\n")
            print(r.get("text", ""))
            return 0
        print(f"  ⚠️  ikke sendt: {r.get('reason', 'ukjent')}")
        # Ingen forslag er en normal tilstand, ikke en feil: da har eieren alt
        # vurdert dagens bunke, og jobben skal ikke lyse rødt for det.
        return 0 if "ingen uvurderte" in str(r.get("reason", "")) else 1

    if args.les:
        r = les_og_publiser(vault=v, dry_run=dry)
        print(f"  📬 {r['svar']} svar: {r['publisert']} publisert, "
              f"{r['hoppet']} hoppet, {r['feilet']} feilet")
        return 1 if r["feilet"] else 0

    ap.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
