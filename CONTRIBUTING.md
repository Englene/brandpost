# Contributing

This is a tool someone built for themselves and published because it might be
useful to others. It is not a product, and no support comes with it.

**Expectations, so you do not have to guess:**

- Issues get read, but may sit for a while. No response time is promised.
- Pull requests are welcome. Small and focused move fastest.
- Code comments are in Norwegian. Not a principle, just how it happened. User-facing
  documentation is in English and Norwegian.
- Tests must be green without network access, without API keys and without a
  workspace. If your change needs any of those three, it belongs behind a flag.

**One thing that will not be merged:** anything that lets the system publish without
a human click. The whole design rests on a person seeing the content before it goes
out into the world with a company name on it.

```bash
python -m pytest -q
```
