"""linkedin — publiser ETT SoMe-utkast til Demo Labs-firmasida (menneske-gated).

Propose-only-linja er urørt: generatoren foreslår (mail + vault, status "proposed").
Denne modulen poster ett VALGT utkast NÅR du sier fra, aldri i nattkjøringen.

Trygg default (speiler `mailer` sitt `NOTATER_MAIL_ENABLED`): `LINKEDIN_ENABLED=0`
→ dry-run, som skriver hva som VILLE postes og sender ingenting. Først `=1` poster ekte.

Firmaside = LinkedIn «Community Management API» (scope `w_organization_social`).
Bilde OG karusell (PDF-dokumentpost) bruker samme 3-stegs rest.li-flyt:
  1. POST /rest/{images|documents}?action=initializeUpload (owner = ORG URN) → uploadUrl + urn
  2. PUT  {uploadUrl}  (binær PNG / PDF)
  3. POST /rest/posts  (author = ORG URN, commentary = body, media = urn, PUBLISHED)
For dokumenter er `title` i media-objektet påkrevd; LinkedIn viser PDF-en swipe-bar.

Ekte utkast finnes IKKE i API-et: Post-skjemaet sier «PUBLISHED is the only accepted
field during creation» (DRAFT er ren lese-tilstand). Utkastene bor derfor i vaulten +
SoMe-eposten, og publisering skjer først når du peker.

Access-token utløper etter ~60 dager; ved 401 refresher vi automatisk med refresh-token.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path

import requests

API = "https://api.linkedin.com"
OAUTH_TOKEN_URL = "https://www.linkedin.com/oauth/v2/accessToken"
# LinkedIn-Version er månedlig (YYYYMM); LinkedIn deprecerer gamle. Overstyr ved migrering.
LINKEDIN_VERSION = (os.environ.get("LINKEDIN_VERSION") or "202607").strip()
_RESTLI = {"X-Restli-Protocol-Version": "2.0.0"}


@dataclass(frozen=True)
class LinkedInConfig:
    client_id: str
    client_secret: str
    access_token: str
    refresh_token: str
    org_urn: str          # urn:li:organization:<id> (firmaside) — eller person-URN som fallback
    enabled: bool

    @property
    def ready(self) -> bool:
        """Nok til å faktisk poste (token + hvem vi poster som)."""
        return bool(self.access_token and self.org_urn)


def load_linkedin_config() -> LinkedInConfig:
    """Les LINKEDIN_*-miljøet. Speiler `mailer.load_credentials()`: `LINKEDIN_ENABLED`
    er en trygg av-bryter (0 = dry-run), så vi aldri poster utilsiktet."""
    g = os.environ.get
    return LinkedInConfig(
        client_id=(g("LINKEDIN_CLIENT_ID") or "").strip(),
        client_secret=(g("LINKEDIN_CLIENT_SECRET") or "").strip(),
        access_token=(g("LINKEDIN_ACCESS_TOKEN") or "").strip(),
        refresh_token=(g("LINKEDIN_REFRESH_TOKEN") or "").strip(),
        org_urn=(g("LINKEDIN_ORG_URN") or "").strip(),
        enabled=(g("LINKEDIN_ENABLED", "") or "").strip().lower() in ("1", "true", "yes", "on"),
    )


# ── token ──────────────────────────────────────────────────

def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}",
            "LinkedIn-Version": LINKEDIN_VERSION, **_RESTLI}


def refresh_access_token(cfg: LinkedInConfig, *, session=None) -> str:
    """Bytt refresh-token mot et ferskt access-token. Reiser RuntimeError ved feil.
    Persisterer ikke selv (kalleren kan skrive til .env om ønskelig)."""
    if not cfg.refresh_token:
        raise RuntimeError("access-token utløpt og ingen LINKEDIN_REFRESH_TOKEN å fornye med")
    sess = session or requests
    r = sess.post(OAUTH_TOKEN_URL, timeout=30, data={
        "grant_type": "refresh_token",
        "refresh_token": cfg.refresh_token,
        "client_id": cfg.client_id,
        "client_secret": cfg.client_secret,
    })
    if r.status_code != 200:
        raise RuntimeError(f"token-refresh feilet: {r.status_code} {r.text[:200]}")
    return r.json()["access_token"]


# ── 3-stegs media-innlegg (PNG-bilde og PDF-dokument) ──────

def _initialize_upload(cfg: LinkedInConfig, token: str, *, kind: str = "images",
                       session) -> tuple[str, str]:
    """kind ∈ {'images', 'documents'}. Returnerer (uploadUrl, media-URN)."""
    r = session.post(f"{API}/rest/{kind}?action=initializeUpload", timeout=30,
                     headers={**_headers(token), "Content-Type": "application/json"},
                     json={"initializeUploadRequest": {"owner": cfg.org_urn}})
    r.raise_for_status()
    v = r.json()["value"]
    return v["uploadUrl"], v["image" if kind == "images" else "document"]


def _upload_binary(upload_url: str, path: str, *, mime: str = "image/png",
                   session) -> None:
    data = Path(path).read_bytes()
    r = session.put(upload_url, data=data, timeout=180,
                    headers={"Content-Type": mime})
    r.raise_for_status()


def _create_post(cfg: LinkedInConfig, token: str, *, media: dict, body: str,
                 session) -> str:
    """media = {'id': urn, 'altText': ...} for bilder, {'id': urn, 'title': ...}
    for dokumenter (title er påkrevd for dokumenter i Post-skjemaet)."""
    payload = {
        "author": cfg.org_urn,
        "commentary": body,
        "visibility": "PUBLIC",
        "distribution": {"feedDistribution": "MAIN_FEED",
                         "targetEntities": [], "thirdPartyDistributionChannels": []},
        "content": {"media": media},
        "lifecycleState": "PUBLISHED",     # eneste lovlige verdi ved opprettelse
        "isReshareDisabledByAuthor": False,
    }
    r = session.post(f"{API}/rest/posts", timeout=30,
                     headers={**_headers(token), "Content-Type": "application/json"},
                     json=payload)
    r.raise_for_status()
    return (r.headers.get("x-restli-id") or r.headers.get("x-linkedin-id") or "").strip()


def post_url(post_urn: str) -> str:
    """urn:li:share:123 / urn:li:ugcPost:123 → feed-URL."""
    pid = (post_urn or "").strip()
    return f"https://www.linkedin.com/feed/update/{pid}" if pid else ""


def _with_token_refresh(cfg: LinkedInConfig, sess, do) -> str:
    """Kjør `do(token)`; ved 401 (utløpt token) refreshes én gang og HELE
    sekvensen prøves på nytt (upload-URN-er kan ikke gjenbrukes på tvers)."""
    try:
        return do(cfg.access_token)
    except requests.HTTPError as e:
        resp = getattr(e, "response", None)
        if resp is not None and resp.status_code == 401 and cfg.refresh_token:
            return do(refresh_access_token(cfg, session=sess))
        raise


def fetch_org_posts(*, cfg: LinkedInConfig | None = None, count: int = 30,
                    brand_key: str | None = None, session=None) -> list[dict]:
    """Publiserte innlegg på firmasida, nyeste først: [{id, publishedAt, commentary}, …].

    Read-only. Brukes til å vite NÅR noe faktisk gikk ut, i stedet for å gjette ut
    fra hvilken dagsmappe utkastet lå i. Tom liste ved manglende oppsett eller feil,
    så en kaller aldri må gjette på tomt svar kontra unntak."""
    cfg = _with_brand_org(cfg or load_linkedin_config(), brand_key)
    if not cfg.access_token or not cfg.org_urn:
        return []
    sess = session or requests.Session()

    def _do(token: str) -> list[dict]:
        r = sess.get(f"{API}/rest/posts", timeout=30,
                     headers={**_headers(token), "X-RestLi-Method": "FINDER"},
                     params={"author": cfg.org_urn, "q": "author", "count": count})
        r.raise_for_status()
        return r.json().get("elements", []) or []

    try:
        return _with_token_refresh(cfg, sess, _do)
    except Exception:  # noqa: BLE001
        return []


def publish_image_post(image_path: str, body: str, *, alt_text: str = "",
                       cfg: LinkedInConfig | None = None, session=None) -> str:
    """Publiser ETT enkeltbilde-innlegg til firmasida; returner feed-URL."""
    cfg = cfg or load_linkedin_config()
    if not cfg.ready:
        raise RuntimeError("LinkedIn ikke konfigurert (mangler LINKEDIN_ACCESS_TOKEN / LINKEDIN_ORG_URN)")
    sess = session or requests.Session()

    def _do(token: str) -> str:
        upload_url, urn = _initialize_upload(cfg, token, kind="images", session=sess)
        _upload_binary(upload_url, image_path, mime="image/png", session=sess)
        return _create_post(cfg, token, media={"id": urn, "altText": alt_text or ""},
                            body=body, session=sess)

    return post_url(_with_token_refresh(cfg, sess, _do))


def publish_document_post(pdf_path: str, body: str, *, title: str,
                          cfg: LinkedInConfig | None = None, session=None) -> str:
    """Publiser ÉN karusell (PDF) som swipe-bar dokumentpost på firmasida;
    returner feed-URL. Samme flyt og gating som bildene."""
    cfg = cfg or load_linkedin_config()
    if not cfg.ready:
        raise RuntimeError("LinkedIn ikke konfigurert (mangler LINKEDIN_ACCESS_TOKEN / LINKEDIN_ORG_URN)")
    sess = session or requests.Session()

    def _do(token: str) -> str:
        upload_url, urn = _initialize_upload(cfg, token, kind="documents", session=sess)
        _upload_binary(upload_url, pdf_path, mime="application/pdf", session=sess)
        return _create_post(cfg, token,
                            media={"id": urn, "title": (title or "Karusell").strip()},
                            body=body, session=sess)

    return post_url(_with_token_refresh(cfg, sess, _do))


# ── CLI-vendt: publiser ett manifest-utkast (med dry-run) ──

def _write_dry_metadata(draft: dict, payload: dict, *, when: datetime | None = None) -> Path:
    """Skriv «hva som VILLE postes» ved siden av bildet (speiler .eml-dry-run)."""
    when = when or datetime.now()
    img = draft.get("png_path") or draft.get("cover_path") or ""
    day_dir = Path(img).parent
    out = day_dir / "published-metadata.json"
    log = []
    if out.exists():
        try:
            log = json.loads(out.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            log = []
    log.append({"headline": draft.get("headline"), "at": when.isoformat(timespec="seconds"),
                "would_post": payload})
    out.write_text(json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")
    return out


def api_commentary(body: str, *, brand_name: str, org_urn: str) -> str:
    """«@Demo Labs» i innleggsteksten → ekte @-mention av firmasida i Posts-API-ets
    little-text-format: `@[Navn](urn:li:organization:…)`. Manuell posting beholder
    klarteksten (du skriver taggen selv i composeren); API-veien får den ekte."""
    tag = f"@{brand_name}"
    if not body or not org_urn or tag not in body:
        return body
    return body.replace(tag, f"@[{brand_name}]({org_urn})")


def _with_brand_org(cfg: LinkedInConfig, brand_key: str | None) -> LinkedInConfig:
    """Merkets egen firmaside ([linkedin].org_urn i brands/<key>/profile.toml)
    vinner over global LINKEDIN_ORG_URN: samme app + token poster til alle sidene
    du er admin på, siden velges per utkast via merket."""
    if not brand_key:
        return cfg
    try:
        from . import brandkit
        urn = brandkit.load_brand(brand_key).linkedin_org_urn
    except Exception:
        return cfg
    return replace(cfg, org_urn=urn) if urn else cfg


def publish_draft(draft: dict, *, cfg: LinkedInConfig | None = None,
                  dry_run: bool | None = None, when: datetime | None = None) -> dict:
    """Publiser ett manifest-utkast. Returnerer {posted, url|reason, dry_run, preview?}.
    Dry-run når `dry_run=True` ELLER `LINKEDIN_ENABLED` er av: ingen API-kall, skriver metadata."""
    cfg = _with_brand_org(cfg or load_linkedin_config(), draft.get("brand"))
    dry = (not cfg.enabled) if dry_run is None else bool(dry_run)
    body = api_commentary((draft.get("body") or "").strip(),
                          brand_name=(draft.get("brand_name") or "Demo Labs").strip(),
                          org_urn=cfg.org_urn)
    headline = (draft.get("headline") or "").strip()

    if (draft.get("type") or draft.get("format")) == "karusell":
        pdf_path = draft.get("pdf_path")
        if not pdf_path or not Path(pdf_path).exists():
            return {"posted": False, "dry_run": dry, "reason": f"fant ikke PDF: {pdf_path}"}
        title = (draft.get("tittel") or headline or "Karusell").strip()
        preview = {"author": cfg.org_urn or "(LINKEDIN_ORG_URN mangler)",
                   "commentary": body, "document": pdf_path, "title": title,
                   "lifecycleState": "PUBLISHED", "visibility": "PUBLIC"}
        if dry:
            meta = _write_dry_metadata(draft, preview, when=when)
            return {"posted": False, "dry_run": True, "preview": preview, "metadata": str(meta)}
        url = publish_document_post(pdf_path, body, title=title, cfg=cfg)
        return {"posted": True, "dry_run": False, "url": url}

    image_path = draft.get("png_path") or draft.get("cover_path")
    if not image_path or not Path(image_path).exists():
        return {"posted": False, "dry_run": dry, "reason": f"fant ikke bilde: {image_path}"}

    preview = {"author": cfg.org_urn or "(LINKEDIN_ORG_URN mangler)",
               "commentary": body, "image": image_path, "altText": headline,
               "lifecycleState": "PUBLISHED", "visibility": "PUBLIC"}
    if dry:
        meta = _write_dry_metadata(draft, preview, when=when)
        return {"posted": False, "dry_run": True, "preview": preview, "metadata": str(meta)}

    url = publish_image_post(image_path, body, alt_text=headline, cfg=cfg)
    return {"posted": True, "dry_run": False, "url": url}
