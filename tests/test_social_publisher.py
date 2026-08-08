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


# ── Slack-varselet (6. august 2026) ──────────────────────────────────────────

def test_slack_varsel_har_merkenavn_overskrift_og_lenke(tmp_path, monkeypatch):
    """Merkenavnet er hele poenget her.

    Publisert-eposten har det ikke, og det gikk bra så lenge én mottaker fikk
    varsel om ett merke. En felles Slack-kanal får innlegg fra Tilskudd.ai,
    Vitandi og den personlige profilen, og «Publisert på LinkedIn» uten avsender
    er ubrukelig da."""
    sendt = {}
    monkeypatch.setattr(publisher.slackmod, "send_message",
                        lambda tekst, **k: sendt.update(tekst=tekst, kw=k) or {"sent": True})
    publisher._publisert_slack(_draft(1, headline="Regenerer er dyrt"), "https://li/7")

    assert "Demo Labs" in sendt["tekst"], "merkenavnet må være med"
    assert "Regenerer er dyrt" in sendt["tekst"]
    assert "https://li/7" in sendt["tekst"]


def test_slackfeil_velter_ikke_publiseringen(tmp_path, monkeypatch):
    """Samme lov som for e-posten: innlegget ER ute på LinkedIn når varselet
    sendes. Et varsel som feiler skal rapporteres, aldri rulles tilbake."""
    mpath = _manifest(tmp_path, [_draft(1)])
    monkeypatch.setattr(publisher.linkedin, "publish_draft",
                        lambda d, dry_run=None: {"posted": True, "url": "https://li/7"})
    monkeypatch.setattr(publisher, "_publisert_epost", lambda d, url, **k: {"sent": True})

    def _sprekk(d, url, **k):
        raise RuntimeError("slack nede")
    monkeypatch.setattr(publisher, "_publisert_slack", _sprekk)

    tall = publisher.publish_due(tmp_path, now=datetime(2026, 7, 23, 11, 0))
    assert tall["publisert"] == 1 and tall["feilet"] == 0
    assert json.loads(mpath.read_text())["drafts"][0]["status"] == "published"


def test_epostfeil_stanser_ikke_slack(tmp_path, monkeypatch):
    """Hvert varsel har sin egen try/except. Med én felles ville en død
    SMTP-server tatt Slack-meldingen med seg, og de to har ingenting med
    hverandre å gjøre."""
    mpath = _manifest(tmp_path, [_draft(1)])
    monkeypatch.setattr(publisher.linkedin, "publish_draft",
                        lambda d, dry_run=None: {"posted": True, "url": "https://li/7"})

    def _smtp_nede(d, url, **k):
        raise RuntimeError("smtp nede")
    monkeypatch.setattr(publisher, "_publisert_epost", _smtp_nede)
    slack_kom = {}
    monkeypatch.setattr(publisher, "_publisert_slack",
                        lambda d, url, **k: slack_kom.update(url=url) or {"sent": True})

    tall = publisher.publish_due(tmp_path, now=datetime(2026, 7, 23, 11, 0))
    assert tall["publisert"] == 1
    assert slack_kom == {"url": "https://li/7"}, "Slack skal gå selv om e-posten ryker"


def test_torrkjoring_uten_token_sender_ingenting(monkeypatch):
    """Standard er tørrkjøring. En fersk kloning skal ikke kunne poste i noens
    Slack ved et uhell, på samme måte som mailer ikke kan sende e-post."""
    from brandpost import slack as slackmod
    monkeypatch.delenv("BRANDPOST_SLACK_ENABLED", raising=False)
    r = slackmod.send_message("hei", channel="C123")
    assert r == {"sent": False, "dry_run": True, "channel": "C123", "text": "hei"}


def test_slack_rapporterer_feilen_slack_selv_oppgir(monkeypatch):
    """«not_in_channel» og «missing_scope» er forskjellen på noe eieren kan fikse
    og et mysterium. Ta teksten med videre."""
    from brandpost import slack as slackmod
    monkeypatch.setenv("BRANDPOST_SLACK_ENABLED", "1")
    monkeypatch.setenv("BRANDPOST_SLACK_TOKEN", "xoxp-test")

    class _Svar:
        status_code = 200

        @staticmethod
        def json():
            return {"ok": False, "error": "not_in_channel"}

    class _Sess:
        @staticmethod
        def post(*a, **k):
            return _Svar()

    r = slackmod.send_message("hei", channel="C123", session=_Sess())
    assert r["sent"] is False
    assert "not_in_channel" in r["reason"]


def test_slack_uten_kanal_er_en_tydelig_feil(monkeypatch):
    from brandpost import slack as slackmod
    monkeypatch.setenv("BRANDPOST_SLACK_ENABLED", "1")
    monkeypatch.delenv("BRANDPOST_SLACK_CHANNEL", raising=False)
    r = slackmod.send_message("hei")
    assert r["sent"] is False and "kanal" in r["reason"]


def test_merkekanal_overstyrer_den_globale(monkeypatch):
    """Feltet er tomt i dag, men skal virke den dagen firmaene får hver sin
    kanal, uten at det krever en kodeendring."""
    from brandpost import brandkit
    monkeypatch.setattr(
        brandkit, "load_brand",
        lambda k: type("B", (), {"slack_channel": "C-MERKE", "slack_varsle": True,
                                 "slack_token_env": "ANNET_WORKSPACE_TOKEN"})())
    assert publisher._slack_for({"brand": "demo"}) == (
        "C-MERKE", True, "ANNET_WORKSPACE_TOKEN")

    # Ulesbar profil skal gi den globale kanalen OG varsle, ikke en feil: et
    # firmainnlegg som går ut uten kvittering er verre enn ett varsel for mye.
    def _sprekk(k):
        raise ValueError("ukjent merke")
    monkeypatch.setattr(brandkit, "load_brand", _sprekk)
    assert publisher._slack_for({"brand": "finnes-ikke"}) == ("", True, "")
