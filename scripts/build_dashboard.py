#!/usr/bin/env python3
"""
Build the progress dashboard (docs/index.html) and the README progress table
from curriculum.yaml + progress.json.

    uv run python scripts/build_dashboard.py [--today YYYY-MM-DD]

`tracker.py done` runs this automatically; CI runs it on every push.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from statistics import mean
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))
from tracker import ROOT, Lab, _parse  # noqa: E402

TEMPLATE = ROOT / "scripts" / "dashboard_template.html"
OUT = ROOT / "docs" / "index.html"
README = ROOT / "README.md"
START, END = "<!-- PROGRESS:START -->", "<!-- PROGRESS:END -->"


def collect(lab: Lab) -> dict:
    summary = lab.summary()
    due_ids = {t.id for t in lab.due()}
    weak_ids = {t.id for t in lab.weak()}

    topics = []
    for t in lab.topics:
        e = lab.entry(t)
        topics.append({
            "n": t.order + 1, "id": t.id, "title": t.title, "module": t.module_title,
            "module_id": t.module_id, "difficulty": t.difficulty, "minutes": t.minutes,
            "status": e["status"], "last_score": lab.last_score(t), "confidence": e["confidence"],
            "next_review": e["next_review"], "completed": e["completed"],
            "due": t.id in due_ids, "weak": t.id in weak_ids, "path": t.rel_path,
        })

    modules = []
    for m in summary["modules"]:
        mt = [t for t in topics if t["module_id"] == m["id"]]
        scores = [t["last_score"] for t in mt if t["status"] == "done" and t["last_score"] is not None]
        conf = [t["confidence"] for t in mt if t["status"] == "done" and t["confidence"] is not None]
        modules.append({**m, "in_progress": sum(t["status"] == "in-progress" for t in mt),
                        "avg_score": round(mean(scores)) if scores else None,
                        "avg_confidence": round(mean(conf), 1) if conf else None})

    activity: dict[str, dict] = {}
    labels = {"done": "finished", "quiz": "quiz", "start": "started", "reset": "reset"}
    for ev in lab.data["log"]:
        day = activity.setdefault(ev["date"], {"minutes": 0, "events": []})
        day["minutes"] += ev.get("minutes") or 0
        title = lab.by_id[ev["topic"]].title if ev["topic"] in lab.by_id else ev["topic"]
        extra = f" {ev['score']}%" if ev["event"] == "quiz" else ""
        if ev["event"] == "quiz" and ev.get("review"):
            labels_ev = "review"
        else:
            labels_ev = labels.get(ev["event"], ev["event"])
        day["events"].append(f"{labels_ev}: {title}{extra}")

    quizzes = [
        {"date": ev["date"], "topic": ev["topic"], "score": ev["score"], "confidence": ev["confidence"],
         "review": ev.get("review", False),
         "title": lab.by_id[ev["topic"]].title if ev["topic"] in lab.by_id else ev["topic"]}
        for ev in lab.data["log"] if ev["event"] == "quiz"
    ]

    return {
        "title": lab.cfg["dashboard"]["title"],
        "generated": datetime.now(ZoneInfo(lab.cfg["timezone"])).strftime("%Y-%m-%d %H:%M") if lab.cfg.get("timezone")
        else datetime.now().strftime("%Y-%m-%d %H:%M"),
        "today": lab.today.isoformat(),
        "summary": summary,
        "plan": lab.plan(),
        "pace": lab.cfg["pace"],
        "pass_score": lab.cfg["review"]["pass_score"],
        "heatmap_weeks": lab.cfg["dashboard"]["heatmap_weeks"],
        "topics": topics,
        "modules": modules,
        "activity": activity,
        "quizzes": quizzes,
    }


def readme_table(data: dict) -> str:
    s = data["summary"]
    pr = s["projection"]
    finish = "complete 🎉" if pr.get("complete") else (pr.get("finish") or "—")
    badge = f"![progress](https://img.shields.io/badge/progress-{s['percent']}%25-2a78d6)"
    lines = [
        badge,
        "",
        f"**{s['done']}/{s['total']} topics** · {s['hours']} h studied · streak {s['streak']} day(s) · "
        f"avg quiz {str(s['avg_score']) + '%' if s['avg_score'] is not None else '—'} · projected finish **{finish}**",
        "",
        "| Module | Progress | Done | Avg quiz |",
        "|---|---|---|---|",
    ]
    for m in data["modules"]:
        filled = round(10 * m["done"] / m["total"]) if m["total"] else 0
        bar = "▓" * filled + "░" * (10 - filled)
        avg = f"{m['avg_score']}%" if m["avg_score"] is not None else "—"
        lines.append(f"| {m['id']} {m['title']} | `{bar}` | {m['done']}/{m['total']} | {avg} |")
    return "\n".join(lines)


def build(lab: Lab | None = None) -> None:
    lab = lab or Lab()
    data = collect(lab)
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    html = TEMPLATE.read_text().replace("/*__DATA__*/null", payload, 1)
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(html)
    (OUT.parent / ".nojekyll").touch()

    text = README.read_text()
    if START in text and END in text:
        block = f"{START}\n{readme_table(data)}\n{END}"
        text = re.sub(re.escape(START) + r".*?" + re.escape(END), lambda _: block, text, flags=re.S)
        README.write_text(text)
    print(f"dashboard → {OUT.relative_to(ROOT)} · README progress table updated")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--today", help="simulate a different date (YYYY-MM-DD)")
    a = ap.parse_args()
    build(Lab(_parse(a.today) if a.today else None))
