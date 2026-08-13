import argparse
import csv
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent
TODAY = datetime.now()


def daily_filenames(run_date):
    short_date = run_date.strftime("%m%d")
    full_date = run_date.strftime("%Y%m%d")
    return (
        f"{short_date}AUTOTRD_grouped.csv",
        f"{short_date}AUTOTRD_grouped_copied.csv",
        f"{full_date}_latency_impulse.csv",
        f"{full_date}_latency_volatility.csv",
    )


(
    BASE_GROUPED_CSV,
    GREEKSOFT_GROUPED_CSV,
    STRATX_IMPULSE_CSV,
    STRATX_VOLATILITY_CSV,
) = daily_filenames(TODAY)
STRATX_CLIENT_ID = "Y05601"

OUTPUT_CSV = "latency_comparison_Y05601.csv"

# Copied GreekSoft rows do not have the base order id available for matching.
GREEK_MAX_MATCH_SECONDS = 20

INPUT_DT_FMT = "%d %b %Y %H:%M:%S"
INPUT_SLASH_DT_FMT = "%d/%m/%Y %H:%M:%S"
STRATX_DT_FMT = "%Y-%m-%d %H:%M:%S"


FIELDNAMES = [
    "BaseOrderId",
    "Symbol",
    "BuySell",
    "BaseQty",
    "BasePrice",
    "BaseTime",
    "GreekOrderId",
    "GreekQty",
    "GreekPrice",
    "GreekTime",
    "GreekStrategy",
    "GreekDelaySec",
    "GreekPriceDiff",
    "GreekQtyXPriceDiff",
    "ImpulseReferenceId",
    "ImpulseClientId",
    "ImpulseCreatedAt",
    "ImpulseExecutedOn",
    "ImpulseDelaySecFromBaseCreated",
    "ImpulseDelaySecFromBaseExecuted",
    "ImpulseReportedDelaySec",
    "ImpulseInitiatedPrice",
    "ImpulsePrice",
    "ImpulsePriceDiff",
    "ImpulseQtyXPriceDiff",
    "VolatilityReferenceId",
    "VolatilityClientId",
    "VolatilityCreatedAt",
    "VolatilityExecutedOn",
    "VolatilityDelaySecFromBaseCreated",
    "VolatilityDelaySecFromBaseExecuted",
    "VolatilityReportedDelaySec",
    "VolatilityInitiatedPrice",
    "VolatilityPrice",
    "VolatilityPriceDiff",
    "VolatilityQtyXPriceDiff",
]


def to_decimal(value):
    try:
        return Decimal(str(value).strip())
    except (InvalidOperation, AttributeError):
        return Decimal("0")


def read_csv(path):
    with (BASE_DIR / path).open(newline="", encoding="utf-8-sig") as file:
        return list(csv.DictReader(file))


def parse_base_time(value):
    cleaned = value.strip()
    for fmt in (INPUT_SLASH_DT_FMT, INPUT_DT_FMT):
        try:
            return datetime.strptime(cleaned.title(), fmt)
        except ValueError:
            pass
    raise ValueError(f"Unsupported base TradeDateTime format: {value!r}")


def parse_stratx_time(value):
    return datetime.strptime(value.strip(), STRATX_DT_FMT)


def seconds_between(start, end):
    if not start or not end:
        return ""
    return int((end - start).total_seconds())


def adjusted_price_diff(side, output_price, base_price):
    diff = to_decimal(output_price) - to_decimal(base_price)
    if side == "B":
        diff = -diff
    return diff


def amount_from_diff(base_qty, price_diff):
    return to_decimal(base_qty) * price_diff


def nearest_unused(candidates, base_dt, used_indexes, max_abs_seconds):
    best_index = None
    best_score = None

    for index, row in enumerate(candidates):
        if index in used_indexes:
            continue

        diff_seconds = abs((row["_dt"] - base_dt).total_seconds())
        if diff_seconds > max_abs_seconds:
            continue

        # If two rows are equally close, prefer the one at/after base time.
        direction_penalty = 0 if row["_dt"] >= base_dt else 0.25
        score = (diff_seconds, direction_penalty)
        if best_score is None or score < best_score:
            best_score = score
            best_index = index

    if best_index is None:
        return None

    used_indexes.add(best_index)
    return candidates[best_index]


def select_stratx_row(candidates, base_dt, base_price, side, client_mode):
    if client_mode == "default":
        client_rows = [
            row for row in candidates
            if row.get("client_id") == STRATX_CLIENT_ID
        ]
        return min(
            client_rows,
            key=lambda row: abs((row["_dt"] - base_dt).total_seconds()),
            default=None,
        )

    selected_row = None
    selected_diff = None

    for row in candidates:
        price_diff = adjusted_price_diff(side, row["price"], base_price)
        if (
            selected_diff is None
            or client_mode == "best" and price_diff > selected_diff
            or client_mode == "worst" and price_diff < selected_diff
        ):
            selected_diff = price_diff
            selected_row = row

    return selected_row


def prepare_rows(
    base_grouped_csv,
    greeksoft_grouped_csv,
    stratx_impulse_csv,
    stratx_volatility_csv,
    include_greeksoft=True,
):
    base_rows = read_csv(base_grouped_csv)
    greek_rows = (
        read_csv(greeksoft_grouped_csv) if include_greeksoft else []
    )
    impulse_rows = read_csv(stratx_impulse_csv)
    volatility_rows = read_csv(stratx_volatility_csv)

    for row in base_rows:
        row["_dt"] = parse_base_time(row["TradeDateTime"])
    for row in greek_rows:
        row["_dt"] = parse_base_time(row["TradeDateTime"])
    for row in impulse_rows:
        row["_dt"] = parse_stratx_time(row["created_at"])
        row["_executed_dt"] = parse_stratx_time(row["executed_on"])
    for row in volatility_rows:
        row["_dt"] = parse_stratx_time(row["created_at"])
        row["_executed_dt"] = parse_stratx_time(row["executed_on"])

    base_rows.sort(key=lambda row: row["_dt"])
    impulse_rows.sort(key=lambda row: row["_dt"])
    volatility_rows.sort(key=lambda row: row["_dt"])

    greek_by_symbol_side = {}
    for row in greek_rows:
        key = (row["Symbol"], row["BuySell"])
        greek_by_symbol_side.setdefault(key, []).append(row)
    for rows in greek_by_symbol_side.values():
        rows.sort(key=lambda row: row["_dt"])

    impulse_by_trigger = {}
    for row in impulse_rows:
        impulse_by_trigger.setdefault(row.get("trigger", "").strip(), []).append(row)

    volatility_by_trigger = {}
    for row in volatility_rows:
        volatility_by_trigger.setdefault(row.get("trigger", "").strip(), []).append(row)

    return (
        base_rows,
        greek_by_symbol_side,
        impulse_by_trigger,
        volatility_by_trigger,
    )


def build_comparison_rows(
    base_grouped_csv=BASE_GROUPED_CSV,
    greeksoft_grouped_csv=GREEKSOFT_GROUPED_CSV,
    stratx_impulse_csv=STRATX_IMPULSE_CSV,
    stratx_volatility_csv=STRATX_VOLATILITY_CSV,
    include_greeksoft=True,
    client_mode="default",
):
    base_rows, greek_by_key, impulse_by_trigger, volatility_by_trigger = prepare_rows(
        base_grouped_csv,
        greeksoft_grouped_csv,
        stratx_impulse_csv,
        stratx_volatility_csv,
        include_greeksoft,
    )
    used_greek_by_key = {key: set() for key in greek_by_key}
    output_rows = []

    for base in base_rows:
        base_dt = base["_dt"]
        base_price = base["WeightedAvgPrice"]
        base_qty = base["TotalQty"]
        side = base["BuySell"]
        key = (base["Symbol"], side)

        greek = (
            nearest_unused(
                greek_by_key.get(key, []),
                base_dt,
                used_greek_by_key.setdefault(key, set()),
                GREEK_MAX_MATCH_SECONDS,
            )
            if include_greeksoft
            else None
        )
        base_order_id = base["OrderId"].strip()
        impulse = select_stratx_row(
            impulse_by_trigger.get(base_order_id, []),
            base_dt,
            base_price,
            side,
            client_mode,
        )
        volatility = select_stratx_row(
            volatility_by_trigger.get(base_order_id, []),
            base_dt,
            base_price,
            side,
            client_mode,
        )

        greek_diff = (
            adjusted_price_diff(side, greek["WeightedAvgPrice"], base_price)
            if greek else None
        )
        impulse_diff = (
            adjusted_price_diff(side, impulse["price"], base_price)
            if impulse else None
        )
        volatility_diff = (
            adjusted_price_diff(side, volatility["price"], base_price)
            if volatility else None
        )

        output_rows.append(
            {
                "BaseOrderId": base["OrderId"],
                "Symbol": base["Symbol"],
                "BuySell": side,
                "BaseQty": base_qty,
                "BasePrice": base_price,
                "BaseTime": base["TradeDateTime"],
                "GreekOrderId": greek["OrderId"] if greek else "",
                "GreekQty": greek["TotalQty"] if greek else "",
                "GreekPrice": greek["WeightedAvgPrice"] if greek else "",
                "GreekTime": greek["TradeDateTime"] if greek else "",
                "GreekStrategy": greek["StrategyName"] if greek else "",
                "GreekDelaySec": seconds_between(base_dt, greek["_dt"]) if greek else "",
                "GreekPriceDiff": f"{greek_diff:.2f}" if greek else "",
                "GreekQtyXPriceDiff": (
                    f"{amount_from_diff(base_qty, greek_diff):.2f}" if greek else ""
                ),
                "ImpulseReferenceId": impulse["reference_id"] if impulse else "",
                "ImpulseClientId": impulse["client_id"] if impulse else "",
                "ImpulseCreatedAt": impulse["created_at"] if impulse else "",
                "ImpulseExecutedOn": impulse["executed_on"] if impulse else "",
                "ImpulseDelaySecFromBaseCreated": (
                    seconds_between(base_dt, impulse["_dt"]) if impulse else ""
                ),
                "ImpulseDelaySecFromBaseExecuted": (
                    seconds_between(base_dt, impulse["_executed_dt"])
                    if impulse else ""
                ),
                "ImpulseReportedDelaySec": (
                    impulse["execution_delay_seconds"] if impulse else ""
                ),
                "ImpulseInitiatedPrice": impulse["initiated_price"] if impulse else "",
                "ImpulsePrice": impulse["price"] if impulse else "",
                "ImpulsePriceDiff": f"{impulse_diff:.2f}" if impulse else "",
                "ImpulseQtyXPriceDiff": (
                    f"{amount_from_diff(base_qty, impulse_diff):.2f}"
                    if impulse else ""
                ),
                "VolatilityReferenceId": (
                    volatility["reference_id"] if volatility else ""
                ),
                "VolatilityClientId": volatility["client_id"] if volatility else "",
                "VolatilityCreatedAt": volatility["created_at"] if volatility else "",
                "VolatilityExecutedOn": volatility["executed_on"] if volatility else "",
                "VolatilityDelaySecFromBaseCreated": (
                    seconds_between(base_dt, volatility["_dt"])
                    if volatility else ""
                ),
                "VolatilityDelaySecFromBaseExecuted": (
                    seconds_between(base_dt, volatility["_executed_dt"])
                    if volatility else ""
                ),
                "VolatilityReportedDelaySec": (
                    volatility["execution_delay_seconds"] if volatility else ""
                ),
                "VolatilityInitiatedPrice": (
                    volatility["initiated_price"] if volatility else ""
                ),
                "VolatilityPrice": volatility["price"] if volatility else "",
                "VolatilityPriceDiff": (
                    f"{volatility_diff:.2f}" if volatility else ""
                ),
                "VolatilityQtyXPriceDiff": (
                    f"{amount_from_diff(to_decimal(base_qty) * 2, volatility_diff):.2f}"
                    if volatility else ""
                ),
            }
        )

    return output_rows


def write_comparison(run_date=TODAY, include_greeksoft=True, client_mode="default"):
    filenames = daily_filenames(run_date)
    output_rows = build_comparison_rows(
        *filenames,
        include_greeksoft,
        client_mode,
    )
    output_path = BASE_DIR / OUTPUT_CSV
    fieldnames = (
        FIELDNAMES
        if include_greeksoft
        else [field for field in FIELDNAMES if not field.startswith("Greek")]
    )
    with output_path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=fieldnames,
            extrasaction="ignore",
        )
        writer.writeheader()
        writer.writerows(output_rows)
    return output_path, output_rows


def parse_args():
    parser = argparse.ArgumentParser(description="Build the daily latency comparison.")
    parser.add_argument(
        "--date",
        type=lambda value: datetime.strptime(value, "%Y%m%d"),
        default=TODAY,
        metavar="YYYYMMDD",
        help="Trade date; defaults to today.",
    )
    parser.add_argument(
        "--no-greeksoft",
        action="store_true",
        help="Exclude the copied GreekSoft input and all Greek columns.",
    )
    parser.add_argument(
        "--client-mode",
        choices=("default", "best", "worst"),
        default="default",
        help="Select Y05601, best client, or worst client for each StratX order.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    created_file, rows = write_comparison(
        args.date,
        not args.no_greeksoft,
        args.client_mode,
    )
    print(f"Created comparison CSV: {created_file}")
    print(f"Rows: {len(rows)}")
