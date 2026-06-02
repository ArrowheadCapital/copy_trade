import importlib
import Helper as H
import helperGS as HG
import credentials as cre

import datetime
import time
import os
import json
import threading

import pandas as pd
from queue import Queue, Empty
from concurrent.futures import ThreadPoolExecutor
try:
    from file_watcher import start_file_watcher
    file_watcher_import_error = None
except Exception as e:
    start_file_watcher = None
    file_watcher_import_error = e

# ================= RELOAD =================
importlib.reload(H)
importlib.reload(HG)
importlib.reload(cre)

# ================= INIT =================
H.printt("Starting...")
H.createLogFile()
H.checkTime(datetime.time(5, 15, 1))

BROKER = cre.broker.upper()

H.printt(f"Broker: {BROKER}")

# WAIT FOR INSTRUMENT FILE UPDATE for StratX (8:50 AM)
now = datetime.datetime.now().time()
cutoff = datetime.time(8, 50)

if BROKER == "STRATX":
    if now < cutoff:
        H.printt("Instrument master updates at 8:50 AM. Exiting to avoid stale contracts.")
        exit()

    # CHECK INSTRUMENT MASTER FILE EXISTS
    if not cre.optionInstrumentPath or not os.path.exists(cre.optionInstrumentPath):
        H.printt(f"Instrument file not found: {cre.optionInstrumentPath}")
        exit() 

# Initialize the selected broker
if BROKER == "GREEK":
    brokerObj = HG.greeksoft()
elif BROKER == "STRATX":
    brokerObj = HG.StratX()
else:
    raise ValueError("Invalid broker name in credentials.py")

today = datetime.datetime.today().strftime("%m%d")
csvPathNSE = cre.pathNSE.format(formatted_date=today)
csvPathBSE = cre.pathBSE.format(formatted_date=today)

# ================= LICENSE =================
# License validation removed per request.
H.printt("License validation skipped")

# ================= CONFIG =================
MAX_WORKERS = 40
POLL_INTERVAL = 0.25
ALLOWED_SYMBOLS = {'NIFTY', 'BANKNIFTY', 'FINNIFTY', 'MIDCPNIFTY', 'SENSEX', 'BANKEX'}

# Risk limits (commented out for now, can enable later)
# MAX_POSITION_VALUE = 5000000
# DAILY_LOSS_LIMIT = -50000

# ================= HELPER FUNCTIONS =================
def read_csv_safely(path, sep=',', max_retries=3):
    for attempt in range(max_retries):
        try:
            df = pd.read_csv(path, header=None, engine="python", sep=sep, on_bad_lines='skip')
            return df if not df.empty else None
        
        except pd.errors.EmptyDataError:
            return None
        
        except Exception as e:
            if attempt < max_retries - 1:
                time.sleep(0.1 * (attempt + 1))  # Exponential backoff
            else:
                H.printt(f"Failed to read {path}: {e}")
                return None
            
    return None


def validate_trade(symbol, qty, strike=None, max_qty=50000):
    try:
        symbol = str(symbol).strip()

        if not symbol or int(qty) <= 0:
            return False
        
        if strike is not None and float(strike) <= 0:
            return False
        
        # if int(qty) > max_qty:
        #     H.printt(f"WARNING: Abnormal qty {qty} for {symbol}")
        #     return False
        return True
    except:
        return False


def is_market_open():
    now = datetime.datetime.now()
    return datetime.time(9, 15) <= now.time() <= datetime.time(15, 30)


def is_symbol_allowed(symbol):
    return str(symbol).upper().strip() in ALLOWED_SYMBOLS


# Commented out for future use
# def check_position_limit(symbol, quantity, price=100):
#     """Check if position is within limits"""
#     global position_tracker, MAX_POSITION_VALUE
#     current_value = sum(position_tracker.values())
#     new_value = quantity * price
#     
#     if current_value + new_value > MAX_POSITION_VALUE:
#         H.printt(f"RISK LIMIT: Position limit exceeded! Current: {current_value}")
#         return False
#     return True


# def check_circuit_breaker():
#     """Check if circuit breaker is triggered"""
#     global daily_pnl, DAILY_LOSS_LIMIT
#     if daily_pnl <= DAILY_LOSS_LIMIT:
#         H.printt(f"CIRCUIT BREAKER: Daily loss limit hit! PnL: {daily_pnl}")
#         return False
#     return True


# ================= ORDERBOOK THREAD =================
def fetch_order_book():
    while True:
        try:
            book = brokerObj.getOrderBookALL()

            data = None
            if isinstance(book, dict):
                data = book.get("data")

            if data is None:
                time.sleep(0.25)
                continue

            if BROKER == "STRATX":
                try:
                    brokerObj.retry_failed_orderbook_orders(data)
                except Exception as retry_error:
                    H.printt(f"StratX orderbook retry processor error: {retry_error}")

            df = pd.DataFrame(data)
            if df.empty:
                time.sleep(0.25)
                continue

            df.to_csv("trades.csv", index=False)
            time.sleep(0.25)
        except Exception as e:
            H.printt(f"OrderBook Error: {e}")
            time.sleep(1)

threading.Thread(target=fetch_order_book, daemon=True).start()

# ================= QUEUES =================
NSE_QUEUE = Queue(maxsize=4000)
BSE_QUEUE = Queue(maxsize=4000)

# ================= SELF-TRADE SAFE EXECUTION =================
def execute_with_retry(place_fn, args, lot_size=None):
    try:
        for _ in range(1):
            orders = place_fn(*args)
        #     time.sleep(0.5)

        #     for o in orders:
        #         d = brokerObj.getOrderStatus(o)
        #         if not d:
        #             H.printt(f"Order status not available for {o}")
        #             continue
        #         H.printt(
        #             f"Symbol:{d.get('symbol')} | "
        #             f"Status:{d.get('order_status')} | "
        #             f"Pending:{d.get('pending_qty')}"
        #         )

        #         if d.get("errorCode") == 17080:
        #             if BROKER == 'STRATX':
        #                 args = list(args)
        #             else:
        #                 args = list(args)
        #                 args[3] = int(d["pending_qty"] / lot_size)
        #                 args[4] = int(d["pending_qty"])
        #         else:
        #             return

        # H.printt("Self-trade retry failed")
    except Exception as e:
        H.printt(f"Self-trade retry error: {e}")

# ================= NSE WORKER =================
def nse_worker():
    while True:
        try:
            if not is_market_open():
                time.sleep(0.5)
                continue

            if NSE_QUEUE.empty():
                time.sleep(0.001)
                continue

            item = NSE_QUEUE.get()

            if BROKER == "STRATX":
                t, csv_read_ts = item
                timing_ctx = {
                    "worker_dequeue_ts": time.perf_counter(),
                }
            else:
                t = item
                csv_read_ts = None
                timing_ctx = None

            symbol = str(t[3]).strip()
            qty = int(t[14])
            side = int(t[13])
            inst_type = str(t[2]).strip().upper()

            if inst_type.startswith("FUT"):
                strike = None
            else:
                strike = float(t[5])
            
            # Validation checks
            if not validate_trade(symbol, qty, strike):
                H.printt(f"Invalid trade data: {symbol}")
                NSE_QUEUE.task_done()
                continue
            
            if not is_symbol_allowed(symbol):
                H.printt(f"Symbol not whitelisted: {symbol}")
                NSE_QUEUE.task_done()
                continue
            
            # Commented out for future use
            # if not check_circuit_breaker():
            #     H.printt("Circuit breaker active!")
            #     NSE_QUEUE.task_done()
            #     continue

            # ---- Order placement ----
            if BROKER == "GREEK":
                dt = brokerObj.getData(t)
                execute_with_retry(
                        brokerObj.placeOrder,
                        [dt.GreekToken, side, dt.Symbol, int(qty/dt.LotSize), qty, dt],
                        dt.LotSize
                    )
            else:
                execute_with_retry(
                        brokerObj.placeOrderStratX_NSE,
                        [symbol, 'BUY' if side==1 else 'SELL', t, csv_read_ts, timing_ctx]
                    )

            NSE_QUEUE.task_done()

        except Empty:
            continue
        except Exception as e:
            H.printt(f"NSE Worker Error: {e}")

# ================= BSE WORKER =================
def bse_worker():
    while True:
        try:
            if not is_market_open():
                time.sleep(0.5)
                continue

            if BSE_QUEUE.empty():
                time.sleep(0.001)
                continue

            item = BSE_QUEUE.get()
            if BROKER == "STRATX":
                t, csv_read_ts = item
                timing_ctx = {
                    "worker_dequeue_ts": time.perf_counter(),
                }
            else:
                t = item
                csv_read_ts = None
                timing_ctx = None

            symbol = str(t[5]).strip()
            qty = int(t[7])
            side_flag = str(t[6]).strip().upper()   # 'B' or 'S'

            # Validation checks
            if not validate_trade(symbol, qty):
                H.printt(f"Invalid BSE trade data: {symbol}")
                BSE_QUEUE.task_done()
                continue
            
            # if not is_symbol_allowed(symbol):
            #     H.printt(f"BSE symbol not whitelisted: {symbol}")
            #     BSE_QUEUE.task_done()
            #     continue

            # Commented out for future use
            # if not check_circuit_breaker():
            #     H.printt("Circuit breaker active!")
            #     BSE_QUEUE.task_done()
            #     continue

            # ---- Order placement ----
            if BROKER == "GREEK":
                dt = brokerObj.getDataBSE(t[4])
                execute_with_retry(
                        brokerObj.placeOrderBSE,
                        [dt.GreekToken, 'Buy' if side_flag=='B' else 'Sell', dt.Symbol, int(qty/dt.LotSize), qty, dt],
                        dt.LotSize
                    )
            else:
                execute_with_retry(
                        brokerObj.placeOrderStratX_BSE,
                        [symbol, 'BUY' if side_flag=='B' else 'SELL', t, csv_read_ts, timing_ctx]
                    )

            BSE_QUEUE.task_done()

        except Empty:
            continue
        except Exception as e:
            H.printt(f"BSE Worker Error: {e}")

# ================= PRE-LOAD STRATX INSTRUMENT MASTER =================
if BROKER == "STRATX":
    brokerObj.load_instrument_master()
    brokerObj.start_retry_state_saver()
    brokerObj.warmup_stratx_sessions()

# ================= START 50 WORKERS =================
NSE_EXECUTOR = ThreadPoolExecutor(max_workers=MAX_WORKERS)
BSE_EXECUTOR = ThreadPoolExecutor(max_workers=MAX_WORKERS)

for _ in range(MAX_WORKERS):
    NSE_EXECUTOR.submit(nse_worker)
    BSE_EXECUTOR.submit(bse_worker)

H.printt(f"Started {MAX_WORKERS} NSE workers and {MAX_WORKERS} BSE workers")

# ================= CSV TRACKERS =================
last_nse = pd.DataFrame()
last_bse = pd.DataFrame()
nse_last_mtime = 0
bse_last_mtime = 0
csv_state_lock = threading.Lock()

# NSE
if os.path.exists(csvPathNSE):
    try:
        df_init = pd.read_csv(csvPathNSE, header=None, engine="python")
        # df_init = df_init[df_init[17].str.strip() == cre.clientCodeToCopy]
        nse_seen = len(df_init)
        last_nse = df_init
        nse_last_mtime = os.path.getmtime(csvPathNSE)
        H.printt(f"NSE copy starts from row {nse_seen}")
    except pd.errors.EmptyDataError:
        nse_seen = 0
    except Exception as e:
        H.printt(f"NSE init read error: {e}")
        nse_seen = 0
else:
    nse_seen = 0

# BSE
if os.path.exists(csvPathBSE):
    try:
        df_init = pd.read_csv(csvPathBSE, sep="|", header=None)
        # df_init = df_init[df_init[9].str.strip() == cre.clientCodeToCopy]
        bse_seen = len(df_init)
        last_bse = df_init
        bse_last_mtime = os.path.getmtime(csvPathBSE)
        H.printt(f"BSE copy starts from row {bse_seen}")
    except pd.errors.EmptyDataError:
        bse_seen = 0
    except Exception as e:
        H.printt(f"BSE init read error: {e}")
        bse_seen = 0
else:
    bse_seen = 0


def process_nse_csv():
    global nse_seen, last_nse, nse_last_mtime
    if not os.path.exists(csvPathNSE):
        return
    try:
        current_mtime = os.path.getmtime(csvPathNSE)
        with csv_state_lock:
            if current_mtime <= nse_last_mtime:
                return

        df = read_csv_safely(csvPathNSE)
        if df is None:
            return

        with csv_state_lock:
            if current_mtime <= nse_last_mtime:
                return
            nse_last_mtime = current_mtime
            last_nse = df
            if len(df) <= nse_seen:
                return
            new_rows = df.iloc[nse_seen:]
            nse_seen = len(df)

        new_rows = new_rows.replace(r'^\s+|\s+$', '', regex=True)

        qty_col = 14
        exchange_order_id_col = 23
        agg_map = {col: "first" for col in new_rows.columns}
        agg_map[qty_col] = "sum"
        
        combined_rows = (
            new_rows.groupby(
                exchange_order_id_col,
                dropna=False,
                sort=False,
                as_index=False,
            )
            .agg(agg_map)
        )
        combined_rows = combined_rows[new_rows.columns]
        
        for row in combined_rows.itertuples(index=False, name=None):
            if BROKER == "STRATX":
                NSE_QUEUE.put((row, time.perf_counter()))
            else:
                NSE_QUEUE.put(row)
        
        H.printt(f"NSE: Added {len(combined_rows)} combined trades from {len(new_rows)} rows")

    except Exception as e:
        H.printt(f"NSE file error: {e}")


def process_bse_csv():
    global bse_seen, last_bse, bse_last_mtime
    if not os.path.exists(csvPathBSE):
        return
    try:
        current_mtime = os.path.getmtime(csvPathBSE)
        with csv_state_lock:
            if current_mtime <= bse_last_mtime:
                return

        df = read_csv_safely(csvPathBSE, sep="|")
        if df is None:
            return

        with csv_state_lock:
            if current_mtime <= bse_last_mtime:
                return
            bse_last_mtime = current_mtime
            last_bse = df
            if len(df) <= bse_seen:
                return
            new_rows = df.iloc[bse_seen:]
            bse_seen = len(df)

        new_rows = new_rows.replace(r'^\s+|\s+$', '', regex=True)

        qty_col = 7
        exchange_order_id_col = 16
        agg_map = {col: "first" for col in new_rows.columns}
        agg_map[qty_col] = "sum"
        
        combined_rows = (
            new_rows.groupby(
                exchange_order_id_col,
                dropna=False,
                sort=False,
                as_index=False,
            )
            .agg(agg_map)
        )
        combined_rows = combined_rows[new_rows.columns]
        
        for row in combined_rows.itertuples(index=False, name=None):
            if BROKER == "STRATX":
                BSE_QUEUE.put((row, time.perf_counter()))
            else:
                BSE_QUEUE.put(row)
        
        H.printt(f"BSE: Added {len(combined_rows)} combined trades from {len(new_rows)} rows")

    except Exception as e:
        H.printt(f"BSE file error: {e}")


file_observer = None
if start_file_watcher is not None:
    file_observer = start_file_watcher(
        csvPathNSE,
        csvPathBSE,
        on_nse_change=process_nse_csv,
        on_bse_change=process_bse_csv,
    )
if file_observer is not None:
    H.printt("File watcher started - zero-sleep signal detection active")
else:
    if file_watcher_import_error is not None:
        H.printt(f"File watcher import failed: {file_watcher_import_error}")
    H.printt("File watcher failed to start - fallback polling active")

FALLBACK_POLL_INTERVAL = 5.0

# ================= MAIN PRODUCER LOOP =================
while True:
    try:
        process_nse_csv()
        process_bse_csv()

        # -------- HEALTH LOG --------
        if NSE_QUEUE.qsize() > 200 or BSE_QUEUE.qsize() > 200:
            H.printt(f"Queue Load | NSE:{NSE_QUEUE.qsize()} | BSE:{BSE_QUEUE.qsize()}")

        time.sleep(FALLBACK_POLL_INTERVAL)

    except Exception as e:
        H.printt(f"Main Loop Error: {e}")
        time.sleep(1)