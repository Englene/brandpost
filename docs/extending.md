# Extension points

Three places the system is deliberately dumb, so you can plug in your own.

## Context: `workspace/notes/`

Every `.md` file under the workspace's `notes/` folder becomes raw material. The
first line is the title, the following lines the summary. No structure required.

To automate it, see [agent/context.md](../agent/context.md).

## Pulse: `socials/pulse/<date>.json`

If the file exists, the brain picks it up automatically. The format:

```json
{
  "generated": "2026-07-25T08:00:00",
  "angles": [
    {"tema": "People ask the same thing three times a week",
     "hvorfor": "Three customer calls this week, unprompted"}
  ],
  "wins": ["Customer got an answer before the deadline"]
}
```

This is where you connect Slack, your support system or your sales notes.
**Anonymise before writing here.** The content can end up in a public post.

## Calendar: `_events_by_day()` in `web/app.py`

Currently returns an empty dict. Fill it with

```python
{"2026-07-28": [{"tid": "09:00", "hva": "Webinar"}]}
```

and meetings or deadlines appear in the calendar cells next to your posts. Useful
for not publishing something tone-deaf on the same day as something else.

## Your brand in a private repo

`brandpost` ships with `demo/` and `minimal/`. Your real brand, the strategy, the
voice, the logos, is business material and usually does not belong in a public
package you also pull updates from.

Point `BRANDPOST_BRANDS_DIR` at your own directory:

```bash
pip install "brandpost[all] @ git+https://github.com/Englene/brandpost"
export BRANDPOST_BRANDS_DIR=~/my-brands
export BRANDPOST_BRANDS=mycompany
brandpost run --brand mycompany
```

The variable takes several directories separated by `:`, like `PATH`, and yours
win on name collision, so you can override `demo` with your own version. The
bundled brands stay available either way.

A private setup then holds only what is actually yours:

```
my-brands/
  mycompany/
    profile.toml
    voice/{strategy,writing,design,archetype}.md
    company/{about,products,rules}.md
    media/logo.png
```

## Publishing from something else: `publish --json`

`brandpost publish --post N --json` writes exactly one JSON object to stdout and
nothing else, so another system can drive publishing and report the outcome back
to a human:

```json
{"ok": true, "posted": true, "dry_run": false, "url": "https://...",
 "date": "2026-07-28", "nr": 2, "brand_name": "Demo Labs", "headline": "..."}
```

Exit code 0 means the command was **understood**, including dry-run and "already
published". Exit 1 means a usage error or a crash. The distinction matters: it
lets the caller tell "the system said no" apart from "the system is broken", and
say the right thing to the person waiting for an answer.

`--vault` is a top-level flag and must come **before** the subcommand:

```bash
brandpost --vault /path/to/workspace publish --post 2 --json
```
