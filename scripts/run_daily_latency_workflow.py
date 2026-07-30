import argparse
import sys
from datetime import datetime
from pathlib import Path


REPO_DIR = Path(__file__).resolve().parent.parent
if str(REPO_DIR) not in sys.path:
    sys.path.insert(0, str(REPO_DIR))

from metrics.compare_latency_outputs import write_comparison
from metrics.execute_delay import run_for_mode
from scripts.convert_trade_txt_to_csv import exchange_for_date, run_for_date


def run_workflow(run_date, include_greeksoft=True):
    date_text = run_date.strftime("%Y%m%d")
    exchange = exchange_for_date(run_date)
    print(
        f"Running latency workflow for {date_text} "
        f"using {exchange} trade files..."
    )

    run_for_mode("volatility", run_date)
    run_for_mode("impulse", run_date)
    run_for_date(run_date, copied=False)

    if include_greeksoft:
        run_for_date(run_date, copied=True)
    else:
        print("Skipping copied GreekSoft trade file and Greek comparison columns.")

    output_path, rows = write_comparison(run_date, include_greeksoft)
    print(f"Created comparison CSV: {output_path}")
    print(f"Rows: {len(rows)}")
    return output_path


def parse_args():
    parser = argparse.ArgumentParser(
        description="Run the complete daily latency comparison workflow."
    )
    parser.add_argument(
        "--date",
        type=lambda value: datetime.strptime(value, "%Y%m%d"),
        default=datetime.now(),
        metavar="YYYYMMDD",
        help="Trade date; defaults to today.",
    )
    parser.add_argument(
        "--no-greeksoft",
        action="store_true",
        help="Skip the copied GreekSoft file and omit Greek columns.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    run_workflow(args.date, not args.no_greeksoft)
