#!/usr/bin/env python3
"""
System Design Lab — progress tracker & adaptive daily planner.

All learning state lives in progress.json. Don't edit it by hand; use this CLI
(the Claude Code skills call it for you).

    uv run python scripts/tracker.py plan                      # today's adaptive plan
    uv run python scripts/tracker.py info  <topic>             # metadata + lesson path (JSON)
    uv run python scripts/tracker.py start <topic>
    uv run python scripts/tracker.py quiz  <topic> --score 80 --confidence 4
    uv run python scripts/tracker.py done  <topic> --minutes 45
    uv run python scripts/tracker.py due                       # reviews due + weak topics
    uv run python scripts/tracker.py status                    # overall summary
    uv run python scripts/tracker.py reset <topic>             # back to todo
    uv run python scripts/tracker.py sync | validate

<topic> may be an exact id or any unique part of an id/title ("bloom", "cache-aside").
Add `--today YYYY-MM-DD` before the command to simulate another date.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from statistics import mean
from zoneinfo import ZoneInfo

import yaml

ROOT = Path(__file__).resolve().parent.parent
CURRICULUM = ROOT / "curriculum.yaml"
CONFIG = ROOT / "config.yaml"
PROGRESS = ROOT / "progress.json"

PROJECTION_REVIEW_OVERHEAD = 0.10  # share of future budgets assumed to go to reviews
PROJECTION_MAX_DAYS = 1000


@dataclass
class Topic:
    id: str
    title: str
    difficulty: int
    minutes: int
    prereqs: list[str]
    docker: bool
    tools: list[str]
    module_id: str
    module_slug: str
    module_title: str
    index: int  # 1-based position inside its module
    order: int  # 0-based position in the whole curriculum

    @property
    def rel_path(self) -> str:
        return f"modules/{self.module_id}-{self.module_slug}/{self.index:02d}-{self.id}"

    @property
    def path(self) -> Path:
        return ROOT / self.rel_path


def _iso(d: date) -> str:
    return d.isoformat()


def _parse(s: str) -> date:
    return date.fromisoformat(s)


def _empty_entry() -> dict:
    return {
        "status": "todo",  # todo | in-progress | done
        "started": None,
        "completed": None,
        "minutes": None,  # actual minutes spent (recorded at `done`)
        "quiz": [],  # [{date, score, confidence, review}]
        "confidence": None,  # latest self-rated confidence 1..5
        "reviews": 0,  # successful spaced-repetition reviews in a row
        "next_review": None,
    }


class Lab:
    def __init__(self, today: date | None = None):
        self.cfg = yaml.safe_load(CONFIG.read_text())
        tz = self.cfg.get("timezone")
        self.today = today or (datetime.now(ZoneInfo(tz)).date() if tz else date.today())
        self.modules = yaml.safe_load(CURRICULUM.read_text())["modules"]
        self.topics: list[Topic] = []
        for m in self.modules:
            for i, t in enumerate(m["topics"], start=1):
                self.topics.append(
                    Topic(
                        id=t["id"],
                        title=t["title"],
                        difficulty=int(t["difficulty"]),
                        minutes=int(t["minutes"]),
                        prereqs=list(t.get("prereqs") or []),
                        docker=bool(t.get("docker", False)),
                        tools=list(t.get("tools") or []),
                        module_id=str(m["id"]),
                        module_slug=m["slug"],
                        module_title=m["title"],
                        index=i,
                        order=len(self.topics),
                    )
                )
        self.by_id = {t.id: t for t in self.topics}
        if PROGRESS.exists():
            self.data = json.loads(PROGRESS.read_text())
        else:
            self.data = {"version": 1, "topics": {}, "log": []}
        for t in self.topics:
            self.data["topics"].setdefault(t.id, _empty_entry())

    # ---------- persistence ----------

    def save(self) -> None:
        PROGRESS.write_text(json.dumps(self.data, indent=2) + "\n")

    def entry(self, t: Topic | str) -> dict:
        return self.data["topics"][t if isinstance(t, str) else t.id]

    def log(self, event: str, topic: str, **fields) -> None:
        self.data["log"].append(
            {"date": _iso(self.today), "ts": datetime.now().astimezone().isoformat(timespec="seconds"),
             "event": event, "topic": topic, **fields}
        )

    def resolve(self, query: str) -> Topic:
        if query in self.by_id:
            return self.by_id[query]
        q = query.lower()
        hits = [t for t in self.topics if q in t.id or q in t.title.lower()]
        if len(hits) == 1:
            return hits[0]
        if not hits:
            sys.exit(f"No topic matches '{query}'.")
        sys.exit(f"'{query}' is ambiguous: " + ", ".join(t.id for t in hits))

    # ---------- derived state ----------

    def by_status(self, status: str) -> list[Topic]:
        return [t for t in self.topics if self.entry(t)["status"] == status]

    def done_ids(self) -> set[str]:
        return {t.id for t in self.by_status("done")}

    def last_score(self, t: Topic) -> int | None:
        q = self.entry(t)["quiz"]
        return q[-1]["score"] if q else None

    def minutes_on(self, day: date) -> int:
        return sum(ev.get("minutes") or 0 for ev in self.data["log"] if ev["date"] == _iso(day))

    def activity(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for ev in self.data["log"]:
            out[ev["date"]] = out.get(ev["date"], 0) + (ev.get("minutes") or 0)
        return out

    def streak(self) -> int:
        active = {ev["date"] for ev in self.data["log"]}
        rest = set(self.cfg["pace"].get("rest_days") or [])
        d = self.today if _iso(self.today) in active else self.today - timedelta(days=1)
        n = 0
        while True:
            if _iso(d) in active:
                n += 1
            elif d.weekday() not in rest:  # rest days don't break a streak
                break
            d -= timedelta(days=1)
            if (self.today - d).days > 3660:  # safety net if every day is a rest day
                break
        return n

    def due(self, day: date | None = None) -> list[Topic]:
        day = day or self.today
        out = [t for t in self.by_status("done")
               if self.entry(t)["next_review"] and self.entry(t)["next_review"] <= _iso(day)]
        # most overdue first; among equals, the weakest (lowest last score) first
        return sorted(out, key=lambda t: (self.entry(t)["next_review"], self.last_score(t) or 0))

    def weak(self) -> list[Topic]:
        pass_score = self.cfg["review"]["pass_score"]
        out = []
        for t in self.by_status("done"):
            s, c = self.last_score(t), self.entry(t)["confidence"]
            if (s is not None and s < pass_score) or (c is not None and c <= 2):
                out.append(t)
        return out

    def pace_factors(self) -> dict:
        """How fast you've actually been going vs. the estimates, and how well it's sticking."""
        pc = self.cfg["pace"]
        done = sorted(self.by_status("done"), key=lambda t: (self.entry(t)["completed"] or "", t.order))
        recent = done[-pc["window"]:]
        timed = [t for t in recent if self.entry(t)["minutes"]]
        scores = [s for t in recent if (s := self.last_score(t)) is not None]

        time_factor, multiplier = 1.0, 1.0
        if pc["adaptive"] and len(timed) >= 2:
            raw = sum(self.entry(t)["minutes"] for t in timed) / sum(t.minutes for t in timed)
            time_factor = min(max(raw, pc["time_factor_min"]), pc["time_factor_max"])
        avg = round(mean(scores), 1) if scores else None
        if pc["adaptive"] and len(scores) >= 2:
            if avg >= pc["mastery_boost_above"]:
                multiplier = 1.15
            elif avg < pc["mastery_brake_below"]:
                multiplier = 0.85
        return {"time_factor": round(time_factor, 2), "budget_multiplier": multiplier,
                "avg_score": avg, "sample": len(recent)}

    # ---------- planning ----------

    def day_budget(self, day: date, multiplier: float) -> int:
        pc = self.cfg["pace"]
        if day.weekday() in (pc.get("rest_days") or []):
            return 0
        base = pc["weekend_minutes"] if day.weekday() >= 5 else pc["weekday_minutes"]
        return round(base * multiplier)

    def _pick(self, available: set[str], left: float, time_factor: float,
              force_first: bool, already: int = 0) -> list[Topic]:
        """Greedy, in curriculum order: batch easy topics until the budget is used;
        a deep-focus topic (difficulty >= threshold) only goes first and ends the day."""
        pc = self.cfg["pace"]
        picked: list[Topic] = []
        spent = 0.0
        for t in self.topics:
            if t.id in available or not all(p in available for p in t.prereqs):
                continue
            n = already + len(picked)
            if n >= pc["max_topics_per_day"]:
                break
            cost = t.minutes * time_factor
            hard = t.difficulty >= pc["deep_focus_difficulty"]
            first = n == 0 and force_first
            if not first and (spent + cost > left or (hard and n > 0)):
                break
            picked.append(t)
            spent += cost
            available.add(t.id)
            if hard:
                break
        return picked

    def plan(self, day: date | None = None) -> dict:
        day = day or self.today
        rc = self.cfg["review"]
        f = self.pace_factors()
        budget = self.day_budget(day, f["budget_multiplier"])
        used = self.minutes_on(day)
        left = max(budget - used, 0)

        # 1) reviews first, capped at a share of what's left (always at least one if due).
        #    When quiz scores are low, consolidating beats racing ahead: reviews get more room.
        review_share = 0.6 if f["budget_multiplier"] < 1 else 0.4
        reviews, review_min = [], 0
        for t in self.due(day):
            if reviews and review_min + rc["minutes_per_review"] > left * review_share:
                break
            reviews.append(t)
            review_min += rc["minutes_per_review"]

        # 2) finish what's in progress, 3) then new topics
        continuing = self.by_status("in-progress")
        cont_min = sum(round(t.minutes * f["time_factor"]) for t in continuing)
        available = self.done_ids() | {t.id for t in continuing}
        finished_today = any(ev["event"] == "done" and ev["date"] == _iso(day) for ev in self.data["log"])
        new = []
        if budget > 0:
            new = self._pick(set(available), left - review_min - cont_min, f["time_factor"],
                             force_first=not continuing and not finished_today, already=len(continuing))
        stretch = None
        if not new and not continuing:
            nxt = self._pick(set(available), float("inf"), 1.0, force_first=True)
            stretch = nxt[0] if nxt else None

        def item(t: Topic) -> dict:
            return {"id": t.id, "title": t.title, "module": t.module_title, "difficulty": t.difficulty,
                    "minutes": round(t.minutes * f["time_factor"]), "docker": t.docker, "path": t.rel_path,
                    "lesson_exists": (t.path / "README.md").exists()}

        planned = review_min + cont_min + sum(round(t.minutes * f["time_factor"]) for t in new)
        return {
            "date": _iso(day),
            "weekday": day.strftime("%A"),
            "rest_day": budget == 0,
            "budget": budget,
            "used": used,
            "left": left,
            "planned": planned,
            "over_budget": max(planned - left, 0) if budget > 0 else 0,
            "factors": f,
            "reviews": [{"id": t.id, "title": t.title, "minutes": rc["minutes_per_review"],
                         "due": self.entry(t)["next_review"]} for t in reviews],
            "continue": [item(t) for t in continuing],
            "new": [item(t) for t in new],
            "stretch": item(stretch) if stretch else None,
            "projection": self.projection(),
        }

    def projection(self) -> dict:
        """Simulate the remaining curriculum day by day at the current adaptive pace."""
        f = self.pace_factors()
        available = self.done_ids()
        remaining = len(self.topics) - len(available)
        if remaining == 0:
            return {"finish": None, "remaining": 0, "days": 0, "complete": True}
        day = self.today
        # today counts only for what's left of today's budget
        left_today = max(self.day_budget(day, f["budget_multiplier"]) - self.minutes_on(day), 0)
        finished_today = any(ev["event"] == "done" and ev["date"] == _iso(day) for ev in self.data["log"])
        for i in range(PROJECTION_MAX_DAYS):
            budget = left_today if i == 0 else self.day_budget(day, f["budget_multiplier"])
            if budget > 0:
                left = budget * (1 - PROJECTION_REVIEW_OVERHEAD)
                force = not (i == 0 and finished_today)
                picked = self._pick(available, left, f["time_factor"], force_first=force)
                if not picked and force and len(available) < len(self.topics):
                    return {"finish": None, "remaining": remaining, "days": None, "complete": False,
                            "blocked": True}
                if len(available) == len(self.topics):
                    return {"finish": _iso(day), "remaining": remaining, "days": i + 1, "complete": False}
            day += timedelta(days=1)
        return {"finish": None, "remaining": remaining, "days": None, "complete": False}

    # ---------- mutations ----------

    def start(self, t: Topic) -> None:
        e = self.entry(t)
        if e["status"] == "done":
            print(f"'{t.id}' is already done (use `quiz` to review it, or `reset` to redo it).")
            return
        if e["status"] == "todo":
            e["status"], e["started"] = "in-progress", _iso(self.today)
            self.log("start", t.id)
        missing = [p for p in t.prereqs if p not in self.done_ids()]
        if missing:
            print(f"note: prerequisites not done yet: {', '.join(missing)}")

    def quiz(self, t: Topic, score: int, confidence: int, minutes: int | None) -> None:
        rc = self.cfg["review"]
        e = self.entry(t)
        if e["status"] == "todo":
            self.start(t)
        review = e["status"] == "done"
        e["quiz"].append({"date": _iso(self.today), "score": score, "confidence": confidence, "review": review})
        e["confidence"] = confidence
        if review:
            if score >= rc["pass_score"]:
                e["reviews"] += 1
                days = rc["intervals_days"][min(e["reviews"], len(rc["intervals_days"]) - 1)]
            else:
                e["reviews"], days = 0, 1
            e["next_review"] = _iso(self.today + timedelta(days=days))
            minutes = rc["minutes_per_review"] if minutes is None else minutes
        self.log("quiz", t.id, score=score, confidence=confidence, review=review, minutes=minutes or 0)
        if review:
            print(f"review recorded — next review {e['next_review']}")

    def done(self, t: Topic, minutes: int) -> None:
        rc = self.cfg["review"]
        e = self.entry(t)
        if not e["quiz"]:
            print("note: no quiz recorded — run /quiz first so pacing can adapt to your scores.")
        e["status"], e["completed"], e["minutes"] = "done", _iso(self.today), minutes
        e["started"] = e["started"] or _iso(self.today)
        e["reviews"] = 0
        s = self.last_score(t)
        days = 1 if (s is not None and s < rc["pass_score"]) else rc["intervals_days"][0]
        e["next_review"] = _iso(self.today + timedelta(days=days))
        self.log("done", t.id, minutes=minutes)

    def reset(self, t: Topic) -> None:
        self.data["topics"][t.id] = _empty_entry()
        self.log("reset", t.id)

    # ---------- checks ----------

    def validate(self) -> list[str]:
        problems, seen = [], {}
        for t in self.topics:
            if t.id in seen:
                problems.append(f"duplicate id: {t.id}")
            seen[t.id] = t.order
            if not 1 <= t.difficulty <= 5:
                problems.append(f"{t.id}: difficulty must be 1..5")
        for t in self.topics:
            for p in t.prereqs:
                if p not in seen:
                    problems.append(f"{t.id}: unknown prereq '{p}'")
                elif seen[p] > t.order:
                    problems.append(f"{t.id}: prereq '{p}' comes later in the curriculum (warning)")
        orphans = set(self.data["topics"]) - set(self.by_id)
        problems += [f"progress.json has unknown topic '{o}' (removed from curriculum?)" for o in sorted(orphans)]
        return problems

    def summary(self) -> dict:
        total = len(self.topics)
        done = self.by_status("done")
        mods = []
        for m in self.modules:
            ids = [t["id"] for t in m["topics"]]
            d = sum(1 for i in ids if self.entry(i)["status"] == "done")
            mods.append({"id": m["id"], "title": m["title"], "done": d, "total": len(ids)})
        scores = [s for t in done if (s := self.last_score(t)) is not None]
        return {
            "total": total,
            "done": len(done),
            "in_progress": len(self.by_status("in-progress")),
            "percent": round(100 * len(done) / total, 1) if total else 0,
            "hours": round(sum(self.activity().values()) / 60, 1),
            "streak": self.streak(),
            "avg_score": round(mean(scores), 1) if scores else None,
            "due": len(self.due()),
            "weak": [t.id for t in self.weak()],
            "modules": mods,
            "projection": self.projection(),
            "factors": self.pace_factors(),
        }


# ---------- CLI ----------

def _dots(n: int) -> str:
    return "●" * n + "○" * (5 - n)


def print_plan(p: dict) -> None:
    f = p["factors"]
    print(f"Today — {p['weekday']} {p['date']}")
    if p["rest_day"]:
        print("  Rest day (config.yaml → pace.rest_days).")
    else:
        print(f"  Budget {p['budget']} min · used {p['used']} · left {p['left']} · planned {p['planned']}")
    mastery = f"avg quiz {f['avg_score']}%" if f["avg_score"] is not None else "avg quiz — (needs 2+ topics)"
    print(f"  Pace: time factor ×{f['time_factor']} · budget ×{f['budget_multiplier']} · {mastery}")
    if p["reviews"]:
        print("\nReviews due:")
        for r in p["reviews"]:
            print(f"  ↺ {r['id']:<28} {r['title']}  (~{r['minutes']} min, due {r['due']})")
    if p["continue"]:
        print("\nContinue:")
        for t in p["continue"]:
            print(f"  ▸ {t['id']:<28} {t['title']}  {_dots(t['difficulty'])} ~{t['minutes']} min  {t['path']}")
    if p["new"]:
        print("\nNew topics:")
        for i, t in enumerate(p["new"], 1):
            tag = " [docker]" if t["docker"] else ""
            print(f"  {i}. {t['id']:<27} {t['title']}  {_dots(t['difficulty'])} ~{t['minutes']} min{tag}")
    if p["over_budget"] and p["new"]:
        print(f"\n  Over budget by {p['over_budget']} min: every study day includes at least one new topic."
              "\n  Short on time? Do the reviews today and start the topic tomorrow.")
    if p["stretch"]:
        s = p["stretch"]
        print(f"\nDaily budget reached. Optional stretch: {s['id']} — {s['title']} (~{s['minutes']} min)")
    pr = p["projection"]
    if pr.get("complete"):
        print("\nCurriculum complete. 🎉")
    elif pr.get("finish"):
        print(f"\nProjected finish: {pr['finish']} ({pr['remaining']} topics left, at current pace)")
    elif pr.get("blocked"):
        print("\nProjection blocked: some topics have prerequisites that can never be met (run `validate`).")


def print_status(s: dict) -> None:
    print(f"Progress: {s['done']}/{s['total']} topics ({s['percent']}%) · {s['in_progress']} in progress")
    avg = f"{s['avg_score']}%" if s["avg_score"] is not None else "—"
    print(f"Time: {s['hours']} h · streak {s['streak']} day(s) · avg quiz {avg} · reviews due {s['due']}")
    if s["weak"]:
        print(f"Weak topics: {', '.join(s['weak'])}")
    print()
    for m in s["modules"]:
        bar = "█" * round(20 * m["done"] / m["total"]) if m["total"] else ""
        print(f"  {m['id']} {m['title']:<30} {bar:<20} {m['done']}/{m['total']}")
    pr = s["projection"]
    if pr.get("finish"):
        print(f"\nProjected finish: {pr['finish']}")


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="System Design Lab tracker")
    ap.add_argument("--today", help="simulate a different date (YYYY-MM-DD)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("plan", "status", "due"):
        sp = sub.add_parser(name)
        sp.add_argument("--json", action="store_true")
    sub.add_parser("sync")
    sub.add_parser("validate")
    for name in ("info", "start", "reset"):
        sub.add_parser(name).add_argument("topic")
    q = sub.add_parser("quiz")
    q.add_argument("topic")
    q.add_argument("--score", type=int, required=True, help="percent 0-100")
    q.add_argument("--confidence", type=int, required=True, choices=range(1, 6))
    q.add_argument("--minutes", type=int, help="minutes spent (reviews default to config value)")
    d = sub.add_parser("done")
    d.add_argument("topic")
    d.add_argument("--minutes", type=int, required=True)
    d.add_argument("--no-build", action="store_true", help="skip rebuilding the dashboard")
    a = ap.parse_args(argv)

    lab = Lab(_parse(a.today) if a.today else None)

    if a.cmd == "plan":
        p = lab.plan()
        print(json.dumps(p, indent=2)) if a.json else print_plan(p)
    elif a.cmd == "status":
        s = lab.summary()
        print(json.dumps(s, indent=2)) if a.json else print_status(s)
    elif a.cmd == "due":
        due, weak = lab.due(), lab.weak()
        if a.json:
            print(json.dumps({"due": [t.id for t in due], "weak": [t.id for t in weak]}, indent=2))
        else:
            print("Due for review:" if due else "Nothing due for review.")
            for t in due:
                print(f"  ↺ {t.id:<28} {t.title}  (due {lab.entry(t)['next_review']}, last score {lab.last_score(t)}%)")
            extra = [t for t in weak if t not in due]
            if extra:
                print("Weak (low score or confidence):")
                for t in extra:
                    print(f"  ! {t.id:<28} {t.title}  (score {lab.last_score(t)}%, confidence {lab.entry(t)['confidence']})")
    elif a.cmd == "info":
        t = lab.resolve(a.topic)
        e = lab.entry(t)
        print(json.dumps({
            "id": t.id, "title": t.title, "module": f"{t.module_id} {t.module_title}",
            "difficulty": t.difficulty, "minutes": t.minutes, "docker": t.docker, "tools": t.tools,
            "prereqs": {p: lab.entry(p)["status"] for p in t.prereqs},
            "path": t.rel_path, "lesson_exists": (t.path / "README.md").exists(), **e,
        }, indent=2))
    elif a.cmd == "sync":
        lab.save()
        print(f"progress.json in sync with curriculum ({len(lab.topics)} topics).")
        for p in lab.validate():
            print("  " + p)
    elif a.cmd == "validate":
        problems = lab.validate()
        print("\n".join(problems) if problems else f"OK — {len(lab.topics)} topics, no problems.")
        sys.exit(1 if any("warning" not in p for p in problems) else 0)
    else:
        t = lab.resolve(a.topic)
        if a.cmd == "start":
            lab.start(t)
            print(f"{t.id}: {lab.entry(t)['status']} → {t.rel_path}")
        elif a.cmd == "quiz":
            if not 0 <= a.score <= 100:
                sys.exit("--score is a percentage 0-100")
            lab.quiz(t, a.score, a.confidence, a.minutes)
            print(f"{t.id}: quiz {a.score}% · confidence {a.confidence}/5 recorded")
        elif a.cmd == "done":
            lab.done(t, a.minutes)
            print(f"{t.id}: done in {a.minutes} min · first review {lab.entry(t)['next_review']}")
        elif a.cmd == "reset":
            lab.reset(t)
            print(f"{t.id}: reset to todo")
        lab.save()
        if a.cmd == "done" and not a.no_build:
            from build_dashboard import build  # same folder

            build(lab)


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    main()
