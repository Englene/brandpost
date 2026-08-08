"""bildevalg — skaff et EKTE bilde til et personlig innlegg.

Bakgrunn (3.-4. august 2026): den personlige profilen fikk først de samme
designede typografi-kortene som firmasidene, og eieren forkastet dem. En
privatperson med perfekt merkevaregrafikk på hvert innlegg leser som en kampanje,
og det undergraver hele poenget med at han faktisk bygger noe selv.

Første retting var å droppe bildet helt. Det var riktig som strakstiltak, men
etterlot noe på bordet: lang tekst MED bilde ligger på 2,77 % engasjement mot
1,98 % for ren tekst av samme lengde. Bildet er ikke problemet, firmagrafikken er.

Så her er fire kilder til bilder som faktisk dokumenterer noe, i den rekkefølgen
eieren prioriterte dem:

  utdrag     et bilde av det innlegget FAKTISK handler om: teksten som ble
             forkastet, logglinja, tabellen. Vi har dataene, så dette koster
             ingenting og treffer alltid.
  bevis      hans egne skjermbilder, gjennom bildebanken som allerede flagger
             kundenavn og e-post og slipper bare de trygge gjennom.
  nettkilde  skjermbilde av siden en påstand er hentet fra. Sterkest
             dokumentasjon. Utsnitt med synlig kilde, aldri hele artikkelen.
  figur      et nøkternt søylediagram når tallene bærer det.

MODELLEN VELGER, KODEN FALLER TILBAKE. Hver kilde kan feile av grunner vi ikke
kontrollerer (siden er nede, bildet er flagget, dataene mangler), og da er svaret
INGEN BILDE, aldri et pent erstatningskort. Det var nettopp fallback-til-kort som
ga firmagrafikken på en personlig profil i utgangspunktet.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from PIL import Image, ImageDraw

from . import bildebank, brandkit, render

# Skjermbilde-lignende flate: nøytral, uten merkevare. Poenget er at det skal se
# ut som noe som er tatt, ikke som noe som er designet.
BREDDE = 1200
MARG = 56
BAKGRUNN = (250, 250, 248)
BLEKK = (28, 28, 26)
DEMPET = (122, 122, 116)
RAMME = (223, 223, 216)


# Fast bredde gjør at et utdrag LESES som et utdrag og ikke som en plakat.
#
# Absolutte stier, ikke brandkit.font_path(): den leter bare etter .ttf og .otf,
# og macOS legger Menlo og Courier som .ttc (font-samlinger). Menlo fantes hele
# tiden, men ble aldri funnet, og teksten falt stille tilbake til Inter.
_MONO_STIER = (
    "/System/Library/Fonts/SFNSMono.ttf",
    "/System/Library/Fonts/Menlo.ttc",
    "/System/Library/Fonts/Supplemental/Menlo.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
)


def _mono(size: int):
    from PIL import ImageFont
    for sti in _MONO_STIER:
        if Path(sti).exists():
            try:
                return ImageFont.truetype(sti, size)
            except OSError:
                continue
    p = brandkit.font_path("DejaVuSansMono.ttf")
    if p:
        try:
            return ImageFont.truetype(str(p), size)
        except OSError:
            pass
    return render._load_font("Inter.ttf", size)


def _brekk(tekst: str, *, maks_linjer: int = 22) -> list[str]:
    """Bryt teksten så den faktisk får plass innenfor rammen.

    MÅLER bredden med fonten i stedet for å telle tegn. Første forsøk gjettet på
    96 tegn, som er riktig for Inter og altfor mye for en monofont: første linje
    stakk utenfor rammen og siste ord ble kuttet midt i.

    Utdraget beskjæres i stedet for å krympes. Et utdrag skalert ned til
    uleselighet dokumenterer ingenting.
    """
    f = _mono(26)
    d = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    maks_bredde = BREDDE - MARG * 2 - 12

    ut: list[str] = []
    for rad in tekst.splitlines():
        rad = rad.rstrip()
        if not rad:
            ut.append("")
            continue
        while rad and d.textlength(rad, font=f) > maks_bredde:
            kutt = len(rad)
            while kutt > 1 and d.textlength(rad[:kutt], font=f) > maks_bredde:
                kutt -= 1
            mellomrom = rad.rfind(" ", 0, kutt)
            brudd = mellomrom if mellomrom > kutt // 2 else kutt
            ut.append(rad[:brudd])
            rad = rad[brudd:].lstrip()
        if rad:
            ut.append(rad)
        if len(ut) >= maks_linjer:
            return ut[:maks_linjer] + ["…"]
    return ut


def _tekstbilde(tittel: str, linjer: list[str], *, fotnote: str = "") -> bytes:
    """Rendr tekst som et utdrag med ramme. Ikke et typografi-kort: ingen logo,
    ingen merkefarge, ingen dramatisk sats. Det skal ligne et klipp fra en skjerm."""
    f_tit = render._load_font("Inter.ttf", 30, bold=True)
    f_txt = _mono(26)
    f_fot = render._load_font("Inter.ttf", 22)

    linje_h = 40
    # Tittelen trenger luft under seg, ellers leses den som første tekstlinje i
    # utdraget i stedet for som etiketten på det.
    tit_h = 78 if tittel else 0
    hoyde = MARG * 2 + tit_h + linje_h * max(len(linjer), 1) + (52 if fotnote else 0)
    img = Image.new("RGB", (BREDDE, max(hoyde, 320)), BAKGRUNN)
    d = ImageDraw.Draw(img)
    d.rectangle([(MARG // 2, MARG // 2),
                 (BREDDE - MARG // 2, img.height - MARG // 2)], outline=RAMME, width=2)

    y = MARG
    if tittel:
        d.text((MARG, y), tittel[:78], font=f_tit, fill=BLEKK)
        # Tynn skillelinje: markerer at det under er sitert materiale, ikke vår tekst.
        d.line([(MARG, y + 46), (BREDDE - MARG, y + 46)], fill=RAMME, width=1)
        y += tit_h
    for rad in linjer:
        d.text((MARG, y), rad[:96], font=f_txt, fill=BLEKK)
        y += linje_h
    if fotnote:
        d.text((MARG, img.height - MARG - 8), fotnote[:110], font=f_fot, fill=DEMPET)
    return render._to_png(img)


def _fra_utdrag(spec: dict, **_) -> dict | None:
    """Et bilde av det innlegget handler om, tatt fra `spec['utdrag']`.

    Dette er kilden med best treffrate, fordi dataene alltid finnes: skriver
    innlegget om en tekst som ble forkastet, ER den teksten bildet.
    """
    u = spec.get("utdrag")
    if not isinstance(u, dict):
        return None
    tekst = (u.get("tekst") or "").strip()
    if len(tekst) < 20:
        return None
    return {"png": _tekstbilde(u.get("tittel", ""), _brekk(tekst),
                               fotnote=u.get("fotnote", "")),
            "format": "utdrag", "how": "utdrag:egne-data"}


def _fra_bevis(spec: dict, *, vault=None, **_) -> dict | None:
    """Eierens egne skjermbilder, via bildebanken.

    Banken er fail-closed og håndhever godkjenningen selv, så en ukjent eller
    flagget id gir None her framfor å slippe gjennom et bilde med en kundes navn.
    """
    p = bildebank.finn(spec.get("bevis_id", ""), vault)
    if p is None:
        return None
    return {"png": p.read_bytes(), "format": "eget-bilde", "how": f"bevis:{p.name}"}


_URL = re.compile(r"https?://[^\s»<>\"]+")


def _fra_nettkilde(spec: dict, **_) -> dict | None:
    """Skjermbilde av siden en påstand er hentet fra.

    Utsnitt fra toppen, ikke hele artikkelen: dette er en referanse til kilden,
    ikke en gjengivelse av den. Adressefeltet er med i bildet med vilje, så det er
    synlig hvor det kommer fra.

    Krever BRANDPOST_BROWSER_ENABLED=1, som ellers styrer nettleser-automatiseringen.
    Uten den, og ved enhver feil, er svaret None. En kilde som ikke svarer skal
    ikke stoppe innlegget.
    """
    url = (spec.get("kilde_url") or "").strip()
    if not url or not _URL.fullmatch(url):
        return None
    if os.environ.get("BRANDPOST_BROWSER_ENABLED") != "1":
        return None
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return None
    try:
        with sync_playwright() as pw:
            b = pw.chromium.launch()
            side = b.new_page(viewport={"width": 1200, "height": 800})
            side.goto(url, timeout=25000, wait_until="domcontentloaded")
            side.wait_for_timeout(1200)
            png = side.screenshot(clip={"x": 0, "y": 0, "width": 1200, "height": 800})
            b.close()
        return {"png": png, "format": "nettkilde", "how": f"kilde:{url[:60]}"}
    except Exception:  # noqa: BLE001
        # Nede, treg, bak innlogging, cookie-vegg. Alle sammen betyr det samme
        # her: ikke noe bilde denne gangen.
        return None


def _fra_figur(spec: dict, **_) -> dict | None:
    """Nøkternt søylediagram fra `spec['figur']`.

    Bevisst stygt enkelt: ingen merkefarge, ingen gradient, ingen ikoner. Så snart
    dette begynner å ligne infografikk, er vi tilbake til kortene som ble
    forkastet.
    """
    f = spec.get("figur")
    if not isinstance(f, dict):
        return None
    punkter = [p for p in (f.get("punkter") or [])
               if isinstance(p, dict) and isinstance(p.get("verdi"), (int, float))]
    if not 2 <= len(punkter) <= 6:
        return None

    f_tit = render._load_font("Inter.ttf", 30, bold=True)
    f_lab = render._load_font("Inter.ttf", 24)
    hoyde = 200 + 78 * len(punkter)
    img = Image.new("RGB", (BREDDE, hoyde), BAKGRUNN)
    d = ImageDraw.Draw(img)
    tittel = (f.get("tittel") or "").strip()
    y = MARG
    if tittel:
        d.text((MARG, y), tittel[:70], font=f_tit, fill=BLEKK)
        y += 62

    maks = max(abs(p["verdi"]) for p in punkter) or 1
    bredde_full = BREDDE - MARG * 2 - 260
    for p in punkter:
        navn = str(p.get("navn", ""))[:26]
        d.text((MARG, y + 6), navn, font=f_lab, fill=BLEKK)
        bx = MARG + 240
        bw = max(int(bredde_full * abs(p["verdi"]) / maks), 3)
        d.rectangle([(bx, y), (bx + bw, y + 34)], fill=BLEKK)
        d.text((bx + bw + 14, y + 4), str(p.get("etikett") or p["verdi"]),
               font=f_lab, fill=DEMPET)
        y += 78

    if f.get("kilde"):
        d.text((MARG, hoyde - MARG), f"Kilde: {str(f['kilde'])[:90]}",
               font=render._load_font("Inter.ttf", 21), fill=DEMPET)
    return {"png": render._to_png(img), "format": "figur", "how": "figur:soyler"}


KILDER = {
    "utdrag": _fra_utdrag,
    "bevis": _fra_bevis,
    "nettkilde": _fra_nettkilde,
    "figur": _fra_figur,
}

# TATT, ikke TEGNET. Bare disse to prøves automatisk.
#
# Første versjon hadde `utdrag` først, altså en render av tekst i monofont med
# ramme rundt. Eieren gjenkjente den umiddelbart for det den var: «DET SKAL VÆRE
# EKTE BILDE IKKE SÅNN JÆLVA TYPGRAFI GREIE PÅ PERSONLIG». Han har rett. Et
# tekstkort er det samme designede uttrykket som ble forkastet 3. august, bare med
# en annen font.
#
# `utdrag` og `figur` finnes fortsatt, men er tegnede flater og kan bare velges
# EKSPLISITT av modellen. De er aldri fallback, for da blir de standardsvaret hver
# gang de ekte kildene ikke leverer, og det var nøyaktig det som skjedde.
REKKEFOLGE = ("bevis", "nettkilde")


def skaff(spec: dict, *, vault=None) -> dict | None:
    """Prøv modellens valgte bildetype først, så de andre i prioritert rekkefølge.

    Returnerer None når ingen kilde ga noe, og DET ER ET GYLDIG SVAR. Ren tekst er
    et normalt format på en personlig profil, og bedre enn et bilde som ikke
    dokumenterer noe. Aldri fall tilbake til et designet kort her.
    """
    valgt = (spec.get("bildetype") or "").strip().lower()
    if valgt == "ingen":
        return None
    prov = ([valgt] if valgt in KILDER else []) + [k for k in REKKEFOLGE if k != valgt]
    for navn in prov:
        try:
            r = KILDER[navn](spec, vault=vault)
        except Exception:  # noqa: BLE001
            continue
        if r:
            return r
    return None
