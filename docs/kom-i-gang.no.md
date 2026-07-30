# Kom i gang, fra helt null

Denne guiden går ut fra at du aldri har brukt GitHub, ikke vet hva en API-nøkkel
er, og ikke skriver kode. Det går helt fint. Du skal ikke programmere noe. Du skal
laste ned en mappe, hente et par nøkler, og la en KI-assistent gjøre resten.

Sett av rundt en halvtime første gang.

**Hva du sitter igjen med:** ferdige LinkedIn-innlegg til firmasiden din, med
bilde og tekst, som dukker opp av seg selv på de dagene du har valgt. Du leser
gjennom, og trykker publiser på det du liker. Ingenting går ut uten at du sier ja.

---

## Del 1: Hva er GitHub, og hvordan får jeg tak i koden

### Hva GitHub er

GitHub er en nettside der folk legger ut programkode, omtrent som Google Drive er
for dokumenter. En «repo» (kort for repository) er bare en mappe med filer.

Koden du skal bruke ligger her, åpent for alle:

**https://github.com/Englene/brandpost**

Du trenger ikke bruker for å laste den ned. Slik ser den ut:

![GitHub-repoet](img/1-github-repo.png)

Det du ser er en filliste. `agent`, `brandpost`, `docs` og `web` er mapper.
Teksten til høyre for hver er en beskrivelse av siste endring. Du trenger ikke
forstå noe av det.

### Laste den ned

Trykk på den grønne **Code**-knappen, og velg **Download ZIP** nederst:

![Last ned ZIP](img/2-last-ned-zip.png)

Du får en zip-fil i nedlastingsmappa. Dobbeltklikk for å pakke den ut. Du har nå
en mappe som heter `brandpost-main`. Flytt den dit du vil ha den, for eksempel i
Dokumenter. **Husk hvor du la den**, du skal peke assistenten dit om litt.

> **Enklere alternativ:** har du allerede Claude Code eller Codex, kan du hoppe
> over nedlastingen og be assistenten om det i stedet:
> «Last ned https://github.com/Englene/brandpost til Dokumenter og åpne mappa.»

---

## Del 2: Hva er en API-nøkkel

Programmet skal lage bilder til innleggene dine. Det gjør det ikke selv, det
spør en bildetjeneste om hjelp, på samme måte som du ville spurt ChatGPT.

For at tjenesten skal vite hvem som spør, og hvem regningen går til, trenger du en
**API-nøkkel**. Det er en lang tekststreng som ser omtrent slik ut:

```
sk-proj-a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8s9T0
```

Tre ting å vite om den:

- **Den er som et passord.** Alle som har den, kan bruke den og du får regningen.
  Aldri lim den inn i en chat, en e-post eller et dokument du deler.
- **Den vises bare én gang.** Når du lager den, får du se den én eneste gang. Kopier
  den med det samme. Mister du den, lager du bare en ny.
- **Den koster penger per bruk.** Ikke et abonnement, men noen ører per bilde. Du
  setter selv et tak.

---

## Del 3: Lag OpenAI-konto og hent nøkkelen

Bildene lages av OpenAI (samme selskap som ChatGPT). Merk at dette er en **egen
konto** fra ChatGPT-abonnementet ditt, med egen betaling. Har du ChatGPT Plus,
dekker det ikke dette.

Gjør disse tre i rekkefølge. Lenkene går rett dit, så du slipper å lete:

**1. Lag konto**
https://platform.openai.com/signup
Bruk e-post eller Google. Du må bekrefte et telefonnummer.

**2. Legg inn betaling og sett et tak**
https://platform.openai.com/settings/organization/billing/overview
Legg inn kort og fyll på et lite beløp, for eksempel 10 dollar. Det holder lenge.

Finn deretter **Limits** i menyen på samme side, og sett en månedlig grense. Da
kan det aldri løpe løpsk, uansett hva som skjer. Gjør dette før du lager nøkkelen,
så slipper du å tenke på det siden.

**3. Lag nøkkelen**
https://platform.openai.com/api-keys
Trykk **Create new secret key**, gi den et navn du kjenner igjen (for eksempel
«brandpost»), og trykk opprett. **Kopier nøkkelen med en gang** og lim den
midlertidig et sted bare du ser, for eksempel i en tom Notes-fil. Du skal bruke
den om et øyeblikk, og deretter kan du slette den derfra.

> Får du en side som ber deg «verifisere at du er et menneske», er det bare
> OpenAIs vanlige bot-sjekk. Kryss av og fortsett.

### Hva med teksten i innleggene?

Bildene kommer fra OpenAI. **Teksten** kommer fra en annen modell, og der har du
to valg:

| Har du dette | Da trenger du |
|---|---|
| Claude Code-abonnement (eller ChatGPT-abonnement med Codex) | ingenting mer, assistenten skriver teksten selv |
| Ingen av delene | en nøkkel til fra https://console.anthropic.com/settings/keys |

De fleste som leser denne guiden har det første. Assistenten du limer prompten
inn i, er den samme som skriver teksten.

---

## Del 4: Sett det opp

Nå gjør assistenten resten. Du trenger **én** av disse:

- **Claude Code**, https://claude.com/claude-code
- **Codex**, som følger med ChatGPT-abonnement, https://openai.com/codex

Åpne den i mappa du lastet ned. I Claude Code gjør du det ved å åpne mappa i
appen; i Codex peker du den på mappa.

Så limer du inn dette, ordrett:

```
Les agent/setup.md i denne mappa og gjør det den sier. Jeg har ikke gjort dette
før, så forklar underveis og spør meg om én ting av gangen.
```

Assistenten intervjuer deg nå om firmaet ditt: hva dere gjør, hvem dere snakker
til, hva dere vil være kjent for, og hvordan dere høres ut. **Dette er den delen
som betyr noe.** Motoren kan tegne og formulere, men den kan ikke vite hva firmaet
ditt mener. Bruk et kvarter på svarene, så blir innleggene deretter.

Den ber deg også om OpenAI-nøkkelen. Da limer du inn den du kopierte. Den lagres i
en fil som heter `.env` i mappa, og den fila deles aldri videre.

Når intervjuet er ferdig, be om et prøveinnlegg:

```
Lag tre utkast til meg nå, så jeg får se hvordan det ser ut.
```

---

## Del 5: Få det til å gå av seg selv

Så langt må du be om innlegg hver gang. Neste steg er at de bare dukker opp.

Lim inn dette til samme assistent:

```
Les agent/automate.md og sett opp automatikken for meg. Jeg vil ha nye utkast
automatisk, og jeg vil godkjenne dem selv før noe publiseres.
```

Den spør hvilke dager du vil ha innlegg, og setter opp resten. Den viser deg også
at jobbene faktisk kjører, ikke bare at de burde.

### De to måtene å planlegge på

Assistenten setter opp jobbene på maskinen din. I tillegg kan du la selve
skrivingen skje som en fast oppgave i verktøyet du bruker:

- **Claude Code** har *routines*: faste kjøringer på et klokkeslett. Be
  assistenten: «Lag en routine som kjører agent/generate.md hver mandag klokka 7.»
- **Codex** har *automations*, som er det samme. Du lager en ny automation, velger
  prosjektet, og skriver instruksen den skal kjøre.

Begge deler forutsetter at maskinen er på. Sover laptopen klokka sju om morgenen,
skjer det ingenting. Si det til assistenten, så velger den et tidspunkt som passer
eller foreslår at det heller kjører på en maskin som alltid er på.

---

## Hva det koster

| | Pris |
|---|---|
| Selve programmet | gratis, åpen kildekode |
| Bilder (OpenAI) | noen ører per bilde, se https://openai.com/api/pricing |
| Tekst | inkludert i Claude Code- eller ChatGPT-abonnementet ditt |

Med fire innlegg i uka snakker vi småpenger i måneden på bilder. Taket du satte i
Del 3 gjør at det uansett ikke kan løpe løpsk.

---

## Trygghet, kort

- **Ingenting publiseres av seg selv.** Publisering er avslått fra start, og selv
  når du skrur den på, går bare de innleggene ut som du selv har planlagt.
- **Alt ligger på din egen maskin.** Utkast, bilder og merkevaren din. Ingen
  skytjeneste eier innholdet ditt.
- **Nøkkelen din deles aldri.** Den ligger i `.env`, som er satt opp til aldri å
  følge med hvis du deler mappa videre.

---

## Hvis noe går galt

Du trenger ikke feilsøke selv. Lim inn feilmeldingen til assistenten og skriv «hva
betyr dette, og kan du fikse det?». Det er nettopp det den er god til.

De vanligste tingene:

| Det skjer | Som regel fordi |
|---|---|
| «ukjent merke» | oppsettet ble ikke fullført, kjør `agent/setup.md` på nytt |
| Ingen bilder, bare tekst | OpenAI-nøkkelen mangler eller det er tomt på kontoen |
| Ingenting skjer på de dagene jeg valgte | maskinen var av eller sov, se Del 5 |
| Innleggene føles generiske | intervjuet gikk for fort. Be assistenten om å ta det på nytt, og vær konkret om hva dere ALDRI ville sagt |

---

## Kort oppsummert

1. Last ned mappa fra https://github.com/Englene/brandpost
2. Lag OpenAI-konto, sett et forbrukstak, kopier nøkkelen
3. Åpne mappa i Claude Code eller Codex, lim inn: *«Les agent/setup.md og gjør det den sier»*
4. Lim inn: *«Les agent/automate.md og sett opp automatikken»*
5. Les gjennom utkastene som dukker opp, og trykk publiser på dem du liker
