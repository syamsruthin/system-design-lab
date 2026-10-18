---
name: learn
description: Build a complete System Design Lab lesson for one topic — technical explanation, ELI5 with a real-world example, a from-scratch Python implementation, Docker infra if needed, tests, and real captured output. Use when the learner says "/learn <topic>", "teach me <topic>", or asks to study a specific system design concept.
argument-hint: <topic id or part of its name>
---

# /learn — build and verify a lesson

Topic: `$ARGUMENTS`. If it's empty, use the first new topic from `tracker.py plan --json`.

## 1. Resolve the topic

Run `uv run python scripts/tracker.py info "$ARGUMENTS"`. Note `id`, `title`, `module`,
`difficulty`, `minutes`, `docker`, `tools`, `prereqs` (with status) and `path`.

- If prereqs aren't done, list them in one line and ask whether to continue anyway. Wait.
- If the topic isn't in the curriculum, offer to add it to `curriculum.yaml` (right module,
  difficulty, minutes, prereqs), then run `tracker.py sync && tracker.py validate`.

## 2. Existing lesson → verify, don't rebuild

If `lesson_exists` is true: run the lesson (step 5), confirm the output still matches the README,
fix any drift, run `tracker.py start <id>`, and go to step 7.

## 3. Prepare

- Read `CLAUDE.md` (rules), `templates/lesson.md` (structure) and the reference lesson
  `modules/03-databases/11-consistent-hashing/README.md` (target depth and tone).
- Read the TL;DR of each prerequisite lesson that exists, so the new lesson can link back
  to them ("builds on [Sharding](../10-sharding/README.md)").
- Scale depth with `difficulty`: 1–2 is focused and short; 4–5 goes deep, with a longer
  implementation, more failure modes and a richer Break-it.

## 4. Build the lesson at `path`

```
README.md            # every section of templates/lesson.md, in order, nothing skipped
Makefile             # copy templates/Makefile unchanged
docker-compose.yml   # only if docker: true
src/__init__.py
src/<concept>.py     # the concept implemented from scratch, typed, commented on the WHY
src/demo.py          # labelled output that makes the concept visible (before/after, tables)
tests/test_<concept>.py   # asserts the defining property of the concept
```

Design the demo so the output teaches something. Show numbers that change when a parameter
changes: hit ratios, keys moved, p99 latency, requests rejected, messages duplicated.

For Docker lessons: `name: <topic id>` at the top of the compose file, pinned image tags,
healthchecks (so `make up` can `--wait`), only localhost ports. If a library is needed, run
`uv add <pkg>` at the repo root.

## 5. Run it for real

```bash
docker info --format '{{.ServerVersion}}'   # Docker lessons only. If it fails, ask the learner to start Docker Desktop and wait.
make -C <path> up
make -C <path> run
make -C <path> test
make -C <path> down
```

Fix until `run` produces clean output and all tests pass. Then paste the **actual** demo
output into "Expected output" and explain what each part shows. Never write output you didn't
see.

## 6. Quality check before presenting

- [ ] ELI5 has an analogy, a mapping table from analogy to components, and a named real system
- [ ] Mermaid diagram present; trade-offs table; failure modes; "when NOT to use it"
- [ ] Concept implemented by hand, not imported from a library
- [ ] Tests prove the property; randomness seeded; output reproducible
- [ ] Break-it has exact steps and what to watch for
- [ ] 3 interview Q&As; 5 quiz questions with answers in `<details>`
- [ ] Infra stopped (`make down`)

## 7. Mark started and hand over

Run `uv run python scripts/tracker.py start <id>`, then tell the learner, in about 6 lines:

- the TL;DR and the ELI5 analogy in one line each
- what the demo proves (one striking number from the real output)
- the Break-it experiment to try
- the lesson link, as a markdown link to `<path>/README.md`
- next step: "Study it, run it yourself, try Break it, then `/quiz <id>`."

Do not mark the topic done. The learner does that with `/done` after the quiz.
