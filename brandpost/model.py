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
from pathlib import Path
from typing import Any

DEFAULT_MODEL = "claude-sonnet-5"
DEFAULT_FALLBACK = "claude-haiku-4-5-20251001"
DEFAULT_MAX_TOKENS = 8000


class ModelError(RuntimeError):
    """Modellen svarte ikke brukbart, på noen av bakendene som ble prøvd."""


class QuotaExhausted(ModelError):
    """Konto-vid grense: ingen modell svarer nå, så fallback er meningsløst."""


class OppsettFeil(ModelError):
    """Noe mangler i oppsettet: nøkkel, pakke, binærfil.

    Egen type fordi den skal HOPPE OVER fallback-stigen. En manglende nøkkel feiler
    like hardt på modell to, og å prøve igjen gir bare en forvirrende ekstra
    feilmelding oppå den ene som betyr noe."""


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

_BILDETYPER = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
               ".gif": "image/gif", ".webp": "image/webp"}


def _bildeblokker(images: list[str]) -> list[dict]:
    """Bildefiler som base64-blokker til Anthropic-API-et.

    Ulesbare eller ukjente filtyper hoppes over i stillhet: kalleren bestemmer selv
    hva som skal skje når ingen bilder kom med, og det er en bedre plass å ta den
    avgjørelsen enn her nede."""
    import base64
    ut: list[dict] = []
    for sti in images:
        p = Path(sti)
        mediatype = _BILDETYPER.get(p.suffix.lower())
        if not mediatype:
            continue
        try:
            raa = p.read_bytes()
        except OSError:
            continue
        ut.append({"type": "image", "source": {
            "type": "base64", "media_type": mediatype,
            "data": base64.standard_b64encode(raa).decode("ascii")}})
    return ut


def _call_api(system_prompt: str, user_message: str, schema: dict,
              model: str, timeout: int, images: list[str] | None = None) -> dict:
    try:
        import anthropic
    except ImportError as e:  # noqa: BLE001
        raise OppsettFeil(
            "pakken `anthropic` mangler. Installer den, eller sett "
            "BRANDPOST_MODEL_BACKEND=cli for å bruke Claude Code i stedet.") from e
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise OppsettFeil(
            "ANTHROPIC_API_KEY mangler. Sett den, eller bruk "
            "BRANDPOST_MODEL_BACKEND=cli hvis du har Claude Code installert.")

    client = anthropic.Anthropic(timeout=timeout)
    # Verktøy-kall er den bærbare måten å få garantert skjema-form på: modellen må
    # fylle inn parametrene, i stedet for å skrive JSON i fritekst som vi må gjette på.
    verktoy = {"name": "svar", "description": "Lever svaret på dette skjemaet.",
               "input_schema": schema}
    # Bildene FØRST, teksten sist: modellen skal ha sett bildet før den leser
    # spørsmålet om det.
    innhold: list[dict] = _bildeblokker(images or [])
    innhold.append({"type": "text", "text": user_message})
    try:
        resp = client.messages.create(
            model=model,
            max_tokens=int(os.environ.get("BRANDPOST_MAX_TOKENS") or DEFAULT_MAX_TOKENS),
            system=system_prompt,
            tools=[verktoy],
            tool_choice={"type": "tool", "name": "svar"},
            messages=[{"role": "user", "content": innhold}],
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

_CLI_ERROR_TEXT_KEYS = {"detail", "error", "errors", "message", "reason", "result"}
_CLI_QUOTA_MARKERS = (
    "credit balance",
    "credit limit",
    "credits exhausted",
    "hit your limit",
    "quota exceeded",
    "rate limit",
    "usage limit",
    "weekly limit",
    "weekly usage",
)


def _kort_feiltekst(tekst: str, grense: int = 200) -> str:
    """Enlinjesammendrag uten at hele CLI-svaret havner i logger/feilmeldinger."""
    return " ".join(tekst.split())[:grense]


def _har_cli_kvotesignal(verdi: object) -> bool:
    """Finn konto-/rategrense i en Claude CLI-konvolutt uten å serialisere den.

    Claude CLI legger noen API-feil i stdout som JSON, og kan samtidig returnere
    både exit 0 og exit != 0. Derfor kan ikke stderr alene brukes som fasit.
    """
    if isinstance(verdi, dict):
        for nokkel, innhold in verdi.items():
            if str(nokkel).lower() == "api_error_status":
                try:
                    if int(innhold) == 429:
                        return True
                except (TypeError, ValueError):
                    pass
            if _har_cli_kvotesignal(innhold):
                return True
        return False
    if isinstance(verdi, list):
        return any(_har_cli_kvotesignal(element) for element in verdi)
    if isinstance(verdi, str):
        tekst = verdi.lower()
        return any(markor in tekst for markor in _CLI_QUOTA_MARKERS)
    return False


def _cli_feilsammendrag(envelope: dict[str, object]) -> str:
    """Trekk ut et kort, kontrollert sammendrag fra kjente feilfelt."""
    funn: list[str] = []

    def legg_til(verdi: object) -> None:
        if len(" ".join(funn)) >= 200:
            return
        if isinstance(verdi, str):
            kort = _kort_feiltekst(verdi)
            if kort:
                funn.append(kort)
        elif isinstance(verdi, dict):
            for nokkel, innhold in verdi.items():
                if str(nokkel).lower() in _CLI_ERROR_TEXT_KEYS:
                    legg_til(innhold)
        elif isinstance(verdi, list):
            for element in verdi:
                legg_til(element)

    for nokkel, verdi in envelope.items():
        if str(nokkel).lower() in _CLI_ERROR_TEXT_KEYS:
            legg_til(verdi)
    return _kort_feiltekst("; ".join(funn))


def _call_cli(system_prompt: str, user_message: str, schema: dict,
              model: str, timeout: int, images: list[str] | None = None) -> dict:
    cmd = [claude_bin(), "--print", "--model", model, "--output-format", "json",
           "--json-schema", json.dumps(schema), "--append-system-prompt", system_prompt]
    if images:
        # Kommandolinja tar ikke bilder som argument, men Claude Code kan lese dem
        # selv. Stien i meldingen er derfor hele mekanismen, og den forutsetter at
        # Read er tillatt i kjøringen. Er den ikke det, kommer svaret uten å ha sett
        # bildet, og kalleren MÅ behandle det som en mislykket vurdering.
        stier = "\n".join(f"- {s}" for s in images)
        user_message = (f"Les disse bildefilene med Read-verktøyet før du svarer:\n"
                        f"{stier}\n\n{user_message}")
    try:
        r = subprocess.run(cmd, input=user_message, capture_output=True,
                           text=True, timeout=timeout)
    except FileNotFoundError as e:
        raise OppsettFeil(
            "fant ikke `claude`. Installer Claude Code, eller la "
            "BRANDPOST_MODEL_BACKEND stå på `api`.") from e
    except subprocess.TimeoutExpired as e:
        raise ModelError(f"{model}: tidsavbrudd etter {timeout}s") from e

    feil = (r.stderr or "").strip()
    stdout = (r.stdout or "").strip()
    if not stdout:
        if _har_cli_kvotesignal(feil):
            raise QuotaExhausted(f"{model}: Claude-bruksgrensen er nådd")
        sammendrag = _kort_feiltekst(feil) or "Claude CLI ga ikke noe svar"
        raise ModelError(f"{model}: exit {r.returncode}: {sammendrag}")
    try:
        envelope = json.loads(stdout)
    except json.JSONDecodeError as e:
        # Teksten brukes bare til klassifisering. Den gjengis aldri i unntaket.
        if _har_cli_kvotesignal(stdout) or _har_cli_kvotesignal(feil):
            raise QuotaExhausted(f"{model}: Claude-bruksgrensen er nådd") from e
        if r.returncode != 0:
            sammendrag = _kort_feiltekst(feil) or "Claude CLI returnerte ugyldig JSON"
            raise ModelError(f"{model}: exit {r.returncode}: {sammendrag}") from e
        raise ModelError(f"{model}: ugyldig JSON-svar ({e})") from e
    if not isinstance(envelope, dict):
        raise ModelError(f"{model}: JSON-svaret var ikke en objektkonvolutt")

    er_feil = envelope.get("is_error") is True
    if (r.returncode != 0 or er_feil) and _har_cli_kvotesignal(envelope):
        # Ikke ta med stdout-detaljene: de kan inneholde prompt, interne felter eller
        # andre store/sensitive verdier. Feiltypen er all informasjon kalleren trenger.
        raise QuotaExhausted(f"{model}: Claude-bruksgrensen er nådd")
    if r.returncode != 0 or er_feil:
        sammendrag = _cli_feilsammendrag(envelope)
        if not sammendrag:
            sammendrag = _kort_feiltekst(feil) or "Claude CLI rapporterte en feil"
        status = f"exit {r.returncode}: " if r.returncode != 0 else ""
        raise ModelError(f"{model}: {status}{sammendrag}")
    envelope["_model"] = model
    return envelope


# ── offentlig API ──────────────────────────────────────────

def structured_call(system_prompt: str, user_message: str, schema: dict,
                    timeout: int = 300, label: str = "kall",
                    model: str | None = None,
                    images: list[str] | None = None) -> dict[str, Any]:
    """Be modellen om JSON som følger `schema`.

    Returnerer konvolutten, der svaret ligger under `structured_output`. Konvolutt-
    formen er delt mellom begge bakendene med vilje, så kallerne slipper å vite
    hvilken som svarte.

    `images` er stier til bildefiler modellen skal se på. De to bakendene løser det
    ulikt: API-et får dem som base64, kommandolinja får stiene og leser dem selv.
    Forskjellen betyr at CLI-veien kan svare UTEN å ha sett bildet dersom Read ikke
    er tillatt, så en kaller som tar sikkerhetsavgjørelser på bildeinnhold må kreve
    et positivt bevis i svaret framfor å stole på at bildet ble lest.

    Prøver fallback-modellen én gang hvis primæren feiler, men ALDRI ved konto-vid
    grense: da hjelper ingen modell, og et nytt forsøk er bare bortkastet tid.
    """
    primaer = model or model_name()
    stige = [primaer]
    fb = fallback_name()
    if fb and _family(fb) != _family(primaer):
        stige.append(fb)

    kall = _call_cli if backend() == "cli" else _call_api
    # `images` sendes bare når det faktisk er bilder. Uten bilder er kallet
    # nøyaktig som før, helt ned til antall argumenter, og da fortsetter kode som
    # bytter ut bakenden (tester, egne bakender) å virke uendret.
    ekstra = {"images": images} if images else {}
    siste = ""
    for i, m in enumerate(stige):
        try:
            svar = kall(system_prompt, user_message, schema, m, timeout, **ekstra)
        except (QuotaExhausted, OppsettFeil):
            raise  # ingen modell fikser en tom nøkkel eller en nådd kontogrense
        except ModelError as e:
            siste = str(e)
            if i < len(stige) - 1:
                print(f"  ⚠️  {label}: {siste[:160]}, prøver {stige[i + 1]}")
            continue
        if i > 0:
            print(f"  ({label}: falt tilbake til {m})")
        return svar
    raise ModelError(f"{label}: alle modellene feilet. Siste: {siste[:300]}")
