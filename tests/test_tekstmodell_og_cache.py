"""Tekstkallene: hvilken modell som skriver, og hva som går inn i hvert kall.

Målt 29. september 2026 på en ekte bunke-prompt: med Claude Codes standardoppsett
var to tredjedeler av genereringskallet kodeagent-prompt, verktøylister og
CLAUDE.md fra arbeidskatalogen (46 600 tokens mot 20 000), og med Bash tilgjengelig
brukte modellen ni runder på å lese vaulten før den skrev. Systemprompten var
heller aldri lik to ganger, så cachen traff aldri mellom to påfyll.
"""
from __future__ import annotations

import json
from subprocess import CompletedProcess

from brandpost import brandkit, model

SKJEMA = {"type": "object", "properties": {"ok": {"type": "boolean"}}}


def _fang_run(monkeypatch) -> dict:
    sett: dict = {}

    def run(cmd, **kw):
        sett["cmd"] = cmd
        sett["cwd"] = kw.get("cwd")
        return CompletedProcess(args=cmd, returncode=0, stderr="",
                                stdout=json.dumps({"structured_output": {"ok": True}}))
    monkeypatch.setattr(model.subprocess, "run", run)
    return sett


def _flagg(cmd: list[str], navn: str) -> str | None:
    return cmd[cmd.index(navn) + 1] if navn in cmd else None


# ── kommandolinja ──────────────────────────────────────────

def test_tekstkall_er_rene(monkeypatch):
    """Vår prompt er hele systemprompten, uten verktøy, MCP eller skills."""
    monkeypatch.delenv("BRANDPOST_EFFORT", raising=False)
    sett = _fang_run(monkeypatch)
    model._call_cli("SYSTEM", "bruker", SKJEMA, "claude-sonnet-5-5", 10)
    cmd = sett["cmd"]
    assert _flagg(cmd, "--system-prompt") == "SYSTEM"
    assert "--append-system-prompt" not in cmd, "Claude Codes kodeagent-prompt skal ikke med"
    assert _flagg(cmd, "--tools") == "", "uten verktøy kan modellen ikke gå rundt i vaulten"
    assert "--strict-mcp-config" in cmd and "--disable-slash-commands" in cmd
    assert "--effort" not in cmd, "uten BRANDPOST_EFFORT gjelder modellens standard"


def test_tekstkall_kjorer_fra_tom_katalog(monkeypatch):
    """CLAUDE.md i arbeidskatalogen ble lest inn som instruksjon i hver generering."""
    sett = _fang_run(monkeypatch)
    model._call_cli("s", "u", SKJEMA, "claude-sonnet-5-5", 10)
    assert sett["cwd"], "tekstkallet skal ha sin egen arbeidskatalog"
    from pathlib import Path
    assert not (Path(sett["cwd"]) / "CLAUDE.md").exists()


def test_bildekall_beholder_lesetilgangen(monkeypatch, tmp_path):
    """Bildene leses med Read. Den veien er uendret: uten verktøy ville svaret
    komme uten at bildet er sett, og bildebanken er fail-closed på nettopp det."""
    bilde = tmp_path / "b.png"
    bilde.write_bytes(b"\x89PNG")
    sett = _fang_run(monkeypatch)
    model._call_cli("SYSTEM", "u", SKJEMA, "claude-opus-5", 10, images=[str(bilde)])
    assert _flagg(sett["cmd"], "--append-system-prompt") == "SYSTEM"
    assert "--tools" not in sett["cmd"]
    assert sett["cwd"] is None


def test_effort_laases_bare_med_gyldig_verdi(monkeypatch):
    sett = _fang_run(monkeypatch)
    monkeypatch.setenv("BRANDPOST_EFFORT", "High")
    model._call_cli("s", "u", SKJEMA, "claude-opus-5-5", 10)
    assert _flagg(sett["cmd"], "--effort") == "high"

    monkeypatch.setenv("BRANDPOST_EFFORT", "turbo")
    model._call_cli("s", "u", SKJEMA, "claude-opus-5-5", 10)
    assert "--effort" not in sett["cmd"], "en skrivefeil skal gi standarden, ikke en feil"


# ── modell per merke og reserven ───────────────────────────

def test_merkemodell_fra_samme_familie_som_fallbacken_faar_hovedmodellen_som_reserve(
        monkeypatch):
    monkeypatch.setenv("BRANDPOST_MODEL_BACKEND", "api")
    monkeypatch.setenv("BRANDPOST_MODEL", "claude-opus-5-5")
    monkeypatch.setenv("BRANDPOST_MODEL_FALLBACK", "claude-sonnet-5")
    sett = []

    def flakete(system, user, schema, m, timeout):
        sett.append(m)
        if len(sett) == 1:
            raise model.ModelError("overbelastet")
        return {"structured_output": {"ok": True}, "_model": m}
    monkeypatch.setattr(model, "_call_api", flakete)

    model.structured_call("s", "u", SKJEMA, model="claude-sonnet-5-5")
    assert sett == ["claude-sonnet-5-5", "claude-opus-5-5"]


def test_ingen_reserve_naar_alt_er_samme_familie(monkeypatch):
    monkeypatch.setenv("BRANDPOST_MODEL", "claude-sonnet-5")
    monkeypatch.setenv("BRANDPOST_MODEL_FALLBACK", "claude-sonnet-5")
    assert model._fallback_for("claude-sonnet-5-5") == ""


def _lag_merke(base, key, *, ekstra: str = "") -> None:
    d = base / key
    (d / "media").mkdir(parents=True)
    (d / "profile.toml").write_text(f"""\
key = "{key}"
name = "Test {key}"
handle = "{key}"
enabled = true
{ekstra}
[palette]
bg = "#FAFAF8"
ink = "#5B6472"
headline = "#22303F"
brand = "#7A5C3E"
shape = "#EDE7DE"
dark = "#22303F"

[fonts]
display = "Fraunces.ttf"
body = "Inter.ttf"

[[pillar]]
id = "funn"
label = "Funn"
desc = "Det vi har funnet"

[[pillar]]
id = "metode"
label = "Metode"
desc = "Hvordan vi jobber"
""", encoding="utf-8")


def test_profilen_kan_velge_tekstmodell(tmp_path, monkeypatch):
    _lag_merke(tmp_path, "medmodell", ekstra='\n[model]\ntext = " claude-sonnet-5-5 "\n')
    _lag_merke(tmp_path, "utenmodell")
    monkeypatch.setenv("BRANDPOST_BRANDS_DIR", str(tmp_path))
    assert brandkit.load_brand("medmodell").text_model == "claude-sonnet-5-5"
    assert brandkit.load_brand("utenmodell").text_model == ""


# ── genereringen ───────────────────────────────────────────

def _generer(monkeypatch, tmp_path, merke: str, dekning: dict) -> dict:
    from brandpost import cli, store
    from brandpost import model as loop_model
    monkeypatch.setenv("BRANDPOST_WORKSPACE", str(tmp_path / "ws"))
    monkeypatch.setattr(store, "pillar_coverage", lambda *a, **k: dict(dekning))
    sett: dict = {}

    def fanger(system, user, schema, label="", timeout=300, **kw):
        sett.update(system=system, user=user, kw=kw)
        return {"structured_output": {"posts": []}}
    monkeypatch.setattr(loop_model, "structured_call", fanger)

    class A:
        brand = merke
        n = 3
        days = 5
        dry_run = True
        bunke = 5
        vault = str(tmp_path / "ws")
    cli.cmd_run(A())
    return sett


def test_systemprompten_er_lik_naar_dekningen_endrer_seg(tmp_path, monkeypatch):
    """Dekningen teller de siste 24 utkastene og endrer seg etter hver runde. Så
    lenge den sto i systemprompten, traff cachen aldri mellom to påfyll."""
    _lag_merke(tmp_path, "cachet")
    monkeypatch.setenv("BRANDPOST_BRANDS_DIR", str(tmp_path))
    foer = _generer(monkeypatch, tmp_path, "cachet", {"funn": 3, "metode": 0})
    etter = _generer(monkeypatch, tmp_path, "cachet", {"funn": 3, "metode": 5})

    assert foer["system"] == etter["system"]
    assert "Det vi har funnet" in foer["system"], "pilarene selv står fast i systemprompten"
    assert "- metode: brukt 0x (PRIORITER)" in foer["user"]
    assert "- funn: brukt 3x (PRIORITER)" in etter["user"]


def test_genereringen_bruker_merkets_tekstmodell(tmp_path, monkeypatch):
    _lag_merke(tmp_path, "medmodell", ekstra='\n[model]\ntext = "claude-sonnet-5-5"\n')
    _lag_merke(tmp_path, "utenmodell")
    monkeypatch.setenv("BRANDPOST_BRANDS_DIR", str(tmp_path))
    assert _generer(monkeypatch, tmp_path, "medmodell", {})["kw"] == {
        "model": "claude-sonnet-5-5"}
    assert "model" not in _generer(monkeypatch, tmp_path, "utenmodell", {})["kw"]


def test_personprompten_anbefaler_ikke_det_schemaet_avviser(tmp_path, monkeypatch):
    """`utdrag` sto som førstevalget i personprompten lenge etter at schemaet
    sluttet å godta den. Modellen fulgte teksten, valideringen avviste svaret, og
    hele genereringen ble kjørt én gang til."""
    from brandpost import cli
    _lag_merke(tmp_path, "menneske", ekstra='\n[voice]\nmode = "person"\n')
    monkeypatch.setenv("BRANDPOST_BRANDS_DIR", str(tmp_path))
    brand = brandkit.load_brand("menneske")
    enum = cli._post_schema(brand)["properties"]["posts"]["items"]["properties"][
        "bildetype"]["enum"]
    assert "utdrag" not in enum

    sett = _generer(monkeypatch, tmp_path, "menneske", {})
    assert "`utdrag`" not in sett["system"]
    assert "`utdrag`" not in sett["user"]
