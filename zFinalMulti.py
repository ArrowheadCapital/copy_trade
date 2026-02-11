import importlib
import Helper as H
import helperGS as HG
import credentials as cre

import datetime
import time
import os
import json
import threading
import wmi

import pandas as pd
from cryptography.fernet import Fernet
from queue import Queue, Empty
from concurrent.futures import ThreadPoolExecutor

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
MAX_WORKERS = 25
POLL_INTERVAL = 0.25
MAX_ORDERS_PER_SECOND = 10
ALLOWED_SYMBOLS = {'NIFTY', 'BANKNIFTY', 'FINNIFTY', 'MIDCPNIFTY', 'SENSEX', 'BANKEX'}

# Risk limits (commented out for now, can enable later)
# MAX_POSITION_VALUE = 5000000
# DAILY_LOSS_LIMIT = -50000

order_timestamps = []
latency_records = []

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


def check_order_rate_limit():
    global order_timestamps
    now = time.time()

    order_timestamps = [t for t in order_timestamps if now - t < 1]

    if len(order_timestamps) >= MAX_ORDERS_PER_SECOND:
        H.printt("RISK: Order rate exceeded")
        return False
    order_timestamps.append(now)
    return True


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
            pd.DataFrame(book["data"]).to_csv("trades.csv", index=False)
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
        for _ in range(3):
            orders = place_fn(*args)
            time.sleep(0.5)

            for o in orders:
                d = brokerObj.getOrderStatus(o)
                H.printt(
                    f"Symbol:{d.get('symbol')} | "
                    f"Status:{d.get('order_status')} | "
                    f"Pending:{d.get('pending_qty')}"
                )

                if d.get("errorCode") == 17080:
                    if BROKER == 'STRATX':
                        args = list(args)
                    else:
                        args = list(args)
                        args[3] = int(d["pending_qty"] / lot_size)
                        args[4] = int(d["pending_qty"])
                else:
                    return

        H.printt("Self-trade retry failed")
    except Exception as e:
        H.printt(f"Self-trade retry error: {e}")

# ================= NSE WORKER =================
def nse_worker():
    while True:
        try:
            t = NSE_QUEUE.get(timeout=1)
            start_time = time.time()

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
            
            if not is_market_open():
                H.printt("Market closed, skipping trade")
                NSE_QUEUE.task_done()
                continue
            
            if not check_order_rate_limit():
                time.sleep(1)
                NSE_QUEUE.put(t)  # Re-queue
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
                        [symbol, 'BUY' if side==1 else 'SELL', t]
                    )
                
            # ---- Latency tracking ----
            latency_records.append((time.time() - start_time) * 1000)
            if len(latency_records) > 1000:
                latency_records.pop(0)

            NSE_QUEUE.task_done()

        except Empty:
            continue
        except Exception as e:
            H.printt(f"NSE Worker Error: {e}")

# ================= BSE WORKER =================
def bse_worker():
    while True:
        try:
            t = BSE_QUEUE.get(timeout=1)
            start_time = time.time()

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
            
            if not is_market_open():
                H.printt("Market closed, skipping BSE trade")
                BSE_QUEUE.task_done()
                continue
            
            if not check_order_rate_limit():
                time.sleep(1)
                BSE_QUEUE.put(t)
                BSE_QUEUE.task_done()
                continue

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
                        [symbol, 'BUY' if side_flag=='B' else 'SELL', t]
                    )
                
            # ---- Latency tracking ----
            latency_records.append((time.time() - start_time) * 1000)
            if len(latency_records) > 1000:
                latency_records.pop(0)

            BSE_QUEUE.task_done()

        except Empty:
            continue
        except Exception as e:
            H.printt(f"BSE Worker Error: {e}")

# ================= START 50 WORKERS =================
NSE_EXECUTOR = ThreadPoolExecutor(max_workers=MAX_WORKERS)
BSE_EXECUTOR = ThreadPoolExecutor(max_workers=MAX_WORKERS)

for _ in range(MAX_WORKERS):
    NSE_EXECUTOR.submit(nse_worker)
    BSE_EXECUTOR.submit(bse_worker)

H.printt(f"Started {MAX_WORKERS} NSE workers and {MAX_WORKERS} BSE workers")

# ================= LATENCY MONITOR =================
def latency_monitor():
    while True:
        time.sleep(300) # Every 5 mins
        if latency_records:
            lat_sec = [x / 1000 for x in latency_records]
            avg = sum(lat_sec)/len(lat_sec)
            H.printt(f"[LATENCY] Avg:{avg:.3f}s | Min:{min(lat_sec):.3f}s | Max:{max(lat_sec):.3f}s")

threading.Thread(target=latency_monitor, daemon=True).start()

# ================= CSV TRACKERS =================
# nse_seen = 0
# bse_seen = 0
# last_nse = pd.DataFrame()
# last_bse = pd.DataFrame()

# ================= CSV TRACKERS =================
last_nse = pd.DataFrame()
last_bse = pd.DataFrame()
nse_last_mtime = 0
bse_last_mtime = 0

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


# ================= MAIN PRODUCER LOOP =================
while True:
    try:
        # -------- NSE --------
        if os.path.exists(csvPathNSE):
            try:
                current_mtime = os.path.getmtime(csvPathNSE)

                if current_mtime > nse_last_mtime:
                    nse_last_mtime = current_mtime

                    df = read_csv_safely(csvPathNSE)
                    if df is not None:
                        last_nse = df

                        if len(df) > nse_seen:
                            new_rows = df.iloc[nse_seen:]
                            for _, row in new_rows.iterrows():
                                NSE_QUEUE.put(row)
                            H.printt(f"NSE: Added {len(new_rows)} new trades to queue")
                            nse_seen = len(df)


            except Exception as e:
                H.printt(f"NSE file error: {e}")

        # -------- BSE --------
        if os.path.exists(csvPathBSE):
            try:
                current_mtime = os.path.getmtime(csvPathBSE)

                if current_mtime > bse_last_mtime:
                    bse_last_mtime = current_mtime

                    df = read_csv_safely(csvPathBSE, sep="|")
                    if df is not None:
                        last_bse = df

                        if len(df) > bse_seen:
                            new_rows = df.iloc[bse_seen:]
                            for _, row in new_rows.iterrows():
                                BSE_QUEUE.put(row)
                            H.printt(f"BSE: Added {len(new_rows)} new trades to queue")
                            bse_seen = len(df)

            except Exception as e:
                H.printt(f"BSE file error: {e}")

        # -------- HEALTH LOG --------
        if NSE_QUEUE.qsize() > 200 or BSE_QUEUE.qsize() > 200:
            H.printt(
                f"Queue Load | NSE:{NSE_QUEUE.qsize()} | BSE:{BSE_QUEUE.qsize()}"
            )

        time.sleep(POLL_INTERVAL)

    except Exception as e:
        H.printt(f"Main Loop Error: {e}")
        time.sleep(1)