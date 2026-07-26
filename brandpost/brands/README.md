# Merkevare-profiler

Én mappe per selskap. Generatoren laster alt herfra via `brandkit.load_brand(key)`,
så **å legge til et selskap er en drop-in mappe, ikke kode.**

## Struktur

```
brands/<key>/
  profile.toml                    maskin-tokens (palett, fonter, media, pilarer, enabled)
  merkevare/
    designstil.md                 visuell stil (til bilde-hjernen)
    skrivestil.md                 stemme + regler (blir MERKEVARESTEMME i prompten)
    arketype.md                   merke-personlighet
    strategi.md                   publikum + posisjon + innholdspilarene (rik prosa)
  bedrift/
    om-oss.md                     om selskapet
    produkter.md                  produkt + faktakuler (blir PRODUKTFAKTA i prompten)
    innholdspreferanser.md        miks, kadens, hva vi unngår, hard-sperrer
  media/
    logo.png  tilda.png  refs/…   merke-spesifikke bilder (fonter DELES via ../../assets/fonts/)
```

## Slik legger du til et selskap

1. Kopier `demo/` til `brands/<nytt-navn>/` og bytt innholdet.
2. `profile.toml`: sett `key`, `name`, `wordmark`, de 6 palett-hexene, media-stier og
   `[[pillar]]`-blokkene (stabile `id`-er). Sett `enabled = false` til du er klar.
3. Legg logo/tilda/ref-bilder i `media/`. Uten logo/refs degraderer motoren pent
   (typografi-kort fungerer fortsatt).
4. Skriv de 7 markdown-filene. Manglende fil er lov (blir tom seksjon).
5. Test: `.venv/bin/python -c "from brandpost import brandkit;
   print(brandkit.load_brand('<nytt-navn>'))"`.
6. `[linkedin].org_urn`: merkets egen firmaside, og det eneste som skiller to sider
   fra hverandre når de deler app og token. Finn ID-en i URL-en til firmasidas
   admin-panel (`linkedin.com/company/<ID>/admin/dashboard/`) og skriv den som
   `urn:li:organization:<ID>`. Automatisk oppslag av sidene du er admin på krever
   scopet `r_organization_admin`, som vi ikke har, så URL-en er veien.
7. Aktiver med `enabled = true`, eller kjør ad hoc: `BRANDPOST_BRANDS=<navn>`.

## Maskinlesbart vs prosa

- **profile.toml** (typet): palett-hex, fontfilnavn, media-stier, pilar-id-er. Brukes av
  renderer og rotasjons-motoren.
- **markdown**: all prosa. Mates KUN inn i hjernens system-prompt, aldri til renderer.
  Rediger fritt uten å røre kode.
