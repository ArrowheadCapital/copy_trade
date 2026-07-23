import csv
from datetime import datetime


INPUT_CSV_PATH = "Trades/20260601.csv"
OUTPUT_CSV_PATH = "trades_grouped.csv"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
REQUIRED_COLUMNS = ("executed_on", "reference_id", "status")


def parse_executed_on(value):
    return datetime.strptime(value.strip(), DATE_FORMAT)


def group_reference_times(input_path):
    grouped = {}

    with open(input_path, newline="", encoding="utf-8") as csv_file:
        reader = csv.DictReader(csv_file)
        missing_columns = [col for col in REQUIRED_COLUMNS if col not in reader.fieldnames]
        if missing_columns:
            raise ValueError(f"Missing required columns: {', '.join(missing_columns)}")

        for row_number, row in enumerate(reader, start=2):
            reference_id = row["reference_id"].strip()
            executed_on_raw = row["executed_on"].strip()
            status = row["status"].strip().upper()

            if status != "TRADED" or not reference_id or not executed_on_raw:
                continue

            try:
                executed_on = parse_executed_on(executed_on_raw)
            except ValueError as exc:
                raise ValueError(
                    f"Invalid executed_on at row {row_number}: {executed_on_raw!r}"
                ) from exc

            if reference_id not in grouped:
                grouped[reference_id] = {
                    "min_executed_on": executed_on,
                    "max_executed_on": executed_on,
                }

            item = grouped[reference_id]
            item["min_executed_on"] = min(item["min_executed_on"], executed_on)
            item["max_executed_on"] = max(item["max_executed_on"], executed_on)

    return grouped


def write_grouped_times(grouped, output_path):
    fieldnames = [
        "reference_id",
        "min_executed_on",
        "max_executed_on",
        "time_diff_sec",
    ]

    with open(output_path, "w", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
        writer.writeheader()

        for reference_id, item in sorted(grouped.items()):
            writer.writerow(
                {
                    "reference_id": reference_id,
                    "min_executed_on": item["min_executed_on"].strftime(DATE_FORMAT),
                    "max_executed_on": item["max_executed_on"].strftime(DATE_FORMAT),
                    "time_diff_sec": int(
                        (
                            item["max_executed_on"] - item["min_executed_on"]
                        ).total_seconds()
                    ),
                }
            )


def main():
    grouped = group_reference_times(INPUT_CSV_PATH)
    write_grouped_times(grouped, OUTPUT_CSV_PATH)
    print(f"Wrote {len(grouped)} reference_id groups to {OUTPUT_CSV_PATH}")


if __name__ == "__main__":
    main()
