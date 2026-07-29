# Automation prompt

You have set up your brand and produced a few drafts by hand. This prompt makes it
run on its own: drafts appear on a schedule, scheduled posts go out, and the
dashboard is always there when you want to look.

Paste the block below into Claude Code, Codex or another coding agent sitting in
this repo. It works out your platform, writes the job files, installs them, and
then **proves they run** instead of telling you they should.

**Nothing in here publishes on its own.** The publisher only puts out posts you
have already scheduled by hand, and it stays in dry-run until you set
`LINKEDIN_ENABLED=1` yourself.

The three moving parts, and why they are different kinds of job:

| Part | What it is | How often |
|---|---|---|
| **Generation** | judgement: which angle is worth taking this week | on your posting days |
| **Publishing** | mechanics: is anything due right now | every 15 minutes |
| **Dashboard** | where you approve things | always on |

Generation is the only one that needs a model. Running it as an agent is the
point. Publishing is a script, and making it an agent run would mean 96 model
calls a day for something that takes a second.

---

````markdown
Set this repo up to run automatically. Read README.md and agent/generate.md first,
then work through the steps below in order. Interview me in the language I write to
you in.

Do not install anything until step 2 is answered.

## 1. Work out where we are

Find out and tell me:

- Operating system, and which scheduler it has (launchd on macOS, systemd or cron
  on Linux). Do not guess from my prompt, check.
- Is this machine always on, or does it sleep? A laptop that sleeps needs
  catch-up behaviour; a server does not.
- Absolute path to this repo, and to the Python in its virtualenv. Use absolute
  paths in every job file: schedulers do not inherit my shell's PATH.
- Is `.env` filled in? Which of `LINKEDIN_ENABLED`, `BRANDPOST_MAIL_ENABLED` are
  on? Tell me before we automate anything with side effects.
- Which brands are enabled, and does `python -m brandpost.cli plan` show a plan?

## 2. Ask me what to automate, one question at a time

Give your recommendation with each question, briefly justified.

- **Publishing every 15 minutes?** Recommended if you plan posts ahead. Skip it if
  you would rather press publish yourself each time.
- **Generation on which days?** Match `BRANDPOST_POST_DAYS`. Ask what time of day;
  early morning means drafts wait for me, not the other way around.
- **Dashboard always on?** Recommended: it is where approval happens. Ask which
  port, and whether it should be reachable from other machines on the network
  (`--host 0.0.0.0`) or only this one (`127.0.0.1`, the safer default).
- **Which agent runs generation?** Claude Code has scheduled runs; otherwise it is
  a timed job that starts the agent with agent/generate.md as the prompt.

## 3. Write the job files

Put them in `deploy/` in this repo so they are version controlled and I can read
them, then install copies where the scheduler expects them. Never write only into
the system location: I lose them on the next machine.

Every job file must set, explicitly:

- **Absolute path** to the virtualenv's Python. Not `python`, not `python3`.
- **Working directory** = this repo. `.env` is read from the working directory,
  so getting this wrong means my configuration is silently never loaded.
- **PATH**, including `/opt/homebrew/bin` and `/usr/local/bin` on macOS. Without
  it, `claude` and other tools are "not found" only when the scheduler runs them,
  never when I test by hand.
- **Log files**, stdout and stderr to separate paths. A job with nowhere to write
  is a job you cannot debug.

Put the install and uninstall commands in a comment at the top of each file, so
they are there the day I need them and have forgotten.

**macOS:** launchd, `~/Library/LaunchAgents/`. `StartInterval` for the publisher,
`StartCalendarInterval` (one dict per weekday) for generation, `KeepAlive` for the
dashboard. Validate every file with `plutil -lint` before loading it.

**Linux:** systemd user units with timers, or cron. With systemd, remember
`WorkingDirectory=` and `EnvironmentFile=`. With cron, remember that it has almost
no environment at all, so set everything explicitly.

## 4. Prove each job actually runs

This is the part that matters, and the part that is usually skipped. For each job:

1. Trigger it manually through the scheduler, not by running the command in the
   shell. `launchctl kickstart -k gui/$(id -u)/<label>` or
   `systemctl --user start <unit>`. Running the command yourself proves the
   command works, not that the job does.
2. Read the log file and show it to me.
3. Show that it did something observable: a file written, a line in the log with a
   timestamp from just now, an HTTP 200 from the dashboard.

Then tell me, per job, what you actually saw. If something did not run, say so
plainly rather than describing what should happen.

## 5. Watch for these

Every one of these fails quietly. There is no error message pointing at the cause.

- **The scheduler has a different environment than your shell.** This is the
  single most common cause. A job that works when you run it and fails on
  schedule is almost always PATH or working directory.
- **`.env` is read from the working directory.** Set it wrong and the job runs
  with default configuration, finds nothing, and reports success.
- **A laptop that sleeps** does not run missed jobs on wake for every scheduler.
  If the machine sleeps, say so and prefer intervals over exact clock times.
- **Catch-up on publishing is deliberately limited.** The publisher refuses posts
  more than six hours late (`BRANDPOST_CATCHUP_H`). If the machine was off, some
  posts will not go out, and that is on purpose.
- **`brandpost.cli pulse` is a stub**, not a feature. It prints an explanation of
  the extension point. Putting it in a job gives you a step that looks successful
  and does nothing. See docs/extending.md.
- **The dashboard on `0.0.0.0`** is reachable by anything on the network. It has
  no authentication. Only do that on a network I control, and tell me that is what
  it means.

## 6. Finish

- Show me the exact commands to stop, start and inspect each job. I will need them
  when something looks wrong at eight in the morning.
- Tell me where the logs are.
- Tell me what is NOT automated, and what I still do by hand. Approving and
  scheduling posts should stay mine.
- Commit the files in `deploy/`.
````

---

## Checking on it later

Whatever the platform, the same three questions tell you if it is healthy:

```bash
python -m brandpost.publisher --dry-run
```

Says what the publisher sees right now, without doing anything.

```bash
python -m brandpost.cli plan
```

Shows the plan: which slots have drafts, which are scheduled, which went out.

```bash
curl -s -o /dev/null -w '%{http_code}\n' http://localhost:5050/healthz
```

`200` means the dashboard is alive.

If drafts stop appearing, the generation job is the place to look, and its log
will usually say the model call failed or that the brand could not be loaded. If
drafts appear but nothing goes out, that is either `LINKEDIN_ENABLED=0` or nothing
being scheduled, and both are working as designed.
