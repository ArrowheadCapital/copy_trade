import json
import logging
from datetime import datetime
from pathlib import Path

import pandas as pd
import requests

import credentials as cre


PAGE_SIZE = 5000
MAX_PAGES = 100
OUTPUT_DIR = Path("Trades")
LOG_PATH = "fetch_order_book.log"


def setup_logging():
    OUTPUT_DIR.mkdir(exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
        handlers=[
            logging.FileHandler(LOG_PATH),
            logging.StreamHandler(),
        ],
    )


def fetch_order_book_all():
    payload = json.dumps({
        "id": cre.id,
        "secret_key": cre.secret_key,
    })
    headers = {"Content-Type": "application/json"}

    all_data = []

    for page_number in range(1, MAX_PAGES + 1):
        try:
            url = (
                f"https://{cre.stratX_url}/api/v1/reports/order/fields/"
                f"?page_size={PAGE_SIZE}&page_number={page_number}"
            )
            response = requests.request("POST", url, headers=headers, data=payload)
            response.raise_for_status()
            page_response = response.json()
        except Exception:
            logging.exception("Failed to fetch StratX order book page %s", page_number)
            raise

        if not isinstance(page_response, dict):
            raise RuntimeError(f"Unexpected StratX response type: {type(page_response).__name__}")

        page_data = page_response.get("data")
        if not isinstance(page_data, list):
            raise RuntimeError(f"Unexpected StratX data format: {page_response}")

        all_data.extend(page_data)
        logging.info("Fetched page %s with %s rows", page_number, len(page_data))

        if len(page_data) != PAGE_SIZE:
            return all_data

    raise RuntimeError(f"Reached MAX_PAGES={MAX_PAGES}; stopping to avoid endless pagination")


def main():
    setup_logging()

    try:
        data = fetch_order_book_all()

        output_path = OUTPUT_DIR / f"{datetime.now():%Y%m%d}.csv"
        pd.DataFrame(data).to_csv(output_path, index=False)
        logging.info("Saved %s order rows to %s", len(data), output_path)
    except Exception:
        logging.exception("Failed to save StratX order book")
        raise


if __name__ == "__main__":
    main()
