"""Command line: ``python -m evmkit run | pm | generate``."""

from __future__ import annotations

import argparse
import datetime as dt
import sys
import time
from pathlib import Path


def _date(s: str) -> dt.date:
    return dt.date.fromisoformat(s)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="evmkit", description="EVM + RAID status reporting kit")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_run = sub.add_parser("run", help="generate data if missing, analyse, chart and report")
    p_run.add_argument("--root", default=".", help="repository root (default: current directory)")
    p_run.add_argument("--data-dir", default=None, help="input folder (default: <root>/examples)")
    p_run.add_argument("--status-date", type=_date, default=None,
                       help="status date YYYY-MM-DD (default: status_date in project.yml)")

    p_pm = sub.add_parser("pm", help="run the AI project manager")
    p_pm.add_argument("--root", default=".")
    p_pm.add_argument("--date", type=_date, default=None, help="report date (default: today)")
    p_pm.add_argument("--no-llm", action="store_true", help="skip the optional LLM summary")

    p_gen = sub.add_parser("generate", help="(re)write the synthetic example CSVs")
    p_gen.add_argument("--data-dir", default="examples")
    p_gen.add_argument("--seed", type=int, default=None)

    args = parser.parse_args(argv)
    t0 = time.perf_counter()

    if args.cmd == "run":
        from evmkit.pipeline import run

        s = run(args.root, status_date=args.status_date, data_dir=args.data_dir)
        e, es, r = s["evm"], s["earned_schedule"], s["rag"]
        if s.get("_generated_data"):
            print("Generated synthetic example data.")
        print(f"Status {s['status_date']}  overall {r['overall']}  "
              f"(scope {r['scope']}, schedule {r['schedule']}, cost {r['cost']}, risk {r['risk']})")
        print(f"BAC {e['bac']:,.0f}  PV {e['pv']:,.0f}  EV {e['ev']:,.0f}  AC {e['ac']:,.0f}")
        print(f"CPI {e['cpi']:.3f}  SPI {e['spi']:.3f}  SPI(t) {es['spi_t']:.3f}  "
              f"EAC {e['eac_cpi']:,.0f}  forecast finish {es['forecast_finish']} "
              f"({es['slip_working_days']:+d} wd)")
        print("Wrote reports/status_report.md, reports/summary.json and docs/img/*.png")
    elif args.cmd == "pm":
        from evmkit.ai_pm import run as pm_run

        f = pm_run(args.root, today=args.date, use_llm=not args.no_llm)
        print(f"AI PM {f['date']}: health {f['health']['rag']} - {f['health']['reason']}")
        print(f"Summary source: {f['executive_summary_source']}")
        print("Wrote project/STATUS.md and project/status.json")
    elif args.cmd == "generate":
        from evmkit.config import load_config
        from evmkit.data import generate

        counts = generate(Path(args.data_dir), load_config(args.data_dir), seed=args.seed)
        print(f"Wrote {counts['plan']} tasks, {counts['timesheets']} timesheet rows, "
              f"{counts['raid']} RAID items to {args.data_dir}/")
    print(f"Done in {time.perf_counter() - t0:.1f}s", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
