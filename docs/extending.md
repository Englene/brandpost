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
