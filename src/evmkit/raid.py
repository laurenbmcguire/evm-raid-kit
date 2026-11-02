"""RAID log analytics: risk scoring, 5x5 heatmap, overdue and aging items, issues by owner."""

from __future__ import annotations

import pandas as pd

from evmkit.workcal import to_date

TYPES = ["Risk", "Assumption", "Issue", "Dependency"]
AGING_BUCKETS = [(0, 14, "0-14 d"), (15, 30, "15-30 d"), (31, 60, "31-60 d"), (61, 10**9, "61+ d")]


def heat_label(score: float) -> str:
    """Heat label for a probability x impact score on 1-5 x 1-5 scales."""
    if score >= 15:
        return "High"
    if score >= 8:
        return "Medium"
    return "Low"


def aging_bucket(age_days: int) -> str:
    for lo, hi, label in AGING_BUCKETS:
        if lo <= age_days <= hi:
            return label
    return AGING_BUCKETS[0][2]


def prepare(raid: pd.DataFrame, status_date) -> pd.DataFrame:
    """Add score, open flag, age and overdue status as of ``status_date``.

    An item is open at the status date if it was raised on or before it and was not
    closed on or before it (``closed_date``; a ``Closed`` status without a date counts as closed).
    """
    sd = pd.Timestamp(to_date(status_date))
    df = raid[raid["raised"] <= sd].copy()
    df["score"] = (df["probability"] * df["impact"]).astype(int)
    closed_date = df["closed_date"] if "closed_date" in df else pd.Series(pd.NaT, index=df.index)
    closed_by_date = closed_date.notna() & (closed_date <= sd)
    closed_no_date = closed_date.isna() & (df["status"].str.lower() == "closed")
    df["is_open"] = ~(closed_by_date | closed_no_date)
    df["age_days"] = (sd - df["raised"]).dt.days.astype(int)
    df["overdue"] = df["is_open"] & df["due"].notna() & (df["due"] < sd)
    df["days_overdue"] = ((sd - df["due"]).dt.days.where(df["overdue"], 0)).fillna(0).astype(int)
    df["aging_bucket"] = [aging_bucket(a) for a in df["age_days"]]
    df["heat"] = [heat_label(s) for s in df["score"]]
    return df


def heatmap(df: pd.DataFrame) -> list[list[int]]:
    """5x5 counts of open risks; ``grid[impact-1][probability-1]``."""
    grid = [[0] * 5 for _ in range(5)]
    risks = df[(df["type"] == "Risk") & df["is_open"]]
    for p, i in zip(risks["probability"], risks["impact"]):
        grid[int(i) - 1][int(p) - 1] += 1
    return grid


def analyze(raid: pd.DataFrame, status_date, high_score: int = 15) -> dict:
    df = prepare(raid, status_date)
    open_df = df[df["is_open"]]
    open_risks = open_df[open_df["type"] == "Risk"].sort_values(
        ["score", "impact", "id"], ascending=[False, False, True]
    )
    overdue = open_df[open_df["overdue"]].sort_values(["days_overdue", "id"], ascending=[False, True])
    issues = open_df[open_df["type"] == "Issue"]
    aging = (
        open_df.groupby(["aging_bucket", "type"]).size().unstack(fill_value=0)
        .reindex(index=[b[2] for b in AGING_BUCKETS], columns=TYPES, fill_value=0)
    )

    def rows(frame: pd.DataFrame, n: int | None = None) -> list[dict]:
        cols = ["id", "type", "category", "description", "owner", "probability", "impact",
                "score", "heat", "due", "status", "age_days", "days_overdue"]
        out = []
        for _, r in (frame.head(n) if n else frame)[cols].iterrows():
            rec = r.to_dict()
            rec["due"] = None if pd.isna(rec["due"]) else rec["due"].date().isoformat()
            for k in ("probability", "impact", "score", "age_days", "days_overdue"):
                rec[k] = int(rec[k])
            out.append(rec)
        return out

    return {
        "items_total": int(len(df)),
        "open_total": int(len(open_df)),
        "open_by_type": {t: int((open_df["type"] == t).sum()) for t in TYPES},
        "open_risks_high": int((open_risks["score"] >= high_score).sum()),
        "max_open_risk_score": int(open_risks["score"].max()) if len(open_risks) else 0,
        "mean_open_age_days": round(float(open_df["age_days"].mean()), 1) if len(open_df) else 0.0,
        "overdue_count": int(len(overdue)),
        "top_risks": rows(open_risks, 5),
        "overdue_items": rows(overdue),
        "issues_by_owner": {k: int(v) for k, v in issues.groupby("owner").size()
                            .sort_values(ascending=False).items()},
        "open_by_owner": {k: int(v) for k, v in open_df.groupby("owner").size()
                          .sort_values(ascending=False).items()},
        "heatmap": heatmap(df),
        "aging": {b: {t: int(aging.at[b, t]) for t in TYPES} for b in aging.index},
    }
