# brandpost

Et selvhostet system for å lage LinkedIn-innhold til en firmaside: det foreslår
innlegg, tegner bildene, og publiserer først når du har sagt ja.

Du fyller ut merkevaren din i noen tekstfiler. Motoren bruker dem til å skrive
innlegg og tegne kort som ser ut som deg. Du godkjenner i et dashbord. Ingenting
går ut uten et klikk.

> **English:** self-hosted LinkedIn content engine for company pages. Brand voice
> lives in plain text files, posts are generated and reviewed in a local dashboard,
> and nothing publishes without an explicit approval. The code comments and the
> default brand are Norwegian; set `language` in your brand profile to change the
> language of generated posts.

---

## Les dette først

**Nettleser-automatisering av LinkedIn er i strid med brukeravtalen deres.** Denne
kildekoden inneholder en Playwright-vei som logger inn som deg og lagrer utkast.
Den finnes fordi API-et ikke kan lage utkast, og den er nyttig, men den er ikke uten
risiko: kontoen din kan i verste fall begrenses. Du velger selv om du bruker den.
API-veien er innenfor avtalen. Se [nettleser mot API](#nettleser-mot-api) under.

**Ingenting publiseres av seg selv.** Publisering er avslått til du setter
`LINKEDIN_ENABLED=1`, og selv da skjer det bare når du trykker eller planlegger noe.

---

## Kom i gang

```bash
git clone <dette-repoet> brandpost && cd brandpost
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # fyll inn minst ANTHROPIC_API_KEY + én bildenøkkel
```

Lag ditt eget merke:

```bash
cp -R brandpost/brands/demo brandpost/brands/mitt-firma
```

Åpne `brandpost/brands/mitt-firma/profile.toml` og bytt navn, farger og pilarer.
Skriv deretter om markdown-filene i `merkevare/` og `bedrift/`. **Det er de to
tingene som avgjør kvaliteten**: motoren kan ikke gjette hva selskapet ditt mener.

Generer og se på resultatet:

```bash
python -m brandpost.cli run --brand mitt-firma
python main.py                      # http://localhost:5050/some
```

Har du ikke lyst til å gjøre dette for hånd, se [agent/](agent/): der ligger en
prompt du limer inn i Claude Code eller Codex, som intervjuer deg og fyller ut
filene for deg.

---

## Slik henger det sammen

```
notes/*.md ──┐
             ├──► hjernen (tekstmodell) ──► forslag ──► dashbord ──► LinkedIn
merkevare ───┘         │                                   ▲
                       └──► bildemotor ──► kort            │
                                                     du godkjenner
```

- **Merkevaren** er tekstfiler, ikke kode. Ingen kodeendringer for et nytt merke.
- **Notatene** er valgfrie. Legg markdown i `notes/`, så bruker hjernen det som
  råstoff. Tom mappe fungerer, det blir bare mer generisk.
- **Bildene** lages i to lag: modellen tegner KUN innholdet i merkefargene, og
  koden legger overskrift, logo og ordmerke oppå. Det er grepet som gjør at
  AI-delen ser ut som typografi og ikke som et innlimt bilde.
- **Planen** fordeler temaer utover uka og roterer mellom pilarene dine, så du ikke
  skriver om det samme hver gang.

---

## Nettleser mot API

To veier, og de kan ikke det samme. Dette er hele grunnen til at begge finnes.

| | API | Nettleser |
|---|---|---|
| Publisere nå | ja | ja |
| Publisere til avtalt tid | ja, systemet holder tida selv | ja, LinkedIn holder tida |
| Lage et ekte utkast i LinkedIn | **nei** | ja |
| Lese hva som er publisert | ja | ja |
| Innenfor brukeravtalen | ja | **nei** |
| Krever godkjenning fra LinkedIn | ja, ukers ventetid | nei |
| Virker dag én | nei | ja |

API-et godtar bare `PUBLISHED` når et innlegg opprettes. Det finnes ingen
utkast-tilstand. Vil du at et utkast skal ligge i LinkedIn og vente på deg der,
er nettleser-veien eneste mulighet.

De to koordineres: et innlegg som er planlagt inne i LinkedIn merkes, og den
automatiske publiseringen rører det aldri. Uten det ville samme innlegg gått ut
to ganger, uten at noe så ut som en feil.

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
4. Sett `LINKEDIN_CLIENT_ID` og `LINKEDIN_CLIENT_SECRET` i `.env`.
5. Kjør engangs-innloggingen:
   ```bash
   python -m brandpost.linkedin_auth
   ```
   Den åpner nettleseren, fanger svaret på localhost, og skriver ut token du limer
   inn i `.env`.
6. Finn firmasidas ID i URL-en til admin-panelet
   (`linkedin.com/company/<ID>/admin/dashboard/`) og sett
   `org_urn = "urn:li:organization:<ID>"` i merkeprofilen din.

Scopene du trenger er `w_organization_social` (publisere) og
`r_organization_social` (lese egne innlegg).

**Blir du avslått,** eller har du ingen firmaside: nettleser-veien virker fortsatt,
og hele genereringsdelen krever ingen LinkedIn-tilgang i det hele tatt.

---

## Automatisk drift

Publiseringen er et mekanisk skript og bør kjøres som en vanlig tidsstyrt jobb, ikke
som en agent. Den ser etter innlegg du har planlagt og legger ut de som har forfalt:

```bash
python -m brandpost.publisher            # kjør hvert kvarter
python -m brandpost.publisher --dry-run  # se hva som ville skjedd
```

Den nekter å publisere noe som er mer enn seks timer på etterskudd. Et innlegg som
skulle ut i går skal ikke plutselig dukke opp i dag uten at et menneske ser på det.

Selve *genereringen* er derimot skjønn, og passer som en agent-kjøring. Se
[agent/generering.md](agent/generering.md).

---

## Hva som kan bli bedre

Ærlig liste over det som mangler, i den rekkefølgen jeg ville tatt det:

- **Personlig profil som mål.** I dag støttes kun firmasider. Personlig profil er et
  annet LinkedIn-produkt («Share on LinkedIn», scope `w_member_social`) som er
  selvbetjent og godkjennes på dager. For de fleste ville det senket terskelen mest.
- **Ytelsesmåling per pilar.** Engasjementstallene hentes inn, men brukes ikke til å
  vri innholdet mot det som faktisk virker.
- **AI-motiv på alle karusell-slides.** I dag får bare forsiden et motiv, fordi åtte
  uavhengig genererte bilder lett ser ut som åtte ulike serier. Løses det, blir
  karusellene mye sterkere.
- **Flere plattformer.** Alt er bygget rundt LinkedIn. Motoren er ikke det.
- **Kontekst-tilkoblinger.** `notes/` er bevisst dum. En kobling mot kalender,
  e-post eller Slack ville gitt hjernen ferskere råstoff. Se
  [docs/utvidelser.md](docs/utvidelser.md).
- **Redigering av enkelt-slides** i dashbordet.

---

## Lisens

MIT. Se [LICENSE](LICENSE).
