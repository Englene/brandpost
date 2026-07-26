"""linkedin_auth — engangs OAuth 2.0 (authorization code) for LinkedIn firmaside-posting.

Kjør ÉN gang lokalt (åpner nettleser, fanger redirect på localhost):

    .venv/bin/python -m brandpost.social.linkedin_auth

Krav:
  - LINKEDIN_CLIENT_ID + LINKEDIN_CLIENT_SECRET i .env (fra LinkedIn Developer-appen).
  - Redirect-URL http://localhost:8765/callback registrert i appen (Auth-fanen).
  - Appen har «Community Management API»-produktet + scope w_organization_social godkjent.

Den SKRIVER IKKE til .env. Den printer access-token, refresh-token og (best-effort) ORG URN,
som du selv limer inn i .env (og ssh-er til Mini). Access-token varer ~60 dager; refresh ~1 år.
"""

from __future__ import annotations

import os
import secrets
import sys
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import requests
from dotenv import load_dotenv

from . import paths

_REPO_ROOT = paths.REPO_ROOT
AUTHORIZE_URL = "https://www.linkedin.com/oauth/v2/authorization"
TOKEN_URL = "https://www.linkedin.com/oauth/v2/accessToken"
API = "https://api.linkedin.com"
SCOPES = "w_organization_social r_organization_social"  # posting + org-oppslag
PORT = int(os.environ.get("LINKEDIN_REDIRECT_PORT") or "8765")
REDIRECT_URI = f"http://localhost:{PORT}/callback"


class _Catch(BaseHTTPRequestHandler):
    code: str | None = None
    state_seen: str | None = None

    def do_GET(self):  # noqa: N802
        q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        _Catch.code = (q.get("code") or [None])[0]
        _Catch.state_seen = (q.get("state") or [None])[0]
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        ok = "Ferdig, du kan lukke denne fanen og gå tilbake til terminalen."
        err = "Fant ingen ?code i redirect. Sjekk at tilgangen ble godkjent."
        self.wfile.write(f"<h3>{ok if _Catch.code else err}</h3>".encode("utf-8"))

    def log_message(self, *_args):  # stille
        return


def _fetch_org_urns(access_token: str) -> list[str]:
    """Best-effort: list organisasjonene brukeren er ADMIN for (så du får ORG URN)."""
    try:
        r = requests.get(
            f"{API}/rest/organizationAcls",
            params={"q": "roleAssignee", "role": "ADMINISTRATOR", "state": "APPROVED"},
            headers={"Authorization": f"Bearer {access_token}",
                     "LinkedIn-Version": (os.environ.get("LINKEDIN_VERSION") or "202607").strip(),
                     "X-Restli-Protocol-Version": "2.0.0"},
            timeout=30)
        if r.status_code != 200:
            return []
        return [e.get("organization", "") for e in r.json().get("elements", []) if e.get("organization")]
    except requests.RequestException:
        return []


def main() -> int:
    load_dotenv(_REPO_ROOT / ".env")
    cid = (os.environ.get("LINKEDIN_CLIENT_ID") or "").strip()
    csec = (os.environ.get("LINKEDIN_CLIENT_SECRET") or "").strip()
    if not cid or not csec:
        print("Mangler LINKEDIN_CLIENT_ID / LINKEDIN_CLIENT_SECRET i .env", file=sys.stderr)
        return 1

    state = secrets.token_urlsafe(16)
    auth_url = AUTHORIZE_URL + "?" + urllib.parse.urlencode({
        "response_type": "code", "client_id": cid, "redirect_uri": REDIRECT_URI,
        "scope": SCOPES, "state": state,
    })
    print(f"Redirect-URL som MÅ være registrert i appen: {REDIRECT_URI}\n")
    print("Åpner nettleser for innlogging/godkjenning. Hvis den ikke åpner, lim inn:\n")
    print(auth_url + "\n")
    webbrowser.open(auth_url)

    server = HTTPServer(("localhost", PORT), _Catch)
    server.handle_request()  # blokkerer til redirect kommer inn
    server.server_close()

    if not _Catch.code:
        print("Fikk ingen authorization code. Avbryter.", file=sys.stderr)
        return 1
    if _Catch.state_seen != state:
        print("State stemmer ikke (mulig CSRF). Avbryter.", file=sys.stderr)
        return 1

    tok = requests.post(TOKEN_URL, timeout=30, data={
        "grant_type": "authorization_code", "code": _Catch.code,
        "redirect_uri": REDIRECT_URI, "client_id": cid, "client_secret": csec,
    })
    if tok.status_code != 200:
        print(f"Token-bytte feilet: {tok.status_code} {tok.text[:300]}", file=sys.stderr)
        return 1
    data = tok.json()
    access = data.get("access_token", "")
    refresh = data.get("refresh_token", "")
    orgs = _fetch_org_urns(access)

    print("\n─────────── LIM INN I .env (og ssh til Mini) ───────────")
    print(f"LINKEDIN_ACCESS_TOKEN={access}")
    print(f"LINKEDIN_REFRESH_TOKEN={refresh}")
    if orgs:
        print(f"LINKEDIN_ORG_URN={orgs[0]}   # global fallback (brukes når merket ikke har egen)")
    else:
        print("LINKEDIN_ORG_URN=urn:li:organization:<ID>   "
              "# fant ingen automatisk; hent ID fra firmaside-admin-URL-en")
    print(f"# access_token utløper om ~{data.get('expires_in', 0)} sek (~60 dager); refresh fornyer.")
    if len(orgs) > 1:
        print("\nDu er admin på FLERE sider. Samme app/token dekker alle: lim riktig URN")
        print("inn i hvert merkes profil ([linkedin].org_urn i brands/<key>/profile.toml):")
        for urn in orgs:
            print(f"  org_urn = \"{urn}\"")
    print("─────────────────────────────────────────────────────────")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
