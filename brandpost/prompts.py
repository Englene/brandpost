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


def _hls(hex_farge: str) -> tuple[float, float, float] | None:
    s = (hex_farge or "").strip().lstrip("#")
    if len(s) == 3:
        s = "".join(ch * 2 for ch in s)
    if len(s) != 6:
        return None
    try:
        r, g, b = (int(s[i:i + 2], 16) / 255 for i in (0, 2, 4))
    except ValueError:
        return None
    import colorsys
    return colorsys.rgb_to_hls(r, g, b)


def fargenavn(hex_farge: str) -> str:
    """Beskrivende norsk navn for en hex-tone, deterministisk fra hue/lys/metning.

    Bildemodeller leser ikke hex-koder pålitelig: «#1A3A8F» er i praksis en
    gjetning for motoren, mens «dyp marineblå» treffer. Derfor gjør NAVNET jobben
    i prompten og hexen står som notat (bransjerådet høsten 2026). Navnene er
    beregnet, aldri hardkodet per merke, så ingen identitet lekker på tvers."""
    hls = _hls(hex_farge)
    if hls is None:
        return "tonen"
    h, l, s = hls
    grader = (h * 360) % 360
    if l < 0.09:
        return "nesten svart"
    if s < 0.12:  # grå-aksen
        if l < 0.30:
            return "mørk kullgrå"
        if l < 0.72:
            return "dempet grå"
        return "kremhvit"
    if l > 0.84:  # svært lyse toner leses som flate, ikke farge
        return "varm sand" if 15 <= grader <= 90 else "blek pastell"
    if grader < 15 or grader >= 340:
        navn = "rød"
    elif grader < 35:
        navn = "terrakotta-oransje"
    elif grader < 52:
        navn = "gyllen honninggul"
    elif grader < 70:
        navn = "gul"
    elif grader < 150:
        navn = "grønn"
    elif grader < 180:
        navn = "salviegrønn"
    elif grader < 200:
        navn = "petrolgrønn"
    elif grader < 260:
        navn = "marineblå" if l < 0.28 else "blå"
    elif grader < 290:
        navn = "lilla"
    else:
        navn = "rosa"
    if l < 0.22:
        return f"dyp mørk{navn}" if navn in ("grønn", "gul") else f"mørk {navn}"
    if l >= 0.58:
        return f"lys {navn}"
    if s > 0.45:
        return f"frisk {navn}"
    return f"dempet {navn}"


def med_navn(hex_farge: str) -> str:
    """«frisk grønn, #24a03d»-formen: navnet styrer, hexen dokumenterer."""
    return f"{fargenavn(hex_farge)}, {hex_farge}"


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


def _fargehierarki(pal, lys: str, rolle: str) -> str:
    """Fargeplasserings-loven for motivet, rotert per innlegg (render._FARGE_ROLLER).

    Én låst lov ga identisk fargeplassering på hvert kort (designer-tilbakemelding
    aug 2026: «helt samme design og fargeplassering»). Rollene flytter hvilken tone
    som bærer de store formene, uten å slippe fremmede farger inn: alt går fortsatt
    via merkets egen palett, aldri hardkodede hex-verdier."""
    aksent = (getattr(pal, "accent", "") or "").strip()
    if rolle == "aksent" and not aksent:
        rolle = "brand"  # merket har ingen aksentfarge: fall til hovedloven
    if rolle == "lys":
        return (
            f"FARGEHIERARKI (viktig): den LYSERE tonen av merkefargen (ca. {med_navn(lys)}) fyller "
            f"de STORE, bærende formene (søyler, blokker, andeler, kort) denne gangen, og "
            f"den friske merkefargen ({med_navn(pal.brand)}) sitter KUN på det ENE viktigste "
            f"elementet (den største verdien, konklusjonen, haken), så det spretter fram. "
            f"Aksent ({med_navn(pal.shape)}) er KUN en svak, sekundær bakgrunnstone på små flater, "
            f"aldri hovedfyll. Mørk ({med_navn(pal.headline)}) er KUN til tekst, tynne konturer og "
            f"negative markører, ALDRI som stor fylt flate. Ellers kun sand ({med_navn(pal.bg)}). "
            f"INGEN farger utenfor paletten; avslags-markører (x, kryss) i mørk eller "
            f"dempet grå, ALDRI rødt. "
            f"Det ENE viktigste elementet får merkefargen ({med_navn(pal.brand)}); alt annet stort "
            f"fyll er den lysere tonen. Aldri flere enn ett element i merkefargen. ")
    if rolle == "aksent":
        return (
            f"FARGEHIERARKI (viktig): merkefargen ({med_navn(pal.brand)}) er HOVEDFARGEN og fyller "
            f"de STORE, bærende formene (søyler, blokker, andeler, kort). Trengs en andre "
            f"tone i samme figur, bruk en LYSERE tone av merkefargen (ca. {med_navn(lys)}). "
            f"NYTT DENNE GANGEN: nøyaktig ETT lite element (den viktigste markøren, en "
            f"hake, ett tall-felt eller en tynn strek) settes i aksentfargen ({med_navn(aksent)}), "
            f"så kortet får et varmt blikkfang. ALDRI mer enn ett aksent-element, og aldri "
            f"aksent som stort fyll. Aksent-bakgrunnstonen ({med_navn(pal.shape)}) er KUN en svak, "
            f"sekundær tone på små flater. Mørk ({med_navn(pal.headline)}) er KUN til tekst, tynne "
            f"konturer og negative markører, ALDRI som stor fylt flate. Ellers kun sand "
            f"({pal.bg}). INGEN farger utenfor paletten; avslags-markører (x, kryss) i "
            f"mørk eller dempet grå, ALDRI rødt. "
            f"Den STØRSTE/viktigste blokka skal ha merkefargen ({med_navn(pal.brand)}); en mindre, "
            f"sekundær blokk kan ha den lysere tonen. Aldri motsatt. ")
    return (
        f"FARGEHIERARKI (viktig, som nettsida): den friske merkefargen ({med_navn(pal.brand)}) er "
        f"HOVEDFARGEN og skal fylle de STORE, bærende formene (søyler, blokker, andeler, "
        f"kort). Trengs en andre tone i samme figur, bruk en LYSERE tone av merkefargen "
        f"(ca. {med_navn(lys)}), IKKE aksenttonen og IKKE den mørke. Aksent ({med_navn(pal.shape)}) er KUN en "
        f"svak, sekundær bakgrunnstone på små flater, aldri hovedfyll. Mørk "
        f"({med_navn(pal.headline)}) er KUN til tekst, tynne konturer og negative markører, ALDRI "
        f"som stor fylt flate. Ellers kun sand ({med_navn(pal.bg)}). INGEN rød, oransje eller andre "
        f"farger utenfor paletten; avslags-markører (x, kryss) i mørk eller dempet grå, "
        f"ALDRI rødt. "
        f"Den STØRSTE/viktigste blokka skal ha den friske merkefargen ({med_navn(pal.brand)}); en "
        f"mindre, sekundær blokk kan ha den lysere tonen. Aldri motsatt. ")


def content_prompt(motif: str, *, brand: Brand, size=(1080, 1350),
                   concept: str | None = None, use_tilda: bool = False,
                   farge_rolle: str = "brand") -> str:
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
    farge_blokk = _fargehierarki(pal, lys, (farge_rolle or "brand").strip().lower())
    if har_egen_logo(brand):
        grep = (
            f"SELVE GREPET (viktigst): {brand.name}s egen mark (den vedlagte logoen) er det "
            f"gjennomgående bygge-elementet. Hvert repeterende element, node, punkt, ikon-holder "
            f"eller markør, ER marken, i logoens EGNE to toner: {med_navn(pal.brand)} + en LYSERE tone av "
            f"samme (ca. {med_navn(lys)}). Tegn ALLTID HELE marken, samme mark igjen og igjen, aldri "
            f"forvrengt. Trenger et element en betydning (hake/kryss), sitter den inni eller ved "
            f"siden av marken. Slik leser motivet umiskjennelig som {brand.name}. ")
    else:
        # Uten egen logo skal motoren IKKE be om en gjentatt mark: den låner da et
        # annet merkes mark eller finner på en, og innlegget bærer feil avsender.
        grep = (
            f"SELVE GREPET: enkle, nøytrale geometriske former (sirkel, rektangel med liten lik "
            f"hjørneradius, strek) i {med_navn(pal.brand)} og en LYSERE tone av samme (ca. {med_navn(lys)}). "
            f"{brand.name} har INGEN logo-mark her: ALDRI tegn en logo, et emblem eller en "
            f"gjentatt merke-form, og ALDRI lån en mark fra et annet merke. ")
    return (
        f"Lag KUN selve infografikk-INNHOLDET på rolig, ENSFARGET sand ({med_navn(pal.bg)}) bakgrunn, "
        f"{fmt}. Innhold: {motif}. Det SKAL være en infografikk-enhet (bunke, rad, rutenett, "
        f"sammenligning, liste eller sjekkliste) med FLERE elementer og noen få KORTE etiketter. Etikettene staves NØYAKTIG og på korrekt norsk (æ, ø, å er egne bokstaver, aldri ae/o/a); gjengi etikett-ord fra innholdet ORDRETT, og dropp heller en etikett enn å gjette. "
        f"{grep}MAKS 3-4 elementer/rader TOTALT (ber motivet om flere: slå sammen "
        f"eller dropp de minst viktige), og STORE luftrom mellom elementene, minst et halvt "
        f"elements høyde. Luftig og ryddig er viktigere enn komplett. "
        f"ETT grep per kort: ALDRI to ulike figurtyper i samme bilde (aldri en tidslinje OG "
        f"søyler, aldri en liste OG et diagram): velg det ene som bærer poenget og dropp "
        f"resten. "
        f"Flat vektor. {farge_blokk}"
        f"FORMVETT (viktig): INGEN pille- eller kapselform. Alle avlange flater tegnes som "
        f"REKTANGLER med liten, LIK hjørneradius i alle fire hjørner, aldri med halvsirkel-"
        f"ende eller kuppel-topp. Er motivet en andel/prosent/sammenligning, tegn det som TO "
        f"ATSKILTE blokker med tydelig luft mellom seg (eller et rutenett, en ring/donut, "
        f"eller stablede kort), ALDRI som én sammenhengende avlang form delt i to. Unngå "
        f"generelt former som kan leses anatomisk, særlig en avlang form med rund ende, og "
        f"aldri en slik form flankert av to sirkler. "
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
        f"MERKEVARE: Frisk grønn ({med_navn(pal.brand)}) er HOVEDFARGEN og fyller de store, bærende "
        f"formene i motivet; trengs en andre grønntone, bruk en LYSERE tone av samme "
        f"(ca. {med_navn(lys)}), IKKE aksenttonen og IKKE den mørke som stort fyll. Den mørke "
        f"({med_navn(pal.headline)}) KUN til display-tekst og tynne konturer, mørkt panel "
        f"({med_navn(pal.dark)}) ved behov.\n"
        f"FORMVETT: INGEN pille-/kapselform; avlange flater er REKTANGLER med liten, lik "
        f"hjørneradius, aldri halvsirkel-ende. Andeler tegnes som TO ATSKILTE blokker med "
        f"luft mellom (eller rutenett/ring/stablede kort), aldri én avlang form delt i to. "
        f"Unngå former som kan leses anatomisk, særlig avlang form med rund ende flankert "
        f"av sirkler. Største blokk får den friske merkegrønne, ikke den lyse tonen.\n"
        + (f"LOGOFARGE-LOV (viktigst av alt): når marken vises SOM logo/merke, har den ALLTID "
           f"originalfargene fra det vedlagte logobildet: {pal.brand} og en LYSERE tone av samme "
           f"(ca. {med_navn(lys)}). ALDRI omfarget logo.\n" if egen_logo else
           f"INGEN LOGO: {brand.name} har ingen mark her. Tegn ALDRI en logo, et emblem eller en "
           f"gjentatt merke-form, og lån ALDRI en mark fra et annet selskap.\n")
        +
        f"BAKGRUNN (VIKTIG, akkurat som malen/native-eksemplene): rolig varm sand ({med_navn(pal.bg)}). "
        + (f"De store bakgrunns-formene i hjørnene skal være selve LOGOENS former (den vedlagte "
           f"marken) brukt STORT og abstrahert som bakgrunnskomponenter, i bleke ({med_navn(pal.shape)})-"
           f"toner, delvis utenfor kanten i 2-3 hjørner. Man skal kjenne igjen logoen som selve "
           f"bakgrunnen. Enkelt og ryddig, IKKE mange små blobber. Motivet ligger rolig oppå.\n"
           f"Bruk marken som et GJENNOMGÅENDE grafisk element i illustrasjonen: f.eks. et lite "
           f"merke på hvert dokument/kort, eller som aksent, alltid i logofargene over. "
           if egen_logo else
           f"Bakgrunns-formene i hjørnene er enkle, nøytrale geometriske flater i bleke "
           f"({med_navn(pal.shape)})-toner, delvis utenfor kanten i 2-3 hjørner. INGEN logo-form, verken "
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
