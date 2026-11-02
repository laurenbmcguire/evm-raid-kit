"""Project configuration: defaults plus an optional ``project.yml`` next to the CSVs."""

from __future__ import annotations

import copy
from pathlib import Path

import yaml

DEFAULTS: dict = {
    "project": "ERP Data Platform Rollout (synthetic example)",
    "currency": "USD",
    "project_start": "2026-03-02",
    # Data date of plan.csv (percent_complete / actual_cost are "as of" this date).
    "status_date": "2026-06-19",
    # Synthetic example company holidays (non-working days in the calendar).
    "holidays": ["2026-04-03", "2026-05-25", "2026-07-03", "2026-09-07"],
    "seed": 12,
    "thresholds": {
        "schedule": {"green_spi_t": 0.95, "red_spi_t": 0.90, "green_slip_days": 5, "red_slip_days": 20},
        "cost": {"green_cpi": 0.95, "red_cpi": 0.90, "green_vac_pct": -0.05, "red_vac_pct": -0.10},
        "scope": {"score_min": 12, "amber_count": 2, "red_count": 3},
        "risk": {"high_score": 15, "red_score": 20, "red_high_count": 3, "amber_overdue": 3},
    },
}


def _merge(base: dict, extra: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (extra or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def load_config(data_dir: str | Path) -> dict:
    """Load ``<data_dir>/project.yml`` merged over the defaults (defaults if missing)."""
    path = Path(data_dir) / "project.yml"
    if path.exists():
        with open(path, encoding="utf-8") as fh:
            return _merge(DEFAULTS, yaml.safe_load(fh) or {})
    return copy.deepcopy(DEFAULTS)


def write_config(data_dir: str | Path, config: dict | None = None) -> Path:
    path = Path(data_dir) / "project.yml"
    path.parent.mkdir(parents=True, exist_ok=True)
    cfg = config or DEFAULTS
    header = (
        "# evmkit project settings. status_date is the data date of plan.csv;\n"
        "# override it at run time with: python -m evmkit run --status-date YYYY-MM-DD\n"
    )
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(header)
        yaml.safe_dump(cfg, fh, sort_keys=False)
    return path
