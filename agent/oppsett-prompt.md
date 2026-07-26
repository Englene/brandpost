# Oppsett-prompt

Lim hele blokka under inn i Claude Code, Codex eller en annen kodeagent som står i
dette repoet. Den intervjuer deg og fyller ut merkevaren din, i stedet for at du
skal skrive TOML for hånd.

Den spør om få ting, og den spør om de riktige: motoren kan tegne og formulere, men
den kan ikke vite hva selskapet ditt faktisk mener.

Prompten er testet ved å kjøre den for et oppdiktet selskap fra bunnen av. Punktene
som virker overdrevent detaljerte er det fordi noen faktisk gikk i den fella.

---

```
Du skal sette opp dette repoet for mitt selskap. Les README.md og
brandpost/brands/README.md først, så du vet hvordan merkevare-laget fungerer.

Jobb slik:

1. INTERVJU MEG, ett spørsmål av gangen. Ikke en punktliste. Gi din egen anbefaling
   sammen med hvert spørsmål, og begrunn den kort. Det du trenger å få vite:

   - Hva selskapet gjør, i én setning, slik en kunde ville sagt det.
   - Hvem innleggene skal treffe, og hva de allerede tror som er feil.
   - Tre til seks PILARER: temaene vi vil bli kjent for. Foreslå dem selv ut fra
     svarene mine, og la meg korrigere. Dette er det viktigste valget.
   - Stemme: to eller tre setninger om hvordan vi høres ut. Be om et eksempel på
     noe vi ALDRI ville sagt; det avgrenser bedre enn ti adjektiver.
   - TRE TIL FEM TALL vi kan stå for offentlig: pris, responstid, volum, hva noe
     koster å miste. Uten tall blir innleggene påstander. Har vi ingen ennå, si
     det, og skriv en eksplisitt sperre mot oppdiktede tall i bedrift/produkter.md.
   - Nettadressen vår, hvis vi har en. Spør direkte, ikke gjett på domenet.
   - LinkedIn-handlen vår, eller «ingen ennå». Uten den skal det ikke skrives
     noen @-tagg i innleggene.
   - Logo: sti til en PNG, eller ingen. Uten logo blir kortene typografi-drevne,
     og det er et helt greit valg.
   - Språk innleggene skal skrives på.
   - Kadence: hvor mange innlegg i uka, og hvilke dager.

2. Har vi en nettside, HENT farger fra stilarket i stedet for å spørre meg om hex.
   Men BEKREFT FØRST at domenet faktisk er vårt: et gjettet domene tilhører som
   regel noen andre, og da henter du en fremmed bedrifts palett. Vis meg hva du
   fant og la meg si ja.

   Fonter kan du IKKE hente fra sida uten videre: `fonts.display` må være et
   filnavn som ligger i brandpost/assets/fonts/. Tre følger med (Fraunces, Inter,
   YoungSerif). Vil vi ha en annen, må .ttf-fila legges der først.

3. Lag brandpost/brands/<vår-nøkkel>/ ved å kopiere demo-mappa og fylle den ut.

   RYDD ETTER KOPIERINGEN: demo-mappa inneholder Demo Labs sin logo. Har jeg ikke
   levert en egen, SLETT media/logo.png og fjern [media]-seksjonen. Ellers får
   merket vårt et fremmed selskaps logo på hvert eneste kort.

   Skriv markdown-filene i merkevare/ og bedrift/ med MITT innhold, ikke generiske
   formuleringer. Er et svar mitt vagt, spør igjen i stedet for å pynte på det:
   vage merkevarefiler gir vage innlegg, og det er den vanligste feilen.

   Sett BRANDPOST_POST_DAYS i .env til dagene jeg valgte (0 = mandag). Det feltet
   finnes ikke i profile.toml, så uten dette blir kadence-svaret mitt liggende
   ubrukt.

4. Sett opp .env fra .env.example. Spør meg om nøklene du trenger. Skriv ALDRI
   nøkkelverdier tilbake til meg i chatten.

   Har jeg Claude Code-abonnement, sett BRANDPOST_MODEL_BACKEND=cli i stedet for
   å be om ANTHROPIC_API_KEY: da koster tekstgenereringen ingenting ekstra. En
   bildenøkkel trengs uansett for motiver; uten den blir det typografi-kort.

5. Kjør en første generering. Bruk SAMME BRANDPOST_WORKSPACE som du senere starter
   dashbordet med, ellers ser jeg en tom side:

       BRANDPOST_WORKSPACE=./workspace python -m brandpost.cli run --brand <nøkkel>

   Åpne bildet og LES teksten. Gå gjennom anti-mønstrene i skrivestil.md LINJE FOR
   LINJE. Modellen bryter dem jevnlig i åpningssetningen selv når fila er tydelig,
   særlig «ikke X, men Y»-figuren. Er den brutt, regenerer med en konkret rettelse.

   Vurder ærlig om teksten er god eller bare grammatisk riktig. Er den generisk,
   si det, og foreslå hva i merkevarefilene som må bli mer konkret. Ikke lever noe
   du selv synes er middelmådig.

6. Fortell meg til slutt:
   - Hva som ble laget og hvor det ligger.
   - Hvordan jeg ser på det (BRANDPOST_WORKSPACE=./workspace python main.py, så
     http://localhost:5050/some).
   - At ingenting publiseres før jeg setter LINKEDIN_ENABLED=1 og trykker.
   - Hva som gjenstår hvis jeg vil publisere automatisk.

Regler:
- Publiser ALDRI noe. Du foreslår, jeg bestemmer.
- Ikke rør brandpost/brands/demo/ eller minimal/: de er eksempler andre trenger.
- Kjør testene før du sier deg ferdig: python -m pytest -q
```
