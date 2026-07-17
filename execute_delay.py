import os
import pandas as pd

INPUT_CSV = r"\\DESKTOP-CLI5HO6\Desktop\Codes\copy_trade_volatility_core\Trades\20260715.csv"
OUTPUT_CSV = os.path.join(os.getcwd(), "20260715_latency_volatility.csv")

# Read only required columns
df = pd.read_csv(
    INPUT_CSV,
    usecols=["created_at", "executed_on", "reference_id", "status", "client_id", "trading_symbol", "quantity", "buyorsell", "initiated_price", "price", "trigger"]
)

# Filter TRADED rows
df = df[df["status"].str.upper() == "TRADED"].copy()

# Convert datetimes
df["created_at"] = pd.to_datetime(
    df["created_at"],
    format="%Y-%m-%d %H:%M:%S"
)

df["executed_on"] = pd.to_datetime(
    df["executed_on"],
    format="%Y-%m-%d  %H:%M:%S"
)

# Difference in seconds
df["execution_delay_seconds"] = (
    df["executed_on"] - df["created_at"]
).dt.total_seconds()

# Output
df[["reference_id", "client_id", "trading_symbol", "quantity", "buyorsell", "execution_delay_seconds", "created_at", "executed_on", "initiated_price", "price", "trigger"]].to_csv(
    OUTPUT_CSV,
    index=False
)

print(f"Saved {len(df)} records to: {OUTPUT_CSV}")
