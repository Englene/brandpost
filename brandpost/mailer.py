"""mailer — valgfri e-postlevering.

E-post er et TILLEGG her, ikke bæresøylen: dashbordet er stedet du godkjenner og
publiserer fra. Uten SMTP-oppsett tørrkjører alt, og systemet virker likevel.

Slår du det på (BRANDPOST_MAIL_ENABLED=1), får du forslagene og en kvittering når
noe faktisk er publisert. Nyttig hvis du vil kunne godkjenne fra telefonen uten å
åpne dashbordet.

Miljø:
    BRANDPOST_MAIL_ENABLED   1 for å faktisk sende (alt annet = tørrkjøring)
    BRANDPOST_SMTP_HOST      standard smtp.gmail.com
    BRANDPOST_SMTP_PORT      standard 587
    BRANDPOST_SMTP_USER      avsender
    BRANDPOST_SMTP_PASSWORD  app-passord, ikke kontopassordet
    BRANDPOST_MAIL_TO        mottaker (standard: samme som SMTP_USER)
"""

from __future__ import annotations

import os
import smtplib
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path

_DAYS = ("mandag", "tirsdag", "onsdag", "torsdag", "fredag", "lørdag", "søndag")
_MONTHS = ("januar", "februar", "mars", "april", "mai", "juni", "juli",
           "august", "september", "oktober", "november", "desember")


def no_datestamp(dt: datetime | None = None) -> str:
    """«onsdag 3. juni 13:51». Bygges for hånd fordi strftime bruker C-locale."""
    dt = dt or datetime.now()
    return f"{_DAYS[dt.weekday()]} {dt.day}. {_MONTHS[dt.month - 1]} {dt.strftime('%H:%M')}"


def enabled() -> bool:
    return (os.environ.get("BRANDPOST_MAIL_ENABLED") or "").strip().lower() in (
        "1", "true", "yes", "on")


def send_email(subject: str, html_body: str, *, to: str | None = None,
               dry_run: bool | None = None, preheader: str | None = None,
               vault: Path | None = None,
               inline_images: dict[str, bytes] | None = None,
               attachments: list[dict] | None = None) -> dict:
    """Send en HTML-e-post, eller tørrkjør.

    Tørrkjøring er standard og krever ingen konfigurasjon: da returneres
    {"sent": False, "dry_run": True} og ingenting forlater maskinen. Det er med
    vilje: en fersk kloning skal aldri kunne sende e-post ved et uhell.
    """
    tørr = (not enabled()) if dry_run is None else bool(dry_run)
    mottaker = (to or os.environ.get("BRANDPOST_MAIL_TO")
                or os.environ.get("BRANDPOST_SMTP_USER") or "").strip()
    if tørr:
        return {"sent": False, "dry_run": True, "to": mottaker}
    if not mottaker:
        return {"sent": False, "dry_run": False, "reason": "ingen mottaker satt"}

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = os.environ.get("BRANDPOST_SMTP_USER", mottaker)
    msg["To"] = mottaker
    msg.set_content(preheader or subject)
    msg.add_alternative(html_body, subtype="html")

    if inline_images:
        del_ = msg.get_payload()[-1]
        for cid, data in inline_images.items():
            if data:
                del_.add_related(data, maintype="image", subtype="png", cid=f"<{cid}>")
    for ved in attachments or []:
        if ved.get("data"):
            msg.add_attachment(ved["data"], maintype=ved.get("maintype", "application"),
                               subtype=ved.get("subtype", "pdf"),
                               filename=ved.get("filename", "vedlegg"))

    host = os.environ.get("BRANDPOST_SMTP_HOST", "smtp.gmail.com")
    port = int(os.environ.get("BRANDPOST_SMTP_PORT") or "587")
    try:
        with smtplib.SMTP(host, port, timeout=60) as s:
            s.starttls()
            s.login(os.environ["BRANDPOST_SMTP_USER"],
                    os.environ["BRANDPOST_SMTP_PASSWORD"])
            s.send_message(msg)
    except Exception as e:  # noqa: BLE001
        # En e-postfeil skal aldri velte en publisering som ALT har skjedd.
        return {"sent": False, "dry_run": False, "reason": f"{type(e).__name__}: {e}"}
    return {"sent": True, "dry_run": False, "to": mottaker}
