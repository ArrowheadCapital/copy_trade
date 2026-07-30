import argparse
import csv
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent
TODAY = datetime.now()

OUTPUT_FIELDS = [
    "Exchange",
    "OrderId",
    "Symbol",
    "BuySell",
    "TotalQty",
    "WeightedAvgPrice",
    "BrokerAccount",
    "TradeDateTime",
    "StrategyName",
]


def exchange_for_date(run_date):
    if run_date.weekday() in (0, 1, 4):
        return "NSE"
    if run_date.weekday() in (2, 3):
        return "BSE"
    raise ValueError("Trade conversion is only supported from Monday to Friday.")


def build_paths(run_date, copied=False):
    short_date = run_date.strftime("%m%d")
    exchange = exchange_for_date(run_date)
    if copied:
        input_path = (
            rf"\\100.125.204.120\c\Users\admin\Documents"
            rf"\AutoOnlineBackup\{exchange}\FO\{short_date}AUTOTRD.txt"
        )
        output_path = BASE_DIR / f"{short_date}AUTOTRD_grouped_copied.csv"
    else:
        input_path = (
            rf"\\100.125.204.120\c"
            rf"\AutoOnlineBackup\{exchange}\FO\{short_date}AUTOTRD.txt"
        )
        output_path = BASE_DIR / f"{short_date}AUTOTRD_grouped.csv"
    return input_path, output_path


def clean(value):
    return str(value or "").replace("\xa0", " ").strip()


def to_decimal(value):
    text = clean(value).replace(",", "")
    if not text:
        return Decimal("0")
    try:
        return Decimal(text)
    except InvalidOperation:
        return Decimal("0")


def decimal_to_text(value):
    return format(value.normalize(), "f")


def normalize_side(value):
    text = clean(value).upper()
    if text == "1":
        return "B"
    if text == "2":
        return "S"
    return text


def read_rows(input_path):
    raw_text = input_path.read_text(encoding="utf-8-sig", errors="replace")
    first_line = raw_text.splitlines()[0] if raw_text.splitlines() else ""
    delimiter = "|" if "|" in first_line else ","
    exchange = "BSE" if delimiter == "|" else "NSE"
    rows = csv.reader(raw_text.splitlines(), delimiter=delimiter)

    return exchange, rows


def get_col(row, index):
    return clean(row[index]) if index < len(row) else ""


def convert_file(input_file, output_file=""):
    input_path = Path(input_file).expanduser()
    if not input_path.exists():
        raise FileNotFoundError(f"Input file not found: {input_path}")

    output_path = (
        Path(output_file).expanduser()
        if output_file
        else input_path.with_name(f"{input_path.stem}_grouped.csv")
    )

    exchange, rows = read_rows(input_path)
    grouped = {}

    for row in rows:
        if exchange == "BSE":
            order_id = get_col(row, 16)
            script = get_col(row, 5)
            side = normalize_side(get_col(row, 6))
            qty = to_decimal(get_col(row, 7))
            price = to_decimal(get_col(row, 8))
            broker = get_col(row, 9)
            trade_dt = get_col(row, 12)
            trade_time = get_col(row, 13)
            strategy = get_col(row, 22 if len(row) >= 24 else 21)
        else:
            order_id = get_col(row, 23)
            script = get_col(row, 7) or get_col(row, 3)
            side = normalize_side(get_col(row, 13))
            qty = to_decimal(get_col(row, 14))
            price = to_decimal(get_col(row, 15))
            broker = get_col(row, 17)
            trade_dt = get_col(row, 21)
            trade_time = ""
            strategy = get_col(row, 26)

        if not order_id:
            continue

        trade_datetime = " ".join(part for part in [trade_dt, trade_time] if part)
        item = grouped.setdefault(
            order_id,
            {
                "Exchange": exchange,
                "OrderId": order_id,
                "Symbol": script,
                "BuySell": side,
                "TotalQty": Decimal("0"),
                "WeightedValue": Decimal("0"),
                "BrokerAccount": broker,
                "TradeDateTime": trade_datetime,
                "StrategyName": strategy,
            },
        )

        item["TotalQty"] += qty
        item["WeightedValue"] += qty * price

    with output_path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=OUTPUT_FIELDS)
        writer.writeheader()

        for item in grouped.values():
            total_qty = item["TotalQty"]
            avg_price = (
                item["WeightedValue"] / total_qty if total_qty else Decimal("0")
            )
            writer.writerow(
                {
                    "Exchange": item["Exchange"],
                    "OrderId": item["OrderId"],
                    "Symbol": item["Symbol"],
                    "BuySell": item["BuySell"],
                    "TotalQty": decimal_to_text(total_qty),
                    "WeightedAvgPrice": f"{avg_price:.2f}",
                    "BrokerAccount": item["BrokerAccount"],
                    "TradeDateTime": item["TradeDateTime"],
                    "StrategyName": item["StrategyName"],
                }
            )

    return output_path


def run_for_date(run_date, copied=False):
    input_path, output_path = build_paths(run_date, copied)
    created_file = convert_file(input_path, output_path)
    print(f"Created CSV: {created_file}")
    return created_file


def parse_args():
    parser = argparse.ArgumentParser(description="Group a daily GreekSoft trade file.")
    parser.add_argument(
        "--date",
        type=lambda value: datetime.strptime(value, "%Y%m%d"),
        default=TODAY,
        metavar="YYYYMMDD",
        help="Trade date; defaults to today.",
    )
    parser.add_argument(
        "--copied",
        action="store_true",
        help="Process the copied GreekSoft trade file.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    run_for_date(args.date, args.copied)
