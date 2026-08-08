"""publisher — vi eier publiseringen: legg ut planlagte utkast til avtalt tid.

valget 22. juli 2026. Alternativet var å la LinkedIn eie planleggingen (den
publiserer selv, men vi vet ikke når, så varselet måtte komme av etterkant-polling).
Nå lagrer vi tidspunktet selv, publiserer via API akkurat da, og sender e-posten
i samme øyeblikk.

Kompromisset eieren tok bevisst: dette krever at maskinen er våken til avtalt tid.
Derfor tar jobben IGJEN forsinkelser i stedet for å hoppe over dem, men den nekter
å publisere noe som er mer enn CATCHUP_LIMIT_H timer på etterskudd: et innlegg som
skulle ut i går morges bør et menneske se på før det plutselig dukker opp i dag.
Slike varsles i stedet, og blir liggende som planlagt.

Kjøres jevnlig (routine/launchd):
    .venv/bin/python -m brandpost.social.publisher
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

from .mailer import no_datestamp, send_email
from . import paths
from . import brandkit, linkedin, store
from . import slack as slackmod
from .email import _doc, _draft_image

# Jobben startes av en tidsstyrt kjøring, ikke fra et skall med repoets .env lastet.
# Uten dette ser den ingen LINKEDIN_*-nøkler, faller til dry-run og «lykkes» hvert
# kvarter uten å publisere noe. Overstyrer aldri variabler som alt er satt.
try:
    from dotenv import load_dotenv
    paths.load_env()
except Exception:  # noqa: BLE001
    pass

# Hvor sent er for sent? Kortere enn et døgn, så en natt med nedetid ikke gir
# et morgeninnlegg på kvelden, men langt nok til å tåle en treg oppstart.
CATCHUP_LIMIT_H = float(os.environ.get("BRANDPOST_CATCHUP_H") or "6")


def linkedin_owns(draft: dict) -> bool:
    """Er innlegget planlagt inne i LinkedIn (nettleserveien), sånn at LinkedIn
    publiserer det selv? `scheduled_confirmed` er LinkedIns egen bekreftede
    tidslinje, og settes KUN av nettleserveien. Publiserer vi det i tillegg via
    API-et, står samme innlegg to ganger på firmasida uten at noe feiler."""
    return bool((draft.get("scheduled_confirmed") or "").strip())


def _due_rows(vault: Path, now: datetime) -> list[dict]:
    out: list[dict] = []
    for mpath in sorted(store.socials_dir(vault).glob("*/manifest.json")):
        try:
            manifest = json.loads(mpath.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for idx, d in enumerate(manifest.get("drafts") or []):
            if not isinstance(d, dict) or d.get("status") != "planlagt":
                continue
            raw = (d.get("scheduled_at") or "").strip()
            if not raw:
                continue
            try:
                when = datetime.fromisoformat(raw)
            except ValueError:
                continue
            if when <= now:
                out.append({"mpath": mpath, "manifest": manifest, "idx": idx,
                            "draft": d, "when": when,
                            "forsinket_t": (now - when).total_seconds() / 3600})
    return sorted(out, key=lambda r: r["when"])


def due_drafts(vault: Path, *, now: datetime | None = None) -> list[dict]:
    """Utkast som er planlagt, har passert tidspunktet sitt, OG er våre å publisere.
    Hver rad har manifest-stien og indeksen, så kalleren kan skrive status tilbake.
    Innlegg LinkedIn allerede eier holdes utenfor: se `linkedin_owns`."""
    return [r for r in _due_rows(vault, now or datetime.now())
            if not linkedin_owns(r["draft"])]


def linkedin_owned_due(vault: Path, *, now: datetime | None = None) -> list[dict]:
    """Forfalte utkast LinkedIn publiserer selv. Skilles ut så de kan RAPPORTERES
    i stedet for å forsvinne i stillhet: null linjer i loggen ville lest som
    «ingenting å gjøre», ikke som «noen andre gjør det»."""
    return [r for r in _due_rows(vault, now or datetime.now())
            if linkedin_owns(r["draft"])]


def _publisert_epost(draft: dict, url: str, *, vault: Path | None,
                     dry_run: bool | None = None) -> dict:
    """Varsel om at ETT innlegg nettopp gikk ut, med innholdet som ble publisert."""
    headline = (draft.get("headline") or "").strip() or "(uten overskrift)"
    body = (draft.get("body") or "").strip()
    png = _draft_image(draft)
    cid = "publisert1"
    bilde = (f'<img src="cid:{cid}" alt="" '
             f'style="width:100%;max-width:520px;border-radius:12px;margin:14px 0">'
             if png else "")
    krop = "".join(
        f'<p style="margin:0 0 10px">{linje}</p>'
        for linje in (body.split("\n") if body else []) if linje.strip())
    inner = (
        f'<h1>Publisert på LinkedIn</h1>'
        f'<div class="meta">{no_datestamp()}</div>'
        f'<p class="muted">Dette gikk ut nå, lagt ut av planleggeren.</p>'
        f'<h2>{headline}</h2>'
        f'{bilde}'
        f'{krop}'
        f'<p style="margin:16px 0 0"><a href="{url}">Se innlegget på LinkedIn</a></p>'
    )
    return send_email(f"✅ Publisert: {headline[:60]}",
                      _doc(inner, preheader="Innlegg publisert på LinkedIn"),
                      vault=vault, dry_run=dry_run,
                      inline_images={cid: png} if png else None)


def _publisert_slack(draft: dict, url: str, *, dry_run: bool | None = None) -> dict:
    """Samme varsel som e-posten, men i kanalen der arbeidet foregår.

    MERKENAVNET er med her, i motsetning til i e-posten. En felles kanal får
    innlegg fra flere merker, og «Publisert på LinkedIn» uten avsender er ubrukelig
    når både firmasidene og en personlig profil rapporterer samme sted.
    `draft["brand_name"]` har ligget klart hele tiden.

    Kort med vilje: overskrift og lenke. Hele brødteksten hører hjemme i e-posten
    og på LinkedIn, ikke som en vegg av tekst i en kanal.
    """
    kanal, varsle, token_env = _slack_for(draft)
    if not varsle:
        return {"sent": False, "dry_run": False, "reason": "merket varsler ikke i Slack"}
    headline = (draft.get("headline") or "").strip() or "(uten overskrift)"
    merke = (draft.get("brand_name") or draft.get("brand") or "").strip()
    hvem = f"*{merke}*" if merke else "Publisert"
    tekst = f"{hvem} la nettopp ut på LinkedIn:\n*{headline}*"
    if url:
        tekst += f"\n{url}"
    return slackmod.send_message(tekst, channel=kanal, token_env=token_env,
                                 dry_run=dry_run)


def _slack_for(draft: dict) -> tuple[str, bool, str]:
    """(kanal, skal varsle, token_env) for merket bak utkastet.

    Kanal "" betyr den globale. `varsle=False` er hvordan en personlig profil
    holdes ute av en delt arbeidskanal: hva eieren legger ut på sin egen profil
    er ikke teamets sak. `token_env` finnes fordi et merke kan ligge i et helt
    annet Slack-workspace, og da holder det ikke å bytte kanal.

    Best effort: klarer vi ikke å laste profilen, varsler vi i den globale
    kanalen. Et firmainnlegg som går ut uten kvittering er verre enn ett varsel
    for mye, og en ulesbar merkemappe skal ikke stanse noe."""
    try:
        b = brandkit.load_brand(draft.get("brand", ""))
    except Exception:  # noqa: BLE001
        return "", True, ""
    return b.slack_channel, b.slack_varsle, b.slack_token_env


def _urn_i(url: str) -> str:
    """Innleggs-ID-en inne i en LinkedIn-URL, uansett om den er skrevet som
    ugcPost, share eller activity. Tallet er det samme innlegget."""
    m = re.search(r"urn:li:(?:ugcPost|share|activity):(\d+)", url or "")
    return m.group(1) if m else ""


MATCH_TEGN = 60          # nok til å skille innlegg, kort nok til å tåle småredigering


def _nokkeltekst(tekst: str) -> str:
    """Sammenlignbar form av et innlegg: småbokstaver, kollapset mellomrom, avkortet."""
    return re.sub(r"\s+", " ", (tekst or "").strip().lower())[:MATCH_TEGN]


def _finn_post(draft: dict, etter_id: dict, etter_tekst: dict) -> dict | None:
    """Finn LinkedIn-innlegget som svarer til utkastet.

    ID først, men den holder ikke alene: LinkedIn gir SAMME innlegg ulike ID-er
    (vi lagret urn:li:activity:…, API-et svarer urn:li:share:… med et annet tall).
    Derfor faller vi tilbake på innleggsteksten, og kun når den peker på nøyaktig
    ett innlegg. Flere treff betyr at vi ikke vet, og da skriver vi ingenting."""
    treff = etter_id.get(_urn_i(draft.get("linkedin_url", "")))
    if treff:
        return treff
    kandidater = etter_tekst.get(_nokkeltekst(draft.get("body", "")))
    return kandidater[0] if kandidater and len(kandidater) == 1 else None


def backfill_published_at(vault: Path | None = None, *, hentet: list[dict] | None = None,
                          now: datetime | None = None) -> list[str]:
    """Fyll inn published_at på innlegg som ble publisert før vi begynte å lagre
    tidspunktet. Fasit hentes fra LinkedIn (publishedAt), ikke gjettes fra dagsmappa.

    Finner vi ikke innlegget hos LinkedIn, lar vi utkastet være heller enn å skrive
    en dato vi ikke vet: en gjettet publiseringsdato er verre enn ingen.
    Returnerer nøklene som ble fylt."""
    poster = hentet if hentet is not None else linkedin.fetch_org_posts()
    etter_id = {_urn_i(p.get("id", "")): p for p in poster if _urn_i(p.get("id", ""))}
    etter_tekst: dict[str, list[dict]] = {}
    for p in poster:
        n = _nokkeltekst(p.get("commentary", ""))
        if n:
            etter_tekst.setdefault(n, []).append(p)
    fylt: list[str] = []
    for mpath in sorted(store.socials_dir(vault).glob("*/manifest.json")):
        try:
            manifest = json.loads(mpath.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        endret = False
        for i, d in enumerate(manifest.get("drafts") or []):
            if not isinstance(d, dict) or d.get("status") != "published":
                continue
            if (d.get("published_at") or "").strip():
                continue
            treff = _finn_post(d, etter_id, etter_tekst)
            if not treff or not treff.get("publishedAt"):
                continue
            naar = datetime.fromtimestamp(treff["publishedAt"] / 1000)
            d["published_at"] = naar.isoformat(timespec="minutes")
            fylt.append(f"{mpath.parent.name}#{d.get('nr', i + 1)}")
            endret = True
        if endret:
            store.atomic_write_json(mpath, manifest)
    return fylt


def publiser_ett(mpath: Path, manifest: dict, idx: int, draft: dict, *,
                 vault: Path | None, dry_run: bool | None = None) -> dict:
    """Publiser ETT utkast, marker det, og varsle på e-post og i Slack. ÉN vei,
    brukt av den planlagte jobben, av Publiser-knappen i dashbordet og av CLI-en:
    da kan de ikke gli fra hverandre, slik de gjorde da knappen postet uten å sende
    varselet, og slik CLI-en gjorde helt til 6. august.

    Varselet kan aldri velte en vellykket publisering: innlegget ER ute, og en
    varslingsfeil skal rapporteres, ikke rulles tilbake.

    Hvert varsel har SIN EGEN try/except. Med én felles ville en død SMTP-server
    stanset Slack-meldingen, og de to har ingenting med hverandre å gjøre."""
    res = dict(linkedin.publish_draft(draft, dry_run=dry_run))
    if not res.get("posted"):
        return res
    url = res.get("url", "")
    store.mark_published(mpath, manifest, idx, url)
    try:
        ep = _publisert_epost(draft, url, vault=vault)
        res["epost"] = "sendt" if ep.get("sent") else "dry-run"
    except Exception as e:  # noqa: BLE001
        res["epost"] = f"feilet: {type(e).__name__}: {e}"
    try:
        sl = _publisert_slack(draft, url)
        res["slack"] = ("sendt" if sl.get("sent")
                        else "dry-run" if sl.get("dry_run")
                        else f"feilet: {sl.get('reason', 'ukjent')}")
    except Exception as e:  # noqa: BLE001
        res["slack"] = f"feilet: {type(e).__name__}: {e}"
    return res


def publish_due(vault: Path, *, now: datetime | None = None,
                dry_run: bool | None = None) -> dict:
    """Publiser alt som har forfalt. Returnerer {publisert, hoppet, feilet}."""
    now = now or datetime.now()
    rader = due_drafts(vault, now=now)
    tall = {"publisert": 0, "hoppet": 0, "feilet": 0}

    for r in linkedin_owned_due(vault, now=now):
        tall["hoppet"] += 1
        key = f"{r['mpath'].parent.name}#{r['draft'].get('nr')}"
        print(f"  ⏭  {key} er planlagt inne i LinkedIn ({r['draft'].get('scheduled_confirmed')}). "
              f"LinkedIn legger det ut selv, så vi rører det ikke.")

    if not rader:
        if not tall["hoppet"]:
            print("Ingenting forfalt.")
        return tall

    for r in rader:
        d, key = r["draft"], f"{r['mpath'].parent.name}#{r['draft'].get('nr')}"
        if r["forsinket_t"] > CATCHUP_LIMIT_H:
            tall["hoppet"] += 1
            print(f"  ⏭  {key} «{(d.get('headline') or '')[:40]}» er "
                  f"{r['forsinket_t']:.1f} t på etterskudd (grense {CATCHUP_LIMIT_H} t). "
                  f"Blir liggende som planlagt, sett nytt tidspunkt i dashbordet.")
            continue
        try:
            res = publiser_ett(r["mpath"], r["manifest"], r["idx"], d,
                               vault=vault, dry_run=dry_run)
        except Exception as e:  # noqa: BLE001
            tall["feilet"] += 1
            print(f"  ⚠️  {key}: {type(e).__name__}: {e}")
            continue
        if res.get("dry_run") and not res.get("posted"):
            # Uventet tørrkjøring er en STILLE feil: innlegget skulle ut, og alt ser
            # vellykket ut mens ingenting skjer. Telles som feil når det ikke var bedt
            # om, så jobben avslutter rødt i stedet for å «lykkes» hvert kvarter.
            if dry_run:
                tall["hoppet"] += 1
                print(f"  🧪 {key}: tørrkjøring, ingenting postet")
            else:
                tall["feilet"] += 1
                print(f"  ⚠️  {key} SKULLE VÆRT PUBLISERT, men LinkedIn er ikke skrudd på "
                      f"(LINKEDIN_ENABLED / manglende token). Ingenting postet.")
            continue
        if not res.get("posted"):
            tall["feilet"] += 1
            print(f"  ⚠️  {key}: ikke publisert ({res.get('reason', 'ukjent')})")
            continue
        tall["publisert"] += 1
        print(f"  ✅ {key} «{(d.get('headline') or '')[:44]}» → {res.get('url', '')}")
        # BEGGE varslene i loggen. Med bare e-posten der ser en tapt
        # Slack-melding ut som om alt gikk bra, og det er nettopp den typen
        # stillhet som gjorde at feil publiseringsjobb fikk stå i en uke.
        print(f"      e-post: {res.get('epost', 'ukjent')} · "
              f"slack: {res.get('slack', 'ukjent')}")
    return tall


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Publiser planlagte SoMe-utkast som har forfalt, og varsle på e-post")
    ap.add_argument("--vault", default=None)
    ap.add_argument("--dry-run", action="store_true",
                    help="vis hva som ville blitt publisert, uten å poste")
    ap.add_argument("--backfill-datoer", action="store_true",
                    help="hent publiseringstidspunkt fra LinkedIn for eldre innlegg")
    args = ap.parse_args(argv)
    vault = paths.workspace(args.vault)
    if args.backfill_datoer:
        fylt = backfill_published_at(vault)
        print(f"Fylte publiseringsdato på {len(fylt)}: {', '.join(fylt) or 'ingen'}")
        return 0
    tall = publish_due(vault, dry_run=True if args.dry_run else None)
    print(f"Ferdig: {tall['publisert']} publisert, {tall['hoppet']} hoppet, "
          f"{tall['feilet']} feilet.")
    return 0 if not tall["feilet"] else 1


if __name__ == "__main__":
    sys.exit(main())
