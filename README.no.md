# brandpost

Et selvhostet system for å lage LinkedIn-innhold til en firmaside: det foreslår
innlegg, tegner bildene, og publiserer først når du har sagt ja.

Du beskriver merkevaren din i noen tekstfiler. Motoren bruker dem til å skrive
innlegg og tegne kort som ser ut som deg. Du godkjenner i et lokalt dashbord.
Ingenting går ut uten et klikk.

**[English version of this file](README.md)**

> **Har du aldri brukt GitHub før, og vet ikke hva en API-nøkkel er?**
> Start med [kom-i-gang-guiden](docs/kom-i-gang.no.md) i stedet. Den forutsetter
> ingenting, har skjermbilder, og tar deg fra null til innlegg som lager seg selv.
> Resten av denne fila går ut fra at du er litt vant til kode.

> **Om språk:** kodekommentarene er på norsk. Alt du trenger for å BRUKE prosjektet
> finnes på begge språk. `language` i merkeprofilen bestemmer hvilket språk
> innleggene skrives på, og oppsett-prompten intervjuer deg på det språket du
> skriver til den.

---

## Les dette først

**Nettleser-automatisering av LinkedIn er i strid med brukeravtalen deres.** Repoet
inneholder en Playwright-vei som logger inn som deg og lagrer utkast. Den finnes
fordi API-et ikke kan lage utkast, og den er nyttig, men den er ikke uten risiko:
kontoen din kan i verste fall begrenses. Det valget er ditt. API-veien er innenfor
avtalen. Se [nettleser mot API](#nettleser-mot-api) under.

**Ingenting publiseres av seg selv.** Publisering er avslått til du setter
`LINKEDIN_ENABLED=1`, og selv da skjer det bare når du trykker eller planlegger noe.

---

## Kom i gang

```bash
git clone https://github.com/Englene/brandpost && cd brandpost
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
chmod 600 .env
export BRANDPOST_ENV_FILE="$PWD/.env"          # motoren leser aldri andre .env-filer
export BRANDPOST_STATE_DIR="$PWD/.brandpost-state"
```

Åpne `.env` lokalt i en teksteditor og fyll inn det oppsettet du trenger. Ikke
send API-nøkler, tokens eller filinnholdet til en assistent/chat. Prosessmiljøet
vinner over fila, og produksjonsjobben må ha de to `BRANDPOST_*`-pekerne over.

Har du Claude Code-abonnement kan du hoppe over `ANTHROPIC_API_KEY` og sette
`BRANDPOST_MODEL_BACKEND=cli` i stedet. Da koster tekstgenereringen ingenting
ekstra. Bildenøkkel trengs uansett for motiver; uten den blir alle kortene
typografi-drevne, som også ser bra ut.

Lag ditt eget merke:

```bash
cp -R brandpost/brands/demo brandpost/brands/mitt-firma
```

Åpne `brandpost/brands/mitt-firma/profile.toml` og bytt navn, farger og pilarer.
Sett `language = "no"` hvis du vil ha norske innlegg. Skriv deretter om
markdown-filene i `voice/` og `company/`. **Det er de to som avgjør kvaliteten.**
Motoren kan ikke gjette hva selskapet ditt mener.

Generer og se på resultatet:

```bash
python -m brandpost.cli run --brand mitt-firma
python main.py                      # http://localhost:5050/some
```

Utkastene havner i `workspace/`. Peker du `BRANDPOST_WORKSPACE` et annet sted, må
den peke samme sted når du starter dashbordet, ellers ser du en tom side.

Vil du slippe å gjøre det for hånd, se [agent/](agent/): der ligger en prompt du
limer inn i Claude Code eller Codex, som intervjuer deg og fyller ut filene.

---

## Slik henger det sammen

```
workspace/notes/*.md ──┐
                       ├──► hjernen (tekstmodell) ──► forslag ──► dashbord ──► LinkedIn
merkefiler ────────────┘         │                                  ▲
                                 └──► bildemodell ──► kort          │
                                                              du godkjenner
```

- **Merkevaren** er tekstfiler, ikke kode. Ingen kodeendringer for et nytt merke.
- **Notatene er valgfrie.** Legg markdown i `workspace/notes/`, så bruker hjernen
  det som råstoff. Tom mappe fungerer, det blir bare mer generisk.
- **Bildene lages i to lag:** modellen tegner KUN innholdet i merkefargene, og
  koden legger overskrift, logo og ordmerke oppå. Den delingen er grepet som gjør
  at AI-delen leses som typografi og ikke som et innlimt bilde.
- **Planen** fordeler temaer utover uka og roterer mellom pilarene dine, så du ikke
  skriver det samme innlegget om igjen.

---

## Nettleser mot API

To veier, og de kan ikke det samme. Det er hele grunnen til at begge finnes.

| | API | Nettleser |
|---|---|---|
| Publisere nå | ja | ja |
| Publisere til avtalt tid | ja, vi holder tida | ja, LinkedIn holder tida |
| Lage et ekte utkast i LinkedIn | **nei** | ja |
| Lese hva som er publisert | ja | ja |
| Innenfor brukeravtalen | ja | **nei** |
| Krever godkjenning fra LinkedIn | ja, ukers ventetid | nei |
| Virker dag én | nei | ja |

API-et godtar bare `PUBLISHED` når et innlegg opprettes. Det finnes ingen
utkast-tilstand. Vil du at et utkast skal ligge i LinkedIn og vente på deg der, er
nettleser-veien eneste mulighet.

De to koordineres: et innlegg som er planlagt inne i LinkedIn merkes, og den
automatiske publiseringen rører det aldri. Uten det ville samme innlegg gått ut to
ganger, uten at noe så ut som en feil.

**Anbefaling:** begynn med nettleser-veien mens du venter på API-tilgang, og bytt
når den er innvilget.

---

## Skaffe API-tilgang

Du trenger **Community Management API** for å publisere til en firmaside. Det
forutsetter et registrert selskap med en verifisert LinkedIn-side.

1. Lag en app på [linkedin.com/developers](https://www.linkedin.com/developers/apps)
   og knytt den til firmasida di.
2. Be om produktet **Community Management API**. Regn med dager til uker, og at du
   må beskrive hva appen skal gjøre.
3. Legg til `http://localhost:8765/callback` som redirect-URL.
4. Sett `LINKEDIN_CLIENT_ID` og `LINKEDIN_CLIENT_SECRET` direkte i den lokale
   miljøfila som `BRANDPOST_ENV_FILE` peker på (aldri i chat).
5. Kjør engangs-innloggingen:
   ```bash
   python -m brandpost.linkedin_auth
   ```
   Den åpner nettleseren, fanger svaret på localhost, og skriver ut token du limer
   inn i `.env`.
6. Finn firmasidas ID i admin-URL-en
   (`linkedin.com/company/<ID>/admin/dashboard/`) og sett
   `org_urn = "urn:li:organization:<ID>"` i merkeprofilen din.

Scopene du trenger er `w_organization_social` (publisere) og
`r_organization_social` (lese egne innlegg).

**Blir du avslått,** eller har du ingen firmaside: nettleser-veien virker fortsatt,
og hele genereringsdelen krever ingen LinkedIn-tilgang i det hele tatt.

---

## Skrive som et menneske

Motoren er skrevet for selskaper: «vi», produktfakta, sperre mot salgspåstander.
En personlig profil trenger den motsatte aksen, og på LinkedIn er den forskjellen
verdt mye: personlige profiler får rundt 65 % av feed-allokeringen, firmasider
rundt 5 %.

Sett dette i merkeprofilen din:

```toml
[voice]
mode = "person"
```

Da bytter systemprompten fem ting: rollen (førsteperson entall i stedet for
innholdssjef), taggeregelen (du tagger ikke deg selv), fakta-seksjonen (erfaringer
i stedet for produktark), konfidensialiteten, og den legger til fire harde krav.
Kravene er ikke stil, de er det som avgjør om innlegget blir sett: forankring i en
faktisk hendelse med dato, oversettelse så folk uten fagbakgrunn forstår det, ingen
pitch, og ingen navn på kunder eller kolleger. Alt annet, altså språkreglene,
LinkedIn-algoritmen, kildekravet og pilar-rotasjonen, er identisk for begge.

**Egne bilder i stedet for generert grafikk.** En privatperson som poster designet
infografikk på hvert innlegg leser som en kampanje. Legg en bildebank i
`<workspace>/socials/bevis.json`, så tilbys bildene til hjernen, som setter
`bevis_id` på utkastene der de passer:

```json
{"bilder": {"dashbord-1": {
  "sti": "/…/skjermbilde.png", "sett": true, "sensitiv": false, "egnet": true,
  "beskrivelse": "Et dashbord med fire kolonner og en feilmelding øverst"}}}
```

Godkjenningen er fail-closed: alle tre flaggene må være positive, og et manglende
felt betyr nei. Hvem som fyller banken og hva som regnes som sensitivt er ditt
valg, fordi det avhenger av hva du jobber med. `brandpost.bildebank` leser den
bare. Personlige utkast åpner dessuten feed-komposeren i stedet for firmasidas,
så `linkedin_draft` lagrer dem på profilen din.

---

## Automatisk drift

Publiseringen er et mekanisk skript og hører hjemme i en vanlig tidsstyrt jobb, ikke
i en agent-kjøring. Den ser etter innlegg du har planlagt og legger ut de som har
forfalt:

```bash
python -m brandpost.publisher            # kjør hvert kvarter
python -m brandpost.publisher --dry-run  # se hva som ville skjedd
```

Den nekter å publisere noe som er mer enn seks timer på etterskudd. Et innlegg som
skulle ut i går morges skal ikke plutselig dukke opp i dag uten at et menneske ser
på det.

*Genereringen* er derimot skjønn, og passer som en agent-kjøring. Se
[agent/generate.md](agent/generate.md).

**For å sette opp alt sammen:** lim [agent/automate.md](agent/automate.md) inn i
kodeagenten din. Den finner ut hvilken plattform du er på, skriver jobbfilene til
`deploy/`, installerer dem, og beviser deretter at hver enkelt kjører i stedet for
å fortelle deg at den burde.

---

## Hva som kan bli bedre

Ærlig liste, i den rekkefølgen jeg ville tatt det:

- **Personlig profil via API-et.** Utkast til personprofil virker allerede (se
  «Skrive som et menneske» under), men det går gjennom nettleseren. Automatisk
  publisering til personprofil er et annet LinkedIn-produkt («Share on LinkedIn»,
  scope `w_member_social`) som er selvbetjent og godkjennes på dager.
- **Ytelsesmåling per pilar.** Engasjementstallene hentes inn, men brukes aldri til
  å vri innholdet mot det som faktisk virker.
- **AI-motiv på alle karusell-slides.** I dag får bare forsiden et motiv, fordi åtte
  uavhengig genererte bilder lett leses som åtte ulike serier. Løses det, blir
  karusellene mye sterkere.
- **Flere plattformer.** Alt er bygget rundt LinkedIn. Motoren er ikke det.
- **Kontekst-tilkoblinger.** Notatmappa er bevisst dum. En kobling mot kalender,
  e-post eller chat ville gitt hjernen ferskere råstoff. Se
  [docs/extending.md](docs/extending.md).
- **Redigering av enkelt-slides** i dashbordet.

---

## Lisens

MIT. Se [LICENSE](LICENSE).
