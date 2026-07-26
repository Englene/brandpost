# brandpost

A self-hosted system for making LinkedIn content for a company page: it proposes
posts, draws the images, and publishes only after you say yes.

You describe your brand in a few text files. The engine uses them to write posts
and render cards that look like you. You approve in a local dashboard. Nothing
goes out without a click.

**[Norsk versjon av denne fila](README.no.md)**

> **On language:** the code comments are in Norwegian, because that is where this
> came from. Everything you need to *use* the project exists in both English and
> Norwegian. Set `language` in your brand profile to choose what language your
> posts are written in; the setup prompt will interview you in whichever language
> you write to it.

---

## Read this first

**Browser automation of LinkedIn violates their user agreement.** This repo
includes a Playwright path that logs in as you and saves drafts. It exists because
the API cannot create drafts, and it is genuinely useful, but it is not without
risk: your account could be restricted. That is your call to make. The API path is
within the agreement. See [browser vs API](#browser-vs-api) below.

**Nothing publishes on its own.** Publishing is off until you set
`LINKEDIN_ENABLED=1`, and even then only when you click or schedule something.

---

## Getting started

```bash
git clone https://github.com/Englene/brandpost && cd brandpost
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # fill in at least ANTHROPIC_API_KEY + one image key
```

If you have a Claude Code subscription you can skip `ANTHROPIC_API_KEY` and set
`BRANDPOST_MODEL_BACKEND=cli` instead, which costs nothing extra for text. You
still need an image key for illustrations; without one every card falls back to
typography, which also looks good.

Create your own brand:

```bash
cp -R brandpost/brands/demo brandpost/brands/my-company
```

Open `brandpost/brands/my-company/profile.toml` and change the name, colours and
pillars. Then rewrite the markdown files in `voice/` and `company/`. **Those two
decide the quality.** The engine cannot guess what your company actually thinks.

Generate and look at the result:

```bash
python -m brandpost.cli run --brand my-company
python main.py                      # http://localhost:5050/some
```

Drafts land in `workspace/`. If you point `BRANDPOST_WORKSPACE` somewhere else, it
has to point at the same place when you start the dashboard, or you will see an
empty page.

Rather not do this by hand? See [agent/](agent/): a prompt you paste into Claude
Code or Codex that interviews you and fills in the files for you.

---

## How it fits together

```
workspace/notes/*.md ──┐
                       ├──► brain (text model) ──► drafts ──► dashboard ──► LinkedIn
brand files ───────────┘         │                              ▲
                                 └──► image model ──► cards     │
                                                          you approve
```

- **The brand** is text files, not code. No code changes for a new brand.
- **Notes are optional.** Drop markdown in `workspace/notes/` and the brain uses it
  as raw material. An empty folder works, the output is just more generic.
- **Images are made in two layers:** the model draws only the *content* in your
  brand colours, and code puts the headline, logo and wordmark on top. That split
  is what makes the AI part read as typography rather than a pasted-in picture.
- **The plan** spreads topics across the week and rotates through your pillars, so
  you do not keep writing the same post.

---

## Browser vs API

Two paths, and they cannot do the same things. That is the whole reason both exist.

| | API | Browser |
|---|---|---|
| Publish now | yes | yes |
| Publish at a set time | yes, we hold the clock | yes, LinkedIn holds the clock |
| Create a real draft in LinkedIn | **no** | yes |
| Read what has been published | yes | yes |
| Within the user agreement | yes | **no** |
| Needs LinkedIn approval | yes, weeks | no |
| Works on day one | no | yes |

The API only accepts `PUBLISHED` when a post is created. There is no draft state.
If you want a draft sitting in LinkedIn waiting for you, the browser path is the
only option.

The two are coordinated: a post scheduled inside LinkedIn is marked, and the
automatic publisher never touches it. Without that, the same post would go out
twice and nothing would look like an error.

**Recommendation:** start with the browser path while you wait for API access, and
switch once it is granted.

---

## Getting API access

You need the **Community Management API** to publish to a company page. That
requires a registered company with a verified LinkedIn page.

1. Create an app at [linkedin.com/developers](https://www.linkedin.com/developers/apps)
   and associate it with your company page.
2. Request the **Community Management API** product. Expect days to weeks, and
   expect to describe what your app will do.
3. Add `http://localhost:8765/callback` as a redirect URL.
4. Put `LINKEDIN_CLIENT_ID` and `LINKEDIN_CLIENT_SECRET` in `.env`.
5. Run the one-time login:
   ```bash
   python -m brandpost.linkedin_auth
   ```
   It opens your browser, catches the redirect on localhost, and prints the tokens
   for you to paste into `.env`.
6. Find your page ID in the admin URL
   (`linkedin.com/company/<ID>/admin/dashboard/`) and set
   `org_urn = "urn:li:organization:<ID>"` in your brand profile.

The scopes you need are `w_organization_social` (publish) and
`r_organization_social` (read your own posts).

**If you are rejected,** or you have no company page: the browser path still works,
and the whole generation side needs no LinkedIn access at all.

---

## Running it automatically

Publishing is a mechanical script and belongs in a plain scheduled job, not an
agent run. It looks for posts you have scheduled and puts out the ones that are due:

```bash
python -m brandpost.publisher            # run every 15 minutes
python -m brandpost.publisher --dry-run  # show what would happen
```

It refuses to publish anything more than six hours late. A post that should have
gone out yesterday morning should not suddenly appear today without a human
looking at it.

*Generation*, on the other hand, is judgement, and suits an agent run. See
[agent/generate.md](agent/generate.md).

---

## What could be better

An honest list, in the order I would tackle it:

- **Personal profiles as a target.** Only company pages are supported today.
  Personal posting is a different LinkedIn product ("Share on LinkedIn", scope
  `w_member_social`) that is self-serve and approved in days. For most people that
  would lower the barrier the most.
- **Performance feedback per pillar.** Engagement numbers are collected but never
  used to steer content toward what actually works.
- **AI art on every carousel slide.** Today only the cover gets art, because eight
  independently generated images easily read as eight different series. Solve that
  and carousels get much stronger.
- **More platforms.** Everything is built around LinkedIn. The engine is not.
- **Context connectors.** The notes folder is deliberately dumb. A connector for
  calendar, email or chat would give the brain fresher material. See
  [docs/extending.md](docs/extending.md).
- **Editing individual slides** in the dashboard.

---

## License

MIT. See [LICENSE](LICENSE).
