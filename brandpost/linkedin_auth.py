"""One-time OAuth 2.0 login for LinkedIn company-page publishing.

Run locally after setting ``BRANDPOST_ENV_FILE`` to the installation's one
environment file::

    .venv/bin/python -m brandpost.linkedin_auth

The access and refresh tokens are written atomically to that explicit file.
They are never printed.  Company-page URNs are not credentials and are shown
only as choices for ``[linkedin].org_urn`` in the relevant brand profile.
"""

from __future__ import annotations

import os
import re
import secrets
import stat
import sys
import tempfile
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import requests

from . import paths

_REPO_ROOT = paths.REPO_ROOT
AUTHORIZE_URL = "https://www.linkedin.com/oauth/v2/authorization"
TOKEN_URL = "https://www.linkedin.com/oauth/v2/accessToken"
API = "https://api.linkedin.com"
SCOPES = "w_organization_social r_organization_social"  # publish + org lookup
PORT = int(os.environ.get("LINKEDIN_REDIRECT_PORT") or "8765")
REDIRECT_URI = f"http://localhost:{PORT}/callback"

_TOKEN_KEYS = ("LINKEDIN_ACCESS_TOKEN", "LINKEDIN_REFRESH_TOKEN")
_ENV_ASSIGNMENT = re.compile(
    r"^\s*(?:export\s+)?(?P<key>[A-Za-z_][A-Za-z0-9_]*)\s*="
)
_ORG_URN = re.compile(r"^urn:li:organization:\d+$")


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

    def log_message(self, *_args):  # keep callback requests out of logs
        return


def _explicit_env_file() -> Path:
    """Return the sole authorised token target, or fail before OAuth starts."""
    raw = (os.environ.get("BRANDPOST_ENV_FILE") or "").strip()
    if not raw:
        raise ValueError("BRANDPOST_ENV_FILE må peke på én eksplisitt miljøfil")

    candidate = Path(raw).expanduser()
    if not candidate.is_absolute():
        candidate = Path.cwd() / candidate
    if candidate.is_symlink():
        raise ValueError("BRANDPOST_ENV_FILE kan ikke være en symbolsk lenke")
    candidate = candidate.resolve(strict=False)
    if candidate.exists() and not candidate.is_file():
        raise ValueError("BRANDPOST_ENV_FILE må peke på en vanlig fil")
    if not candidate.parent.is_dir():
        raise ValueError("Mappa til BRANDPOST_ENV_FILE finnes ikke")
    return candidate


def _dotenv_literal(value: str) -> str:
    """Quote one opaque token without allowing it to create extra env lines."""
    if any(char in value for char in ("\x00", "\r", "\n")):
        raise ValueError("OAuth-token hadde ugyldig format")
    return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"


def _replace_tokens(existing: str, *, access_token: str, refresh_token: str) -> str:
    """Replace only OAuth token assignments and preserve every unrelated line."""
    values = {
        "LINKEDIN_ACCESS_TOKEN": _dotenv_literal(access_token),
        "LINKEDIN_REFRESH_TOKEN": _dotenv_literal(refresh_token),
    }
    newline = "\r\n" if "\r\n" in existing else "\n"
    rendered: list[str] = []
    seen: set[str] = set()

    for line in existing.splitlines(keepends=True):
        match = _ENV_ASSIGNMENT.match(line)
        key = match.group("key") if match else ""
        if key not in values:
            rendered.append(line)
            continue
        if key in seen:
            # Duplicate secret assignments are unsafe and have no useful meaning.
            continue
        ending = "\r\n" if line.endswith("\r\n") else "\n" if line.endswith("\n") else ""
        rendered.append(f"{key}={values[key]}{ending}")
        seen.add(key)

    for key in _TOKEN_KEYS:
        if key in seen:
            continue
        if rendered and not rendered[-1].endswith(("\n", "\r")):
            rendered.append(newline)
        rendered.append(f"{key}={values[key]}{newline}")
    return "".join(rendered)


def _persist_tokens(env_file: Path, *, access_token: str, refresh_token: str) -> None:
    """Atomically persist OAuth tokens with mode 0600 and no secondary copy."""
    if not access_token:
        raise ValueError("LinkedIn returnerte ikke et access-token")
    if env_file.is_symlink() or (env_file.exists() and not env_file.is_file()):
        raise ValueError("BRANDPOST_ENV_FILE må peke på en vanlig fil, ikke en lenke")

    existing = env_file.read_text(encoding="utf-8") if env_file.exists() else ""
    updated = _replace_tokens(
        existing, access_token=access_token, refresh_token=refresh_token
    )
    fd, temporary = tempfile.mkstemp(
        prefix=f".{env_file.name}.", suffix=".tmp", dir=env_file.parent
    )
    temporary_path = Path(temporary)
    try:
        os.fchmod(fd, stat.S_IRUSR | stat.S_IWUSR)
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            handle.write(updated)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, env_file)
        env_file.chmod(stat.S_IRUSR | stat.S_IWUSR)
        # Make the directory entry durable as well as the file contents.
        directory_fd = os.open(env_file.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except BaseException:
        try:
            os.close(fd)
        except OSError:
            pass
        temporary_path.unlink(missing_ok=True)
        raise


def _fetch_org_urns(access_token: str) -> list[str]:
    """Best-effort list of company pages where the OAuth user is an admin."""
    try:
        response = requests.get(
            f"{API}/rest/organizationAcls",
            params={"q": "roleAssignee", "role": "ADMINISTRATOR", "state": "APPROVED"},
            headers={
                "Authorization": f"Bearer {access_token}",
                "LinkedIn-Version": (
                    os.environ.get("LINKEDIN_VERSION") or "202607"
                ).strip(),
                "X-Restli-Protocol-Version": "2.0.0",
            },
            timeout=30,
        )
        if response.status_code != 200:
            return []
        candidates = [
            entry.get("organization", "")
            for entry in response.json().get("elements", [])
            if isinstance(entry, dict)
        ]
        return sorted(
            {
                urn
                for urn in candidates
                if isinstance(urn, str) and _ORG_URN.fullmatch(urn)
            }
        )
    except (requests.RequestException, ValueError, AttributeError):
        return []


def main() -> int:
    try:
        env_file = _explicit_env_file()
    except (OSError, ValueError):
        print(
            "OAuth avbrutt: sett BRANDPOST_ENV_FILE til miljøfila som skal eie tokenene.",
            file=sys.stderr,
        )
        return 1

    paths.load_env()
    client_id = (os.environ.get("LINKEDIN_CLIENT_ID") or "").strip()
    client_secret = (os.environ.get("LINKEDIN_CLIENT_SECRET") or "").strip()
    if not client_id or not client_secret:
        print(
            "Mangler LINKEDIN_CLIENT_ID / LINKEDIN_CLIENT_SECRET i den valgte miljøfila.",
            file=sys.stderr,
        )
        return 1

    state = secrets.token_urlsafe(16)
    auth_url = AUTHORIZE_URL + "?" + urllib.parse.urlencode(
        {
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": REDIRECT_URI,
            "scope": SCOPES,
            "state": state,
        }
    )
    print(f"Redirect-URL som må være registrert i appen: {REDIRECT_URI}\n")
    print("Åpner nettleser for innlogging. Hvis den ikke åpner, bruk denne URL-en:\n")
    print(auth_url + "\n")
    webbrowser.open(auth_url)

    _Catch.code = None
    _Catch.state_seen = None
    server = HTTPServer(("localhost", PORT), _Catch)
    server.handle_request()
    server.server_close()

    if not _Catch.code:
        print("Fikk ingen authorization code. Avbryter.", file=sys.stderr)
        return 1
    if _Catch.state_seen != state:
        print("State stemmer ikke (mulig CSRF). Avbryter.", file=sys.stderr)
        return 1

    try:
        token_response = requests.post(
            TOKEN_URL,
            timeout=30,
            data={
                "grant_type": "authorization_code",
                "code": _Catch.code,
                "redirect_uri": REDIRECT_URI,
                "client_id": client_id,
                "client_secret": client_secret,
            },
        )
    except requests.RequestException:
        print("Token-bytte feilet på grunn av en nettverksfeil.", file=sys.stderr)
        return 1
    if token_response.status_code != 200:
        # Never echo the provider response: it may itself contain credentials.
        print(f"Token-bytte feilet (HTTP {token_response.status_code}).", file=sys.stderr)
        return 1

    try:
        data = token_response.json()
        access_token = data.get("access_token", "")
        refresh_token = data.get("refresh_token", "")
        if not isinstance(access_token, str) or not isinstance(refresh_token, str):
            raise ValueError("ugyldig tokenrespons")
        _persist_tokens(
            env_file, access_token=access_token, refresh_token=refresh_token
        )
    except (OSError, UnicodeError, ValueError, AttributeError):
        print(
            "OAuth lyktes, men tokenene kunne ikke lagres trygt. Ingen tokenverdier vises.",
            file=sys.stderr,
        )
        return 1

    orgs = _fetch_org_urns(access_token)
    print(f"\nOAuth-tokenene er lagret atomisk i {env_file} (verdier: [REDACTED]).")
    print("Miljøfila er satt til filmodus 0600.")
    print("Ingen global LINKEDIN_ORG_URN ble skrevet.")
    if orgs:
        print("\nVelg riktig side og lim bare URN-en inn i merkets profile.toml:")
        for urn in orgs:
            print(f'  org_urn = "{urn}"')
    else:
        print(
            "\nFant ingen administratorside automatisk. Hent organisasjons-ID-en fra "
            "firmasidens admin-URL og legg urn:li:organization:<ID> i merkets profile.toml."
        )
    expires_in = data.get("expires_in", 0)
    if isinstance(expires_in, (int, float)) and expires_in > 0:
        print(f"Access-tokenet utløper om omtrent {int(expires_in)} sekunder.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
