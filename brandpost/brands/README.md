# Brands

One folder per company. Nothing in the code knows any brand: everything is read
from these files, so adding a brand needs zero code changes.

```
brands/<key>/
  profile.toml        colours, fonts, pillars, LinkedIn page   (required)
  media/logo.png      optional. Without it, cards go typography-driven
  voice/writing.md    voice and rules            <- decides quality
  voice/design.md     visual style
  voice/archetype.md  personality
  voice/strategy.md   positioning and cadence
  company/about.md    who you are
  company/products.md what you can actually claim <- decides quality
  company/rules.md    what can never be said
```

Two examples ship with the repo: `demo/` is filled in, `minimal/` is the smallest
thing that works (no logo, no pillars, no prose). Compare them to see what each
piece buys you.

## Adding a company

1. `cp -R demo brands/<your-name>` and change the contents.
2. `profile.toml`: set `key`, `name`, `wordmark`, `language`, the six palette hex
   values, and the `[[pillar]]` blocks. Keep `enabled = false` until you are ready.
3. Put a logo in `media/`, or delete the `[media]` section. Without a logo the
   engine degrades cleanly to typography cards.
4. Rewrite the markdown. `voice/writing.md` and `company/products.md` are the two
   that actually drive quality; the rest is supporting detail. A missing file is
   fine and becomes an empty section.
5. Check that it loads:
   ```bash
   python -c "from brandpost import brandkit; print(brandkit.load_brand('<your-name>'))"
   ```
6. `[linkedin].org_urn` is your company page, and the only thing separating two
   pages that share an app and token. Find the ID in your admin URL
   (`linkedin.com/company/<ID>/admin/dashboard/`) and write it as
   `urn:li:organization:<ID>`. Automatic lookup of the pages you administer needs
   the `r_organization_admin` scope, which this app does not request, so the URL is
   the way.
7. `[linkedin].handle` is the `@handle` written into the post text to tag your page.
   Look it up in LinkedIn's own mention list: type `@` and see which name gives
   exactly one match. Leave it empty and no tag is written, which is the safe
   default: guessing tags whichever company happens to have that name.
8. Enable with `enabled = true`, or run ad hoc: `BRANDPOST_BRANDS=<name>`.

Norwegian folder names (`merkevare/`, `bedrift/`) are still accepted, so profiles
made before the rename keep working.

## Machine-readable vs prose

- **profile.toml** (typed): palette hex, font filenames, media paths, pillar ids.
  Used by the renderer and the rotation engine.
- **markdown**: all prose. Fed only into the brain's system prompt, never to the
  renderer. Edit freely without touching code.
