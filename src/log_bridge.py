import datetime
import hashlib
import json
import os
import time

import pandas as pd

from src.utils.broker_helpers import createLogFile, printt

# ================= CONFIG =================
LOG_SOURCE_PATH = r"C:\path\to\strategy_repo\logs\sensex_20260806.log"
OUTPUT_TXT_PATH = r"C:\path\to\output\AUTOTRD.txt"
INSTRUMENT_CSV_PATH = r"\\100.103.25.93\d\Raj\signal_generation\instruments_data\options_instruments.csv"
UNDERLYING = "SENSEX"
STRATEGY_NAME = "GREEKSOFT"
BROKER_ID = "TS511"
GREEK_CLIENT_ID = "TS511"
EXCH_RETAILER_ID = "TS511"
POLL_INTERVAL_SECONDS = 0.5
BRIDGE_STATE_FILE = "log_bridge_state.json"
APPEND_RETRY_ATTEMPTS = 3
APPEND_RETRY_SLEEP_SECONDS = 0.2
# ============================================

BSE_COLUMN_COUNT = 24
INITIAL_ORDER_QUEUED_MARKER = "INITIAL_ORDER_QUEUED"
LOG_TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M:%S.%f"
ROW_DATE_FORMAT = "%d/%m/%Y"
ROW_TIME_FORMAT = "%H:%M:%S"


def load_instrument_lookup(path, underlying):
    # Schema is the XTS-style master (columns: Name, ExchangeSegment,
    # Series/InstType, ExchangeInstrumentID, Description, ContractExpiration,
    # StrikePrice, OptionType) - not GreekSoft's own getInstrument() shape.
    # ExchangeInstrumentID lines up with GreekSoft's real BSE ExchangeToken
    # (verified against a live example: 840xxx-range values match). Right
    # (CE/PE) is derived from the Description suffix rather than trusting the
    # numeric OptionType enum, since the text suffix is self-verifying.
    df = pd.read_csv(path, dtype=str)
    df.columns = [str(c).strip() for c in df.columns]

    name = df["Name"].astype(str).str.strip().str.upper()
    segment = df["ExchangeSegment"].astype(str).str.strip().str.upper()
    inst_type = df["Series/InstType"].astype(str).str.strip().str.upper()
    right = df["Description"].astype(str).str.strip().str.upper().str[-2:]

    filtered = df[
        (name == underlying.strip().upper())
        & (segment == "BSEFO")
        & (inst_type == "OPTIDX")
        & (right.isin(["CE", "PE"]))
    ].copy()

    strike_value = pd.to_numeric(filtered["StrikePrice"], errors="coerce")
    expiry_value = pd.to_datetime(filtered["ContractExpiration"], errors="coerce")
    right_key = right.loc[filtered.index]

    lookup = {}
    for idx, row in filtered.iterrows():
        strike = strike_value.loc[idx]
        expiry = expiry_value.loc[idx]
        if pd.isna(strike) or pd.isna(expiry):
            continue
        key = (float(strike), right_key.loc[idx])
        lookup.setdefault(key, []).append(
            (expiry, str(row["ExchangeInstrumentID"]).strip(), str(row["Description"]).strip())
        )

    for entries in lookup.values():
        entries.sort(key=lambda item: item[0])

    return lookup


def resolve_contract(lookup, strike, right):
    entries = lookup.get((float(strike), str(right).strip().upper()))
    if not entries:
        return None
    today = datetime.datetime.now().date()
    for expiry, token, trading_symbol in entries:
        if expiry.date() >= today:
            return token, trading_symbol
    return None


def parse_initial_order_queued_line(line):
    if INITIAL_ORDER_QUEUED_MARKER not in line:
        return None

    parts = [part.strip() for part in line.split("|")]
    if len(parts) < 2:
        return None

    try:
        timestamp = datetime.datetime.strptime(parts[0], LOG_TIMESTAMP_FORMAT)
    except ValueError:
        return None

    marker_index = next((i for i, part in enumerate(parts) if INITIAL_ORDER_QUEUED_MARKER in part), None)
    if marker_index is None:
        return None

    fields = {}
    for part in parts[marker_index + 1:]:
        key, sep, value = part.partition("=")
        if sep:
            fields[key.strip()] = value.strip()

    required = ("slot", "strike", "right", "qty", "price")
    if not all(key in fields for key in required):
        return None

    try:
        return {
            "timestamp": timestamp,
            "slot": fields["slot"],
            "strike": float(fields["strike"]),
            "right": fields["right"].upper(),
            "qty": int(float(fields["qty"])),
            "price": float(fields["price"]),
        }
    except ValueError:
        return None


def build_order_number(event):
    key = f"{event['timestamp'].isoformat()}|{event['slot']}|{event['strike']}|{event['right']}|{event['qty']}"
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
    return str(int(digest[:16], 16))


def build_bse_row(event, contract):
    token, trading_symbol = contract
    entry_date = event["timestamp"].strftime(ROW_DATE_FORMAT)
    entry_time = event["timestamp"].strftime(ROW_TIME_FORMAT)

    fields = [
        "", "", "", "",                 # 0-3 Blank, Blank, ProductCode, ProductType
        token,                           # 4 lToken
        trading_symbol,                  # 5 Script
        "S",                             # 6 BuySell
        str(event["qty"]),               # 7 Trade Qty
        f"{event['price']:.2f}",         # 8 Trade Price
        BROKER_ID,                       # 9 BrokerId or AccountNo
        "N",                             # 10 Pro/Cli
        "",                              # 11 InstId
        entry_date, entry_time,          # 12-13 Trade Entry Dt/Time
        entry_date, entry_time,          # 14-15 Trade Modified Dt/Time
        build_order_number(event),       # 16 order number
        "L,BSE OPT",                     # 17 BookType
        "",                              # 18 InstrumentName
        "",                              # 19 Blank
        GREEK_CLIENT_ID,                 # 20 GreekClientId
        "CarryForWard",                  # 21 CarryForWard
        STRATEGY_NAME,                   # 22 StrategyName
        EXCH_RETAILER_ID,                # 23 Exch Retailer Id
    ]
    assert len(fields) == BSE_COLUMN_COUNT
    return "|".join(fields)


def load_bridge_state():
    if not os.path.exists(BRIDGE_STATE_FILE):
        return {"offset": 0}
    try:
        with open(BRIDGE_STATE_FILE, "r") as f:
            state = json.load(f)
        return {"offset": int(state.get("offset", 0))}
    except Exception as e:
        printt(f"LOG_BRIDGE_STATE_LOAD_FAILED | error={e}")
        return {"offset": 0}


def save_bridge_state(state):
    try:
        temp_path = f"{BRIDGE_STATE_FILE}.tmp"
        with open(temp_path, "w") as f:
            json.dump(state, f)
        os.replace(temp_path, BRIDGE_STATE_FILE)
    except Exception as e:
        printt(f"LOG_BRIDGE_STATE_SAVE_FAILED | error={e}")


def read_new_lines(state):
    if not os.path.exists(LOG_SOURCE_PATH):
        return [], state

    current_size = os.path.getsize(LOG_SOURCE_PATH)
    if current_size < state["offset"]:
        printt(f"LOG_BRIDGE_LOG_ROTATED | previous_offset={state['offset']} | current_size={current_size} | action=reset_offset")
        state = {"offset": 0}

    with open(LOG_SOURCE_PATH, "rb") as f:
        f.seek(state["offset"])
        chunk = f.read()

    if not chunk:
        return [], state

    last_newline = chunk.rfind(b"\n")
    if last_newline == -1:
        # Partial line still being written - wait for it to complete before reading it.
        return [], state

    usable = chunk[:last_newline + 1]
    new_state = {"offset": state["offset"] + len(usable)}
    lines = usable.decode("utf-8", errors="replace").splitlines()
    return lines, new_state


def append_row_with_retry(output_path, row_text):
    last_error = None
    for attempt in range(1, APPEND_RETRY_ATTEMPTS + 1):
        try:
            with open(output_path, "a", encoding="utf-8", newline="") as f:
                f.write(row_text + "\n")
            return True
        except Exception as e:
            last_error = e
            printt(f"LOG_BRIDGE_APPEND_RETRY | attempt={attempt} | max={APPEND_RETRY_ATTEMPTS} | error={e}")
            time.sleep(APPEND_RETRY_SLEEP_SECONDS)
    printt(f"LOG_BRIDGE_APPEND_FAILED | error={last_error}")
    return False


def run():
    createLogFile()
    printt(f"LOG_BRIDGE_START | log_source={LOG_SOURCE_PATH} | output={OUTPUT_TXT_PATH} | underlying={UNDERLYING} | strategy={STRATEGY_NAME}")

    if UNDERLYING.strip().upper() != "SENSEX":
        printt(f"LOG_BRIDGE_UNSUPPORTED_UNDERLYING | underlying={UNDERLYING} | reason=only_SENSEX_BSE_format_supported")
        return

    instrument_lookup = load_instrument_lookup(INSTRUMENT_CSV_PATH, UNDERLYING)
    printt(f"LOG_BRIDGE_INSTRUMENTS_LOADED | underlying={UNDERLYING} | contracts={sum(len(v) for v in instrument_lookup.values())}")

    state = load_bridge_state()
    pending_events = []

    while True:
        try:
            lines, state = read_new_lines(state)
            for line in lines:
                event = parse_initial_order_queued_line(line)
                if event is not None:
                    pending_events.append(event)

            still_pending = []
            for event in pending_events:
                contract = resolve_contract(instrument_lookup, event["strike"], event["right"])
                if contract is None:
                    printt(f"LOG_BRIDGE_TOKEN_NOT_FOUND | strike={event['strike']} | right={event['right']} | action=drop")
                    continue
                row_text = build_bse_row(event, contract)
                if append_row_with_retry(OUTPUT_TXT_PATH, row_text):
                    printt(f"LOG_BRIDGE_ROW_APPENDED | strike={event['strike']} | right={event['right']} | qty={event['qty']} | price={event['price']}")
                else:
                    still_pending.append(event)
            pending_events = still_pending

            # Only persist the read offset once every parsed event up to it has
            # either been appended or permanently dropped - otherwise a crash
            # mid-backlog could advance past events that were never written out.
            if not pending_events:
                save_bridge_state(state)
        except Exception as e:
            printt(f"LOG_BRIDGE_LOOP_ERROR | error={e}")

        time.sleep(POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    run()
