# Oppsett-prompt

Lim hele blokka under inn i Claude Code, Codex eller en annen kodeagent som står i
dette repoet. Den intervjuer deg og fyller ut merkevaren din, i stedet for at du
skal skrive TOML for hånd.

Den spør om få ting, og den spør om de riktige: motoren kan tegne og formulere, men
den kan ikke vite hva selskapet ditt faktisk mener.

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
   - Farger: seks hex-koder, eller nettadressen vår så du henter dem fra stilarket.
   - Logo: sti til en PNG, eller ingen. Uten logo blir kortene typografi-drevne,
     og det er et helt greit valg.
   - Språk innleggene skal skrives på.
   - Kadence: hvor mange innlegg i uka, og hvilke dager.

2. Sjekk om nettsida vår finnes. Gjør den det, HENT farger og fonter fra stilarket
   i stedet for å spørre meg. Vis meg hva du fant og la meg bekrefte. Ikke gjett
   på farger du ikke har sett.

3. Lag brandpost/brands/<vår-nøkkel>/ ved å kopiere demo-mappa og fylle den ut.
   Skriv markdown-filene i merkevare/ og bedrift/ med MITT innhold, ikke generiske
   formuleringer. Er et svar mitt vagt, spør igjen i stedet for å pynte på det:
   vage merkevarefiler gir vage innlegg, og det er den vanligste feilen.

4. Sett opp .env fra .env.example. Spør meg om nøklene du trenger. Skriv ALDRI
   nøkkelverdier tilbake til meg i chatten.

5. Kjør en første generering:
       python -m brandpost.cli run --brand <vår-nøkkel>
   Åpne bildet og LES teksten. Vurder den ærlig mot skrivestil-fila du nettopp
   skrev. Er den generisk, si det, og foreslå hva i merkevarefilene som må bli mer
   konkret. Ikke lever noe du selv synes er middelmådig.

6. Fortell meg til slutt:
   - Hva som ble laget og hvor det ligger.
   - Hvordan jeg ser på det (python main.py, så http://localhost:5050/some).
   - At ingenting publiseres før jeg setter LINKEDIN_ENABLED=1 og trykker.
   - Hva som gjenstår hvis jeg vil publisere automatisk.

Regler:
- Publiser ALDRI noe. Du foreslår, jeg bestemmer.
- Ikke rør brandpost/brands/demo/ eller minimal/: de er eksempler andre trenger.
- Kjør testene før du sier deg ferdig: python -m pytest -q
```
