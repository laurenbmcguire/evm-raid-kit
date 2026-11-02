"""Seeded synthetic data generator and validated CSV loaders.

The example is a generic "ERP data platform rollout": 20 WBS tasks, weekly timesheets and a
RAID log. It is designed to show a mild cost overrun and a slight schedule slip. Nothing in it
describes a real organisation, project or person (owners are role names).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from evmkit.config import DEFAULTS, write_config
from evmkit.cpm import cpm, parse_deps
from evmkit.workcal import WorkCalendar, to_date

PLAN_COLUMNS = ["id", "wbs", "name", "depends_on", "budget", "planned_start", "planned_finish",
                "percent_complete", "actual_cost"]
TIMESHEET_COLUMNS = ["week_ending", "task_id", "hours", "actual_cost", "percent_complete"]
RAID_COLUMNS = ["id", "type", "category", "description", "owner", "probability", "impact",
                "raised", "due", "status", "closed_date"]


@dataclass(frozen=True)
class TaskSpec:
    id: str
    wbs: str
    name: str
    deps: tuple[str, ...]
    duration: int  # working days
    budget: float  # BAC share, USD
    rate: float  # blended hourly rate, USD


TASKS: list[TaskSpec] = [
    TaskSpec("T01", "1.1", "Project charter and kickoff", (), 5, 18_000, 140),
    TaskSpec("T02", "1.2", "Requirements and data inventory", ("T01",), 15, 72_000, 125),
    TaskSpec("T03", "2.1", "Target data architecture", ("T02",), 10, 54_000, 150),
    TaskSpec("T04", "2.2", "Data model and mapping specs", ("T03",), 15, 81_000, 135),
    TaskSpec("T05", "2.3", "Security and access design", ("T03",), 10, 40_000, 150),
    TaskSpec("T06", "3.1", "Cloud landing zone setup", ("T03",), 12, 66_000, 140),
    TaskSpec("T07", "3.2", "Ingestion pipelines: Finance", ("T04", "T06"), 20, 132_000, 130),
    TaskSpec("T08", "3.3", "Ingestion pipelines: Supply chain", ("T04", "T06"), 18, 110_000, 130),
    TaskSpec("T09", "3.4", "Ingestion pipelines: HR", ("T04", "T06"), 12, 64_000, 130),
    TaskSpec("T10", "3.5", "Master data services", ("T04",), 15, 78_000, 135),
    TaskSpec("T11", "3.6", "Data quality rules", ("T07", "T10"), 10, 52_000, 125),
    TaskSpec("T12", "3.7", "Semantic layer and reporting marts", ("T07", "T08"), 15, 96_000, 135),
    TaskSpec("T13", "4.1", "System integration testing", ("T05", "T09", "T11", "T12"), 10, 70_000, 115),
    TaskSpec("T14", "4.2", "Data reconciliation with Finance", ("T13",), 8, 44_000, 120),
    TaskSpec("T15", "4.3", "Performance testing", ("T13",), 5, 30_000, 130),
    TaskSpec("T16", "4.4", "User acceptance testing", ("T14",), 10, 56_000, 110),
    TaskSpec("T17", "5.1", "Training and change management", ("T12",), 15, 48_000, 105),
    TaskSpec("T18", "5.2", "Cutover rehearsal", ("T15", "T16"), 5, 28_000, 130),
    TaskSpec("T19", "5.3", "Production cutover", ("T17", "T18"), 3, 24_000, 140),
    TaskSpec("T20", "5.4", "Hypercare and handover", ("T19",), 10, 42_000, 120),
]

# Mean duration growth by WBS phase (build runs long, design a little long).
PHASE_DURATION_MEAN = {1: 1.02, 2: 1.05, 3: 1.09, 4: 1.06, 5: 1.05}

# (id, type, category, description, owner, probability, impact, raised_offset, due_offset,
#  closed_offset or None, open status). Offsets are calendar days from project start.
RAID_ITEMS = [
    ("R-01", "Risk", "Schedule", "ERP vendor change-data-capture extracts for the general ledger arrive later than planned",
     "Data Lead", 4, 4, 20, 120, None, "In progress"),
    ("R-02", "Risk", "Technical", "Legacy supplier master data has a higher defect rate than profiled, adding DQ rework",
     "Data Quality Lead", 4, 3, 35, 130, None, "Open"),
    ("R-03", "Risk", "Resource", "Loss of a senior data engineer during build would delay the ingestion pipelines",
     "PMO", 2, 4, 10, 150, None, "Open"),
    ("R-04", "Risk", "Cost", "Cloud consumption above estimate because of unoptimised full reloads",
     "Infra Lead", 3, 3, 45, 100, None, "Open"),
    ("R-05", "Risk", "Schedule", "UAT window overlaps quarter-end close, limiting Finance tester availability",
     "Test Manager", 3, 4, 60, 140, None, "Open"),
    ("R-06", "Risk", "Scope", "Additional HR analytics reports requested outside the agreed scope",
     "Change Lead", 3, 3, 70, 125, None, "Open"),
    ("R-07", "Risk", "Schedule", "Security accreditation of the production environment takes longer than planned",
     "Security Architect", 3, 5, 40, 115, None, "In progress"),
    ("R-08", "Risk", "Scope", "Finance reconciliation tolerances not yet agreed, risking disputes at UAT exit",
     "Finance SME", 3, 4, 55, 95, None, "Open"),
    ("R-09", "Risk", "Technical", "Semantic layer query performance at month-end volumes not yet proven",
     "Data Architect", 2, 4, 50, 160, None, "Open"),
    ("R-10", "Risk", "Cost", "Platform licence renewal falls mid-project at a higher list price",
     "Vendor Manager", 2, 2, 15, 60, 58, "Open"),
    ("R-11", "Risk", "Technical", "Integration test environment instability",
     "Infra Lead", 3, 3, 25, 75, 80, "Open"),
    ("I-01", "Issue", "Schedule", "Finance ingestion behind plan: undocumented ledger mappings found during build",
     "Data Lead", 5, 4, 88, 105, None, "In progress"),
    ("I-02", "Issue", "Resource", "Test data masking tool licence not yet procured",
     "PMO", 5, 3, 74, 98, None, "Open"),
    ("I-03", "Issue", "Technical", "Supply chain API rate limits slowed the initial full loads",
     "Integration Lead", 5, 2, 66, 84, 83, "Open"),
    ("I-04", "Issue", "Cost", "Contractor day rates increased mid-project after vendor renegotiation",
     "PMO", 5, 3, 80, 120, None, "Open"),
    ("I-05", "Issue", "Scope", "Two data mapping specifications reopened after sign-off",
     "Data Architect", 5, 2, 92, 112, None, "In progress"),
    ("A-01", "Assumption", "Resource", "Business SMEs are available two days per week through UAT",
     "Change Lead", 3, 4, 5, 170, None, "Open"),
    ("A-02", "Assumption", "Scope", "Legacy ERP configuration stays frozen during the build phase",
     "Data Lead", 2, 4, 5, 150, None, "Open"),
    ("A-03", "Assumption", "Technical", "Enterprise landing zone pattern can be reused without changes",
     "Infra Lead", 2, 3, 8, 50, 45, "Open"),
    ("D-01", "Dependency", "Schedule", "Enterprise IAM team delivers SSO integration before SIT starts",
     "Security Architect", 3, 4, 30, 118, None, "Open"),
    ("D-02", "Dependency", "Schedule", "ERP vendor ships the CDC connector patch for ledger tables",
     "Vendor Manager", 4, 4, 62, 102, None, "Open"),
    ("D-03", "Dependency", "Technical", "Network team opens firewall rules for ingestion endpoints",
     "Infra Lead", 3, 3, 28, 52, 50, "Open"),
    ("D-04", "Dependency", "Schedule", "Finance confirms the quarter-end close calendar for UAT planning",
     "Finance SME", 2, 3, 85, 125, None, "Open"),
]


def _report_pct(done: int, total: int) -> int:
    """Progress as people report it: 5% steps, 100 only when finished."""
    if done <= 0:
        return 0
    if done >= total:
        return 100
    return int(min(95, max(5, 5 * round(20 * done / total))))


def generate(data_dir: str | Path, config: dict | None = None, seed: int | None = None) -> dict:
    """Write plan.csv, timesheets.csv, raid.csv (and project.yml if missing) to ``data_dir``."""
    cfg = config or DEFAULTS
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(cfg["seed"] if seed is None else seed)
    start = to_date(cfg["project_start"])
    status = to_date(cfg["status_date"])
    cal = WorkCalendar(start, cfg["holidays"])
    spec = {t.id: t for t in TASKS}

    base = cpm({t.id: t.duration for t in TASKS}, {t.id: list(t.deps) for t in TASKS})

    # Simulated actuals: tasks start at max(baseline ES, actual finish of predecessors).
    a_es: dict[str, int] = {}
    a_ef: dict[str, int] = {}
    burn: dict[str, float] = {}
    for tid in base.order:
        t = spec[tid]
        phase = int(t.wbs.split(".")[0])
        factor = float(np.clip(rng.normal(PHASE_DURATION_MEAN[phase], 0.04), 0.95, 1.25))
        cost_factor = float(np.clip(rng.normal(1.0, 0.03), 0.92, 1.10))
        a_es[tid] = max([int(base.table.at[tid, "es"])] + [a_ef[p] for p in t.deps])
        a_ef[tid] = a_es[tid] + max(1, int(round(t.duration * factor)))
        burn[tid] = t.budget / t.duration * cost_factor

    # Weekly timesheets (Friday week endings) up to the status date.
    n_status = cal.elapsed(status)
    first_friday = pd.Timestamp(start) + pd.Timedelta(days=(4 - start.weekday()) % 7)
    weeks = [d.date() for d in pd.date_range(first_friday, status, freq="7D")]
    if not weeks or weeks[-1] != status:
        weeks.append(status)
    rows = []
    prev_hi = 0
    for w in weeks:
        hi = min(cal.elapsed(w), n_status)
        lo = prev_hi
        prev_hi = hi
        for tid in base.order:
            active = max(0, min(hi, a_ef[tid]) - max(lo, a_es[tid]))
            if active <= 0:
                continue
            noise = float(rng.normal(0.0, 0.05))
            cost = round(active * burn[tid] * (1.0 + noise), 2)
            done = min(max(hi - a_es[tid], 0), a_ef[tid] - a_es[tid])
            rows.append(
                {
                    "week_ending": w.isoformat(),
                    "task_id": tid,
                    "hours": round(cost / spec[tid].rate, 1),
                    "actual_cost": cost,
                    "percent_complete": _report_pct(done, a_ef[tid] - a_es[tid]),
                }
            )
    ts = pd.DataFrame(rows, columns=TIMESHEET_COLUMNS)

    ac_total = ts.groupby("task_id")["actual_cost"].sum()
    pct_last = ts.groupby("task_id")["percent_complete"].last()
    plan_rows = []
    for tid in base.order:
        t = spec[tid]
        es, ef = int(base.table.at[tid, "es"]), int(base.table.at[tid, "ef"])
        plan_rows.append(
            {
                "id": tid,
                "wbs": t.wbs,
                "name": t.name,
                "depends_on": ";".join(t.deps),
                "budget": t.budget,
                "planned_start": cal.date_at(es).isoformat(),
                "planned_finish": cal.date_at(ef - 1).isoformat(),
                "percent_complete": int(pct_last.get(tid, 0)),
                "actual_cost": round(float(ac_total.get(tid, 0.0)), 2),
            }
        )
    plan = pd.DataFrame(plan_rows, columns=PLAN_COLUMNS).sort_values("wbs", key=_wbs_key)

    start_ts = pd.Timestamp(start)
    raid_rows = []
    for (rid, typ, cat, desc, owner, p, i, r_off, d_off, c_off, st) in RAID_ITEMS:
        raised = start_ts + pd.Timedelta(days=r_off)
        closed = start_ts + pd.Timedelta(days=c_off) if c_off is not None else None
        if raised.date() > status:
            continue
        is_closed = closed is not None and closed.date() <= status
        raid_rows.append(
            {
                "id": rid, "type": typ, "category": cat, "description": desc, "owner": owner,
                "probability": p, "impact": i,
                "raised": raised.date().isoformat(),
                "due": (start_ts + pd.Timedelta(days=d_off)).date().isoformat(),
                "status": "Closed" if is_closed else st,
                "closed_date": closed.date().isoformat() if is_closed else "",
            }
        )
    raid = pd.DataFrame(raid_rows, columns=RAID_COLUMNS)

    plan.to_csv(data_dir / "plan.csv", index=False)
    ts.to_csv(data_dir / "timesheets.csv", index=False)
    raid.to_csv(data_dir / "raid.csv", index=False)
    if not (data_dir / "project.yml").exists():
        write_config(data_dir, cfg)
    return {"plan": len(plan), "timesheets": len(ts), "raid": len(raid)}


def _wbs_key(s: pd.Series) -> pd.Series:
    return s.map(lambda w: tuple(int(x) for x in str(w).split(".")))


# ------------------------------------------------------------------- loaders
def _require(df: pd.DataFrame, cols: list[str], name: str) -> None:
    missing = [c for c in cols if c not in df.columns]
    if missing:
        raise ValueError(f"{name} is missing required column(s): {', '.join(missing)}")


def load_plan(path: str | Path) -> pd.DataFrame:
    df = pd.read_csv(path, dtype={"id": str, "wbs": str, "depends_on": str})
    _require(df, PLAN_COLUMNS, "plan.csv")
    df["depends_on"] = df["depends_on"].fillna("").astype(str)
    df["deps"] = df["depends_on"].map(parse_deps)
    for c in ("planned_start", "planned_finish"):
        df[c] = pd.to_datetime(df[c])
    df["budget"] = df["budget"].astype(float)
    df["percent_complete"] = df["percent_complete"].astype(float).clip(0, 100)
    df["actual_cost"] = df["actual_cost"].fillna(0).astype(float)
    if (df["planned_finish"] < df["planned_start"]).any():
        raise ValueError("plan.csv has tasks that finish before they start")
    return df.reset_index(drop=True)


def load_timesheets(path: str | Path) -> pd.DataFrame:
    df = pd.read_csv(path, dtype={"task_id": str})
    _require(df, ["week_ending", "task_id", "actual_cost"], "timesheets.csv")
    df["week_ending"] = pd.to_datetime(df["week_ending"])
    df["actual_cost"] = df["actual_cost"].astype(float)
    return df


def load_raid(path: str | Path) -> pd.DataFrame:
    df = pd.read_csv(path, dtype={"id": str, "owner": str, "status": str, "category": str})
    _require(df, ["id", "type", "description", "owner", "probability", "impact", "raised", "due", "status"],
             "raid.csv")
    if "category" not in df:
        df["category"] = "General"
    if "closed_date" not in df:
        df["closed_date"] = pd.NaT
    for c in ("raised", "due", "closed_date"):
        df[c] = pd.to_datetime(df[c])
    df["probability"] = df["probability"].astype(int).clip(1, 5)
    df["impact"] = df["impact"].astype(int).clip(1, 5)
    bad = set(df["type"]) - {"Risk", "Assumption", "Issue", "Dependency"}
    if bad:
        raise ValueError(f"raid.csv has unknown type(s): {sorted(bad)}")
    return df
