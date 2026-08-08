# Setup prompt

Paste the block below into Claude Code, Codex or another coding agent sitting in
this repo. It interviews you and fills in your brand, instead of you writing TOML
by hand.

**Write to it in whatever language you prefer.** The prompt asks the agent to
interview you in your language and to set the brand's `language` field to match, so
your posts come out in the right one.

It asks few questions, and it asks the right ones: the engine can draw and phrase,
but it cannot know what your company actually thinks.

The prompt has been tested by running it for a made-up company from scratch. The
steps that look excessively detailed are that way because something actually went
wrong there.

---

```
Set up this repo for my company. Read README.md and brandpost/brands/README.md
first, so you understand how the brand layer works.

Interview me in the language I write to you in, and set the brand's `language`
field to that language.

Work like this:

1. INTERVIEW ME, one question at a time. Not a bullet list. Give your own
   recommendation with each question, briefly justified. What you need to learn:

   - What the company does, in one sentence, the way a customer would say it.
   - Who the posts should reach, and what they already believe that is wrong.
   - Three to six PILLARS: the themes we want to be known for. Propose them
     yourself from my answers and let me correct you. This is the most important
     choice.
   - Voice: two or three sentences on how we sound. Ask for an example of
     something we would NEVER say; that draws the line better than ten adjectives.
   - THREE TO FIVE NUMBERS we can stand behind publicly: price, response time,
     volume, what something costs to lose. Without numbers the posts become
     assertions. If we have none yet, say so, and write an explicit ban on
     invented numbers into company/products.md.
   - Our website URL, if we have one. Ask directly, do not guess the domain.
   - Our LinkedIn handle, or "none yet". Without it, no @-mention should be
     written into posts at all.
   - Logo: a path to a PNG, or none. Without a logo the cards become
     typography-driven, which is a perfectly good choice.
   - Cadence: how many posts per week, and which days.

2. If we have a website, PULL the colours from its stylesheet instead of asking me
   for hex codes. But CONFIRM FIRST that the domain is actually ours: a guessed
   domain usually belongs to someone else, and then you would pull a stranger's
   palette. Show me what you found and let me approve it.

   Fonts you cannot simply pull from the site: `fonts.display` must be a filename
   that exists in brandpost/assets/fonts/. Three ship with the repo (Fraunces,
   Inter, YoungSerif). For anything else, the .ttf has to be placed there first.

3. Create brandpost/brands/<our-key>/ by copying the demo folder and filling it in.

   CLEAN UP AFTER COPYING: the demo folder contains Demo Labs' logo. If I have not
   supplied one, DELETE media/logo.png and remove the [media] section. Otherwise
   our brand gets a stranger's logo on every single card.

   Write the markdown files in voice/ and company/ with MY content, not generic
   phrasing. If an answer of mine is vague, ask again instead of polishing it:
   vague brand files produce vague posts, and that is the most common failure.

   Set BRANDPOST_POST_DAYS in .env to the days I chose (0 = Monday). That field
   does not exist in profile.toml, so without this my cadence answer goes unused.

4. Set up one local environment file from .env.example, `chmod 600` it, and set
   `BRANDPOST_ENV_FILE` to its absolute path. Tell me which variable names are
   needed, but NEVER ask me to send values in chat and never read them back to
   me. I enter each value directly in the local file (or password manager) myself.

   If I have a Claude Code subscription, set BRANDPOST_MODEL_BACKEND=cli instead of
   asking for ANTHROPIC_API_KEY: text generation then costs nothing extra. An image
   key is still needed for illustrations; without one you get typography cards.

5. Run a first generation. Use the SAME BRANDPOST_WORKSPACE you will later start
   the dashboard with, or I will see an empty page:

       BRANDPOST_WORKSPACE=./workspace python -m brandpost.cli run --brand <key>

   Open the image and READ the text. Go through the anti-patterns in
   voice/writing.md LINE BY LINE. The model breaks them regularly in the opening
   sentence even when the file is explicit, especially the "not X, but Y" figure.
   If one is broken, regenerate with a concrete correction.

   Judge honestly whether the text is good or merely grammatical. If it is generic,
   say so, and propose what in the brand files needs to get more concrete. Do not
   hand me something you think is mediocre.

6. Finally, tell me:
   - What was created and where it lives.
   - How to look at it (BRANDPOST_WORKSPACE=./workspace python main.py, then
     http://localhost:5050/some).
   - That nothing publishes until I set LINKEDIN_ENABLED=1 and click.
   - What remains if I want automatic publishing.

Rules:
- NEVER publish anything. You propose, I decide.
- Do not touch brandpost/brands/demo/ or minimal/: other people need those examples.
- Run the tests before you call it done: python -m pytest -q
```
