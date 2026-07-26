"""email — monter SoMe-utkastene til én e-post og send (dry-run som standard).

Gjenbruker brandpost.mailer.send_email (HTML + inline-bilder finnes alt).
wrap_document har et mørkt Dagsbrev-tema, så vi bygger en egen LYS merkevare-mal
(sand bakgrunn, mørkegrønn serif-aktig headline) så eposten ser ut som produktet.

Hvert utkast vises som: bildet inline, klar-til-å-poste LinkedIn-tekst, og en kort
«hvorfor nå»-begrunnelse. du poster selv etter gjennomsyn (propose-only).
"""

from __future__ import annotations

import html
import os
from datetime import datetime
from email.utils import make_msgid
from pathlib import Path

from .mailer import no_datestamp, send_email

_PAL = {  # Demo Labs-lys, e-post-trygge farger
    "bg": "#f3ecdb", "card": "#faf6ec", "ink": "#0e1a17",
    "headline": "#06231c", "brand": "#014d40", "muted": "#51616f", "line": "#e4d9c2",
}


def _doc(inner: str, *, preheader: str) -> str:
    p = _PAL
    return f"""\
<!DOCTYPE html><html lang="no"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0"><title>SoMe-utkast</title>
<style>
 body{{margin:0;padding:0;background:{p['bg']};color:{p['ink']};
   font-family:Georgia,'Times New Roman',serif;}}
 .wrap{{max-width:640px;margin:0 auto;padding:28px 20px;}}
 .pre{{display:none;visibility:hidden;opacity:0;height:0;width:0;overflow:hidden;}}
 h1{{font-size:24px;color:{p['headline']};letter-spacing:-0.02em;margin:0 0 2px;}}
 .meta{{color:{p['muted']};font-size:13px;margin-bottom:22px;
   font-family:-apple-system,Segoe UI,sans-serif;}}
 .card{{background:{p['card']};border:1px solid {p['line']};border-radius:14px;
   padding:18px;margin:0 0 20px;}}
 .card img{{width:100%;max-width:100%;border-radius:10px;display:block;margin:0 0 14px;}}
 .kind{{display:inline-block;font-size:11px;letter-spacing:0.08em;text-transform:uppercase;
   color:{p['brand']};font-family:-apple-system,Segoe UI,sans-serif;margin-bottom:8px;}}
 .copy{{white-space:pre-wrap;font-family:-apple-system,Segoe UI,sans-serif;font-size:15px;
   line-height:1.55;color:{p['ink']};}}
 .why{{margin-top:12px;padding-top:12px;border-top:1px dashed {p['line']};
   font-family:-apple-system,Segoe UI,sans-serif;font-size:13px;color:{p['muted']};}}
 .why b{{color:{p['brand']};}}
 .foot{{margin-top:8px;color:{p['muted']};font-size:11px;
   font-family:-apple-system,Segoe UI,sans-serif;}}
</style></head><body>
<span class="pre">{html.escape(preheader)}</span>
<div class="wrap">{inner}
<div class="foot">Notater · SoMe-generator · {html.escape(no_datestamp())} · propose-only, ingenting er postet</div>
</div></body></html>"""


def publish_command(draft: dict, n: int) -> str:
    """«publiser: 13.07-2» når utkastet hører til en dato (slot-fylling), ellers
    «publiser: 2». Dato-formen er entydig på tvers av dagene i samme epost."""
    ds = (draft.get("date") or "").strip()
    if len(ds) == 10:  # YYYY-MM-DD -> dd.mm
        return f"publiser: {ds[8:10]}.{ds[5:7]}-{n}"
    return f"publiser: {n}"


def _card(draft: dict, cid: str, n: int) -> str:
    is_car = draft.get("type") == "karusell"
    headline = html.escape(draft.get("headline", ""))
    why = html.escape(draft.get("why_now", "") or "ikke oppgitt")
    ds = (draft.get("date") or "").strip()
    day_label = f"{ds[8:10]}.{ds[5:7]} · " if len(ds) == 10 else ""
    cmd = html.escape(publish_command(draft, n))
    publiser = (f"<div class='why'><b>Publiser:</b> svar på denne eposten med "
                f"«{cmd}», så legges den ut på firmasida for deg.</div>")
    kilder = [k for k in (draft.get("kilder") or []) if isinstance(k, str) and k.strip()]
    kildeblokk = ""
    if kilder:
        rows = "".join(f"<li>{html.escape(k)}</li>" for k in kilder)
        kildeblokk = (f"<div class='why'><b>Kilder (kun for deg, ikke i innlegget):</b>"
                      f"<ul style='margin:4px 0 0 16px;padding:0'>{rows}</ul></div>")
    if is_car:
        n_slides = draft.get("n", "?")
        pdf_name = html.escape(Path(draft.get("pdf_path", "karusell.pdf")).name)
        kind = f"nr {n} · {day_label}karusell · {n_slides} slides · PDF vedlagt"
        body = html.escape(draft.get("body", "") or "(karusell, ingen brødtekst)")
        extra = publiser + (f"<div class='why'>Manuelt alternativ: last opp "
                            f"<code>{pdf_name}</code> som dokumentpost "
                            f"(forsiden vises over).</div>")
    else:
        fmt = html.escape(draft.get("format", ""))
        how = draft.get("how", "")
        kind = f"nr {n} · {day_label}" + fmt + (f" · bilde: {html.escape(how)}" if how else "")
        body = html.escape(draft.get("body", "") or "(bilde-kort, ingen brødtekst)")
        extra = publiser
    return f"""\
<div class="card">
 <div class="kind">{kind}</div>
 <img src="cid:{cid}" alt="{headline}">
 <div class="copy">{body}</div>
 <div class="why"><b>Hvorfor nå:</b> {why}</div>
 {kildeblokk}
 {extra}
</div>"""


def _draft_image(draft: dict) -> bytes | None:
    """Bildet som skal vises inline: karusell -> forside, ellers kortet."""
    key_bytes = "cover" if draft.get("type") == "karusell" else "png"
    png = draft.get(key_bytes)
    if png is None:
        path = draft.get("cover_path") if draft.get("type") == "karusell" else draft.get("png_path")
        if path:
            try:
                png = Path(path).read_bytes()
            except OSError:
                png = None
    return png


def build_some_email(drafts: list[dict], *, brand_name: str = "Demo Labs") -> tuple[str, str, dict, list]:
    """Returnerer (subject, html, inline_images={cid: png}, attachments=[{filename,data,mime}])."""
    n = len(drafts)
    n_car = sum(1 for d in drafts if d.get("type") == "karusell")
    label = f"{n} innlegg" + (f" ({n_car} karusell)" if n_car else "")
    subject = f"SoMe-utkast · {brand_name} · {label} · {datetime.now():%d.%m}"
    inline: dict[str, bytes] = {}
    attachments: list[dict] = []
    cards = []
    cmds: list[str] = []
    for i, d in enumerate(drafts, 1):
        png = _draft_image(d)
        if png is None:
            continue
        # Dags-manifest-nummeret «publiser: nr» treffer (felles for alle merker den
        # dagen); posisjonen som fallback for eldre manifester uten nr.
        nr = d.get("nr") or i
        cid = make_msgid(domain="notater.local").strip("<>")
        inline[cid] = png
        cards.append(_card(d, cid, nr))
        cmds.append(publish_command(d, nr))
        if d.get("type") == "karusell":
            pdf = d.get("pdf") or (Path(d["pdf_path"]).read_bytes() if d.get("pdf_path") else None)
            if pdf:
                attachments.append({
                    "filename": Path(d.get("pdf_path", "karusell.pdf")).name,
                    "data": pdf, "mime": "application/pdf",
                })
    eks = html.escape(cmds[0] if cmds else "publiser: 1")  # eksempelet må finnes
    intro = (f"<h1>{label} klare til gjennomsyn</h1>"
             f"<div class='meta'>Utkastene fyller ukas planlagte dager. "
             f"Svar «{eks}» for å legge ut det første på firmasida, eller post selv. "
             f"Dropp resten.</div>")
    doc = _doc(intro + "".join(cards), preheader=f"{label} for {brand_name}")
    return subject, doc, inline, attachments


def send_drafts(drafts: list[dict], *, brand_name: str = "Demo Labs",
                dry_run: bool | None = None, vault: Path | None = None) -> dict:
    """Bygg og send SoMe-eposten. dry_run=None => følg NOTATER_MAIL_ENABLED."""
    if not drafts:
        return {"sent": False, "reason": "ingen utkast"}
    subject, doc, inline, attachments = build_some_email(drafts, brand_name=brand_name)
    to = os.environ.get("NOTATER_SOME_MAIL_TO") or None  # None => mailer bruker NOTATER_MAIL_TO
    return send_email(subject, doc, to=to, dry_run=dry_run, vault=vault,
                      preheader=f"{len(drafts)} SoMe-utkast", inline_images=inline,
                      attachments=attachments)
