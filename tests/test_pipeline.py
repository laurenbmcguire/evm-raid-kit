"""End-to-end pipeline on freshly generated synthetic data."""

import json

import pandas as pd
import pytest

from evmkit.data import generate, load_timesheets
from evmkit.pipeline import analyze, run


@pytest.fixture(scope="module")
def project_root(tmp_path_factory):
    root = tmp_path_factory.mktemp("repo")
    run(root)  # generates examples/ because they are missing
    return root


def test_generator_is_deterministic(tmp_path):
    generate(tmp_path / "a")
    generate(tmp_path / "b")
    for f in ("plan.csv", "timesheets.csv", "raid.csv"):
        assert (tmp_path / "a" / f).read_text() == (tmp_path / "b" / f).read_text()
    plan = pd.read_csv(tmp_path / "a" / "plan.csv")
    assert len(plan) == 20 and plan["budget"].sum() == 1_205_000


def test_pipeline_outputs_and_scenario(project_root):
    for f in ("plan.csv", "timesheets.csv", "raid.csv", "project.yml"):
        assert (project_root / "examples" / f).exists()
    for f in ("s_curves.png", "cpi_spi_trend.png", "risk_heatmap.png", "raid_aging.png", "gantt.png"):
        assert (project_root / "docs" / "img" / f).stat().st_size > 10_000
    s = json.loads((project_root / "reports" / "summary.json").read_text())
    e, es = s["evm"], s["earned_schedule"]
    # Designed scenario: mild cost overrun and a slight slip.
    assert 0.90 < e["cpi"] < 0.97 and e["eac_cpi"] > e["bac"]
    assert 0.90 < es["spi_t"] < 1.0 and es["slip_working_days"] > 0
    # Internal consistency of the reported numbers.
    assert e["eac_cpi"] == pytest.approx(e["bac"] / e["cpi"], rel=1e-3)
    assert e["etc"] == pytest.approx(e["eac_cpi"] - e["ac"], abs=1)
    assert s["reconciliation"]["max_task_abs_diff"] == 0
    assert s["cpm"]["tasks_off_network_dates"] == 0
    report = (project_root / "reports" / "status_report.md").read_text()
    for heading in ("## RAG", "## Key metrics", "## Top risks", "## Decisions needed"):
        assert heading in report


def test_pipeline_is_deterministic(project_root):
    before = (project_root / "reports" / "summary.json").read_text()
    run(project_root)
    assert (project_root / "reports" / "summary.json").read_text() == before


def test_status_date_override_uses_timesheet_history(project_root):
    data = project_root / "examples"
    res = analyze(data, status_date="2026-05-15")
    s = res["summary"]
    ts = load_timesheets(data / "timesheets.csv")
    assert s["progress_source"] == "timesheet progress snapshots"
    assert s["evm"]["ac"] == pytest.approx(ts.loc[ts["week_ending"] <= "2026-05-15", "actual_cost"].sum(),
                                           rel=1e-6)
    assert s["evm"]["ev"] < analyze(data)["summary"]["evm"]["ev"]
