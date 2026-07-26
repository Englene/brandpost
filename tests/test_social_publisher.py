"""publisher: vi eier publiseringen (valget 22. juli 2026).

Ingen nett: linkedin.publish_draft og e-posten mockes.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta

from brandpost import publisher, store


def _manifest(tmp_path, drafts, day="2026-07-23"):
    d = tmp_path / "socials" / day
    d.mkdir(parents=True)
    (d / "manifest.json").write_text(json.dumps({"drafts": drafts}, ensure_ascii=False),
                                     encoding="utf-8")
    return d / "manifest.json"


def _draft(nr=1, *, status="planlagt", when="2026-07-23T10:00", headline="H"):
    return {"nr": nr, "headline": headline, "body": "kropp", "status": status,
            "scheduled_at": when, "brand": "demo", "brand_name": "Demo Labs"}


def test_due_tar_bare_forfalte_planlagte(tmp_path):
    _manifest(tmp_path, [
        _draft(1, when="2026-07-23T10:00"),                    # forfalt
        _draft(2, when="2026-07-23T14:00"),                    # ikke forfalt
        _draft(3, when="2026-07-23T09:00", status="published"),  # alt ute
        {"nr": 4, "headline": "uten tid", "status": "planlagt"},  # mangler tidspunkt
    ])
    due = publisher.due_drafts(tmp_path, now=datetime(2026, 7, 23, 11, 0))
    assert [r["draft"]["nr"] for r in due] == [1]


def test_publiserer_og_varsler(tmp_path, monkeypatch):
    mpath = _manifest(tmp_path, [_draft(1)])
    monkeypatch.setattr(publisher.linkedin, "publish_draft",
                        lambda d, dry_run=None: {"posted": True, "url": "https://li/7"})
    sendt = {}
    monkeypatch.setattr(publisher, "_publisert_epost",
                        lambda d, url, **k: sendt.update(url=url, headline=d["headline"])
                        or {"sent": True})
    tall = publisher.publish_due(tmp_path, now=datetime(2026, 7, 23, 11, 0))
    assert tall["publisert"] == 1 and tall["feilet"] == 0
    assert sendt == {"url": "https://li/7", "headline": "H"}
    m = json.loads(mpath.read_text())
    assert m["drafts"][0]["status"] == "published"
    assert m["drafts"][0]["linkedin_url"] == "https://li/7"


def test_for_sent_publiseres_ikke(tmp_path, monkeypatch):
    """eieren valgte at VI eier tidspunktet, og da er nedetid en reell risiko.
    Et innlegg som skulle ut i gaar skal ikke plutselig dukke opp i dag."""
    mpath = _manifest(tmp_path, [_draft(1, when="2026-07-22T10:00")])
    kalt = []
    monkeypatch.setattr(publisher.linkedin, "publish_draft",
                        lambda d, dry_run=None: kalt.append(d) or {"posted": True, "url": "x"})
    tall = publisher.publish_due(tmp_path, now=datetime(2026, 7, 23, 11, 0))  # 25 t sent
    assert tall == {"publisert": 0, "hoppet": 1, "feilet": 0}
    assert kalt == []                                    # aldri publisert
    assert json.loads(mpath.read_text())["drafts"][0]["status"] == "planlagt"


def test_kort_forsinkelse_tas_igjen(tmp_path, monkeypatch):
    """Treg oppstart skal ikke miste innlegget."""
    _manifest(tmp_path, [_draft(1, when="2026-07-23T10:00")])
    monkeypatch.setattr(publisher.linkedin, "publish_draft",
                        lambda d, dry_run=None: {"posted": True, "url": "https://li/8"})
    monkeypatch.setattr(publisher, "_publisert_epost", lambda *a, **k: {"sent": True})
    tall = publisher.publish_due(tmp_path, now=datetime(2026, 7, 23, 12, 30))  # 2,5 t
    assert tall["publisert"] == 1


def test_epostfeil_velter_ikke_publiseringen(tmp_path, monkeypatch):
    mpath = _manifest(tmp_path, [_draft(1)])
    monkeypatch.setattr(publisher.linkedin, "publish_draft",
                        lambda d, dry_run=None: {"posted": True, "url": "https://li/9"})

    def boom(*a, **k):
        raise RuntimeError("smtp nede")
    monkeypatch.setattr(publisher, "_publisert_epost", boom)
    tall = publisher.publish_due(tmp_path, now=datetime(2026, 7, 23, 11, 0))
    assert tall["publisert"] == 1                       # innlegget teller som ute
    assert json.loads(mpath.read_text())["drafts"][0]["status"] == "published"


def test_dry_run_poster_ingenting(tmp_path, monkeypatch):
    mpath = _manifest(tmp_path, [_draft(1)])
    monkeypatch.setattr(publisher.linkedin, "publish_draft",
                        lambda d, dry_run=None: {"posted": False, "dry_run": True})
    tall = publisher.publish_due(tmp_path, now=datetime(2026, 7, 23, 11, 0), dry_run=True)
    assert tall["publisert"] == 0 and tall["hoppet"] == 1
    assert json.loads(mpath.read_text())["drafts"][0]["status"] == "planlagt"


def test_innlegg_planlagt_i_linkedin_publiseres_ikke_av_oss(tmp_path, monkeypatch, capsys):
    """Nettleserveien planlegger inne i LinkedIn, som legger ut selv. Publiserer vi
    det i tillegg via API-et, står SAMME innlegg to ganger på firmasida, og ingenting
    feiler underveis. Markøren er `scheduled_confirmed` (LinkedIns egen bekreftelse)."""
    i_linkedin = _draft(1)
    i_linkedin["scheduled_confirmed"] = "Planlagt for tor. 23. juli kl. 10.00"
    _manifest(tmp_path, [i_linkedin, _draft(2)])
    kalt: list = []
    monkeypatch.setattr(publisher.linkedin, "publish_draft",
                        lambda d, dry_run=None: kalt.append(d["nr"])
                        or {"posted": True, "url": "https://li/9"})
    monkeypatch.setattr(publisher, "_publisert_epost", lambda d, url, **k: {"sent": True})

    tall = publisher.publish_due(tmp_path, now=datetime(2026, 7, 23, 11, 0))

    assert kalt == [2], "vi skal bare publisere det LinkedIn ikke allerede eier"
    assert tall["publisert"] == 1 and tall["hoppet"] == 1
    # Det vi lot være skal SIES, ikke forsvinne: tom logg leses som «ingenting å gjøre».
    assert "planlagt inne i LinkedIn" in capsys.readouterr().out


def test_linkedin_eide_utkast_holdes_utenfor_due(tmp_path):
    d = _draft(1)
    d["scheduled_confirmed"] = "Planlagt for tor. 23. juli kl. 10.00"
    _manifest(tmp_path, [d])
    naa = datetime(2026, 7, 23, 11, 0)
    assert publisher.due_drafts(tmp_path, now=naa) == []
    assert [r["draft"]["nr"] for r in publisher.linkedin_owned_due(tmp_path, now=naa)] == [1]


def test_uventet_torrkjoring_teller_som_feil(tmp_path, monkeypatch):
    """Kjører jobben uten LinkedIn-nøkler, blir alt tørrkjørt. Det ser ut som
    suksess i loggen, men innlegget gikk aldri ut. Da skal jobben avslutte rødt."""
    _manifest(tmp_path, [_draft(1)])
    monkeypatch.setattr(publisher.linkedin, "publish_draft",
                        lambda d, dry_run=None: {"posted": False, "dry_run": True})

    tall = publisher.publish_due(tmp_path, now=datetime(2026, 7, 23, 11, 0))

    assert tall["feilet"] == 1 and tall["publisert"] == 0


def test_bedt_om_torrkjoring_er_ikke_feil(tmp_path, monkeypatch):
    _manifest(tmp_path, [_draft(1)])
    monkeypatch.setattr(publisher.linkedin, "publish_draft",
                        lambda d, dry_run=None: {"posted": False, "dry_run": True})

    tall = publisher.publish_due(tmp_path, now=datetime(2026, 7, 23, 11, 0), dry_run=True)

    assert tall["hoppet"] == 1 and tall["feilet"] == 0
