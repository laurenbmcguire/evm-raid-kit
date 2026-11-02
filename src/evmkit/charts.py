"""Matplotlib charts (brand style from :mod:`evmkit.style`)."""

from __future__ import annotations

from pathlib import Path

import matplotlib.dates as mdates
import numpy as np
import pandas as pd
from matplotlib.colors import LinearSegmentedColormap
from matplotlib.patches import Patch
from matplotlib.ticker import FuncFormatter

from evmkit import style
from evmkit.raid import AGING_BUCKETS, TYPES

TYPE_COLORS = {"Risk": style.CRIMSON, "Issue": style.DEEP, "Assumption": style.GOLD, "Dependency": style.SAND}
HEAT_CMAP = LinearSegmentedColormap.from_list(
    "brand_heat", [style.BG, style.SAND, style.GOLD, style.CRIMSON, style.DEEP]
)


def _money_axis(ax) -> None:
    def f(v, _):
        return f"${v / 1e6:.1f}M" if abs(v) >= 1e6 else f"${v / 1e3:.0f}k"
    ax.yaxis.set_major_formatter(FuncFormatter(f))


def _date_axis(ax) -> None:
    ax.xaxis.set_major_locator(mdates.MonthLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %Y"))


def s_curves(res: dict, path: Path) -> Path:
    s = res["summary"]
    cal = res["cal"]
    pv_cum = res["pv_cum"]
    trend = res["trend"]
    e, es = s["evm"], s["earned_schedule"]
    start = pd.Timestamp(s["project_start"])
    sd = pd.Timestamp(s["status_date"])
    ff = pd.Timestamp(es["forecast_finish"])
    pf = pd.Timestamp(es["planned_finish"])

    fig, ax = style.new_figure()
    pv_x = [start] + [pd.Timestamp(cal.date_at(n - 1)) for n in range(1, len(pv_cum))]
    ax.plot(pv_x, pv_cum, color=style.GOLD, lw=2.4, label="PV (baseline)")
    x = [start] + list(trend["date"])
    ax.plot(x, [0] + list(trend["ev"]), color=style.CRIMSON, lw=2.6, label="EV (earned)")
    ax.plot(x, [0] + list(trend["ac"]), color=style.INK, lw=2.0, label="AC (actual cost)")
    ax.plot([sd, ff], [e["ac"], e["eac_cpi"]], color=style.INK, lw=1.6, ls="--",
            label="AC projection to EAC (BAC/CPI)")
    ax.plot([sd, ff], [e["ev"], e["bac"]], color=style.CRIMSON, lw=1.6, ls=":",
            label="EV projection to forecast finish (ES)")
    ax.axhline(e["bac"], color=style.MUTED, lw=1.0, ls="--")
    ax.axhline(e["eac_cpi"], color=style.DEEP, lw=1.0, ls=":")
    right = ff + pd.Timedelta(days=6)
    ax.text(right, e["bac"], f"BAC {e['bac'] / 1e6:.2f}M", va="top", ha="left", color=style.MUTED, fontsize=9.5)
    ax.text(right, e["eac_cpi"], f"EAC {e['eac_cpi'] / 1e6:.2f}M", va="bottom", ha="left",
            color=style.DEEP, fontsize=9.5, fontweight="semibold")
    ax.axvline(sd, color=style.MUTED, lw=1.0, alpha=0.7)
    ax.text(sd, ax.get_ylim()[1] * 0.02, f"  status {sd:%d %b}", color=style.MUTED, fontsize=9, rotation=90,
            va="bottom", ha="right")
    ax.scatter([pf], [e["bac"]], color=style.GOLD, zorder=5, s=36)
    ax.scatter([ff], [e["bac"]], color=style.CRIMSON, zorder=5, s=36)
    ax.annotate(f"forecast finish {ff:%d %b}\n(+{es['slip_working_days']} wd vs {pf:%d %b})", (ff, e["bac"]),
                xytext=(10, -40), textcoords="offset points", ha="left", fontsize=9, color=style.DEEP)
    ax.set_xlim(start - pd.Timedelta(days=3), right + pd.Timedelta(days=24))
    ax.set_ylim(0, max(e["eac_cpi"], e["bac"]) * 1.08)
    _money_axis(ax)
    _date_axis(ax)
    ax.set_title(f"Earned value S-curves: CPI {e['cpi']:.2f}, SPI(t) {es['spi_t']:.2f}, "
                 f"EAC {e['eac_cpi'] / 1e6:.2f}M vs BAC {e['bac'] / 1e6:.2f}M")
    ax.set_ylabel("Cumulative cost")
    ax.legend(loc="lower right")
    fig.tight_layout()
    return style.save(fig, path)


def cpi_spi_trend(res: dict, path: Path, th: dict | None = None) -> Path:
    trend = res["trend"].copy()
    trend = trend[trend["pv"] > 0.02 * res["summary"]["evm"]["bac"]]  # skip the first noisy weeks
    green = (th or {}).get("green_cpi", 0.95)
    red = (th or {}).get("red_cpi", 0.90)
    fig, ax = style.new_figure()
    ax.axhspan(0, red, color=style.SAND, alpha=0.35, lw=0)
    ax.axhline(1.0, color=style.MUTED, lw=1.0)
    ax.axhline(green, color=style.GOLD, lw=1.0, ls="--", label=f"Green threshold {green:.2f}")
    ax.axhline(red, color=style.CRIMSON, lw=1.0, ls="--", label=f"Red threshold {red:.2f}")
    ax.plot(trend["date"], trend["cpi"], color=style.CRIMSON, lw=2.4, marker="o", ms=4, label="CPI")
    ax.plot(trend["date"], trend["spi"], color=style.GOLD, lw=2.4, marker="o", ms=4, label="SPI")
    ax.plot(trend["date"], trend["spi_t"], color=style.INK, lw=1.8, ls="--", marker="s", ms=3.5,
            label="SPI(t) earned schedule")
    lo = min(trend[["cpi", "spi", "spi_t"]].min().min(), red) - 0.03
    hi = max(trend[["cpi", "spi", "spi_t"]].max().max(), 1.0) + 0.03
    ax.set_ylim(lo, hi)
    last = trend.iloc[-1]
    ax.set_title(f"Performance indices by week: CPI {last.cpi:.2f}, SPI {last.spi:.2f}, SPI(t) {last.spi_t:.2f}")
    ax.set_ylabel("Index (1.00 = on plan)")
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%d %b"))
    h, lab = ax.get_legend_handles_labels()
    ax.legend(h[2:] + h[:2], lab[2:] + lab[:2], loc="lower right", ncol=2)
    fig.tight_layout()
    return style.save(fig, path)


def risk_heatmap(res: dict, path: Path) -> Path:
    df = res["raid"]
    risks = df[(df["type"] == "Risk") & df["is_open"]]
    fig, ax = style.new_figure()
    ax.grid(False)
    score = np.outer(np.arange(1, 6), np.arange(1, 6))  # [impact, probability]
    ax.imshow(score, origin="lower", cmap=HEAT_CMAP, vmin=1, vmax=25, extent=(0.5, 5.5, 0.5, 5.5),
              aspect="auto")
    for i in range(1, 6):
        for p in range(1, 6):
            cell = risks[(risks["impact"] == i) & (risks["probability"] == p)]
            dark = i * p >= 12
            color = style.BG if dark else style.INK
            ax.text(p - 0.42, i + 0.36, f"{i * p}", fontsize=8, color=color, alpha=0.8, va="top")
            if len(cell):
                ax.text(p, i + 0.05, f"{len(cell)}", ha="center", va="center", fontsize=17,
                        fontweight="semibold", color=color)
                ax.text(p, i - 0.28, ", ".join(cell["id"]), ha="center", va="center", fontsize=8, color=color)
    for k in np.arange(0.5, 6, 1):
        ax.axhline(k, color=style.BG, lw=2)
        ax.axvline(k, color=style.BG, lw=2)
    ax.set_xticks(range(1, 6), ["1 Rare", "2 Unlikely", "3 Possible", "4 Likely", "5 Almost certain"])
    ax.set_yticks(range(1, 6), ["1 Minor", "2 Moderate", "3 Major", "4 Severe", "5 Critical"])
    ax.set_xlabel("Probability")
    ax.set_ylabel("Impact")
    ax.spines[["left", "bottom"]].set_visible(False)
    hi = int((risks["score"] >= 15).sum())
    ax.set_title(f"Open risk heatmap: {len(risks)} open risks, {hi} scored 15 or higher")
    fig.tight_layout()
    return style.save(fig, path)


def raid_aging(res: dict, path: Path) -> Path:
    df = res["raid"]
    open_df = df[df["is_open"]]
    buckets = [b[2] for b in AGING_BUCKETS]
    fig, ax = style.new_figure()
    bottom = np.zeros(len(buckets))
    for t in TYPES:
        vals = np.array([((open_df["aging_bucket"] == b) & (open_df["type"] == t)).sum() for b in buckets])
        ax.bar(buckets, vals, bottom=bottom, color=TYPE_COLORS[t], label=t, width=0.62,
               edgecolor=style.BG, linewidth=1.2)
        bottom += vals
    for k, b in enumerate(buckets):
        od = int(((open_df["aging_bucket"] == b) & open_df["overdue"]).sum())
        label = f"{int(bottom[k])} open" + (f"\n{od} overdue" if od else "")
        ax.text(k, bottom[k] + 0.15, label, ha="center", va="bottom", fontsize=9.5,
                color=style.DEEP if od else style.MUTED, fontweight="semibold" if od else "normal")
    ax.set_ylim(0, bottom.max() + 2.2)
    ax.set_ylabel("Open RAID items")
    ax.set_xlabel("Age since raised (calendar days, at status date)")
    ax.grid(axis="x", visible=False)
    ax.set_title(f"RAID aging: {len(open_df)} open items, {int(open_df['overdue'].sum())} past due")
    ax.legend(loc="upper right", ncol=4)
    fig.tight_layout()
    return style.save(fig, path)


def gantt(res: dict, path: Path) -> Path:
    tasks = res["tasks"].copy()
    cal = res["cal"]
    s = res["summary"]
    sd = pd.Timestamp(s["status_date"])
    fig, ax = style.new_figure()
    ax.grid(axis="y", visible=False)
    n = len(tasks)
    for k, r in enumerate(tasks.itertuples()):
        y = n - 1 - k
        start = mdates.date2num(r.planned_start)
        finish = mdates.date2num(r.planned_finish + pd.Timedelta(days=1))
        width = finish - start
        crit = bool(r.critical)
        ax.barh(y, width, left=start, height=0.62, color=style.CRIMSON if crit else style.SAND,
                alpha=0.28 if crit else 0.9, edgecolor=style.CRIMSON if crit else style.SAND, lw=1)
        if r.pct_complete > 0:
            ax.barh(y, width * r.pct_complete, left=start, height=0.30,
                    color=style.DEEP if crit else style.GOLD)
        if r.total_float > 0:
            late = pd.Timestamp(cal.date_at(cal.index(r.planned_finish) + int(r.total_float))) + pd.Timedelta(days=1)
            ax.plot([finish, mdates.date2num(late)], [y, y], color=style.MUTED, lw=1, ls=(0, (2, 2)))
    ax.set_yticks(range(n), [f"{r.id}  {r.name}" for r in tasks.itertuples()][::-1], fontsize=7.6)
    ax.axvline(mdates.date2num(sd), color=style.INK, lw=1.2, ls="--")
    ax.text(mdates.date2num(sd), n - 0.2, f" status {sd:%d %b}", fontsize=9, color=style.INK, va="bottom")
    ax.xaxis_date()
    _date_axis(ax)
    ax.set_ylim(-0.7, n + 0.4)
    handles = [
        Patch(facecolor=style.CRIMSON, alpha=0.28, edgecolor=style.CRIMSON, label="Critical path (baseline)"),
        Patch(facecolor=style.SAND, label="Non-critical"),
        Patch(facecolor=style.DEEP, label="% complete (critical)"),
        Patch(facecolor=style.GOLD, label="% complete"),
    ]
    ax.legend(handles=handles, loc="lower left", ncol=2, fontsize=8.5)
    c = s["cpm"]
    ax.set_title(f"Baseline Gantt: critical path {c['critical_count']} of {n} tasks, "
                 f"{c['duration_working_days']} working days")
    ax.text(1.0, -0.075, "dotted line = total float", transform=ax.transAxes, ha="right",
            fontsize=8.5, color=style.MUTED)
    fig.tight_layout()
    return style.save(fig, path)


def render_all(res: dict, out_dir: str | Path) -> list[Path]:
    out = Path(out_dir)
    cost = res.get("thresholds", {}).get("cost", {})
    th = {"green_cpi": cost.get("green_cpi", 0.95), "red_cpi": cost.get("red_cpi", 0.90)}
    return [
        s_curves(res, out / "s_curves.png"),
        cpi_spi_trend(res, out / "cpi_spi_trend.png", th),
        risk_heatmap(res, out / "risk_heatmap.png"),
        raid_aging(res, out / "raid_aging.png"),
        gantt(res, out / "gantt.png"),
    ]
