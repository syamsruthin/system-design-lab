# System Design Lab — rules for Claude

This repo is a hands-on system design course for one learner (Python developer).
Every topic becomes a lesson that is **explained twice** (technically and like-I'm-5) and
**proven with runnable code** whose real output is captured in the lesson.

## Daily loop (skills in `.claude/skills/`)

| Command | What it does |
|---|---|
| `/today` | Show today's adaptive plan (reviews due + topics that fit the day's budget) |
| `/next` | Start the next lesson in today's plan (or continue the one in progress) |
| `/learn <topic>` | Build (or re-verify) the lesson for one topic |
| `/quiz <topic>` | Interactive quiz, scored and logged; on a done topic this is a spaced-repetition review |
| `/done <topic>` | Mark complete, log minutes, rebuild dashboard, commit |
| `/revise` | Quiz the topics that are due or weak |

## State: never hand-edit `progress.json`

Use `uv run python scripts/tracker.py <cmd>` (see its docstring). `curriculum.yaml` is the
topic list; `config.yaml` holds pacing. After editing the curriculum, run
`tracker.py sync && tracker.py validate`.

## Lesson layout

`uv run python scripts/tracker.py info <topic>` gives the folder (`modules/NN-module/NN-topic/`).

```
README.md            # the concept: follows templates/lesson.md exactly
CODE_WALKTHROUGH.md  # the code, file by file: follows templates/code-walkthrough.md
Makefile             # up, run, test, down (up/down are no-ops if no Docker)
docker-compose.yml   # only if infra is needed
src/                 # concept implementation + demo script
tests/               # pytest tests that PROVE the concept's behaviour
```

`modules/03-databases/11-consistent-hashing/` is the reference lesson. Match its depth and style.

## Writing rules

- **ELI5**: one everyday analogy a child would get, then map every part of the analogy back to the
  technical pieces, then one *named* real-world system that uses it (e.g. "DynamoDB", "Discord").
- **Technical**: mechanics → Mermaid diagram → trade-offs table → failure modes → when NOT to use it.
  Precise vocabulary; define each term the first time it appears. Link to earlier lessons by path.
- Concise. No filler, no marketing tone. Prefer tables and numbered steps over long paragraphs.
- Quiz answers go inside `<details>` so the learner can self-test.
- **CODE_WALKTHROUGH.md** teaches the code the way README teaches the concept: file map with
  reading order, call-graph diagram, block-by-block excerpts (≤ 15 lines each) with "what it does",
  "why this way" and notes on non-obvious lines, what each test proves, a trace of one real input
  with real intermediate values, Python techniques used, design alternatives, and 3 "change it
  yourself" exercises with hints. Link code by line (`src/x.py#L42`). Write it after the code is
  final, so line links are right. README's Implementation section stays a short overview that
  links to it.

## Code rules

- Python ≥ 3.11, type hints, stdlib first. Add libraries with `uv add <pkg>` (root `pyproject.toml`).
- **Implement the concept yourself** (e.g. write the token bucket, don't import a rate-limit lib).
  Use real infra (Redis, Postgres, Kafka…) only to show the concept working on a real system.
- Comments explain the *concept and the why*, not Python syntax.
- Demos print clear, labelled output (tables, before/after numbers) that makes the concept visible.
- Tests assert the property that defines the concept (e.g. "adding a node moves ≈1/N keys",
  "request N+1 is rejected", "hit ratio > 80%"). Seed all randomness so output is reproducible.
- Docker: one `docker-compose.yml` per lesson, pinned image tags, `name:` set to the topic id,
  healthchecks, only free images. Preferred: redis, postgres, redpanda (Kafka API), rabbitmq,
  nginx, haproxy, minio, etcd, consul, prometheus, grafana, jaeger, toxiproxy.
  Always `make down` when finished so ports are free for the next lesson.

## Non-negotiable

- **Run everything before presenting a lesson**: `make up && make run && make test && make down`.
  Paste the *actual* output into "Expected output". Never invent output.
- If Docker isn't running, say so and ask the learner to start Docker Desktop. Don't fake it.
- Keep the learner in the loop: after building a lesson, give a 5-line summary and the commands to
  run, then let them study. Don't run `/done` for them unless they say they've finished.
- Commits: one per finished topic, message `learn(<module>): <topic title>`.
