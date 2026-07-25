"""Tester for Slack-pulsen, karusell-publiseringen, svar-flyten og engasjementet.

Alt nettverk er mocket: Slack-hjelperne (slack_deep/slack_evidence), modellkallet
(loop_model.structured_call), LinkedIn-sesjonen og mailer.send_email. Testene
verifiserer kontraktene fra planen: DM-er leses aldri, destillatet skrives som
pulse-fil context plukker opp, karusell publiseres som dokumentpost med title,
og «publiser: 2»-svar publiserer akkurat det utpekte utkastet.
"""

from __future__ import annotations

import json
import os
from datetime import date, datetime, timedelta
from pathlib import Path

import requests

from brandpost import model as loop_model
from brandpost import (context as ctxmod, email as emailmod,
                                    engagement, linkedin, store)


# ── hjelpere ───────────────────────────────────────────────

class _Resp:
    def __init__(self, status=200, json_data=None, headers=None):
        self.status_code = status
        self._json = json_data or {}
        self.headers = headers or {}
        self.content = json.dumps(self._json).encode()

    def json(self):
        return self._json

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}", response=self)


class _LinkedInSession:
    """Fanger 3-stegs-sekvensen for dokument- og bildeposter."""

    def __init__(self, kind="documents", urn="urn:li:document:42"):
        self.kind, self.urn, self.calls = kind, urn, []

    def post(self, url, **kw):
        self.calls.append(("POST", url, kw))
        if f"{self.kind}?action=initializeUpload" in url:
            key = "image" if self.kind == "images" else "document"
            return _Resp(json_data={"value": {"uploadUrl": "https://up.example/x",
                                              key: self.urn}})
        if url.endswith("/rest/posts"):
            return _Resp(headers={"x-restli-id": "urn:li:share:99"})
        return _Resp(400)

    def put(self, url, **kw):
        self.calls.append(("PUT", url, kw))
        return _Resp()


def _cfg(**over):
    base = dict(client_id="", client_secret="", access_token="tok",
                refresh_token="", org_urn="urn:li:organization:1", enabled=True)
    base.update(over)
    return linkedin.LinkedInConfig(**base)


def _manifest_with_drafts(vault: Path, day: str, drafts: list[dict]) -> Path:
    day_dir = vault / "socials" / day
    day_dir.mkdir(parents=True, exist_ok=True)
    mp = day_dir / "manifest.json"
    mp.write_text(json.dumps({"brand": "demo", "brand_name": "Demo Labs",
                              "drafts": drafts}, ensure_ascii=False))
    return mp


# ── pulse ──────────────────────────────────────────────────


# ── context: slack_pulse + engagement ──────────────────────


def test_context_engagement_summary_sorts_by_response(tmp_path):
    d = tmp_path / "socials"
    d.mkdir(parents=True)
    (d / "engagement.json").write_text(json.dumps({"updated": "t", "posts": [
        {"headline": "flopp", "pillar": "pris", "format": "motiv", "reactions": 1, "comments": 0},
        {"headline": "hit", "pillar": "fart", "format": "typografi-kort", "reactions": 9, "comments": 4},
    ]}))
    eng = ctxmod.gather_context(tmp_path)["engagement"]
    assert eng["topp"][0]["headline"] == "hit"


# ── linkedin: karusell som dokumentpost ────────────────────

def test_publish_draft_karusell_dry_run_writes_metadata(tmp_path, monkeypatch):
    monkeypatch.delenv("LINKEDIN_ENABLED", raising=False)
    pdf = tmp_path / "karusell-1.pdf"
    cover = tmp_path / "karusell-1-forside.png"
    pdf.write_bytes(b"%PDF-1.4 test")
    cover.write_bytes(b"png")
    draft = {"type": "karusell", "tittel": "Fem grep", "headline": "Fem grep",
             "body": "tekst", "pdf_path": str(pdf), "cover_path": str(cover)}
    res = linkedin.publish_draft(draft)
    assert res["dry_run"] is True and res["posted"] is False
    assert res["preview"]["document"] == str(pdf)
    assert res["preview"]["title"] == "Fem grep"
    assert (tmp_path / "published-metadata.json").exists()


def test_publish_document_post_three_step_sequence(tmp_path):
    pdf = tmp_path / "k.pdf"
    pdf.write_bytes(b"%PDF-1.4 test")
    sess = _LinkedInSession(kind="documents")
    url = linkedin.publish_document_post(str(pdf), "brødtekst", title="Tittelen",
                                         cfg=_cfg(), session=sess)
    assert url == "https://www.linkedin.com/feed/update/urn:li:share:99"
    assert [m for m, _, _ in sess.calls] == ["POST", "PUT", "POST"]
    assert "documents?action=initializeUpload" in sess.calls[0][1]
    assert sess.calls[2][1].endswith("/rest/posts")
    post_payload = sess.calls[-1][2]["json"]
    assert post_payload["content"]["media"] == {"id": "urn:li:document:42", "title": "Tittelen"}
    assert post_payload["lifecycleState"] == "PUBLISHED"
    put_headers = sess.calls[1][2]["headers"]
    assert put_headers["Content-Type"] == "application/pdf"


def test_publish_draft_karusell_posts_for_real_when_enabled(tmp_path, monkeypatch):
    pdf = tmp_path / "k.pdf"
    cover = tmp_path / "c.png"
    pdf.write_bytes(b"%PDF-1.4")
    cover.write_bytes(b"png")
    calls = {}

    def _pub(pdf_path, body, *, title, cfg=None, session=None):
        calls.update(pdf_path=pdf_path, body=body, title=title)
        return "https://www.linkedin.com/feed/update/urn:li:share:7"

    monkeypatch.setattr(linkedin, "publish_document_post", _pub)
    draft = {"type": "karusell", "tittel": "T", "headline": "T", "body": "b",
             "pdf_path": str(pdf), "cover_path": str(cover)}
    res = linkedin.publish_draft(draft, cfg=_cfg(), dry_run=False)
    assert res == {"posted": True, "dry_run": False,
                   "url": "https://www.linkedin.com/feed/update/urn:li:share:7"}
    assert calls["pdf_path"] == str(pdf) and calls["title"] == "T"


def test_publish_draft_uses_brand_org_urn(tmp_path, monkeypatch):
    # Merkets [linkedin].org_urn vinner over global env-URN (multi-side-publisering).
    png = tmp_path / "p.png"
    png.write_bytes(b"png")

    class _B:
        linkedin_org_urn = "urn:li:organization:555"

    monkeypatch.setattr("brandpost.brandkit.load_brand", lambda key: _B())
    draft = {"headline": "H", "brand": "demo", "png_path": str(png), "body": "b"}
    res = linkedin.publish_draft(draft, cfg=_cfg(enabled=False))
    assert res["preview"]["author"] == "urn:li:organization:555"


def test_publish_draft_falls_back_to_global_urn_without_brand_urn(tmp_path, monkeypatch):
    png = tmp_path / "p.png"
    png.write_bytes(b"png")

    class _B:
        linkedin_org_urn = ""  # merket har ikke egen side -> global env-URN

    monkeypatch.setattr("brandpost.brandkit.load_brand", lambda key: _B())
    draft = {"headline": "H", "brand": "demo", "png_path": str(png), "body": "b"}
    res = linkedin.publish_draft(draft, cfg=_cfg(enabled=False))
    assert res["preview"]["author"] == "urn:li:organization:1"


def test_tom_org_urn_er_en_trygg_standard():
    """Eksempelmerkene har INGEN firmaside satt, og det er med vilje: en fersk
    kloning skal ikke kunne poste til en tilfeldig side. Feltet finnes og leses."""
    from brandpost import brandkit
    assert brandkit.load_brand("demo").linkedin_org_urn == ""


def test_hvert_merke_peker_paa_sin_egen_firmaside():
    # To sider på samme app og token: den eneste tingen som skiller dem er URN-en i
    # profilen. Peker to merker på samme side, publiseres det ene merkets innlegg på
    # det andres firmaside uten at noe feiler. Derfor låses det her.
    from brandpost import brandkit
    urns = {k: brandkit.load_brand(k).linkedin_org_urn
            for k in ("demo", "minimal")}
    satt = {k: u for k, u in urns.items() if u}
    assert len(set(satt.values())) == len(satt), satt


def test_utfylt_org_urn_aktiverer_ikke_merket():
    # Å fylle inn en firmaside aktiverer IKKE merket. Kun enabled-flagget gjør det,
    # så du kan forberede et merke uten at det plutselig begynner å publisere.
    from dataclasses import replace
    from brandpost import brandkit
    b = replace(brandkit.load_brand("minimal"), linkedin_org_urn="urn:li:organization:1")
    assert b.linkedin_org_urn
    assert "minimal" not in brandkit.enabled_brands()


# ── digest_replies: «publiser: 2» ──────────────────────────


# ── engagement: respons-tall ───────────────────────────────

def test_update_stats_reads_social_metadata(tmp_path):
    day = date.today().isoformat()
    _manifest_with_drafts(tmp_path, day, [
        {"headline": "Hit", "pillar": "pris", "format": "motiv", "status": "published",
         "linkedin_url": "https://www.linkedin.com/feed/update/urn:li:share:5"},
        {"headline": "Utkast", "status": "proposed"},
    ])

    class _Sess:
        def get(self, url, **kw):
            assert "socialMetadata" in url and "urn%3Ali%3Ashare%3A5" in url
            return _Resp(json_data={"reactionSummaries": {"LIKE": {"count": 3},
                                                          "PRAISE": {"count": 1}},
                                    "commentSummary": {"aggregatedTotalComments": 2}})

    res = engagement.update_stats(tmp_path, cfg=_cfg(), session=_Sess())
    assert res["posts"] == [{"date": day, "headline": "Hit", "pillar": "pris",
                             "format": "motiv",
                             "url": "https://www.linkedin.com/feed/update/urn:li:share:5",
                             "reactions": 4, "comments": 2}]
    saved = json.loads((tmp_path / "socials" / "engagement.json").read_text())
    assert saved["posts"][0]["reactions"] == 4


def test_update_stats_degrades_on_missing_scope(tmp_path):
    day = date.today().isoformat()
    _manifest_with_drafts(tmp_path, day, [
        {"headline": "Hit", "status": "published",
         "linkedin_url": "https://www.linkedin.com/feed/update/urn:li:share:5"}])

    class _Sess:
        def get(self, url, **kw):
            return _Resp(status=403)

    res = engagement.update_stats(tmp_path, cfg=_cfg(), session=_Sess())
    assert res["posts"] == []
    assert any("r_organization_social" in p for p in res["problems"])


# ── dags-manifest: flere merker samme dag ──────────────────
# render MERGER inn i ett felles manifest per dag (aldri overskriv), og hvert
# utkast bærer sitt faste «publiser: nr»-nummer, så andre merkets kjøring ikke
# visker ut første og et nummer fra en eldre epost aldri treffer feil utkast.

def test_merge_manifest_two_brands_same_day(tmp_path):
    when = datetime.now()
    p1, _ = store.merge_manifest(
        tmp_path, brand_key="demo", brand_name="Demo Labs",
        new_drafts=[{"brand": "demo", "headline": "A", "status": "proposed"},
                    {"brand": "demo", "headline": "B", "status": "proposed"}], when=when)
    p2, m = store.merge_manifest(
        tmp_path, brand_key="minimal", brand_name="Minimal",
        new_drafts=[{"brand": "minimal", "headline": "C", "status": "proposed"}], when=when)
    assert p1 == p2  # ETT manifest per dag, felles for merkene
    assert [(d["brand"], d["nr"]) for d in m["drafts"]] == [
        ("demo", 1), ("demo", 2), ("minimal", 3)]
    assert m["brand"] == "minimal" and m["seq"] == 3  # sist rendrede styrer send-default
    assert len(json.loads(p2.read_text())["drafts"]) == 3


def test_merge_manifest_rerender_replaces_own_unpublished_keeps_published(tmp_path):
    when = datetime.now()
    day = when.strftime("%Y-%m-%d")
    store.merge_manifest(
        tmp_path, brand_key="demo", brand_name="Demo Labs",
        new_drafts=[{"brand": "demo", "headline": "A", "status": "proposed"},
                    {"brand": "demo", "headline": "B", "status": "proposed"}], when=when)
    mp, manifest = store.load_manifest(tmp_path, day)
    store.mark_published(mp, manifest, 0, "https://li/1")  # A (nr 1) publiseres
    store.merge_manifest(
        tmp_path, brand_key="minimal", brand_name="Minimal",
        new_drafts=[{"brand": "minimal", "headline": "C", "status": "proposed"}], when=when)
    _, m = store.merge_manifest(
        tmp_path, brand_key="demo", brand_name="Demo Labs",
        new_drafts=[{"brand": "demo", "headline": "D", "status": "proposed"}], when=when)
    rows = [(d["headline"], d["nr"], d["status"]) for d in m["drafts"]]
    # publisert A består (publiseringslogg + engasjement), upostet B er erstattet,
    # C urørt med samme nummer, og D får et FERSKT nummer (aldri gjenbruk)
    assert rows == [("A", 1, "published"), ("C", 3, "proposed"), ("D", 4, "proposed")]


def test_merge_manifest_numbers_legacy_manifest_positionally(tmp_path):
    when = datetime.now()
    day = when.strftime("%Y-%m-%d")
    _manifest_with_drafts(tmp_path, day, [
        {"headline": "Gammel", "brand": "demo", "status": "proposed"}])  # uten nr/seq
    _, m = store.merge_manifest(
        tmp_path, brand_key="minimal", brand_name="Minimal",
        new_drafts=[{"brand": "minimal", "headline": "Ny", "status": "proposed"}], when=when)
    # posisjonen VAR nummeret i den alt utsendte eposten: 1 består, nestemann får 2
    assert [(d["headline"], d["nr"]) for d in m["drafts"]] == [("Gammel", 1), ("Ny", 2)]


def test_select_draft_uses_stable_numbers_never_position():
    manifest = {"drafts": [
        {"headline": "C", "nr": 3, "brand": "minimal"},
        {"headline": "Fem grep", "nr": 4, "type": "karusell", "n": 7},  # "n" = slides
    ]}
    assert store.select_draft(manifest, "3") == (0, manifest["drafts"][0])
    assert store.select_draft(manifest, "4")[0] == 1
    assert store.select_draft(manifest, "1") == (None, None)  # foreldet nummer: bom, aldri naboen
    assert store.select_draft(manifest, "7") == (None, None)  # slide-antall er ikke et nummer


def test_cli_render_merges_brands_and_send_filters(tmp_path, monkeypatch):
    import argparse

    from brandpost import cli as some_cli

    monkeypatch.setattr(
        some_cli.rendermod, "render_post",
        lambda spec, brand=None, seq=0: {"png": b"fake-png", "how": "template",
                                         "format": "typografi-kort"})

    def _render(brand, posts):
        specs = tmp_path / f"specs-{brand}.json"
        specs.write_text(json.dumps({"brand": brand, "posts": posts}, ensure_ascii=False))
        args = argparse.Namespace(vault=str(tmp_path), specs=str(specs), out=None)
        assert some_cli.cmd_render(args) == 0

    _render("demo", [
        {"type": "bilde", "format": "typografi-kort", "headline": "A", "body": "a", "why_now": "w"},
        {"type": "bilde", "format": "typografi-kort", "headline": "B", "body": "b", "why_now": "w"}])
    _render("minimal", [
        {"type": "bilde", "format": "typografi-kort", "headline": "C", "body": "c", "why_now": "w"}])

    _, manifest = store.load_manifest(tmp_path)
    assert [(d["brand"], d["nr"]) for d in manifest["drafts"]] == [
        ("demo", 1), ("demo", 2), ("minimal", 3)]

    sendt = {}
    monkeypatch.setattr(
        some_cli.emailmod, "send_drafts",
        lambda drafts, *, brand_name, dry_run=None, vault=None:
        sendt.update(drafts=drafts, brand_name=brand_name) or {"sent": False})
    args = argparse.Namespace(vault=str(tmp_path), manifest=None, dry_run=True, brand=None)
    assert some_cli.cmd_send(args) == 0
    # send uten --brand tar sist rendrede merke: kun Minimal-utkastet, med dags-nummeret sitt
    assert [d["headline"] for d in sendt["drafts"]] == ["C"]
    assert sendt["brand_name"] == "Minimal" and sendt["drafts"][0]["nr"] == 3
    args = argparse.Namespace(vault=str(tmp_path), manifest=None, dry_run=True, brand="demo")
    assert some_cli.cmd_send(args) == 0
    assert [d["headline"] for d in sendt["drafts"]] == ["A", "B"]


# ── email: publiser-instruks + nummerering ─────────────────

def test_email_cards_carry_publish_numbers_and_pdf():
    drafts = [
        {"headline": "Første", "body": "a", "why_now": "w", "format": "typografi-kort",
         "png": b"png-bytes"},
        {"type": "karusell", "headline": "Fem grep", "tittel": "Fem grep", "body": "b",
         "why_now": "w", "n": 7, "pdf_path": "/tmp/fem-grep.pdf",
         "pdf": b"%PDF", "cover": b"cover-bytes"},
    ]
    subject, doc, inline, attachments = emailmod.build_some_email(drafts)
    assert "SoMe-utkast" in subject
    assert "publiser: 1" in doc and "publiser: 2" in doc
    assert "nr 2 · karusell" in doc
    assert len(inline) == 2
    assert attachments[0]["filename"] == "fem-grep.pdf"
    assert attachments[0]["mime"] == "application/pdf"


def test_email_numbers_follow_day_manifest():
    # Andre merket samme dag starter ikke på 1: kortet og intro-eksempelet
    # viser dags-manifest-nummeret («publiser: 4»), som svar-flyten treffer.
    drafts = [{"headline": "C", "body": "c", "why_now": "w", "format": "motiv",
               "nr": 4, "png": b"png-bytes"}]
    _, doc, _, _ = emailmod.build_some_email(drafts, brand_name="Minimal")
    assert "publiser: 4" in doc and "nr 4" in doc
    assert "publiser: 2" not in doc
