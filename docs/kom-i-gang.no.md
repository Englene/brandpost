# Kom i gang, fra helt null

Denne guiden går ut fra at du aldri har brukt GitHub, ikke vet hva en API-nøkkel
er, og ikke skriver kode. Det går helt fint. Du skal ikke programmere noe. Du skal
laste ned en mappe og la en KI-assistent gjøre resten.

Sett av rundt en halvtime første gang.

**Hva du sitter igjen med:** ferdige LinkedIn-innlegg til firmasiden din, med
bilde og tekst, som dukker opp av seg selv på de dagene du har valgt. Du leser
gjennom, og trykker publiser på det du liker. Ingenting går ut uten at du sier ja.

> **Du trenger ingen API-nøkkel for å komme i gang.** Del 1 til 3 fungerer med
> abonnementet du allerede har. Nøkler er noe du eventuelt legger til i Del 4,
> hvis du vil ha AI-genererte bilder.

---

## Del 0: Skaff deg en assistent først

Alt det tekniske gjøres av en KI-assistent som kan jobbe med filer på maskinen
din. Du trenger **én** av disse, og det er verdt å ta den først, for den hjelper
deg med alt det andre.

| | Hvor |
|---|---|
| **Claude Code** (enklest) | https://claude.ai/download |
| **Codex** | følger med ChatGPT-abonnement |

Last ned **appen**, ikke noe annet. Du skal ikke innom noe som heter terminal
eller kommandolinje. Åpne appen, logg inn, og du har et chattevindu som i tillegg
kan lese og skrive filer på maskinen din.

**Det er dette abonnementet som skriver innleggene dine.** Assistenten leser
merkevaren din og formulerer teksten selv. Du betaler altså ikke for tekst to
ganger.

### La assistenten sjekke maskinen din

Programmet er skrevet i Python. Det er sannsynligvis ikke installert på maskinen
din fra før, og du skal ikke installere det selv. Skriv dette til assistenten:

```
Jeg skal sette opp et program som trenger Python 3.11 eller nyere. Sjekk om jeg
har det, og installer det for meg hvis jeg ikke har. Jeg er ikke teknisk, så
forklar hva du gjør underveis.
```

Den ordner det. Spør den om passordet ditt til maskinen underveis, er det normalt
ved installasjon av programmer. Du skriver det i det vanlige passordvinduet fra
operativsystemet, aldri i chatten.

> **Er du på Windows?** Alt i denne guiden virker, men noen kommandoer ser litt
> annerledes ut. Si «jeg er på Windows» til assistenten med en gang.

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

> **Enklere alternativ:** be assistenten om det i stedet:
> «Last ned https://github.com/Englene/brandpost til Dokumenter og åpne mappa.»

---

## Del 2: Sett det opp

Åpne assistenten fra Del 0 i mappa du lastet ned: i Claude Code åpner du mappa i
appen, i Codex peker du den på mappa.

Så limer du inn dette, ordrett:

```
Les agent/setup.md i denne mappa og gjør det den sier. Jeg har ikke gjort dette
før, så forklar underveis og spør meg om én ting av gangen. Sjekk først at alt
som trengs er installert, og fiks det som mangler.
```

Assistenten intervjuer deg nå om firmaet ditt: hva dere gjør, hvem dere snakker
til, hva dere vil være kjent for, og hvordan dere høres ut.

**Dette er den delen som betyr noe.** Motoren kan tegne og formulere, men den kan
ikke vite hva firmaet ditt mener. Bruk et kvarter på svarene, så blir innleggene
deretter. Det beste spørsmålet den stiller er hva dere ALDRI ville sagt. Svar
ærlig på det, så treffer resten bedre.

Når intervjuet er ferdig, be om et prøveinnlegg:

```
Lag tre utkast til meg nå, så jeg får se hvordan det ser ut.
```

Dette virker uten noen API-nøkkel. Kortene tegnes på maskinen din, med
merkefargene og skrifttypene dine.

---

## Del 3: Se og godkjenne innleggene

Utkastene havner ikke i en app eller på en nettside du logger inn på. De ligger
som filer på din egen maskin, og du ser på dem i et **dashbord** som også kjører
på din egen maskin.

### Hva «localhost» betyr

Be assistenten om dette:

```
Start dashbordet, og gi meg adressen jeg skal åpne.
```

Den svarer med en adresse som ser slik ut:

```
http://localhost:5050
```

Den limer du inn i nettleseren, akkurat som en vanlig nettadresse.

`localhost` betyr **denne maskinen**. Det er ikke en side på internett. Ingen
andre kan åpne den, ikke engang om de har adressen, for den peker på maskinen som
skriver den inn. Tallet `5050` er bare en dør inn til det ene programmet, sånn at
flere programmer kan kjøre samtidig uten å krasje.

Der ser du en kalender med innleggene dine. Du kan lese, rette teksten, slette
det du ikke liker, og planlegge når noe skal ut. **Det er her du godkjenner.**

### Det ene som overrasker folk

Dashbordet finnes bare så lenge programmet kjører. Lukker du vinduet assistenten
startet det i, eller skrur av maskinen, blir adressen død og nettleseren sier
«kan ikke nås». Innholdet ditt er trygt, det ligger i filene, men vinduet inn til
det er borte.

Du har to valg:

- **Starte det når du trenger det.** Be assistenten «start dashbordet» hver gang.
  Helt greit hvis du ser på innlegg én gang i uka.
- **La det alltid kjøre.** Det setter Del 5 opp for deg, og da er adressen der
  bestandig, også etter en omstart.

> Vil du åpne dashbordet fra mobilen eller en annen maskin i huset, si det til
> assistenten. Da må det startes på en annen måte, og du bør vite at dashbordet
> ikke har passord: alle på samme nettverk kommer inn. På et hjemmenettverk er
> det som regel greit, på en kafé er det ikke det.

---

## Del 4: Vil du ha AI-genererte bilder? (valgfritt)

Så langt har kortene vært tegnet av programmet selv: din skrifttype, dine farger,
teksten stor og tydelig. Det er ofte det som fungerer best på LinkedIn, og mange
trenger aldri noe mer.

Vil du i tillegg ha **illustrasjoner laget av AI**, må programmet spørre en
bildetjeneste om hjelp. Det er her, og bare her, du trenger en API-nøkkel.

### Hva en API-nøkkel er

Det er en lang tekststreng som begynner med `sk-` og fortsetter med rundt hundre
tilfeldige tegn:

```
sk-proj-DETTE-ER-BARE-ET-EKSEMPEL-EN-EKTE-NOKKEL-ER-MYE-LENGER-OG-TILFELDIG
```

Den forteller tjenesten hvem som spør, og hvem regningen går til. Tre ting:

- **Den er som et passord.** Alle som har den, kan bruke den og du får regningen.
  Aldri lim den inn i en chat, en e-post eller et dokument du deler.
- **Den vises bare én gang.** Kopier den med det samme. Mister du den, lager du en ny.
- **Den koster per bruk.** Ikke et abonnement, men noen ører per bilde.

### Slik henter du en

Bildene lages av OpenAI, samme selskap som ChatGPT. Merk at dette er en **egen
konto med egen betaling**. Har du ChatGPT Plus, dekker det ikke dette.

**1. Lag konto**
https://platform.openai.com/signup

**2. Legg inn betaling og sett et tak**
https://platform.openai.com/settings/organization/billing/overview
Fyll på et lite beløp, for eksempel 10 dollar. Det holder lenge. Finn deretter
**Limits** i menyen på samme side og sett en månedlig grense, så kan det aldri
løpe løpsk.

**3. Lag nøkkelen**
https://platform.openai.com/api-keys
Trykk **Create new secret key**, gi den navnet «brandpost», og kopier den med en
gang.

**4. Lagre den lokalt, ikke i chat**

Åpne miljøfila på din egen maskin, legg nøkkelen etter `OPENAI_API_KEY=`, lagre
og kjør `chmod 600 <miljøfil>`. Sett `BRANDPOST_ENV_FILE` til akkurat denne fila.
En assistent kan gjerne forklare hvor fila ligger, men du skal aldri sende selve
nøkkelen eller innholdet i miljøfila til den. `.env` skal heller aldri deles,
ZIP-es eller legges i Git.

> Får du en side som ber deg «verifisere at du er et menneske», er det bare
> OpenAIs vanlige bot-sjekk. Kryss av og fortsett.

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

### LinkedIn-innlogging uten å vise tokenene

Når firmasiden har fått API-tilgang, legger du LinkedIn-appens klient-ID og
klienthemmelighet i den lokale miljøfila og kjører:

```bash
BRANDPOST_ENV_FILE=/absolutt/sti/til/.env python -m brandpost.linkedin_auth
```

Kommandoen nekter å starte uten den eksplisitte filpekeren. Access- og
refresh-token lagres atomisk bare i denne fila, som settes til filmodus `0600`;
verdiene skrives aldri til terminal eller logger. Du får en liste over
administrator-sidenes ikke-hemmelige URN-er. Velg riktig URN og legg den i
`[linkedin].org_urn` i det aktuelle merkets `profile.toml` — ikke som en global
miljøverdi. Ikke lim miljøfila, nøkler eller tokenverdier inn i chat.

Dashboardets muterende kall kan låses til kjente adresser med en kommadelt liste,
for eksempel `BRANDPOST_ALLOWED_ORIGINS=http://127.0.0.1:5050,http://localhost:5050`.
Når den er satt, må både nettleserens `Origin` og forespørselens Host/base-adresse
stå i lista. Dermed holder det ikke for en angriper å få en falsk Origin og Host
til å ligne på hverandre. En ugyldig liste stopper alle POST-kall.

### De to måtene å planlegge på

- **Claude Code** har *routines*: faste kjøringer på et klokkeslett. Be
  assistenten: «Lag en routine som kjører agent/generate.md hver mandag klokka 7.»
- **Codex** har *automations*, som er det samme. Du lager en ny automation, velger
  prosjektet, og skriver instruksen den skal kjøre.

Begge deler forutsetter at maskinen er på. Sover laptopen klokka sju om morgenen,
skjer det ingenting. Si det til assistenten, så velger den et tidspunkt som passer.

---

## Hva det koster

| | Pris |
|---|---|
| Selve programmet | gratis, åpen kildekode |
| Teksten i innleggene | inkludert i Claude- eller ChatGPT-abonnementet ditt |
| Kort tegnet av programmet | gratis |
| AI-bilder (valgfritt, Del 4) | noen ører per bilde, se https://openai.com/api/pricing |

Med andre ord: har du allerede et abonnement, koster det deg ingenting å prøve.

---

## Trygghet, kort

- **Ingenting publiseres av seg selv.** Publisering er avslått fra start, og selv
  når du skrur den på, går bare de innleggene ut som du selv har planlagt.
- **Alt ligger på din egen maskin.** Utkast, bilder og merkevaren din.
- **Nøkkelen din deles aldri.** Den ligger i `.env`, som er satt opp til aldri å
  følge med hvis du deler mappa videre.

---

## Hvis noe går galt

Du trenger ikke feilsøke selv. Lim inn feilmeldingen til assistenten og skriv «hva
betyr dette, og kan du fikse det?». Det er nettopp det den er god til.

| Det skjer | Som regel fordi |
|---|---|
| «Siden kan ikke nås» på localhost | dashbordet kjører ikke. Be assistenten starte det, se Del 3 |
| «ukjent merke» | oppsettet ble ikke fullført, kjør `agent/setup.md` på nytt |
| Kortene har tekst, men ingen illustrasjon | helt normalt uten API-nøkkel, se Del 4 |
| Ingenting skjer på de dagene jeg valgte | maskinen var av eller sov, se Del 5 |
| Innleggene føles generiske | intervjuet gikk for fort. Be assistenten ta det på nytt, og vær konkret om hva dere ALDRI ville sagt |

---

## Kort oppsummert

1. Skaff Claude Code eller Codex, og be den installere Python (Del 0)
2. Last ned mappa fra https://github.com/Englene/brandpost
3. Lim inn: *«Les agent/setup.md og gjør det den sier»*, og svar på spørsmålene
4. Be om dashbordet, og åpne `http://localhost:5050`. Det er her du godkjenner
5. Vil du ha AI-bilder, hent en OpenAI-nøkkel (Del 4). Ellers hopp over
6. Lim inn: *«Les agent/automate.md og sett opp automatikken»*
