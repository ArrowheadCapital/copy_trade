import os
import re
import pandas as pd

# Hardcoded log file path
LOG_FILE = r"C:\Users\admin\Desktop\23_06_26_vol.txt"

# Output CSV
OUTPUT_CSV = os.path.join(os.getcwd(), "http_delays_volatility.csv")

results = []

with open(LOG_FILE, "r", encoding="utf-8", errors="ignore") as f:
    for line in f:
        if "STRATX_HTTP_SUCCESS" not in line:
            continue

        # Timestamp
        ts_match = re.search(r"\[(\d{2}:\d{2}:\d{2}\.\d{3})\]", line)

        # HTTP delay
        http_match = re.search(r"http=(\d+(?:\.\d+)?)ms", line)

        # Reference ID
        ref_match = re.search(
            r"ref_id=([0-9a-fA-F-]{36})",
            line
        )

        if not (ts_match and http_match and ref_match):
            continue

        timestamp = ts_match.group(1)
        http_ms = float(http_match.group(1))
        reference_id = ref_match.group(1)

        if http_ms >= 1000:
            results.append({
                "timestamp": timestamp,
                "reference_id": reference_id,
                "http_delay_ms": http_ms
            })

df = pd.DataFrame(results)

df.to_csv(OUTPUT_CSV, index=False)

print(f"Found {len(df)} records with http >= 1000ms")
print(f"Saved to: {OUTPUT_CSV}")