---
name: today
description: Show today's adaptive System Design Lab study plan — reviews due, lessons in progress, and new topics that fit today's time budget. Use when the learner asks what to study, says "today" or "plan", or opens a study session.
---

# /today — today's study plan

1. Run `uv run python scripts/tracker.py plan` and `uv run python scripts/tracker.py status`.
2. Present it compactly:
   - One line: date, budget left, streak, overall % complete, projected finish.
   - **Reviews due** (if any): say they come first and take ~15 min each.
   - **Continue** (in-progress topics), then **New topics**, as a numbered list showing
     title, difficulty dots and minutes. Explain the batch in one line,
     e.g. "4 easy topics fit today" or "Raft is deep-focus, so it gets the day to itself".
   - If the budget is used up, congratulate briefly and show the optional stretch topic.
3. If any planned topic has `docker: true`, run `docker info --format '{{.ServerVersion}}'`.
   If that fails, tell the learner to start Docker Desktop before `/next`.
4. Finish with the next action: `/revise` if reviews are due, otherwise `/next`.

Keep it short. This is a launch pad, not a lecture.
