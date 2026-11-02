"""End-to-end pipeline: load (or generate) data, analyse, chart and report."""

from __future__ import annotations

import json
import math
from pathlib import Path

import pandas as pd

from evmkit import charts, evm, rag, raid, report, schedule
from evmkit.config import load_config
from evmkit.cpm import cpm
from evmkit.data import generate, load_plan, load_raid, load_timesheets
from evmkit.workcal import WorkCalendar, to_date

DATA_FILES = ("plan.csv", "timesheets.csv", "raid.csv")


def ensure_data(data_dir: Path) -> bool:
    """Generate the synthetic example if any input CSV is missing. Returns True if generated."""
    if all((data_dir / f).exists() for f in DATA_FILES):
        return False
    generate(data_dir, load_config(data_dir))
    return True


def analyze(data_dir: str | Path, status_date=None) -> dict:
    """Run every analysis and return a result bundle (frames plus a JSON-ready summary)."""
    data_dir = Path(data_dir)
    cfg = load_config(data_dir)
    th = cfg["thresholds"]
    data_date = to_date(cfg["status_date"])
    sd = to_date(status_date) if status_date else data_date
    use_plan = sd == data_date

    cal = WorkCalendar(cfg["project_start"], cfg["holidays"])
    plan = evm.add_calendar_columns(load_plan(data_dir / "plan.csv"), cal)
    ts = load_timesheets(data_dir / "timesheets.csv")
    raid_df = load_raid(data_dir / "raid.csv")

    # ---- CPM on the baseline network
    cp = cpm(dict(zip(plan["id"], plan["duration"])), dict(zip(plan["id"], plan["deps"])))
    cpm_tab = cp.table
    plan = plan.join(cpm_tab[["es", "total_float", "free_float", "critical"]], on="id")
    off_network = int((plan["start_idx"] != plan["es"]).sum())

    # ---- EVM at the status date
    tasks = evm.task_table(plan, ts, cal, sd, use_plan=use_plan)
    tasks = tasks.join(plan.set_index("id")[["total_float", "free_float", "critical", "planned_start",
                                             "planned_finish", "duration"]], on="id")
    bac = float(plan["budget"].sum())
    m = evm.evm_metrics(bac, tasks["pv"].sum(), tasks["ev"].sum(), tasks["ac"].sum())

    # ---- Earned schedule
    pd_days = int(max(plan["finish_idx"].max(), cp.duration))
    pv_cum = evm.pv_cumulative(plan, cal, pd_days)
    at = cal.elapsed(sd)
    es = schedule.es_metrics(pv_cum, m["ev"], at)
    planned_finish, forecast_finish, slip = schedule.forecast_finish(cal, pd_days, es["spi_t"])

    # ---- Weekly trend
    trend_rows = []
    for d in evm.period_dates(ts, sd):
        tt = evm.task_table(plan, ts, cal, d, use_plan=use_plan and d == sd)
        pv, ev, ac = tt["pv"].sum(), tt["ev"].sum(), tt["ac"].sum()
        e = schedule.es_metrics(pv_cum, ev, cal.elapsed(d))
        trend_rows.append({
            "date": pd.Timestamp(d), "pv": pv, "ev": ev, "ac": ac,
            "spi": ev / pv if pv else math.nan, "cpi": ev / ac if ac else math.nan,
            "es_days": e["es_days"], "spi_t": e["spi_t"],
        })
    trend = pd.DataFrame(trend_rows)

    # ---- RAID and RAG
    raid_prep = raid.prepare(raid_df, sd)
    raid_sum = raid.analyze(raid_df, sd, high_score=th["risk"]["high_score"])
    rags = {}
    whys = {}
    rags["scope"], whys["scope"] = rag.rag_scope(raid_prep, th["scope"])
    rags["schedule"], whys["schedule"] = rag.rag_schedule(es["spi_t"], slip, th["schedule"])
    rags["cost"], whys["cost"] = rag.rag_cost(m["cpi"], m["vac_pct"], th["cost"])
    rags["risk"], whys["risk"] = rag.rag_risk(raid_sum, th["risk"])
    overall = rag.overall(rags)

    # ---- Watch list
    tol = 0.005
    behind = tasks[(tasks["sv"] < -tol * tasks["budget"])].sort_values("sv")
    crit_behind = behind[behind["critical"]]
    recon = None
    if use_plan:
        ts_ac = tasks.set_index("id")["ac"]
        plan_ac = plan.set_index("id")["actual_cost"]
        recon = {
            "plan_ac_total": round(float(plan_ac.sum()), 2),
            "timesheet_ac_total": round(float(ts_ac.sum()), 2),
            "max_task_abs_diff": round(float((plan_ac - ts_ac).abs().max()), 2),
        }

    summary = {
        "project": cfg["project"],
        "currency": cfg["currency"],
        "status_date": sd.isoformat(),
        "data_date": data_date.isoformat(),
        "progress_source": "plan.csv percent_complete" if use_plan else "timesheet progress snapshots",
        "project_start": to_date(cfg["project_start"]).isoformat(),
        "tasks": int(len(plan)),
        "evm": {k: _r(v) for k, v in m.items()},
        "earned_schedule": {
            **{k: _r(v) for k, v in es.items()},
            "planned_finish": planned_finish.isoformat(),
            "forecast_finish": forecast_finish.isoformat(),
            "slip_working_days": int(slip),
        },
        "cpm": {
            "duration_working_days": int(cp.duration),
            "critical_path": cp.critical_path,
            "critical_count": len(cp.critical_path),
            "tasks_off_network_dates": off_network,
            "critical_tasks_behind": [
                {"id": r.id, "name": r.name, "sv": _r(r.sv), "spi": _r(r.spi)} for r in crit_behind.itertuples()
            ],
            "max_total_float_days": int(plan["total_float"].max()),
        },
        "tasks_behind": [{"id": r.id, "name": r.name, "sv": _r(r.sv)} for r in behind.itertuples()],
        "raid": raid_sum,
        "rag": {**rags, "overall": overall, "reasons": whys},
        "reconciliation": recon,
        "trend": [
            {"date": r.date.date().isoformat(), "pv": _r(r.pv), "ev": _r(r.ev), "ac": _r(r.ac),
             "spi": _r(r.spi), "cpi": _r(r.cpi), "spi_t": _r(r.spi_t)}
            for r in trend.itertuples()
        ],
    }
    summary["decisions"] = report.decisions(summary)
    summary["headline"] = report.headline(summary)
    return {"summary": summary, "tasks": tasks, "trend": trend, "plan": plan, "pv_cum": pv_cum,
            "cal": cal, "raid": raid_prep, "cpm": cp, "thresholds": th}


def _r(v, nd: int = 4):
    if v is None:
        return None
    if isinstance(v, float) and math.isnan(v):
        return None
    if isinstance(v, (int,)) and not isinstance(v, bool):
        return v
    try:
        return round(float(v), nd)
    except (TypeError, ValueError):
        return v


def run(root: str | Path = ".", status_date=None, data_dir: str | Path | None = None,
        charts_on: bool = True) -> dict:
    """Full pipeline. Writes docs/img/*.png, reports/status_report.md and reports/summary.json."""
    root = Path(root)
    data_dir = Path(data_dir) if data_dir else root / "examples"
    generated = ensure_data(data_dir)
    res = analyze(data_dir, status_date)
    s = res["summary"]
    img_dir = root / "docs" / "img"
    rep_dir = root / "reports"
    rep_dir.mkdir(parents=True, exist_ok=True)
    if charts_on:
        s["charts"] = [str(p.relative_to(root).as_posix()) for p in charts.render_all(res, img_dir)]
    (rep_dir / "summary.json").write_text(json.dumps(s, indent=2) + "\n", encoding="utf-8")
    (rep_dir / "status_report.md").write_text(report.render_markdown(s), encoding="utf-8")
    s["_generated_data"] = generated
    return s
