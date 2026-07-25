"""prompts — delt brand-brief for bildemotorene (Gemini + OpenAI).

Samme prompt til begge så en sammenligning blir rettferdig. Beskriver ETT
sammenhengende kort for DET MERKET som sendes inn (som en grafisk designer, ikke et
innlimt bilde): merkets egne former + farger + logo integrert, valgfri maskot, og et
meningsbærende motiv. Alt merke-spesifikt kommer fra profilen, aldri hardkodet: et
selskaps identitet skal ikke kunne følge med til et annet.
"""

from __future__ import annotations

from pathlib import Path

from .brandkit import Brand


SPRAAK = {
    "no": "norsk (æøå må gjengis riktig)",
    "nb": "norsk bokmål (æøå må gjengis riktig)",
    "en": "English",
    "sv": "svenska (åäö måste återges korrekt)",
    "da": "dansk (æøå skal gengives korrekt)",
    "de": "Deutsch (Umlaute müssen korrekt sein)",
    "fr": "français (les accents doivent être corrects)",
    "es": "español (las tildes deben ser correctas)",
    "nl": "Nederlands",
}


def spraak(brand: Brand) -> str:
    """Språkkravet til bildemotoren, fra merkets `language`. Var hardkodet norsk,
    så et engelsk merke fikk norske etiketter tegnet inn i illustrasjonen."""
    kode = (getattr(brand, "language", "") or "no").strip().lower()
    return SPRAAK.get(kode, SPRAAK.get(kode.split("-")[0], f"språkkoden {kode}"))


def lysere(hex_farge: str, andel: float = 0.35) -> str:
    """En lysere tone av merkefargen, blandet mot hvitt.

    Erstatter en hardkodet lys grønn (#52b160) som var Demo Labss sekundærtone.
    Den fulgte med til ETHVERT merke som brukte motoren, så et annet selskaps
    innlegg kom ut i Demo Labss farger."""
    s = (hex_farge or "").strip().lstrip("#")
    if len(s) != 6:
        return hex_farge
    try:
        r, g, b = (int(s[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return hex_farge
    a = min(max(andel, 0.0), 1.0)
    return "#%02x%02x%02x" % tuple(round(v + (255 - v) * a) for v in (r, g, b))


def har_egen_logo(brand: Brand) -> bool:
    """Har merket en EGEN logo å bygge på? Uten den skal motoren ikke få beskjed om
    å gjenta en mark, for da låner den et annet merkes mark eller finner på en."""
    p = getattr(brand, "logo_path", None)
    return bool(p and Path(p).exists())

# Stil-arketyper runbooken kan be om for variasjon.
CONCEPTS = {
    "isometrisk": "isometrisk 3D-aktig scene, myke skygger",
    "flat": "flat vektorillustrasjon, rene flater",
    "objekt": "ett tydelig redaksjonelt objekt/stilleben sett ovenfra",
    "scene": "en rolig menneskelig scene (gründer/kontor), varmt og troverdig",
    "data": "et enkelt, elegant data-motiv (kurve/søyler) i merkefargene",
    "abstrakt": "abstrakt geometrisk komposisjon bygd på interlock-formen",
    # Utvidet 22. juli 2026: flere arketyper så kortene ikke blir samme
    # infografikk-form uke etter uke. Farge-, form- og logolov gjelder uansett.
    "tidslinje": "en vannrett tidslinje eller stegrekke med tydelige stopp",
    "for-etter": "to kolonner side om side som stiller før mot etter",
    "sjekkliste": "en ryddig sjekkliste med tydelige haker",
    "kart": "et enkelt kart- eller landskapsgrep som viser terreng og posisjon",
    "forstorrelse": "ett detaljutsnitt forstørret ut av en større flate",
    "stabel": "stablede kort eller lag som viser dybde og rekkefølge",
}


def content_prompt(motif: str, *, brand: Brand, size=(1080, 1350),
                   concept: str | None = None, use_tilda: bool = False) -> str:
    """Brief for KUN innholdet (infografikk-enheten) på ensfarget sand, med tomme
    marger + hjørner. Pillow tegner rammen (logo-hjørner + headline + ordmerke) oppå,
    så tone/ramme blir deterministisk og riktig, og innholdet legges sømløst inn."""
    pal = brand.palette
    portrait = size[1] > size[0]
    fmt = "stående 4:5" if portrait else "kvadratisk 1:1"
    concept_hint = CONCEPTS.get((concept or "").strip().lower(), "")
    concept_line = f"Stil: {concept_hint}. " if concept_hint else ""
    tilda_line = ("Tilda-maskoten kan være med som et lite, sekundært element. "
                  if use_tilda else "")
    lys = lysere(pal.brand)
    if har_egen_logo(brand):
        grep = (
            f"SELVE GREPET (viktigst): {brand.name}s egen mark (den vedlagte logoen) er det "
            f"gjennomgående bygge-elementet. Hvert repeterende element, node, punkt, ikon-holder "
            f"eller markør, ER marken, i logoens EGNE to toner: {pal.brand} + en LYSERE tone av "
            f"samme (ca. {lys}). Tegn ALLTID HELE marken, samme mark igjen og igjen, aldri "
            f"forvrengt. Trenger et element en betydning (hake/kryss), sitter den inni eller ved "
            f"siden av marken. Slik leser motivet umiskjennelig som {brand.name}. ")
    else:
        # Uten egen logo skal motoren IKKE be om en gjentatt mark: den låner da et
        # annet merkes mark eller finner på en, og innlegget bærer feil avsender.
        grep = (
            f"SELVE GREPET: enkle, nøytrale geometriske former (sirkel, rektangel med liten lik "
            f"hjørneradius, strek) i {pal.brand} og en LYSERE tone av samme (ca. {lys}). "
            f"{brand.name} har INGEN logo-mark her: ALDRI tegn en logo, et emblem eller en "
            f"gjentatt merke-form, og ALDRI lån en mark fra et annet merke. ")
    return (
        f"Lag KUN selve infografikk-INNHOLDET på rolig, ENSFARGET sand ({pal.bg}) bakgrunn, "
        f"{fmt}. Innhold: {motif}. Det SKAL være en infografikk-enhet (bunke, rad, rutenett, "
        f"sammenligning, liste eller sjekkliste) med FLERE elementer og noen få KORTE etiketter. "
        f"{grep}MAKS 3-4 elementer/rader TOTALT (ber motivet om flere: slå sammen "
        f"eller dropp de minst viktige), og STORE luftrom mellom elementene, minst et halvt "
        f"elements høyde. Luftig og ryddig er viktigere enn komplett. "
        f"Flat vektor. FARGEHIERARKI (viktig, som nettsida): den friske merkegrønne "
        f"({pal.brand}) er HOVEDFARGEN og skal fylle de STORE, bærende formene (søyler, "
        f"blokker, andeler, kort). Trengs en andre grønntone i samme figur, bruk en LYSERE "
        f"tone av merkefargen (ca. {lys}), IKKE aksenttonen og IKKE den mørke. Aksent "
        f"({pal.shape}) er KUN en svak, sekundær bakgrunnstone på små flater, aldri "
        f"hovedfyll. Mørkegrønn ({pal.headline}) er KUN til tekst, tynne konturer og "
        f"negative markører, ALDRI som stor fylt flate. Ellers kun sand ({pal.bg}). INGEN "
        f"rød, oransje eller andre farger utenfor paletten; avslags-markører (x, kryss) i "
        f"mørkegrønn eller dempet grå, ALDRI rødt. "
        f"FORMVETT (viktig): INGEN pille- eller kapselform. Alle avlange flater tegnes som "
        f"REKTANGLER med liten, LIK hjørneradius i alle fire hjørner, aldri med halvsirkel-"
        f"ende eller kuppel-topp. Er motivet en andel/prosent/sammenligning, tegn det som TO "
        f"ATSKILTE blokker med tydelig luft mellom seg (eller et rutenett, en ring/donut, "
        f"eller stablede kort), ALDRI som én sammenhengende avlang form delt i to. Unngå "
        f"generelt former som kan leses anatomisk, særlig en avlang form med rund ende, og "
        f"aldri en slik form flankert av to sirkler. "
        f"Den STØRSTE/viktigste blokka skal ha den friske merkegrønne ({pal.brand}); en "
        f"mindre, sekundær blokk kan ha den lysere tonen. Aldri motsatt. "
        f"{concept_line}{tilda_line}"
        f"STRENGT: INGEN stor tittel/headline øverst, INGEN «{brand.wordmark}»-ordmerke, INGEN "
        f"dekorformer i hjørnene. La øverste ~28 %, nederste ~14 % og ALLE FIRE HJØRNER være "
        f"HELT TOM sand (jeg legger tittel, logo-hjørner og ordmerke på etterpå; alt innhold "
        f"som havner i de sonene blir flyttet og krympet). All tekst på "
        f"{spraak(brand)}, ingen emoji, ingen watermark."
    )


def brand_card_prompt(motif: str, *, headline: str = "", brand: Brand,
                      size=(1080, 1350), concept: str | None = None,
                      use_tilda: bool = False) -> str:
    """Bygg den delte, MINIMALISTISKE brand-briefen for ett kort."""
    pal = brand.palette
    portrait = size[1] > size[0]
    fmt = "stående 4:5 (portrett)" if portrait else "kvadratisk 1:1"
    concept_hint = CONCEPTS.get((concept or "").strip().lower(), "")
    concept_line = f"Stil-retning: {concept_hint}. " if concept_hint else ""
    head_line = f"Kort serif-headline: «{headline}». " if headline else ""
    lys = lysere(pal.brand)
    egen_logo = har_egen_logo(brand)
    tilda_line = ("Tilda-maskoten (den vedlagte krem frø-figuren) kan være med som et "
                  "LITE, sekundært element i et hjørne eller ved siden av, ALDRI hovedfokus. "
                  if use_tilda else "")
    return (
        f"Design ETT gjennomført {brand.name}-kort, {fmt}, som en dyktig grafisk designer, "
        f"i vår FLATE, GRAFISKE stil (som native-eksemplene: dokumentbunker, rutenett, "
        f"sammenligninger). ALLTID en flat vektor-illustrasjon sett rett forfra eller litt "
        f"ovenfra, ALDRI en fotorealistisk scene: IKKE skrivebord, penn, notatbok, kaffekopp, "
        f"lampe, planter eller foto-skygger. En ren, flat, grafisk komposisjon med RIKT, "
        f"INFORMATIVT innhold, ikke et ensomt ikon på tom flate.\n\n"
        f"MERKEVARE: Frisk grønn ({pal.brand}) er HOVEDFARGEN og fyller de store, bærende "
        f"formene i motivet; trengs en andre grønntone, bruk en LYSERE tone av samme "
        f"(ca. {lys}), IKKE aksenttonen og IKKE den mørke som stort fyll. Den mørke "
        f"({pal.headline}) KUN til display-tekst og tynne konturer, mørkt panel "
        f"({pal.dark}) ved behov.\n"
        f"FORMVETT: INGEN pille-/kapselform; avlange flater er REKTANGLER med liten, lik "
        f"hjørneradius, aldri halvsirkel-ende. Andeler tegnes som TO ATSKILTE blokker med "
        f"luft mellom (eller rutenett/ring/stablede kort), aldri én avlang form delt i to. "
        f"Unngå former som kan leses anatomisk, særlig avlang form med rund ende flankert "
        f"av sirkler. Største blokk får den friske merkegrønne, ikke den lyse tonen.\n"
        + (f"LOGOFARGE-LOV (viktigst av alt): når marken vises SOM logo/merke, har den ALLTID "
           f"originalfargene fra det vedlagte logobildet: {pal.brand} og en LYSERE tone av samme "
           f"(ca. {lys}). ALDRI omfarget logo.\n" if egen_logo else
           f"INGEN LOGO: {brand.name} har ingen mark her. Tegn ALDRI en logo, et emblem eller en "
           f"gjentatt merke-form, og lån ALDRI en mark fra et annet selskap.\n")
        +
        f"BAKGRUNN (VIKTIG, akkurat som malen/native-eksemplene): rolig varm sand ({pal.bg}). "
        + (f"De store bakgrunns-formene i hjørnene skal være selve LOGOENS former (den vedlagte "
           f"marken) brukt STORT og abstrahert som bakgrunnskomponenter, i bleke ({pal.shape})-"
           f"toner, delvis utenfor kanten i 2-3 hjørner. Man skal kjenne igjen logoen som selve "
           f"bakgrunnen. Enkelt og ryddig, IKKE mange små blobber. Motivet ligger rolig oppå.\n"
           f"Bruk marken som et GJENNOMGÅENDE grafisk element i illustrasjonen: f.eks. et lite "
           f"merke på hvert dokument/kort, eller som aksent, alltid i logofargene over. "
           if egen_logo else
           f"Bakgrunns-formene i hjørnene er enkle, nøytrale geometriske flater i bleke "
           f"({pal.shape})-toner, delvis utenfor kanten i 2-3 hjørner. INGEN logo-form, verken "
           f"vår eller et annet selskaps. Enkelt og ryddig. Motivet ligger rolig oppå.\n")
        + f"{tilda_line}\n\n"
        f"{head_line}Sentralt motiv: {motif}. {concept_line}"
        f"Motivet SKAL være en informativ INFOGRAFIKK-ENHET som referanse-eksemplene: en "
        f"BUNKE, RAD, RUTENETT, SAMMENLIGNING eller LISTE med FLERE elementer, noen få "
        + ("Merkets mark kan sitte på elementene. " if egen_logo else "")
        + f"IKKE ett ensomt objekt "
        f"eller abstrakt ikon. Rikt og informativt, men luftig (ett hovedgrep + få støtte-"
        f"elementer, dropp ekstra ikon-rader og bokser nederst). Flat, elegant vektor.\n\n"
        f"«{brand.wordmark}»-ordmerket SKAL stå diskret nederst, midtstilt "
        f"(la ALDRI bunnen stå uten ordmerket). All tekst på {spraak(brand)}. Ingen emoji, ingen "
        f"watermark, ingen forvrengt eller falsk logo."
    )
