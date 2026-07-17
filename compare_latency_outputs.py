import csv
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent

# Base input signal grouped from original NSE/BSE trade text.
BASE_GROUPED_CSV = "0715AUTOTRD_grouped.csv"

# GreekSoft copy-trade grouped output.
GREEKSOFT_GROUPED_CSV = "0715AUTOTRD_grouped_output.csv"

# StratX latency files.
STRATX_IMPULSE_CSV = "20260715_latency_impulse.csv"
STRATX_VOLATILITY_CSV = "20260715_latency_volatility.csv"
STRATX_CLIENT_ID = "Y05601"

OUTPUT_CSV = "latency_comparison_Y05601.csv"

# Keep matches close enough that unrelated trades are not paired by accident.
MAX_MATCH_SECONDS = 300

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


def prepare_rows():
    base_rows = read_csv(BASE_GROUPED_CSV)
    greek_rows = read_csv(GREEKSOFT_GROUPED_CSV)
    impulse_rows = [
        row for row in read_csv(STRATX_IMPULSE_CSV)
        if row.get("client_id") == STRATX_CLIENT_ID
    ]
    volatility_rows = [
        row for row in read_csv(STRATX_VOLATILITY_CSV)
        if row.get("client_id") == STRATX_CLIENT_ID
    ]

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

    return base_rows, greek_by_symbol_side, impulse_rows, volatility_rows


def build_comparison_rows():
    base_rows, greek_by_key, impulse_rows, volatility_rows = prepare_rows()
    used_greek_by_key = {key: set() for key in greek_by_key}
    used_impulse = set()
    used_volatility = set()
    output_rows = []

    for base in base_rows:
        base_dt = base["_dt"]
        base_price = base["WeightedAvgPrice"]
        base_qty = base["TotalQty"]
        side = base["BuySell"]
        key = (base["Symbol"], side)

        greek = nearest_unused(
            greek_by_key.get(key, []),
            base_dt,
            used_greek_by_key.setdefault(key, set()),
            MAX_MATCH_SECONDS,
        )
        impulse = nearest_unused(
            impulse_rows, base_dt, used_impulse, MAX_MATCH_SECONDS
        )
        volatility = nearest_unused(
            volatility_rows, base_dt, used_volatility, MAX_MATCH_SECONDS
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


def write_comparison():
    output_rows = build_comparison_rows()
    output_path = BASE_DIR / OUTPUT_CSV
    with output_path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(output_rows)
    return output_path, output_rows


if __name__ == "__main__":
    created_file, rows = write_comparison()
    print(f"Created comparison CSV: {created_file}")
    print(f"Rows: {len(rows)}")
