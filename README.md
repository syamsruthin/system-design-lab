# System Design Lab

Learning system design end to end, one runnable lab at a time. Every topic is explained **twice**,
once technically and once like you're five with a real-world example, and then **proven with code** you
run and break yourself (Python + Docker, all free tools).

**[📊 Progress dashboard](https://syamsruthin.github.io/system-design-lab/)**

<!-- PROGRESS:START -->
![progress](https://img.shields.io/badge/progress-3.6%25-2a78d6)

**3/84 topics** · 1.8 h studied · streak 3 day(s) · avg quiz 100% · projected finish **2026-12-06**

| Module | Progress | Done | Avg quiz |
|---|---|---|---|
| 00 Foundations | `▓▓▓▓░░░░░░` | 3/8 | 100% |
| 01 Scaling & Traffic | `░░░░░░░░░░` | 0/6 | — |
| 02 Caching | `░░░░░░░░░░` | 0/6 | — |
| 03 Databases | `░░░░░░░░░░` | 0/11 | — |
| 04 Messaging & Async | `░░░░░░░░░░` | 0/7 | — |
| 05 Distributed Systems | `░░░░░░░░░░` | 0/9 | — |
| 06 Data Structures at Scale | `░░░░░░░░░░` | 0/8 | — |
| 07 Reliability & Resilience | `░░░░░░░░░░` | 0/7 | — |
| 08 Observability & Architecture | `░░░░░░░░░░` | 0/10 | — |
| 09 Case Studies | `░░░░░░░░░░` | 0/12 | — |
<!-- PROGRESS:END -->

## How a lesson looks

Each folder in `modules/` is one topic:

| Section | What you get |
|---|---|
| TL;DR | The concept in two lines |
| Explain like I'm 5 | An everyday analogy, mapped back to the real components, plus a named real system |
| Technical deep dive | Mechanics, Mermaid diagram, trade-offs, failure modes, when *not* to use it |
| Implementation | The concept implemented from scratch in Python |
| **Code walkthrough** | A separate `CODE_WALKTHROUGH.md`: every file explained block by block, a traced run with real values, Python techniques used, and exercises to extend the code |
| Run it / Expected output | `make run`, with the real output and what it shows |
| Break it | An experiment that exposes the failure mode |
| Interview angle + quiz | 3 interview Q&As and a 5-question self-check |

Reference lesson: [Consistent Hashing](modules/03-databases/11-consistent-hashing/README.md) and its
[code walkthrough](modules/03-databases/11-consistent-hashing/CODE_WALKTHROUGH.md).

## Daily workflow (Claude Code)

Open this folder in VS Code, start Claude Code, and use:

```text
/today            what to study today (adapts to difficulty and your pace)
/next             build and start the next lesson in today's plan
/quiz <topic>     5 questions, scored; on finished topics this is a spaced-repetition review
/done <topic>     mark finished, log time, update dashboard, commit
/revise           quiz yourself on topics that are due or weak
/learn <topic>    jump to any topic directly
```

### Adaptive pacing

`config.yaml` sets a daily budget (default **120 min on weekdays, 180 on weekends**). Each topic has a
difficulty (1–5) and an estimated time:

- **Easy topics are batched.** On a weekday you might get 3–4 short foundation topics.
- **Hard topics get the day.** A difficulty 4–5 topic (Raft, isolation levels, CRDTs) is always
  scheduled alone.
- **Your pace is measured.** If you finish topics faster than the estimates, more fit in a day; slower,
  fewer. A quiz average above 85% raises the daily budget by 15%; below 60% lowers it and pulls
  revisions forward.
- **Spaced repetition.** Finished topics come back for review after 1, 3, 7, 21 and 60 days. A failed
  review resets the topic to tomorrow.

## Setup

Prerequisites: [Docker Desktop](https://www.docker.com/products/docker-desktop/),
[uv](https://docs.astral.sh/uv/), Git, and Claude Code.

```bash
uv sync
uv run python scripts/tracker.py plan
```

Without Claude Code, the tracker is a plain CLI:

```bash
uv run python scripts/tracker.py plan
uv run python scripts/tracker.py quiz consistent-hashing --score 80 --confidence 4
uv run python scripts/tracker.py done consistent-hashing --minutes 55
uv run python scripts/build_dashboard.py
```

### Publish the dashboard

One-time setup: in **Settings → Pages → Build and deployment**, set Source to **GitHub Actions**.

From then on, `.github/workflows/dashboard.yml` builds the dashboard from `progress.json` and deploys it
on every push, and again daily so "today's plan" and reviews due stay current. It never commits to the
repo, so `git push` after `/done` always goes through cleanly.

## Layout

```text
curriculum.yaml        84 topics in 10 modules: difficulty, minutes, prerequisites
config.yaml            pacing and spaced-repetition settings
progress.json          your state (written only by scripts/tracker.py)
scripts/tracker.py     planner and progress CLI
scripts/build_dashboard.py   writes docs/index.html and the table above
templates/             lesson.md and code-walkthrough.md skeletons, lesson Makefile
modules/               the lessons
.claude/skills/        /today /next /learn /quiz /done /revise
```
