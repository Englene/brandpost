"""Tester for innholdsplanen (social/plan.py): guardrails, rulling og run-kobling."""

from __future__ import annotations

import argparse
import json
from datetime import date

from brandpost import plan as planmod


def _fake_model(monkeypatch, slots, weeks=None):
    def fake_call(system, user, schema, timeout=300, label="", model=None):
        return {"structured_output": {"weeks": weeks or [], "slots": slots}}
    monkeypatch.setattr(planmod.loop_model, "structured_call", fake_call)


def test_refresh_only_fills_post_days_and_snaps(tmp_path, monkeypatch):
    # Kadence fra 22. juli 2026: man/tir/ons/tor (4 i uka). Fredag snappes bort,
    # ukjent pilar nulles, og karusell-cap gjelder fortsatt per uke.
    start = date(2026, 7, 13)  # mandag
    _fake_model(monkeypatch, slots=[
        {"date": "2026-07-13", "tema": "A", "pillar": "myte-avliving", "format": "bilde"},
        {"date": "2026-07-14", "tema": "tirsdag er nå gyldig", "pillar": "myte-avliving"},
        {"date": "2026-07-15", "tema": "B", "pillar": "finnes-ikke", "format": "karusell"},
        {"date": "2026-07-17", "tema": "fredag skal bort", "format": "karusell"},
    ], weeks=[{"iso_week": "2026-W29", "narrativ": "Uka om pris"}])
    res = planmod.refresh_plan(tmp_path, when=start, horizon_days=7)
    assert [s["date"] for s in res["slots"]] == [
        "2026-07-13", "2026-07-14", "2026-07-15", "2026-07-16"]
    by = {s["date"]: s for s in res["slots"]}
    assert by["2026-07-14"]["tema"] == "tirsdag er nå gyldig"
    assert by["2026-07-15"]["pillar"] == ""          # ukjent pilar snappet bort
    assert by["2026-07-15"]["format"] == "karusell"
    assert res["weeks"] == [{"iso_week": "2026-W29", "narrativ": "Uka om pris"}]
    assert (tmp_path / "socials" / "plan.json").exists()


def test_refresh_preserves_locked_slots(tmp_path, monkeypatch):
    start = date(2026, 7, 13)
    _fake_model(monkeypatch, slots=[{"date": "2026-07-13", "tema": "første"}])
    planmod.refresh_plan(tmp_path, when=start, horizon_days=3)
    assert planmod.mark_slot(tmp_path, "2026-07-13", "utkast",
                             draft_ref={"manifest": "2026-07-13"})
    _fake_model(monkeypatch, slots=[
        {"date": "2026-07-13", "tema": "NY som skal ignoreres"},
        {"date": "2026-07-15", "tema": "onsdag"},
    ])
    res = planmod.refresh_plan(tmp_path, when=start, horizon_days=7)
    by = {s["date"]: s for s in res["slots"]}
    assert by["2026-07-13"]["tema"] == "første"      # låst slot består
    assert by["2026-07-13"]["status"] == "utkast"
    assert by["2026-07-13"]["draft_ref"] == {"manifest": "2026-07-13"}
    assert by["2026-07-15"]["tema"] == "onsdag"


def test_model_silence_gives_open_slots(tmp_path, monkeypatch):
    _fake_model(monkeypatch, slots=[])
    res = planmod.refresh_plan(tmp_path, when=date(2026, 7, 13), horizon_days=7)
    assert len(res["slots"]) == 4                    # man/tir/ons/tor finnes uansett
    assert all(s["status"] == "planlagt" and s["tema"] == "" for s in res["slots"])


def test_today_slot_and_mark_slot(tmp_path, monkeypatch):
    _fake_model(monkeypatch, slots=[
        {"date": "2026-07-13", "tema": "X", "pillar": "myte-avliving"}])
    planmod.refresh_plan(tmp_path, when=date(2026, 7, 13), horizon_days=3)
    slot = planmod.today_slot(tmp_path, when=date(2026, 7, 13))
    assert slot and slot["tema"] == "X" and slot["pillar"] == "myte-avliving"
    # Fredag er ikke publiseringsdag etter 22. juli-kadencen, så ingen slot der.
    assert planmod.today_slot(tmp_path, when=date(2026, 7, 17)) is None
    planmod.mark_slot(tmp_path, "2026-07-13", "publisert")
    assert planmod.today_slot(tmp_path, when=date(2026, 7, 13))["status"] == "publisert"


def test_run_fills_open_slots_across_days(tmp_path, monkeypatch):
    # Slot-fylling: run skal be om ETT utkast per åpen slot, rendre dem til
    # riktige dags-manifester og markere slotsene som utkast.
    from datetime import timedelta

    from brandpost import model as loop_model
    from brandpost import cli as clim

    today = date.today()
    d2 = (today + timedelta(days=3)).isoformat()
    d = tmp_path / "socials"
    d.mkdir(parents=True)
    (d / "plan.json").write_text(json.dumps({"weeks": [], "slots": [
        {"date": today.isoformat(), "brand": "demo", "pillar": "myte-avliving",
         "format": "bilde", "tema": "Dagens røde tråd-tema", "status": "planlagt"},
        {"date": d2, "brand": "demo", "pillar": "myte-avliving",
         "format": "bilde", "tema": "Neste tema", "status": "planlagt"},
    ]}, ensure_ascii=False), encoding="utf-8")

    captured: dict = {}

    def fake_call(system, user, schema, timeout=300, label="", model=None):
        captured["user"] = user
        return {"structured_output": {"posts": [
            {"type": "bilde", "format": "typografi-kort", "headline": "A",
             "body": "b", "why_now": "w", "pillar": "myte-avliving",
             "slot_date": today.isoformat()},
            {"type": "bilde", "format": "typografi-kort", "headline": "B",
             "body": "b", "why_now": "w", "pillar": "myte-avliving", "slot_date": d2},
        ]}}

    monkeypatch.setattr(loop_model, "structured_call", fake_call)
    monkeypatch.delenv("BRANDPOST_MAIL_ENABLED", raising=False)  # e-post blir dry-run
    rc = clim.cmd_run(argparse.Namespace(vault=str(tmp_path), brand="demo",
                                         n=3, days=10, dry_run=True))
    assert rc == 0
    assert "ÅPNE PLAN-SLOTS" in captured["user"]
    assert "Dagens røde tråd-tema" in captured["user"] and "Neste tema" in captured["user"]
    for ds in (today.isoformat(), d2):  # ett manifest per slot-dato
        m = json.loads((d / ds / "manifest.json").read_text(encoding="utf-8"))
        assert len(m["drafts"]) == 1
    slots = {s["date"]: s for s in planmod.load_plan(tmp_path)["slots"]}
    assert slots[today.isoformat()]["status"] == "utkast"
    assert slots[d2]["status"] == "utkast"


# ── kadence: ÉN kilde (Oscars retting 22. juli) ──────────────────────────────

def test_post_days_er_fire_i_uka():
    """2-4 i uka er referansen for firmasider; oftere kannibaliserer rekkevidden."""
    assert planmod.POST_DAYS == (0, 1, 2, 3)          # man/tir/ons/tor
    assert 4 not in planmod.POST_DAYS                 # fredag ute (svak B2B-dag)


def test_post_days_kan_overstyres_med_env(monkeypatch):
    """Oscar skal kunne prøve daglig uten kodeendring."""
    monkeypatch.setenv("NOTATER_SOME_POST_DAYS", "0,1,2,3,4")
    assert planmod._post_days() == (0, 1, 2, 3, 4)
    monkeypatch.setenv("NOTATER_SOME_POST_DAYS", "tull")
    assert planmod._post_days() == (0, 1, 2, 3)       # ugyldig -> default




def test_plan_tema_saneres_for_tankestrek(tmp_path, monkeypatch):
    """Plan-temaene mater hjernen, så tankestrek her smitter over i publisert
    tekst. 22. juli hadde 11 av 13 slots tankestrek fordi saneringen bare fantes
    i cli, ikke i plan-motoren."""
    _fake_model(monkeypatch, slots=[
        {"date": "2026-07-13", "tema": "Konsulenten tar 15–25 % — AI gjor jobben",
         "pillar": "myte-avliving"}])
    res = planmod.refresh_plan(tmp_path, when=date(2026, 7, 13), horizon_days=3)
    tema = {s["date"]: s["tema"] for s in res["slots"]}["2026-07-13"]
    assert "—" not in tema and "–" not in tema
    assert "15-25 %" in tema            # tallspenn -> bindestrek
    assert ", AI gjor jobben" in tema   # resten -> komma


def test_bevarte_slots_saneres_ogsaa(tmp_path, monkeypatch):
    """Laaste slots beholder tema og status, men skal ikke baere tankestrek
    videre i det uendelige (5 av 13 gjorde det etter forste fiks)."""
    d = tmp_path / "socials"
    d.mkdir(parents=True)
    (d / "plan.json").write_text(json.dumps({"weeks": [], "slots": [
        {"date": "2026-07-13", "brand": "demo", "pillar": "myte-avliving",
         "format": "bilde", "tema": "Konsulenten tar 15–25 % — AI gjor jobben",
         "status": "utkast"}]}, ensure_ascii=False), encoding="utf-8")
    _fake_model(monkeypatch, slots=[])
    res = planmod.refresh_plan(tmp_path, when=date(2026, 7, 13), horizon_days=3)
    laast = {s["date"]: s for s in res["slots"]}["2026-07-13"]
    assert laast["status"] == "utkast"          # laasingen bestaar
    assert "—" not in laast["tema"] and "–" not in laast["tema"]
    assert "15-25 %" in laast["tema"]
