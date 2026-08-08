from __future__ import annotations

import os
import stat
from pathlib import Path

from dotenv import dotenv_values

from brandpost import linkedin_auth


class _CallbackServer:
    def __init__(self, *_args, **_kwargs):
        pass

    def handle_request(self):
        linkedin_auth._Catch.code = "one-time-code"
        linkedin_auth._Catch.state_seen = "known-state"

    def server_close(self):
        pass


class _Response:
    def __init__(self, status_code: int, payload: dict, *, text: str = ""):
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def json(self):
        return self._payload


def _prepare_success(monkeypatch, env_file: Path, access: str, refresh: str) -> None:
    monkeypatch.setenv("BRANDPOST_ENV_FILE", str(env_file))
    monkeypatch.setenv("LINKEDIN_CLIENT_ID", "client-id")
    monkeypatch.setenv("LINKEDIN_CLIENT_SECRET", "client-secret")
    monkeypatch.setattr(linkedin_auth.secrets, "token_urlsafe", lambda _n: "known-state")
    monkeypatch.setattr(linkedin_auth, "HTTPServer", _CallbackServer)
    monkeypatch.setattr(linkedin_auth.webbrowser, "open", lambda _url: True)
    monkeypatch.setattr(
        linkedin_auth.requests,
        "post",
        lambda *_args, **_kwargs: _Response(
            200,
            {
                "access_token": access,
                "refresh_token": refresh,
                "expires_in": 3600,
            },
        ),
    )


def test_oauth_tokens_lagres_bare_i_valgt_fil_og_output_er_redigert(
    tmp_path, monkeypatch, capsys, caplog
):
    access = "oauth-" + "access-value-123"
    refresh = "oauth-" + "refresh-value-456"
    env_file = tmp_path / "nadia.env"
    original = (
        "# behold denne kommentaren\n"
        "UNRELATED=behold-meg\n"
        "\n"
        "LINKEDIN_ACCESS_TOKEN='gammel'\n"
        "# og denne kommentaren\n"
        "LINKEDIN_REFRESH_TOKEN='utdatert'\n"
    )
    env_file.write_text(original, encoding="utf-8")
    env_file.chmod(0o644)
    old_inode = env_file.stat().st_ino
    _prepare_success(monkeypatch, env_file, access, refresh)
    monkeypatch.setattr(
        linkedin_auth,
        "_fetch_org_urns",
        lambda _token: ["urn:li:organization:222", "urn:li:organization:111"],
    )

    assert linkedin_auth.main() == 0

    captured = capsys.readouterr()
    all_output = captured.out + captured.err + caplog.text
    assert access not in all_output
    assert refresh not in all_output
    assert "gammel" not in all_output
    assert "utdatert" not in all_output
    assert "[REDACTED]" in captured.out
    assert 'org_urn = "urn:li:organization:111"' in captured.out
    assert 'org_urn = "urn:li:organization:222"' in captured.out
    assert "LINKEDIN_ORG_URN=" not in captured.out

    contents = env_file.read_text(encoding="utf-8")
    parsed = dotenv_values(env_file)
    assert parsed["LINKEDIN_ACCESS_TOKEN"] == access
    assert parsed["LINKEDIN_REFRESH_TOKEN"] == refresh
    assert "# behold denne kommentaren\n" in contents
    assert "UNRELATED=behold-meg\n\n" in contents
    assert "# og denne kommentaren\n" in contents
    assert "LINKEDIN_ORG_URN" not in contents
    assert stat.S_IMODE(env_file.stat().st_mode) == 0o600
    assert env_file.stat().st_ino != old_inode  # os.replace, not an in-place partial write

    files = [path for path in tmp_path.rglob("*") if path.is_file()]
    assert files == [env_file]
    assert sum(access in path.read_text(encoding="utf-8") for path in files) == 1
    assert sum(refresh in path.read_text(encoding="utf-8") for path in files) == 1


def test_token_endpoint_body_med_hemmeligheter_blir_aldri_skrevet_ut(
    tmp_path, monkeypatch, capsys, caplog
):
    leaked_access = "provider-" + "access-should-stay-hidden"
    leaked_refresh = "provider-" + "refresh-should-stay-hidden"
    env_file = tmp_path / ".env"
    env_file.write_text("# urørt\n", encoding="utf-8")
    monkeypatch.setenv("BRANDPOST_ENV_FILE", str(env_file))
    monkeypatch.setenv("LINKEDIN_CLIENT_ID", "client-id")
    monkeypatch.setenv("LINKEDIN_CLIENT_SECRET", "client-secret")
    monkeypatch.setattr(linkedin_auth.secrets, "token_urlsafe", lambda _n: "known-state")
    monkeypatch.setattr(linkedin_auth, "HTTPServer", _CallbackServer)
    monkeypatch.setattr(linkedin_auth.webbrowser, "open", lambda _url: True)
    monkeypatch.setattr(
        linkedin_auth.requests,
        "post",
        lambda *_args, **_kwargs: _Response(
            400,
            {},
            text=f"access_token={leaked_access}&refresh_token={leaked_refresh}",
        ),
    )

    assert linkedin_auth.main() == 1

    output = capsys.readouterr()
    all_output = output.out + output.err + caplog.text
    assert leaked_access not in all_output
    assert leaked_refresh not in all_output
    assert "HTTP 400" in output.err
    assert env_file.read_text(encoding="utf-8") == "# urørt\n"


def test_oauth_avviser_manglende_eksplisitt_env_fil(monkeypatch, capsys):
    monkeypatch.delenv("BRANDPOST_ENV_FILE", raising=False)
    monkeypatch.setattr(
        linkedin_auth.webbrowser,
        "open",
        lambda _url: (_ for _ in ()).throw(AssertionError("nettleser skal ikke åpnes")),
    )

    assert linkedin_auth.main() == 1

    output = capsys.readouterr()
    assert "BRANDPOST_ENV_FILE" in output.err


def test_tokenfil_avviser_symlink_og_lar_maalet_vaere_uroert(tmp_path, monkeypatch, capsys):
    target = tmp_path / "virkelig.env"
    target.write_text("UNRELATED=behold\n", encoding="utf-8")
    link = tmp_path / "valgt.env"
    os.symlink(target, link)
    monkeypatch.setenv("BRANDPOST_ENV_FILE", str(link))

    assert linkedin_auth.main() == 1

    output = capsys.readouterr()
    assert "BRANDPOST_ENV_FILE" in output.err
    assert target.read_text(encoding="utf-8") == "UNRELATED=behold\n"
