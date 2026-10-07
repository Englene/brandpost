"""Skisse-ikonene på karusell-slidene (brandpost/spot.py).

Ikonene TEGNES i et annet repo (meetingnotes/tegn) og legges ferdig-rendret i
merkets media/ikoner. Vakten her er derfor todelt: at navnelista og PNG-ene på
disk stemmer overens, og at slidet faktisk får ikonet tegnet inn.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest
from PIL import Image, ImageChops

from brandpost import brandkit, slides, spot

# Tegne-generatoren, når den finnes på denne maskinen. Kontrakt-testen hopper
# over seg selv ellers: motoren skal kunne installeres uten meetingnotes.
IKONER_MJS = Path.home() / "repos/meetingnotes/tegn/ikoner/ikoner.mjs"


def _merker() -> list[str]:
    """Merkene denne installasjonen faktisk har (BRANDPOST_BRANDS_DIR)."""
    return [k for k in brandkit.available_brands() if k not in ("demo", "minimal")]


@pytest.mark.skipif(not IKONER_MJS.exists(), reason="tegne-generatoren finnes ikke her")
def test_navnelista_speiler_generatoren():
    kilde = IKONER_MJS.read_text(encoding="utf-8")
    m = re.search(r"export const IKONER = \{([^}]*)\}", kilde)
    assert m, "fant ikke IKONER-tabellen i tegn/ikoner/ikoner.mjs"
    uten_kommentar = re.sub(r"//[^\n]*", "", m.group(1))
    navn = {n.strip() for n in uten_kommentar.split(",") if n.strip()}
    assert set(spot.IKONER) == navn


def test_merkene_har_ikonene_paa_disk():
    merker = _merker()
    if not merker:
        pytest.skip("ingen egne merker i denne installasjonen")
    mangler: list[str] = []
    for key in merker:
        mappe = spot.ikon_mappe(brandkit.load_brand(key))
        assert mappe is not None
        mangler += [f"{key}/{n}" for n in spot.IKONER if not (mappe / f"{n}.png").exists()]
    assert not mangler, (
        "bygg dem med: ~/repos/meetingnotes/.venv/bin/python -m "
        "inbox_processor.social.bygg_ikoner --tema <merke> --ut <brands>/<merke>/media/ikoner\n"
        + ", ".join(mangler))


def test_nokkelordene_peker_paa_ekte_ikoner():
    for navn, _ord in spot._NOKKELORD:
        assert navn in spot.IKONER, navn


def test_eksplisitt_ikon_vinner_over_nokkelord():
    slide = {"ikon": "rakett", "heading": "Hvor oppstår køen?", "body": "Hvem venter?"}
    assert spot.velg_ikon(slide) == "rakett"


@pytest.mark.parametrize("heading,body,ventet", [
    ("Hvor oppstår køen?", "Hvilket steg venter alt annet på?", "trakt"),
    ("Hvilke variabler henger sammen?", "Når dere skrur på én ting.", "puslebrikke"),
    ("Finnes det en terskel?", "Virker det opp til et visst datavolum?", "graf"),
    ("Hvorfor kan det ikke regnes ut?", "Står svaret i en håndbok?", "kalkulator"),
    ("Samme prosjekt, annen søknad", "Arbeidet er likt.", "sammenligning"),
    ("Hva står det om oppsigelse?", "Bindingstid er også en pris.", "laas"),
])
def test_nokkelord_treffer_typiske_slides(heading, body, ventet):
    assert spot.velg_ikon({"heading": heading, "body": body}) == ventet


def test_tekst_uten_treff_gir_ingen_ikon():
    assert spot.velg_ikon({"heading": "Ålesund", "body": "Ålesund."}) is None


def test_ukjent_ikonnavn_faller_til_nokkelord():
    assert spot.velg_ikon({"ikon": "enhjørning", "heading": "Hvor oppstår køen?",
                           "body": "Hvem venter?"}) == "trakt"


def _brand():
    merker = _merker()
    if not merker:
        pytest.skip("ingen egne merker i denne installasjonen")
    return brandkit.load_brand(merker[0])


def test_last_ikon_gir_rgba_beskaaret():
    brand = _brand()
    im = spot.last_ikon("kolbe", brand)
    assert im is not None and im.mode == "RGBA"
    # Beskjæringen er poenget: en PNG som fortsatt er 480x480 er ikke trimmet,
    # og da blir ikonene ulikt store på slidene.
    assert min(im.size) < 480
    assert spot.last_ikon("finnes-ikke", brand) is None


def test_innholdsslide_faar_ikon_tegnet():
    """Samme tekst, men uten nøkkelordtreff: forskjellen MÅ være ikonet."""
    brand = _brand()
    tekst = {"heading": "Ålesund", "body": "Ålesund."}
    assert spot.velg_ikon(tekst) is None
    uten = slides.render_innhold(tekst, brand, pos=1, total=5, number=1)
    med = slides.render_innhold({**tekst, "ikon": "graf"}, brand, pos=1, total=5, number=1)

    boks = ImageChops.difference(med, uten).convert("L").getbbox()
    assert boks is not None, "ikonet ble ikke tegnet"
    w, h = med.size
    x0, y0, x1, y1 = boks
    assert (x1 - x0) > w * 0.2, "ikonet er mistenkelig smalt"
    assert y0 > h * 0.4, "ikonet skal ligge under teksten, ikke oppe i headingen"
    assert y1 < h - h * 0.08, "ikonet kolliderer med fremdrifts-prikkene"


def test_lang_brodtekst_dropper_ikonet_i_stedet_for_aa_klemme_det():
    brand = _brand()
    img = Image.new("RGBA", slides.SIZE_SLIDE, (255, 255, 255, 255))
    assert slides._tegn_ikon(img, brand, {"heading": "x", "body": "y", "ikon": "graf"},
                             y_tekst=img.size[1] - 40) is None


# ── Kryss-merke-synlighet ────────────────────────────────────────────────
# Egen vakt, ikke ikon-relatert, men samme dags lærdom: to merker publiserte
# nesten samme karusell fordi nabomerkets utkast ikke var synlig i prompten.

def test_recent_angles_tar_med_merke_og_emne(tmp_path, monkeypatch):
    from brandpost import store

    monkeypatch.setenv("BRANDPOST_WORKSPACE", str(tmp_path))
    store.record(tmp_path, [
        {"brand": "alfa", "format": "karusell", "headline": "Seks ting …",
         "pillar": "hvem-passer", "emne": "eksempel-emne"},
    ])
    rad = store.recent_angles(tmp_path)[-1]
    assert rad["brand"] == "alfa"
    assert rad["emne"] == "eksempel-emne"


def test_ute_blokka_skiller_eget_merke_fra_naboene():
    from brandpost.cli import _ute_block

    angles = [
        {"brand": "alfa", "headline": "Seks ting om saken"},
        {"brand": "beta", "headline": "Fem setninger om saken"},
    ]
    blokk = _ute_block(angles, "beta")
    eget, nabo = blokk.split("NABOMERKENE")
    assert "Fem setninger" in eget and "Seks ting" not in eget
    assert "Seks ting" in nabo
    assert "samme grep" in nabo


def test_ute_blokka_uten_naboer_har_ingen_nabodel():
    from brandpost.cli import _ute_block

    blokk = _ute_block([{"brand": "beta", "headline": "Fem setninger"}], "beta")
    assert "NABOMERKENE" not in blokk
