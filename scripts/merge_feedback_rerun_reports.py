from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from rerun_feedback_csv_cases import (
    DEFAULT_DATES,
    DEFAULT_FEEDBACK_DIR,
    evaluate,
    render_report,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("reports", nargs="+", help="JSON reports, oldest to newest")
    parser.add_argument("--feedback-dir", default=str(DEFAULT_FEEDBACK_DIR))
    parser.add_argument("--dates", default=",".join(DEFAULT_DATES))
    parser.add_argument("--output-dir", default="reports")
    parser.add_argument("--name", default="feedback_api_rerun_final")
    args = parser.parse_args()

    latest_by_case: dict[int, dict[str, Any]] = {}
    for report_name in args.reports:
        report_path = Path(report_name)
        for item in json.loads(report_path.read_text(encoding="utf-8")):
            case_no = int(item.get("case_no") or 0)
            if case_no:
                latest_by_case[case_no] = item

    results = [latest_by_case[key] for key in sorted(latest_by_case)]
    for item in results:
        item["evaluation"] = evaluate(item)

    feedback_dir = Path(args.feedback_dir)
    csv_paths = [
        feedback_dir / f"ai_feedback_2026-07-{date.strip()}.csv"
        for date in args.dates.split(",")
        if date.strip()
    ]

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = output_dir / f"{args.name}_{stamp}.json"
    html_path = output_dir / f"{args.name}_{stamp}.html"
    json_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    html_path.write_text(render_report(results, csv_paths), encoding="utf-8")

    status_counts: dict[str, int] = {}
    for item in results:
        status = str((item.get("evaluation") or {}).get("status") or "PENDING")
        status_counts[status] = status_counts.get(status, 0) + 1

    print(f"COUNT={len(results)}")
    print(f"STATUS={json.dumps(status_counts, ensure_ascii=False)}")
    print(f"JSON={json_path.resolve()}")
    print(f"HTML={html_path.resolve()}")


if __name__ == "__main__":
    main()
