---
name: revise
description: Spaced-repetition revision for System Design Lab — quiz the learner on topics that are due for review or weak (low score or confidence), and reschedule them. Use when the learner says "/revise", "review", "revision", or "what should I revise".
---

# /revise — spaced repetition

1. Run `uv run python scripts/tracker.py due --json` and `uv run python scripts/tracker.py plan --json`.
2. Pick topics: the `reviews` listed in today's plan first (already capped to fit the budget),
   then any `weak` topics if the learner wants more.
   - Nothing due and nothing weak → say so. Offer an **interleaved mixed quiz**: 5 questions
     across 3–5 random done topics, which is good for retention. Record each question's topic
     score separately.
3. For each topic, run the **review mode** of `.claude/skills/quiz/SKILL.md`: 3 fresh,
   scenario-heavy questions, asked one at a time, graded, then a confidence rating and a
   `tracker.py quiz` call. Between topics, give a one-line transition.
4. End with a table: topic · score · confidence · next review date (from the tracker output).
   For any failed review, name the README section to re-read. It returns tomorrow.
5. Run `uv run python scripts/build_dashboard.py` so the dashboard reflects the reviews.
