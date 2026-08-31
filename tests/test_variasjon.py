"""Variasjonspakken (aug 2026): persistent temarotasjon, aksent-tokens og
rullerende fargehierarki.

Bakgrunnen er designer-tilbakemeldingen «innleggene skiller seg ikke fra
hverandre, helt samme design og fargeplassering»: telleren ble nullstilt per
kjøring, dashbordet rendret alltid tema 0, og fargeloven i motiv-prompten var
identisk hver gang. Disse testene låser at det ikke skjer igjen.
"""

from __future__ import annotations

from dataclasses import replace
from io import BytesIO

from PIL import Image

from brandpost import brandkit, prompts, render, slides, store


def _brand_med_palett(**endringer):
    b = brandkit.load_brand("demo")
    return replace(b, palette=replace(b.palette, **endringer))


# ── persistent teller ──────────────────────────────────────

def test_theme_seq_overlever_kjoringer(tmp_path):
    """To kjøringer skal fortsette rotasjonen, ikke starte på 0 igjen."""
    assert store.next_theme_seq(tmp_path, "demo", count=3) == 0
    assert store.next_theme_seq(tmp_path, "demo") == 3
    assert store.next_theme_seq(tmp_path, "demo") == 4


def test_theme_seq_er_per_merke(tmp_path):
    store.next_theme_seq(tmp_path, "demo", count=5)
    # Et annet merke har sin egen teller: rotasjonen til det ene skal ikke
    # hoppe fordi det andre genererte i natt.
    assert store.next_theme_seq(tmp_path, "annen") == 0


def test_theme_seq_odelegger_ikke_dedup_state(tmp_path):
    """Telleren bor i content-state.json sammen med posts-lista; den skal ikke
    nullstille dedup-historikken."""
    store.record(tmp_path, [{"brand": "demo", "format": "motiv",
                             "headline": "X", "motif": "m", "pillar": "",
                             "emne": "x"}])
    store.next_theme_seq(tmp_path, "demo")
    assert len(store.load_state(tmp_path)["posts"]) == 1


# ── aksent-tokens med fallback ─────────────────────────────

def test_tomme_valgfrie_tokens_faller_til_brand():
    pal = _brand_med_palett(accent="", on_dark="").palette
    assert render._pcol(pal, "accent") == render._hex(pal.brand)
    assert render._pcol(pal, "on_dark") == render._hex(pal.brand)


def test_satt_aksent_brukes():
    pal = _brand_med_palett(accent="#EFC94C").palette
    assert render._pcol(pal, "accent") == (0xEF, 0xC9, 0x4C)


def test_mork_tema_lyser_for_mork_merkefarge():
    """Vitandi-buggen: brand == dark (marineblå) gjorde kicker/subhead usynlig
    på mørk-temaet. Med on_dark satt skal den fargen faktisk finnes i kortet."""
    b = _brand_med_palett(brand="#1C2E3D", dark="#1C2E3D", headline="#1C2E3D",
                          on_dark="#EFC94C")
    spec = {"format": "typografi-kort", "theme": "mork",
            "headline": "Skjønn avgjorde saken.", "kicker": "MENNESKE I LOOPEN",
            "subhead": "Data alene så det ikke."}
    png = render.render_template(spec, b)
    im = Image.open(BytesIO(png)).convert("RGB")
    gull = (0xEF, 0xC9, 0x4C)
    treff = sum(1 for p in im.resize((120, 150)).getdata()
                if all(abs(a - c) <= 40 for a, c in zip(p, gull)))
    assert treff > 5, "on_dark-fargen (gull) skal være synlig på mørk flate"


# ── temaer + motivrammer roterer bredere ───────────────────

def test_aksent_temaene_finnes_og_roterer():
    keys = {render.pick_theme({}, seq=i).key for i in range(len(render.THEMES))}
    assert {"sand-aksent", "krem", "blokk-aksent"} <= keys


def test_motivrammer_har_fire_varianter():
    assert len({tuple(sorted(f.items())) for f in render._MOTIV_FRAMES}) == 4


# ── rullerende fargehierarki i motiv-prompten ──────────────

def test_fargerolle_endrer_prompten():
    b = brandkit.load_brand("demo")
    p_brand = prompts.content_prompt("tre søyler", brand=b, farge_rolle="brand")
    p_lys = prompts.content_prompt("tre søyler", brand=b, farge_rolle="lys")
    assert p_brand != p_lys
    assert "LYSERE tonen" in p_lys


def test_aksentrolle_krever_aksentfarge():
    """Uten accent-token skal aksent-rollen falle til hovedloven, aldri be
    motoren om en farge merket ikke har."""
    uten = _brand_med_palett(accent="")
    med = _brand_med_palett(accent="#EFC94C")
    p_uten = prompts.content_prompt("tre søyler", brand=uten, farge_rolle="aksent")
    p_med = prompts.content_prompt("tre søyler", brand=med, farge_rolle="aksent")
    assert "#EFC94C" not in p_uten
    assert "HOVEDFARGEN" in p_uten          # falt til brand-loven
    assert "#EFC94C" in p_med
    assert "ETT lite element" in p_med


def test_render_motiv_roterer_fargerolle(monkeypatch):
    """render_motiv skal sette farge_rolle fra seq, så to påfølgende motiver
    ikke får identisk fargeplassering."""
    sett = []

    def _fanger(spec, brand, size):
        sett.append(spec.get("farge_rolle"))
        return None  # ingen motor: faller til mal-kortet, det er greit her

    monkeypatch.setattr(render, "engine_content", _fanger)
    b = brandkit.load_brand("demo")
    for seq in range(3):
        render.render_motiv({"motif": "tre søyler", "headline": "X"}, b, seq=seq)
    assert sett == ["brand", "lys", "aksent"]


# ── karusell-skins ─────────────────────────────────────────

def test_karusell_skins_roterer_pa_seq():
    b = brandkit.load_brand("demo")
    s0 = slides.render_slide({"kind": "innhold", "heading": "A", "body": "b"},
                             b, pos=1, total=3, number=1, seq=0)
    s1 = slides.render_slide({"kind": "innhold", "heading": "A", "body": "b"},
                             b, pos=1, total=3, number=1, seq=1)
    hj0 = s0.getpixel((8, 8))
    hj1 = s1.getpixel((8, 8))
    assert hj0 == render._pcol(b.palette, "bg")
    assert hj1 == render._pcol(b.palette, "bg_alt")
    assert hj0 != hj1, "skin-rotasjonen skal gi ulik flate på seq 0 og 1"
