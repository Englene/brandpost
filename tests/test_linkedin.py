"""Mock-tester for LinkedIn-publiseringen (ingen ekte API-kall)."""

from __future__ import annotations

import json

import pytest
import requests

from brandpost import linkedin, store


class FakeResp:
    def __init__(self, status=200, json_data=None, headers=None, text=""):
        self.status_code = status
        self._json = json_data or {}
        self.headers = headers or {}
        self.text = text

    def json(self):
        return self._json

    def raise_for_status(self):
        if self.status_code >= 400:
            err = requests.HTTPError(f"HTTP {self.status_code}")
            err.response = self
            raise err


class FakeSession:
    """Ruter LinkedIn-endepunktene. `fail_initialize_once` simulerer utløpt token (401)."""

    def __init__(self, *, fail_initialize_once=False):
        self.calls = []
        self.tokens_used = []
        self.fail_initialize_once = fail_initialize_once
        self._init_calls = 0

    def post(self, url, headers=None, json=None, data=None, timeout=None, params=None):
        headers = headers or {}
        self.calls.append(("POST", url))
        if "oauth/v2/accessToken" in url:
            return FakeResp(200, {"access_token": "NEW_TOKEN", "refresh_token": "R",
                                  "expires_in": 5184000})
        if "rest/images" in url:
            self._init_calls += 1
            self.tokens_used.append(headers.get("Authorization"))
            if self.fail_initialize_once and self._init_calls == 1:
                return FakeResp(401, text="expired")
            return FakeResp(200, {"value": {"uploadUrl": "https://upload/here",
                                            "image": "urn:li:image:ABC"}})
        if "rest/posts" in url:
            return FakeResp(201, headers={"x-restli-id": "urn:li:share:123"})
        return FakeResp(404, text=f"unrouted {url}")

    def put(self, url, data=None, headers=None, timeout=None):
        self.calls.append(("PUT", url))
        return FakeResp(200)


def _cfg(**kw):
    base = dict(client_id="c", client_secret="s", access_token="OLD",
                refresh_token="R", org_urn="urn:li:organization:99", enabled=True)
    base.update(kw)
    return linkedin.LinkedInConfig(**base)


def test_load_config_enabled_flag(monkeypatch):
    monkeypatch.setenv("LINKEDIN_ACCESS_TOKEN", "T")
    monkeypatch.setenv("LINKEDIN_ORG_URN", "urn:li:organization:5")
    monkeypatch.setenv("LINKEDIN_ENABLED", "1")
    cfg = linkedin.load_linkedin_config()
    assert cfg.ready and cfg.enabled
    monkeypatch.setenv("LINKEDIN_ENABLED", "0")
    assert linkedin.load_linkedin_config().enabled is False


def test_publish_image_post_happy(tmp_path):
    img = tmp_path / "x.png"
    img.write_bytes(b"\x89PNG\r\n")
    sess = FakeSession()
    url = linkedin.publish_image_post(str(img), "hei", alt_text="A", cfg=_cfg(), session=sess)
    assert url == "https://www.linkedin.com/feed/update/urn:li:share:123"
    assert ("PUT", "https://upload/here") in sess.calls
    # rekkefølge: initialize (images) → put → create (posts)
    kinds = [u for _, u in sess.calls]
    assert any("rest/images" in u for u in kinds)
    assert any("rest/posts" in u for u in kinds)


def test_publish_refreshes_on_401(tmp_path):
    img = tmp_path / "x.png"
    img.write_bytes(b"PNG")
    sess = FakeSession(fail_initialize_once=True)
    url = linkedin.publish_image_post(str(img), "hei", cfg=_cfg(), session=sess)
    assert url.endswith("urn:li:share:123")
    # første forsøk med gammelt token, andre (etter refresh) med nytt
    assert sess.tokens_used == ["Bearer OLD", "Bearer NEW_TOKEN"]


def test_publish_no_refresh_token_raises(tmp_path):
    img = tmp_path / "x.png"
    img.write_bytes(b"PNG")
    sess = FakeSession(fail_initialize_once=True)
    with pytest.raises(requests.HTTPError):
        linkedin.publish_image_post(str(img), "hei", cfg=_cfg(refresh_token=""), session=sess)


def test_publish_draft_dry_run_writes_metadata(tmp_path):
    day = tmp_path / "2026-07-08"
    day.mkdir()
    img = day / "post-1.png"
    img.write_bytes(b"PNG")
    draft = {"headline": "Tittel", "body": "Brødtekst", "png_path": str(img), "format": "motiv"}
    res = linkedin.publish_draft(draft, cfg=_cfg(enabled=False))  # dry pga enabled=False
    assert res["posted"] is False and res["dry_run"] is True
    assert res["preview"]["author"] == "urn:li:organization:99"
    log = json.loads((day / "published-metadata.json").read_text(encoding="utf-8"))
    assert log[0]["would_post"]["commentary"] == "Brødtekst"


def test_publish_draft_carousel_missing_pdf(tmp_path):
    # Karusell publiseres nå som dokumentpost; uten PDF på disk = klar feilmelding.
    cover = tmp_path / "c.png"
    cover.write_bytes(b"PNG")
    draft = {"headline": "K", "type": "karusell", "cover_path": str(cover)}
    res = linkedin.publish_draft(draft, cfg=_cfg(enabled=True))
    assert res["posted"] is False and "fant ikke pdf" in res["reason"].lower()


def test_publish_draft_missing_image(tmp_path):
    draft = {"headline": "X", "format": "motiv", "png_path": str(tmp_path / "nope.png")}
    res = linkedin.publish_draft(draft, cfg=_cfg(enabled=False))
    assert res["posted"] is False and "fant ikke bilde" in res["reason"]


def test_select_draft_and_mark_published(tmp_path):
    manifest = {"drafts": [
        {"headline": "Pris-myten", "png_path": "/x/post-1-demo-pris.png", "status": "proposed"},
        {"headline": "Data som bevis", "png_path": "/x/post-2-demo-data.png", "status": "proposed"},
    ]}
    assert store.select_draft(manifest, "2")[0] == 1
    assert store.select_draft(manifest, "pris")[0] == 0
    assert store.select_draft(manifest, "9") == (None, None)
    assert store.select_draft(manifest, "") == (None, None)

    mp = tmp_path / "manifest.json"
    mp.write_text(json.dumps(manifest), encoding="utf-8")
    store.mark_published(mp, manifest, 0, "https://li/feed/1")
    reloaded = json.loads(mp.read_text(encoding="utf-8"))
    assert reloaded["drafts"][0]["status"] == "published"
    assert reloaded["drafts"][0]["linkedin_url"] == "https://li/feed/1"
    assert reloaded["drafts"][1]["status"] == "proposed"


def test_api_versjon_er_aktiv():
    """LinkedIn deprecerer versjoner loepende. 202506 var utgaatt 22. juli 2026
    og ga 426 NONEXISTENT_VERSION paa hvert kall; defaulten maa foelge med."""
    import os
    from brandpost import linkedin
    assert linkedin.LINKEDIN_VERSION >= "202601", "API-versjonen er for gammel"


# ── Taggen må bli en ekte mention (regresjon oppdaget 2. august 2026) ─────────

def test_mention_finner_taggen_sanitizeren_faktisk_skrev():
    """_sanitize_spec skriver «@handle», men api_commentary lette bare etter
    «@merkenavn». De to har ikke møttes siden handle-støtten kom inn, så taggen
    gikk ut som ren tekst i stedet for en klikkbar mention."""
    from brandpost import linkedin
    ut = linkedin.api_commentary("Vi i @demo-labs ser dette.", brand_name="Demo Labs",
                                 org_urn="urn:li:organization:42", handle="demo-labs")
    assert ut == "Vi i @[Demo Labs](urn:li:organization:42) ser dette."


def test_mention_bruker_merkets_egen_side():
    """To merker, to firmasider. Taggen må peke på utkastets eget selskap."""
    from brandpost import linkedin
    a = linkedin.api_commentary("@merke-a er her", brand_name="Merke A",
                                org_urn="urn:li:organization:111", handle="merke-a")
    b = linkedin.api_commentary("@merke-b er her", brand_name="Merke B",
                                org_urn="urn:li:organization:222", handle="merke-b")
    assert "111" in a and "222" not in a
    assert "222" in b and "111" not in b


def test_mention_faller_tilbake_paa_merkenavnet():
    """Eldre utkast og manuelt skrevet tekst kan ha den gamle @merkenavn-formen."""
    from brandpost import linkedin
    ut = linkedin.api_commentary("Vi i @Demo Labs ser det.", brand_name="Demo Labs",
                                 org_urn="urn:li:organization:42")
    assert ut == "Vi i @[Demo Labs](urn:li:organization:42) ser det."


def test_mention_roerer_ikke_tekst_uten_tagg():
    from brandpost import linkedin
    tekst = "Ingen tagg her i det hele tatt."
    assert linkedin.api_commentary(tekst, brand_name="Demo Labs",
                                   org_urn="urn:li:organization:42",
                                   handle="demo-labs") == tekst


def test_tom_handle_lager_ikke_falsk_treff():
    """Er handlen tom, må «@» alene aldri regnes som en tagg: da ville hver eneste
    e-postadresse og krøllalfa i teksten blitt til en mention."""
    from brandpost import linkedin
    tekst = "Send til post@eksempel.no, ikke @ noen andre."
    ut = linkedin.api_commentary(tekst, brand_name="Ukjent Merke",
                                 org_urn="urn:li:organization:42", handle="")
    assert ut == tekst
