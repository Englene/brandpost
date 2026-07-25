"""model — ett strukturert kall til en tekstmodell.

Systemet trenger bare én ting av en språkmodell: gi meg JSON som følger dette
skjemaet. Alt annet (planlegging, innleggstekst, slide-omskriving) er bygget på det.

To bakender, samme funksjon:

  api  (standard)  Anthropic-API-et direkte. Krever ANTHROPIC_API_KEY.
  cli              Claude Code-kommandolinja. Krever `claude` installert og
                   innlogget, men koster ingenting ekstra for abonnenter.

Velg med BRANDPOST_MODEL_BACKEND. Standarden er `api`, fordi det er det som virker
for en fremmed som nettopp har klonet repoet.

Modellen som brukes settes med BRANDPOST_MODEL. Fallbacken (BRANDPOST_MODEL_FALLBACK)
MÅ være en annen modellfamilie enn primæren: er begge fra samme familie, har en
overbelastning ingen fluktvei.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from typing import Any

DEFAULT_MODEL = "claude-sonnet-5"
DEFAULT_FALLBACK = "claude-haiku-4-5-20251001"
DEFAULT_MAX_TOKENS = 8000


class ModelError(RuntimeError):
    """Modellen svarte ikke brukbart, på noen av bakendene som ble prøvd."""


class QuotaExhausted(ModelError):
    """Konto-vid grense: ingen modell svarer nå, så fallback er meningsløst."""


def backend() -> str:
    b = (os.environ.get("BRANDPOST_MODEL_BACKEND") or "api").strip().lower()
    return "cli" if b == "cli" else "api"


def model_name() -> str:
    return (os.environ.get("BRANDPOST_MODEL") or DEFAULT_MODEL).strip() or DEFAULT_MODEL


def fallback_name() -> str:
    return (os.environ.get("BRANDPOST_MODEL_FALLBACK")
            or DEFAULT_FALLBACK).strip() or DEFAULT_FALLBACK


def _family(m: str) -> str:
    """Grovt modellfamilie-navn, brukt for å hindre at primær og fallback er like."""
    return m.split("[")[0].removeprefix("claude-").split("-")[0]


def claude_bin() -> str:
    return (os.environ.get("BRANDPOST_CLAUDE_BIN")
            or shutil.which("claude") or "claude")


# ── bakende: Anthropic-API ─────────────────────────────────

def _call_api(system_prompt: str, user_message: str, schema: dict,
              model: str, timeout: int) -> dict:
    try:
        import anthropic
    except ImportError as e:  # noqa: BLE001
        raise ModelError(
            "pakken `anthropic` mangler. Installer den, eller sett "
            "BRANDPOST_MODEL_BACKEND=cli for å bruke Claude Code i stedet.") from e
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise ModelError(
            "ANTHROPIC_API_KEY mangler. Sett den, eller bruk "
            "BRANDPOST_MODEL_BACKEND=cli hvis du har Claude Code installert.")

    client = anthropic.Anthropic(timeout=timeout)
    # Verktøy-kall er den bærbare måten å få garantert skjema-form på: modellen må
    # fylle inn parametrene, i stedet for å skrive JSON i fritekst som vi må gjette på.
    verktoy = {"name": "svar", "description": "Lever svaret på dette skjemaet.",
               "input_schema": schema}
    try:
        resp = client.messages.create(
            model=model,
            max_tokens=int(os.environ.get("BRANDPOST_MAX_TOKENS") or DEFAULT_MAX_TOKENS),
            system=system_prompt,
            tools=[verktoy],
            tool_choice={"type": "tool", "name": "svar"},
            messages=[{"role": "user", "content": user_message}],
        )
    except Exception as e:  # noqa: BLE001
        tekst = str(e)
        if "credit" in tekst.lower() or "billing" in tekst.lower():
            raise QuotaExhausted(tekst[:300]) from e
        raise ModelError(tekst[:300]) from e

    for blokk in resp.content:
        if getattr(blokk, "type", "") == "tool_use":
            return {"structured_output": blokk.input, "_model": model}
    raise ModelError(f"{model}: svarte uten å fylle ut skjemaet")


# ── bakende: Claude Code-kommandolinja ─────────────────────

def _call_cli(system_prompt: str, user_message: str, schema: dict,
              model: str, timeout: int) -> dict:
    cmd = [claude_bin(), "--print", "--model", model, "--output-format", "json",
           "--json-schema", json.dumps(schema), "--append-system-prompt", system_prompt]
    try:
        r = subprocess.run(cmd, input=user_message, capture_output=True,
                           text=True, timeout=timeout)
    except FileNotFoundError as e:
        raise ModelError(
            "fant ikke `claude`. Installer Claude Code, eller la "
            "BRANDPOST_MODEL_BACKEND stå på `api`.") from e
    except subprocess.TimeoutExpired as e:
        raise ModelError(f"{model}: tidsavbrudd etter {timeout}s") from e

    feil = (r.stderr or "").strip()
    if r.returncode != 0 or not r.stdout.strip():
        if "credit" in feil.lower() or "usage limit" in feil.lower():
            raise QuotaExhausted(f"{model}: {feil[:200]}")
        raise ModelError(f"{model}: exit {r.returncode}: {feil[:200]}")
    try:
        envelope = json.loads(r.stdout)
    except json.JSONDecodeError as e:
        raise ModelError(f"{model}: ugyldig JSON-svar ({e})") from e
    envelope["_model"] = model
    return envelope


# ── offentlig API ──────────────────────────────────────────

def structured_call(system_prompt: str, user_message: str, schema: dict,
                    timeout: int = 300, label: str = "kall",
                    model: str | None = None) -> dict[str, Any]:
    """Be modellen om JSON som følger `schema`.

    Returnerer konvolutten, der svaret ligger under `structured_output`. Konvolutt-
    formen er delt mellom begge bakendene med vilje, så kallerne slipper å vite
    hvilken som svarte.

    Prøver fallback-modellen én gang hvis primæren feiler, men ALDRI ved konto-vid
    grense: da hjelper ingen modell, og et nytt forsøk er bare bortkastet tid.
    """
    primaer = model or model_name()
    stige = [primaer]
    fb = fallback_name()
    if fb and _family(fb) != _family(primaer):
        stige.append(fb)

    kall = _call_cli if backend() == "cli" else _call_api
    siste = ""
    for i, m in enumerate(stige):
        try:
            svar = kall(system_prompt, user_message, schema, m, timeout)
        except QuotaExhausted:
            raise
        except ModelError as e:
            siste = str(e)
            if i < len(stige) - 1:
                print(f"  ⚠️  {label}: {siste[:160]}, prøver {stige[i + 1]}")
            continue
        if i > 0:
            print(f"  ({label}: falt tilbake til {m})")
        return svar
    raise ModelError(f"{label}: alle modellene feilet. Siste: {siste[:300]}")
