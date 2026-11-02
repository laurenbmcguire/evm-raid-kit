"""AI Project Manager: manages this repo as a project.

Reads ``project/ROADMAP.yml``, ``project/RISKS.yml`` and the pipeline's ``reports/summary.json``,
runs a deterministic engine (health RAG, milestones, risk register, next actions, data bullets,
decision log) and writes ``project/STATUS.md`` and ``project/status.json``.

If ``ANTHROPIC_API_KEY`` is set, an executive summary is requested from the Anthropic Messages API
(standard-library ``urllib`` only), grounded only in the computed facts. Any error, or no key,
falls back to a deterministic template. The LLM can never fail the run.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import urllib.request
from pathlib import Path

import yaml

PRIORITY_RANK = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
API_URL = "https://api.anthropic.com/v1/messages"
DEFAULT_MODEL = "claude-sonnet-4-5"


# ------------------------------------------------------------------ inputs
def load_inputs(root: str | Path) -> tuple[dict, dict, dict | None]:
    root = Path(root)
    with open(root / "project" / "ROADMAP.yml", encoding="utf-8") as fh:
        roadmap = yaml.safe_load(fh) or {}
    with open(root / "project" / "RISKS.yml", encoding="utf-8") as fh:
        risks = yaml.safe_load(fh) or {}
    summary_path = root / "reports" / "summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8")) if summary_path.exists() else None
    return roadmap, risks, summary


def _d(v) -> dt.date:
    return v if isinstance(v, dt.date) else dt.date.fromisoformat(str(v))


# ------------------------------------------------------------------ engine
def heat(score: int) -> str:
    if score >= 15:
        return "High"
    if score >= 8:
        return "Medium"
    return "Low"


def milestone_table(roadmap: dict, today: dt.date) -> list[dict]:
    items = roadmap.get("backlog", [])
    out = []
    for m in roadmap.get("milestones", []):
        linked = [b for b in items if b.get("milestone") == m["id"]]
        if m["status"] == "done":
            pct = 100
        elif linked:
            pct = round(100 * sum(b["status"] == "done" for b in linked) / len(linked))
        else:
            pct = 50 if m["status"] == "in_progress" else 0
        due = _d(m["due"])
        out.append({
            "id": m["id"], "name": m["name"], "due": due.isoformat(), "status": m["status"],
            "pct_done": int(pct), "overdue": m["status"] != "done" and due < today,
            "done_criteria": m.get("done_criteria", ""),
        })
    return out


def risk_register(risks: dict) -> list[dict]:
    rows = []
    for r in risks.get("risks", []):
        score = int(r["probability"]) * int(r["impact"])
        rows.append({**r, "score": score, "heat": heat(score)})
    return sorted(rows, key=lambda r: (-r["score"], -int(r["impact"]), r["id"]))


def next_actions(roadmap: dict, n: int = 3) -> list[dict]:
    """Unblocked ``todo`` items ranked by priority, then by dependencies satisfied, then id."""
    items = roadmap.get("backlog", [])
    status = {b["id"]: b["status"] for b in items}
    ready = []
    for b in items:
        if b["status"] != "todo":
            continue
        deps = b.get("depends_on") or []
        if all(status.get(d) == "done" for d in deps):
            ready.append((PRIORITY_RANK.get(b["priority"], 9), -len(deps), b["id"], b))
    ready.sort(key=lambda t: t[:3])
    return [t[3] for t in ready[:n]]


def health(milestones: list[dict], roadmap: dict, register: list[dict]) -> tuple[str, str]:
    overdue = [m["id"] for m in milestones if m["overdue"]]
    p0_open = [b["id"] for b in roadmap.get("backlog", []) if b["priority"] == "P0" and b["status"] != "done"]
    open_risks = [r for r in register if str(r.get("status", "open")).lower() != "closed"]
    hi = [r["id"] for r in open_risks if r["score"] >= 15]
    crit = [r["id"] for r in open_risks if r["score"] >= 20]
    reasons = []
    if overdue:
        reasons.append(f"{len(overdue)} overdue milestone(s) ({', '.join(overdue)})")
    if p0_open:
        reasons.append(f"{len(p0_open)} open P0 item(s) ({', '.join(p0_open)})")
    if hi:
        reasons.append(f"{len(hi)} risk(s) scored >= 15 ({', '.join(hi)})")
    if len(overdue) >= 2 or (overdue and p0_open) or crit:
        rag = "Red"
    elif overdue or p0_open or hi:
        rag = "Amber"
    else:
        rag = "Green"
    reason = "; ".join(reasons) if reasons else "no overdue milestones, no open P0 items, no risk scored >= 15"
    return rag, reason


def data_bullets(summary: dict | None) -> list[str]:
    if not summary:
        return ["No pipeline results found; run `python -m evmkit run` first."]
    e, es, c, rd, r = (summary["evm"], summary["earned_schedule"], summary["cpm"], summary["raid"],
                       summary["rag"])
    behind = ", ".join(t["id"] for t in c["critical_tasks_behind"]) or "none"
    top = rd["top_risks"][0] if rd["top_risks"] else None
    out = [
        f"EVM at {summary['status_date']}: CPI {e['cpi']:.2f}, SPI {e['spi']:.2f}; EAC (BAC/CPI) "
        f"${e['eac_cpi'] / 1e6:.2f}M vs BAC ${e['bac'] / 1e6:.2f}M (VAC {e['vac_pct']:+.1%}).",
        f"Earned schedule: SPI(t) {es['spi_t']:.2f} forecasts finish {es['forecast_finish']}, "
        f"{es['slip_working_days']:+d} working days vs the {es['planned_finish']} baseline.",
        f"Critical path: {c['critical_count']} of {summary['tasks']} tasks; critical tasks behind plan: {behind}.",
        f"RAID: {rd['open_total']} open items, {rd['overdue_count']} overdue; {rd['open_risks_high']} open "
        f"risk(s) scored >= 15" + (f" (top {top['id']}, score {top['score']})." if top else "."),
        f"Report RAG: scope {r['scope']}, schedule {r['schedule']}, cost {r['cost']}, risk {r['risk']} "
        f"-> overall {r['overall']}.",
    ]
    return out


def decision_entry(today: dt.date, rag: str, reason: str, actions: list[dict]) -> str:
    focus = actions[0] if actions else None
    nxt = f"next focus {focus['id']} ({focus['title']}, {focus['priority']})" if focus else "no unblocked work"
    return f"{today.isoformat()}: health {rag} ({reason}); {nxt}."


def compute(roadmap: dict, risks: dict, summary: dict | None, today: dt.date) -> dict:
    ms = milestone_table(roadmap, today)
    reg = risk_register(risks)
    acts = next_actions(roadmap)
    rag, reason = health(ms, roadmap, reg)
    backlog = roadmap.get("backlog", [])
    return {
        "date": today.isoformat(),
        "project": roadmap.get("project", "evm-raid-kit"),
        "health": {"rag": rag, "reason": reason},
        "milestones": ms,
        "backlog_counts": {s: sum(b["status"] == s for b in backlog) for s in ("todo", "doing", "done")},
        "risks": reg,
        "next_actions": [{k: a.get(k) for k in ("id", "title", "priority", "owner", "depends_on")} for a in acts],
        "data_says": data_bullets(summary),
        "decision_log": decision_entry(today, rag, reason, acts),
    }


# ------------------------------------------------------------- summaries
def template_summary(f: dict) -> str:
    ms = f["milestones"]
    done = sum(m["status"] == "done" for m in ms)
    nxt = ", ".join(f"{a['id']} {a['title']}" for a in f["next_actions"]) or "none"
    top = f["risks"][0] if f["risks"] else None
    bc = f["backlog_counts"]
    data = f["data_says"][0] if f["data_says"] else ""
    return (
        f"Project health is {f['health']['rag']}: {f['health']['reason']}. "
        f"{done} of {len(ms)} milestones are done and the backlog holds {bc['todo']} todo, "
        f"{bc['doing']} in progress and {bc['done']} done items. "
        f"The next three actions are {nxt}. "
        + (f"The highest project risk is {top['id']} ({top['risk']}) with score {top['score']}, "
           f"owned by {top['owner']}. " if top else "")
        + f"On the sample data the pipeline reports: {data} "
        "All figures are computed from the repository's synthetic example data."
    )


def build_prompt(facts: dict) -> str:
    return (
        "You are the AI project manager for a software repository. Write a 90-120 word executive "
        "summary of project status for a busy stakeholder. Use ONLY the facts in the JSON below; do not "
        "invent numbers, dates, people or outcomes. Plain prose, no headings, no bullet points.\n\n"
        f"FACTS JSON:\n{json.dumps(facts, indent=2, default=str)}"
    )


def llm_summary(facts: dict, api_key: str, model: str, timeout: float = 30.0) -> str | None:
    """Call the Anthropic Messages API. Returns None on any problem."""
    body = {
        "model": model,
        "max_tokens": 400,
        "messages": [{"role": "user", "content": build_prompt(facts)}],
    }
    req = urllib.request.Request(
        API_URL,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        text = "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text").strip()
        return text or None
    except Exception:  # noqa: BLE001 - the LLM must never fail the run
        return None


def executive_summary(facts: dict, use_llm: bool = True) -> tuple[str, str]:
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if use_llm and key:
        model = os.environ.get("AI_PM_MODEL", DEFAULT_MODEL)
        text = llm_summary(facts, key, model)
        if text:
            return text, f"LLM ({model}), grounded in the facts below"
    return template_summary(facts), "deterministic template"


# ---------------------------------------------------------------- output
def render_markdown(f: dict, summary_text: str, source: str) -> str:
    L: list[str] = []
    a = L.append
    a(f"# Project status: {f['project']}")
    a("")
    a(f"Date: **{f['date']}** | Health: **{f['health']['rag'].upper()}** | Generated by the AI PM "
      f"(`python -m evmkit pm`)")
    a("")
    a(f"> {f['health']['rag']}: {f['health']['reason']}.")
    a("")
    a("## Executive summary")
    a("")
    a(summary_text)
    a("")
    a(f"<sub>Source: {source}.</sub>")
    a("")
    a("## Milestones")
    a("")
    a("| ID | Milestone | Due | Status | % done |")
    a("|---|---|---|---|---:|")
    for m in f["milestones"]:
        flag = " (overdue)" if m["overdue"] else ""
        a(f"| {m['id']} | {m['name']} | {m['due']} | {m['status']}{flag} | {m['pct_done']}% |")
    a("")
    a("## Next 3 actions")
    a("")
    a("| # | ID | Action | Priority | Owner |")
    a("|---|---|---|---|---|")
    for i, x in enumerate(f["next_actions"], 1):
        a(f"| {i} | {x['id']} | {x['title']} | {x['priority']} | {x['owner']} |")
    a("")
    a("## Risk register")
    a("")
    a("| ID | Risk | P | I | Score | Heat | Owner | Mitigation | Status |")
    a("|---|---|:-:|:-:|:-:|---|---|---|---|")
    for r in f["risks"]:
        a(f"| {r['id']} | {r['risk']} | {r['probability']} | {r['impact']} | {r['score']} | {r['heat']} | "
          f"{r['owner']} | {r['mitigation']} | {r['status']} |")
    a("")
    a("## What the data says")
    a("")
    for b in f["data_says"]:
        a(f"- {b}")
    a("")
    a("## Decision / change log")
    a("")
    a(f"- {f['decision_log']}")
    a("")
    return "\n".join(L)


def run(root: str | Path = ".", today: dt.date | None = None, use_llm: bool = True) -> dict:
    root = Path(root)
    today = today or dt.date.today()
    roadmap, risks, summary = load_inputs(root)
    facts = compute(roadmap, risks, summary, today)
    text, source = executive_summary(facts, use_llm=use_llm)
    facts["executive_summary"] = text
    facts["executive_summary_source"] = source
    out = root / "project"
    (out / "STATUS.md").write_text(render_markdown(facts, text, source), encoding="utf-8")
    (out / "status.json").write_text(json.dumps(facts, indent=2, default=str) + "\n", encoding="utf-8")
    return facts
