---
name: next
description: Start the next System Design Lab lesson from today's adaptive plan, or resume the one in progress. Use when the learner says "next", "next topic", "what's next" or "let's continue".
---

# /next — move to the next lesson

1. Run `uv run python scripts/tracker.py plan --json`.
2. Pick the topic:
   - If `continue` is non-empty, that topic is unfinished. Show its lesson path and ask whether
     they want to keep studying it, take `/quiz <id>` now, or set it aside and start the next one.
     Stop and wait for the answer.
   - Otherwise take the first item in `new`.
   - If `new` is empty and `stretch` is set, the daily budget is used up. Say so and ask whether
     to do the stretch topic anyway. Stop and wait.
   - If everything is done, celebrate and suggest `/revise`.
3. For the chosen topic, follow `.claude/skills/learn/SKILL.md` exactly, with that topic id.
4. After the lesson is presented, mention how many topics remain in today's plan.
