"""Regresjonstester for Claude CLIs JSON-feilkonvolutter på stdout."""

from __future__ import annotations

import json
from subprocess import CompletedProcess

import pytest

from brandpost import model


SKJEMA = {"type": "object", "properties": {"ok": {"type": "boolean"}}}


def _result(stdout: dict, *, returncode: int = 0, stderr: str = "") -> CompletedProcess:
    return CompletedProcess(
        args=["claude"],
        returncode=returncode,
        stdout=json.dumps(stdout),
        stderr=stderr,
    )


def test_ukesgrense_i_stdout_med_feilkode_er_kvote(monkeypatch):
    svar = _result(
        {
            "type": "result",
            "subtype": "error_during_execution",
            "is_error": True,
            "result": "You've hit your weekly limit. Resets Monday.",
        },
        returncode=1,
    )
    monkeypatch.setattr(model.subprocess, "run", lambda *a, **k: svar)

    with pytest.raises(model.QuotaExhausted, match="bruksgrensen"):
        model._call_cli("system", "bruker", SKJEMA, "claude-sonnet", 10)


def test_usage_limit_med_exit_null_er_kvote(monkeypatch):
    svar = _result({"is_error": True, "result": "Usage limit reached"})
    monkeypatch.setattr(model.subprocess, "run", lambda *a, **k: svar)

    with pytest.raises(model.QuotaExhausted):
        model._call_cli("system", "bruker", SKJEMA, "claude-sonnet", 10)


def test_api_error_status_429_i_nested_konvolutt_er_kvote(monkeypatch):
    svar = _result(
        {
            "is_error": True,
            "error": {
                "type": "api_error",
                "api_error_status": 429,
                "message": "Too many requests",
            },
        },
        returncode=1,
    )
    monkeypatch.setattr(model.subprocess, "run", lambda *a, **k: svar)

    with pytest.raises(model.QuotaExhausted):
        model._call_cli("system", "bruker", SKJEMA, "claude-sonnet", 10)


def test_kvoteproevingen_gaar_ikke_videre_til_fallback(monkeypatch):
    monkeypatch.setenv("BRANDPOST_MODEL_BACKEND", "cli")
    monkeypatch.setenv("BRANDPOST_MODEL", "claude-sonnet-5")
    monkeypatch.setenv("BRANDPOST_MODEL_FALLBACK", "claude-haiku-4-5-20251001")
    kall = []

    def kvote(*args, **kwargs):
        kall.append(args[3])
        raise model.QuotaExhausted("kontoens ukesgrense")

    monkeypatch.setattr(model, "_call_cli", kvote)

    with pytest.raises(model.QuotaExhausted):
        model.structured_call("system", "bruker", SKJEMA)
    assert kall == ["claude-sonnet-5"]


def test_ikke_kvote_feilkonvolutt_lekkjer_ikke_hele_stdout(monkeypatch):
    hemmelig_hale = "IKKE_LEKK_" * 200
    svar = _result(
        {
            "is_error": True,
            "result": "Tillatelse mangler. " + hemmelig_hale,
            "debug_payload": hemmelig_hale,
        }
    )
    monkeypatch.setattr(model.subprocess, "run", lambda *a, **k: svar)

    with pytest.raises(model.ModelError) as fanget:
        model._call_cli("system", "bruker", SKJEMA, "claude-sonnet", 10)
    tekst = str(fanget.value)
    assert len(tekst) <= 230
    assert hemmelig_hale not in tekst
    assert "debug_payload" not in tekst


def test_vellykket_konvolutt_returneres_som_foer(monkeypatch):
    svar = _result({"structured_output": {"ok": True}, "is_error": False})
    monkeypatch.setattr(model.subprocess, "run", lambda *a, **k: svar)

    resultat = model._call_cli("system", "bruker", SKJEMA, "claude-sonnet", 10)

    assert resultat == {
        "structured_output": {"ok": True},
        "is_error": False,
        "_model": "claude-sonnet",
    }
