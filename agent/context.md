# Context runbook

The engine writes better the more it knows about what is actually happening at your
company. This recipe collects the week's raw material into `workspace/notes/`, which
is the only context input.

It is deliberately dumb: one folder of markdown. That means you can connect anything
to it, and that nothing breaks if you never do.

Run it once a week, ideally the evening before generation.

---

```
Collect this week's raw material for content into workspace/notes/.

Go through the sources you have access to (calendar, email, meeting notes, customer
calls, support, whatever you have). Look for:

- Questions or objections that came up with several people. Repetition is the
  signal: one person is an anecdote, three is a theme.
- Something that changed: a deadline, a rule, a number, a price.
- Something we learned that others would benefit from.
- Something we believed that turned out to be wrong.

Write ONE note per theme to workspace/notes/<date>-<short-name>.md, like this:

    # One sentence that is the actual point

    Two to five lines on what happened and why it is worth saying something about.
    Include the number if there is one.

The first line becomes the title and the rest becomes the summary, so put the most
important thing first.

ANONYMISE. Never customer names, never another company's name, never figures from a
deal that is not public. Write "a customer in construction" instead of the name.
This is raw material for public posts, and anything that lands here can end up there.

Three sharp notes beat twelve thin ones. If you found nothing worth writing about,
say so, and create no files.
```
