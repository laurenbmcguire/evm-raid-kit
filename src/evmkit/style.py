"""Single matplotlib style helper for every chart in the repo (brand palette)."""

from __future__ import annotations

import logging
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
# DejaVu Sans has no separate semibold face; matplotlib falls back to bold. Silence that notice.
logging.getLogger("matplotlib.font_manager").setLevel(logging.ERROR)

import matplotlib.pyplot as plt  # noqa: E402
from matplotlib import cycler  # noqa: E402

BG = "#FFFBF6"
INK = "#241A18"
MUTED = "#5E4C46"
GRID = "#EAE0D5"
CRIMSON = "#BE1E3C"
DEEP = "#8E1630"
GOLD = "#B08A4E"
SAND = "#E3D2B4"

PALETTE = {
    "bg": BG,
    "ink": INK,
    "muted": MUTED,
    "grid": GRID,
    "crimson": CRIMSON,
    "deep": DEEP,
    "gold": GOLD,
    "sand": SAND,
}

FIGSIZE = (10, 5.625)  # 1600 x 900 px at dpi=160
DPI = 160


def apply_style() -> None:
    """Apply the brand rcParams globally."""
    plt.rcParams.update(
        {
            "figure.facecolor": BG,
            "axes.facecolor": BG,
            "savefig.facecolor": BG,
            "figure.figsize": FIGSIZE,
            "figure.dpi": 100,
            "savefig.dpi": DPI,
            "font.family": "DejaVu Sans",
            "font.size": 10.5,
            "text.color": INK,
            "axes.labelcolor": INK,
            "axes.edgecolor": MUTED,
            "axes.linewidth": 0.9,
            "axes.titlesize": 15,
            "axes.titleweight": "semibold",
            "axes.titlelocation": "left",
            "axes.titlepad": 12,
            "axes.labelsize": 10.5,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "axes.grid": True,
            "axes.axisbelow": True,
            "grid.color": GRID,
            "grid.linewidth": 0.8,
            "xtick.color": MUTED,
            "ytick.color": MUTED,
            "legend.frameon": False,
            "legend.fontsize": 9.5,
            "axes.prop_cycle": cycler(color=[CRIMSON, GOLD, DEEP, INK, SAND, MUTED]),
        }
    )


def new_figure(figsize: tuple[float, float] = FIGSIZE):
    """Create a styled figure and axes."""
    apply_style()
    fig, ax = plt.subplots(figsize=figsize)
    return fig, ax


def save(fig, path: str | Path) -> Path:
    """Save at the brand size (about 1600x900 px at dpi=160) and close."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=DPI, facecolor=BG)
    plt.close(fig)
    return path
