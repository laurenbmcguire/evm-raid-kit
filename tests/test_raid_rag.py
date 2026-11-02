"""RAID analytics and RAG rules."""

import pandas as pd

from evmkit import rag, raid
from evmkit.config import DEFAULTS

TH = DEFAULTS["thresholds"]


def _raid():
    rows = [
        # id, type, category, owner, p, i, raised, due, status, closed_date
        ("R-1", "Risk", "Schedule", "Data Lead", 4, 4, "2026-05-01", "2026-06-30", "Open", None),
        ("R-2", "Risk", "Scope", "PMO", 3, 4, "2026-05-20", "2026-06-01", "Open", None),
        ("R-3", "Risk", "Cost", "PMO", 5, 5, "2026-04-01", "2026-05-01", "Closed", "2026-05-02"),
        ("I-1", "Issue", "Schedule", "PMO", 5, 3, "2026-06-10", "2026-06-15", "Open", None),
        ("I-2", "Issue", "Scope", "Data Lead", 5, 3, "2026-06-12", "2026-07-01", "Open", None),
        ("D-1", "Dependency", "Schedule", "Vendor", 2, 2, "2026-07-01", "2026-07-30", "Open", None),
    ]
    df = pd.DataFrame(rows, columns=["id", "type", "category", "owner", "probability", "impact",
                                     "raised", "due", "status", "closed_date"])
    df["description"] = df["id"]
    for c in ("raised", "due", "closed_date"):
        df[c] = pd.to_datetime(df[c])
    return df


def test_raid_scores_open_overdue_and_aging():
    p = raid.prepare(_raid(), "2026-06-19").set_index("id")
    assert "D-1" not in p.index                      # raised after the status date
    assert p.at["R-1", "score"] == 16 and p.at["R-1", "heat"] == "High"
    assert not p.at["R-3", "is_open"]                # closed before the status date
    assert p.at["R-2", "overdue"] and p.at["R-2", "days_overdue"] == 18
    assert p.at["I-1", "days_overdue"] == 4
    assert p.at["R-1", "age_days"] == 49 and p.at["R-1", "aging_bucket"] == "31-60 d"
    assert p.at["I-2", "aging_bucket"] == "0-14 d"
    # Before R-3 was closed it counts as open.
    assert raid.prepare(_raid(), "2026-04-15").set_index("id").at["R-3", "is_open"]


def test_raid_summary_heatmap_and_owners():
    s = raid.analyze(_raid(), "2026-06-19")
    assert s["open_total"] == 4
    assert s["overdue_count"] == 2
    assert s["open_risks_high"] == 1 and s["max_open_risk_score"] == 16
    assert s["heatmap"][3][3] == 1 and s["heatmap"][3][2] == 1   # [impact-1][prob-1]
    assert sum(map(sum, s["heatmap"])) == 2                       # open risks only
    assert s["issues_by_owner"] == {"Data Lead": 1, "PMO": 1}
    assert [r["id"] for r in s["top_risks"]] == ["R-1", "R-2"]


def test_rag_rules_thresholds():
    sch = TH["schedule"]
    assert rag.rag_schedule(0.97, 3, sch)[0] == "Green"
    assert rag.rag_schedule(0.95, 6, sch)[0] == "Amber"     # slip above 5 working days
    assert rag.rag_schedule(0.89, 2, sch)[0] == "Red"
    cost = TH["cost"]
    assert rag.rag_cost(0.96, -0.04, cost)[0] == "Green"
    assert rag.rag_cost(0.93, -0.07, cost)[0] == "Amber"
    assert rag.rag_cost(0.93, -0.12, cost)[0] == "Red"
    p = raid.prepare(_raid(), "2026-06-19")
    assert rag.rag_scope(p, TH["scope"])[0] == "Amber"      # R-2 (12) and I-2 (15)
    s = raid.analyze(_raid(), "2026-06-19")
    assert rag.rag_risk(s, TH["risk"])[0] == "Amber"        # one risk >= 15
    assert rag.rag_risk({**s, "max_open_risk_score": 20}, TH["risk"])[0] == "Red"
    assert rag.overall({"a": "Green", "b": "Amber", "c": "Green"}) == "Amber"
    assert rag.overall({"a": "Red", "b": "Amber"}) == "Red"
