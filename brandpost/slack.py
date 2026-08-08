"""slack — valgfritt Slack-varsel når noe er publisert.

Samme rolle som `mailer`: et TILLEGG, aldri bæresøylen. Uten token tørrkjører alt,
og publiseringen går like fullt gjennom. En fersk kloning skal ikke kunne poste i
noens Slack ved et uhell.

Miljø:
    BRANDPOST_SLACK_ENABLED   1 for å faktisk sende (alt annet = tørrkjøring)
    BRANDPOST_SLACK_TOKEN     Slack-token med `chat:write`
    BRANDPOST_SLACK_CHANNEL   kanal-ID, f.eks. C0BNC1DTB0V

Kanal-ID og ikke kanalnavn: navn kan endres uten at noen tenker over det, og
`chat.postMessage` godtar begge, men en ID peker på samme kanal for alltid.

Hvorfor et eget token-navn når oppsettet allerede har et Slack-token: dette repoet
er motoren og skal kunne kjøre for hvem som helst. Å lese en variabel som heter
`NOTATER_*` ville bundet den til ett bestemt privat oppsett. Verdien kan godt være
den samme.

FLERE WORKSPACES: et merke kan ligge i et helt annet Slack-workspace, og da holder
det ikke å bytte kanal-ID. `[slack].token_env` i merkets profile.toml oppgir navnet
på en egen miljøvariabel. Aldri selve tokenet: profile.toml ligger i git.

LESING er med her, ikke bare posting. Grunnen er godkjenningsflyten: et merke kan
styres av en kollega som ikke har tilgang til dashbordet, og da postes forslagene
i en kanal og godkjennes med et svar i tråden. Uten lesing er den halve flyten.
"""

from __future__ import annotations

import os
import time

import requests

_POST_URL = "https://slack.com/api/chat.postMessage"
_HIST_URL = "https://slack.com/api/conversations.history"
_REPLIES_URL = "https://slack.com/api/conversations.replies"


def enabled() -> bool:
    return (os.environ.get("BRANDPOST_SLACK_ENABLED") or "").strip().lower() in (
        "1", "true", "yes", "on")


def _token(token_env: str | None = None) -> str:
    """Tokenet for dette merket, eller det globale.

    Et merke kan ligge i et HELT ANNET Slack-workspace, og da er kanal-ID alene
    ikke nok: tokenet må også være et annet. Et merke oppgir da navnet på sin egen
    miljøvariabel (`[slack].token_env` i profile.toml), aldri selve tokenet, som
    ikke har noe i en fil som ligger i git å gjøre.
    """
    if token_env:
        egen = (os.environ.get(token_env) or "").strip()
        if egen:
            return egen
    return (os.environ.get("BRANDPOST_SLACK_TOKEN") or "").strip()


def _channel(channel: str | None = None) -> str:
    return (channel or os.environ.get("BRANDPOST_SLACK_CHANNEL") or "").strip()


def send_message(text: str, *, channel: str | None = None, token_env: str | None = None,
                 dry_run: bool | None = None, session=None) -> dict:
    """Post en melding til Slack, eller tørrkjør.

    KASTER ALDRI. Returnerer {"sent": bool, "dry_run": bool, ...}, samme kontrakt
    som `mailer.send_email`, av samme grunn: dette kalles ETTER at et innlegg er
    ute på LinkedIn. Et varsel som feiler skal rapporteres, aldri velte noe som
    allerede har skjedd.

    `session` finnes for testene, samme mønster som nettfunksjonene i linkedin.py,
    så `FakeSession` fra tests/test_linkedin.py faller rett inn.
    """
    tørr = (not enabled()) if dry_run is None else bool(dry_run)
    kanal = _channel(channel)
    if tørr:
        return {"sent": False, "dry_run": True, "channel": kanal, "text": text}
    if not kanal:
        return {"sent": False, "dry_run": False, "reason": "ingen kanal satt"}
    token = _token(token_env)
    if not token:
        mangler = token_env or "BRANDPOST_SLACK_TOKEN"
        return {"sent": False, "dry_run": False, "reason": f"ingen {mangler}"}

    sess = session or requests
    # Tre forsøk med backoff på 429, som lesesiden gjør. Slack svarer 200 med
    # {"ok": false} på logiske feil, så statuskoden alene sier ingenting.
    for _ in range(3):
        try:
            r = sess.post(_POST_URL,
                          json={"channel": kanal, "text": text,
                                "unfurl_links": False, "unfurl_media": False},
                          headers={"Authorization": f"Bearer {token}",
                                   "Content-Type": "application/json; charset=utf-8"},
                          timeout=20)
        except Exception as e:  # noqa: BLE001
            return {"sent": False, "dry_run": False,
                    "reason": f"{type(e).__name__}: {e}"}
        if getattr(r, "status_code", 200) == 429:
            time.sleep(int(r.headers.get("Retry-After", "3")) + 1)
            continue
        try:
            d = r.json()
        except Exception:  # noqa: BLE001
            return {"sent": False, "dry_run": False, "reason": "ugyldig svar fra Slack"}
        if d.get("ok"):
            return {"sent": True, "dry_run": False, "channel": kanal,
                    "ts": d.get("ts", "")}
        # Slack sier hva som er galt i klartekst («not_in_channel»,
        # «missing_scope», «channel_not_found»). Ta det med videre: det er
        # forskjellen på et varsel eieren kan fikse og et mysterium.
        return {"sent": False, "dry_run": False,
                "reason": f"slack: {d.get('error', 'ukjent feil')}"}
    return {"sent": False, "dry_run": False, "reason": "slack: rate limit"}


def read_replies(channel: str, thread_ts: str, *, token_env: str | None = None,
                 session=None) -> list[dict]:
    """Svarene i en tråd, nyeste sist. Tom liste ved enhver feil.

    Trådsvar og ikke kanalmeldinger: forslaget postes som én melding, og svarene
    henger under den. Da kan flere merker dele en kanal uten at svarene blandes,
    og «publiser 2» er entydig fordi tråden sier hvilke to.

    Krever `channels:history` (offentlig kanal) eller `groups:history` (privat),
    som lesetokenene allerede har.
    """
    token = _token(token_env)
    if not token or not channel or not thread_ts:
        return []
    sess = session or requests
    try:
        r = sess.get(_REPLIES_URL,
                     params={"channel": channel, "ts": thread_ts, "limit": 100},
                     headers={"Authorization": f"Bearer {token}"}, timeout=20)
        d = r.json()
    except Exception:  # noqa: BLE001
        return []
    if not d.get("ok"):
        return []
    # Første melding i en tråd ER forslaget vårt. Den skal ikke tolkes som svar.
    return [m for m in (d.get("messages") or [])[1:] if isinstance(m, dict)]


def read_channel(channel: str, *, limit: int = 50, oldest: str = "",
                 token_env: str | None = None, session=None) -> list[dict]:
    """Nyeste meldinger i kanalen. Tom liste ved enhver feil."""
    token = _token(token_env)
    if not token or not channel:
        return []
    sess = session or requests
    params = {"channel": channel, "limit": limit}
    if oldest:
        params["oldest"] = oldest
    try:
        r = sess.get(_HIST_URL, params=params,
                     headers={"Authorization": f"Bearer {token}"}, timeout=20)
        d = r.json()
    except Exception:  # noqa: BLE001
        return []
    return [m for m in (d.get("messages") or []) if isinstance(m, dict)] if d.get("ok") else []
