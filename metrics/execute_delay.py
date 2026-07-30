import argparse
from datetime import datetime
from pathlib import Path

import pandas as pd


BASE_DIR = Path(__file__).resolve().parent.parent
TODAY = datetime.now()
DEFAULT_MODE = "volatility"


def build_paths(mode, run_date):
    date_text = run_date.strftime("%Y%m%d")
    input_csv = (
        rf"\\DESKTOP-CLI5HO6\Desktop\Codes"
        rf"\copy_trade_{mode}_core\Trades\{date_text}.csv"
    )
    output_csv = BASE_DIR / f"{date_text}_latency_{mode}.csv"
    return input_csv, output_csv


def create_latency_csv(input_csv, output_csv):
    # Read only required columns
    df = pd.read_csv(
        input_csv,
        usecols=["created_at", "executed_on", "reference_id", "status", "client_id", "trading_symbol", "quantity", "buyorsell", "initiated_price", "price", "trigger"],
    )

    # Filter TRADED rows
    df = df[df["status"].str.upper() == "TRADED"].copy()

    # Convert datetimes
    df["created_at"] = pd.to_datetime(
        df["created_at"],
        format="%Y-%m-%d %H:%M:%S",
    )
    df["executed_on"] = pd.to_datetime(
        df["executed_on"],
        format="%Y-%m-%d  %H:%M:%S",
    )

    # Difference in seconds
    df["execution_delay_seconds"] = (
        df["executed_on"] - df["created_at"]
    ).dt.total_seconds()

    # Output
    df[["reference_id", "client_id", "trading_symbol", "quantity", "buyorsell", "execution_delay_seconds", "created_at", "executed_on", "initiated_price", "price", "trigger"]].to_csv(
        output_csv,
        index=False,
    )

    print(f"Saved {len(df)} records to: {output_csv}")
    return Path(output_csv)


def run_for_mode(mode, run_date):
    input_csv, output_csv = build_paths(mode, run_date)
    return create_latency_csv(input_csv, output_csv)


def parse_args():
    parser = argparse.ArgumentParser(description="Create a StratX latency CSV.")
    parser.add_argument(
        "mode",
        nargs="?",
        choices=("impulse", "volatility"),
        default=DEFAULT_MODE,
    )
    parser.add_argument(
        "--date",
        type=lambda value: datetime.strptime(value, "%Y%m%d"),
        default=TODAY,
        metavar="YYYYMMDD",
        help="Trade date; defaults to today.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    run_for_mode(args.mode, args.date)
