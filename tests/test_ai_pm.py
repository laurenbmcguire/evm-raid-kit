"""AI PM deterministic engine and LLM fallback (no network)."""

import datetime as dt
import io
import json
import shutil
from pathlib import Path

import pytest
import yaml

from evmkit import ai_pm

REPO = Path(__file__).resolve().parents[1]
TODAY = dt.date(2026, 11, 2)


def _roadmap():
    return {
        "milestones": [
            {"id": "M1", "name": "Engine", "due": "2026-10-01", "status": "done"},
            {"id": "M2", "name": "Import", "due": "2026-10-20", "status": "in_progress"},
            {"id": "M3", "name": "BI", "due": "2026-12-01", "status": "planned"},
        ],
        "backlog": [
            {"id": "B1", "title": "a", "priority": "P1", "status": "done", "owner": "AI PM", "milestone": "M2", "depends_on": []},
            {"id": "B2", "title": "b", "priority": "P1", "status": "todo", "owner": "AI PM", "milestone": "M2", "depends_on": []},
            {"id": "B3", "title": "c", "priority": "P1", "status": "todo", "owner": "Lauren", "milestone": "M2", "depends_on": ["B1"]},
            {"id": "B4", "title": "d", "priority": "P0", "status": "todo", "owner": "Lauren", "milestone": "M3", "depends_on": ["B2"]},
            {"id": "B5", "title": "e", "priority": "P2", "status": "todo", "owner": "AI PM", "milestone": "M3", "depends_on": []},
            {"id": "B6", "title": "f", "priority": "P3", "status": "todo", "owner": "AI PM", "milestone": "M3", "depends_on": []},
        ],
    }


RISKS = {"risks": [
    {"id": "R1", "risk": "x", "probability": 2, "impact": 3, "owner": "AI PM", "mitigation": "m", "status": "open"},
    {"id": "R2", "risk": "y", "probability": 4, "impact": 4, "owner": "Lauren", "mitigation": "m", "status": "open"},
]}


def test_engine_health_milestones_risks_and_actions():
    f = ai_pm.compute(_roadmap(), RISKS, None, TODAY)
    ms = {m["id"]: m for m in f["milestones"]}
    assert ms["M2"]["overdue"] and ms["M2"]["pct_done"] == 33   # 1 of 3 linked items done
    assert ms["M1"]["pct_done"] == 100 and not ms["M3"]["overdue"]
    # One overdue milestone and an open P0 -> Red.
    assert f["health"]["rag"] == "Red"
    assert [r["id"] for r in f["risks"]] == ["R2", "R1"] and f["risks"][0]["heat"] == "High"
    # B4 (P0) is blocked by B2; P1 ties break on dependencies satisfied (B3 has one).
    assert [a["id"] for a in f["next_actions"]] == ["B3", "B2", "B5"]
    assert f["decision_log"].startswith("2026-11-02: health Red")


def test_health_green_and_amber_rules():
    rm = _roadmap()
    rm["milestones"][1]["due"] = "2026-12-01"
    rm["backlog"][3]["priority"] = "P1"
    low = {"risks": [RISKS["risks"][0]]}
    assert ai_pm.compute(rm, low, None, TODAY)["health"]["rag"] == "Green"
    assert ai_pm.compute(rm, RISKS, None, TODAY)["health"]["rag"] == "Amber"  # risk score 16


@pytest.fixture()
def repo_copy(tmp_path):
    shutil.copytree(REPO / "project", tmp_path / "project")
    (tmp_path / "reports").mkdir()
    summary = REPO / "reports" / "summary.json"
    if summary.exists():
        shutil.copy(summary, tmp_path / "reports" / "summary.json")
    return tmp_path


def test_run_without_key_is_deterministic(repo_copy, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    f1 = ai_pm.run(repo_copy, today=TODAY)
    text1 = (repo_copy / "project" / "STATUS.md").read_text()
    ai_pm.run(repo_copy, today=TODAY)
    assert (repo_copy / "project" / "STATUS.md").read_text() == text1
    assert f1["executive_summary_source"] == "deterministic template"
    assert "## Next 3 actions" in text1 and "2026-11-02" in text1
    data = json.loads((repo_copy / "project" / "status.json").read_text())
    assert data["health"]["rag"] in {"Green", "Amber", "Red"} and len(data["next_actions"]) <= 3
    roadmap = yaml.safe_load((repo_copy / "project" / "ROADMAP.yml").read_text())
    assert len(data["milestones"]) == len(roadmap["milestones"])


def test_llm_error_falls_back_and_success_is_used(repo_copy, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    def boom(*a, **k):
        raise OSError("network disabled in tests")

    monkeypatch.setattr(ai_pm.urllib.request, "urlopen", boom)
    f = ai_pm.run(repo_copy, today=TODAY)
    assert f["executive_summary_source"] == "deterministic template"

    class FakeResp(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    seen = {}

    def fake(req, timeout=0):
        seen["headers"] = dict(req.header_items())
        seen["body"] = json.loads(req.data)
        return FakeResp(json.dumps({"content": [{"type": "text", "text": "Grounded summary."}]}).encode())

    monkeypatch.setattr(ai_pm.urllib.request, "urlopen", fake)
    monkeypatch.setenv("AI_PM_MODEL", "claude-test")
    f = ai_pm.run(repo_copy, today=TODAY)
    assert f["executive_summary"] == "Grounded summary."
    assert seen["body"]["model"] == "claude-test"
    assert seen["headers"]["Anthropic-version"] == "2023-06-01"
    assert seen["headers"]["X-api-key"] == "test-key"
