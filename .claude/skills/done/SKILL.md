---
name: done
description: Mark a System Design Lab topic finished — log actual study minutes, schedule spaced-repetition reviews, rebuild the progress dashboard, and commit. Use when the learner says "/done <topic>", "finished", or "mark it done".
argument-hint: <topic id> [minutes]
---

# /done — finish a topic

Arguments: `$ARGUMENTS` (a topic, optionally followed by minutes spent). With no topic, use the
in-progress one.

1. Run `uv run python scripts/tracker.py info <topic>`.
   - Status `todo` → ask whether they really studied it (no lesson was started). Wait.
   - No quiz recorded → recommend `/quiz <id>` first, because pacing adapts to quiz scores.
     If they decline, continue.
2. Minutes: if not given, ask "Roughly how many minutes did this take? (estimate was N)".
   Real numbers matter: they drive the adaptive time factor. Wait for the answer.
3. Run `uv run python scripts/tracker.py done <id> --minutes <M>`. This also rebuilds
   `docs/index.html` and the README progress table.
4. Run `make -C <path> down` so no containers are left running.
5. Commit, if this is a git repo:
   ```bash
   git add <path> progress.json docs README.md pyproject.toml uv.lock
   git commit -m "learn(<module slug>): <topic title>"
   ```
   Don't push unless the learner asks. Mention that `git push` updates the online dashboard.
6. Run `uv run python scripts/tracker.py plan` and finish with one line: the next topic in
   today's plan (`/next`), or "today's budget is done", with the streak and % complete.
