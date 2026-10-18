---
name: quiz
description: Quiz the learner on a System Design Lab topic one question at a time, grade the answers, and record score and confidence for adaptive pacing and spaced repetition. Use when the learner says "/quiz <topic>", "quiz me", or "test me on <topic>".
argument-hint: <topic id or part of its name>
---

# /quiz — interactive, scored quiz

Topic: `$ARGUMENTS`. If it's empty, use the topic that is `in-progress` (`tracker.py plan --json` → `continue`).

1. Run `uv run python scripts/tracker.py info "$ARGUMENTS"`.
   - `status: done` → **review mode** (spaced repetition). Ask 3 fresh questions.
   - otherwise → **first quiz**. Ask 5 questions.
2. Read the lesson README at `path` so the questions match what was taught. Don't copy its
   self-check questions word for word. Write variations, or new scenarios in review mode.
3. Question mix, for 5 questions: 2 conceptual ("why…", "what's the difference…"),
   2 scenario ("a node dies mid-write, what happens?"), and 1 design trade-off. At least one
   should refer to the lab's code or output ("in the demo, why did X drop to Y?").
   For 3 questions: 1 conceptual, 1 scenario, 1 trade-off.
4. Ask **one question at a time** and wait for the learner's answer. Don't show the answer first.
5. Grade each answer as ✅ correct (1), 🟡 partial (0.5) or ❌ wrong (0). Give a 1–3 sentence
   explanation and the model answer when it wasn't fully correct. Be fair: accept correct
   reasoning in their own words.
6. After the last question, show the score (`round(points / questions × 100)`) and ask:
   "How confident do you feel about this topic, 1–5?" Wait for the answer.
7. Record it: `uv run python scripts/tracker.py quiz <id> --score <S> --confidence <C>`
8. Feedback, in 2–4 lines: the weakest sub-concept, and which README section to re-read.
   - First quiz with score ≥ 60 → suggest `/done <id>`.
   - First quiz with score < 60 → suggest re-reading the named sections and re-running Break it,
     then `/quiz <id>` again.
   - Review mode → report the next review date that the tracker printed.
