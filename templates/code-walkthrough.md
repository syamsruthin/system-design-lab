# Code walkthrough: {{TITLE}}

> Companion to [README.md](README.md). The README explains the *concept*; this file explains the
> *code*, file by file, so you can read it, change it, and rebuild it yourself.
> Line links (e.g. `ring.py#L42`) point at the exact code.

## File map

<!-- Table: every file in the lesson, its role, and the order to read it in. -->

| Read | File | Role |
|---|---|---|
| 1 | [`src/<concept>.py`](src/<concept>.py) | |
| 2 | [`src/demo.py`](src/demo.py) | |
| 3 | [`tests/test_<concept>.py`](tests/test_<concept>.py) | |

## How the pieces fit

<!-- Mermaid diagram: who calls whom (demo → classes/functions → infra). Keep it to the real call graph. -->

```mermaid
flowchart LR
```

## `src/<concept>.py`, the concept

<!-- For each meaningful block (class, method, key function), in reading order:
     ### <name> (link to line)
     - a short excerpt (≤ 15 lines; never paste the whole file)
     - "What it does" in 1–2 sentences
     - "Why this way": the design choice and the concept it implements
     - Line notes for any non-obvious line (a bit trick, an off-by-one guard, a wrap-around)
     Map each block back to a step in the README's "How it works". -->

## `src/demo.py`, making it visible

<!-- How each experiment is set up, what it measures, and which output lines it produces.
     Explain any helper that shapes the output. -->

## Tests: what each one proves

| Test | Property it proves | Why that property matters |
|---|---|---|

## Trace one run

<!-- Follow ONE concrete input through the code with real values (print them while writing this):
     input → each function call → intermediate state → result. A numbered list or a table. -->

## Python techniques used

<!-- Language and library features a learner might not know, where they're used, and why. -->

| Technique | Where | Why it's used here |
|---|---|---|

## Design decisions & alternatives

<!-- 2–4 choices that could have gone another way (data structure, algorithm, library vs
     hand-written) and why this one was picked for teaching. -->

## Change it yourself

<!-- 3 exercises, easy → hard. Each has the goal, the file to change, how to check it
     (a test or demo output to watch), and a hint inside <details>. -->
