"""Explicit, documented RAG rules for scope, schedule, cost and risk."""

from __future__ import annotations

import pandas as pd

ORDER = {"Green": 0, "Amber": 1, "Red": 2}


def rag_schedule(spi_t: float, slip_days: int, th: dict) -> tuple[str, str]:
    """Red if SPI(t) < red or slip > red days; Green if SPI(t) >= green and slip <= green days."""
    why = f"SPI(t) {spi_t:.2f}, forecast slip {slip_days:+d} working days"
    if spi_t < th["red_spi_t"] or slip_days > th["red_slip_days"]:
        return "Red", why
    if spi_t >= th["green_spi_t"] and slip_days <= th["green_slip_days"]:
        return "Green", why
    return "Amber", why


def rag_cost(cpi: float, vac_pct: float, th: dict) -> tuple[str, str]:
    """Red if CPI < red or VAC% < red; Green if CPI >= green and VAC% >= green."""
    why = f"CPI {cpi:.2f}, VAC {vac_pct:+.1%} of BAC"
    if cpi < th["red_cpi"] or vac_pct < th["red_vac_pct"]:
        return "Red", why
    if cpi >= th["green_cpi"] and vac_pct >= th["green_vac_pct"]:
        return "Green", why
    return "Amber", why


def rag_scope(raid_prepared: pd.DataFrame, th: dict) -> tuple[str, str]:
    """Counts open Scope-category RAID items scoring >= score_min."""
    df = raid_prepared
    n = int(((df["category"] == "Scope") & df["is_open"] & (df["score"] >= th["score_min"])).sum())
    why = f"{n} open scope item(s) scored >= {th['score_min']}"
    if n >= th["red_count"]:
        return "Red", why
    if n >= th["amber_count"]:
        return "Amber", why
    return "Green", why


def rag_risk(raid_summary: dict, th: dict) -> tuple[str, str]:
    """Red if any open risk >= red_score or too many high risks; Amber on any high risk or overdue load."""
    high = raid_summary["open_risks_high"]
    top = raid_summary["max_open_risk_score"]
    overdue = raid_summary["overdue_count"]
    why = f"{high} open risk(s) scored >= {th['high_score']} (max {top}), {overdue} overdue RAID item(s)"
    if top >= th["red_score"] or high >= th["red_high_count"]:
        return "Red", why
    if high >= 1 or overdue >= th["amber_overdue"]:
        return "Amber", why
    return "Green", why


def overall(rags: dict[str, str]) -> str:
    """Worst of the dimension RAGs."""
    return max(rags.values(), key=lambda r: ORDER[r])
