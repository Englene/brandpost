# Utvidelsesflater

Tre steder systemet er bevisst dumt, så du kan koble på ditt eget.

## Kontekst: `notes/`

Alt av `.md` under arbeidsmappas `notes/` blir råstoff. Første linje er tittelen,
de neste blir sammendraget. Ingen struktur kreves.

Vil du automatisere det, se [agent/kontekst.md](../agent/kontekst.md).

## Puls: `socials/pulse/<dato>.json`

Finnes fila, plukker hjernen den opp automatisk. Formatet:

```json
{
  "generated": "2026-07-25T08:00:00",
  "angles": [
    {"tema": "Folk spør om det samme tre ganger i uka",
     "hvorfor": "Tre kundesamtaler denne uka, uoppfordret"}
  ],
  "wins": ["Kunde fikk svar før fristen"]
}
```

Dette er stedet å koble på Slack, support-systemet eller salgsnotatene dine.
**Anonymiser før du skriver hit.** Innholdet kan ende opp i et offentlig innlegg.

## Kalender: `_events_by_day()` i `web/app.py`

Returnerer i dag en tom dict. Fyll den med

```python
{"2026-07-28": [{"tid": "09:00", "hva": "Webinar"}]}
```

så dukker møter og frister opp i kalendercellene, ved siden av innleggene.
Nyttig for å ikke publisere noe tonedøvt samme dag som noe annet skjer.
