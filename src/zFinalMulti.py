import importlib
from src.utils import Helper as H
from src import helperGS as HG
import credentials as cre

import datetime
import time
import os
import shutil
import threading

import pandas as pd
from queue import Queue, Empty
from concurrent.futures import ThreadPoolExecutor
try:
    from src.utils.file_watcher import start_file_watcher
    file_watcher_import_error = None
except Exception as e:
    start_file_watcher = None
    file_watcher_import_error = e

# ================= RELOAD =================
importlib.reload(H)
importlib.reload(HG.greeksoft_broker)
importlib.reload(HG.stratx_broker)
importlib.reload(HG)
importlib.reload(cre)

# ================= INIT =================
H.printt("Starting...")
H.createLogFile()
H.checkTime(datetime.time(5, 15, 1))

BROKER = cre.broker.upper()
STRATX_RECONCILIATION_ENABLED = False
StratXReconciliation = None
if BROKER == "STRATX" and STRATX_RECONCILIATION_ENABLED:
    from src.stratx.stratx_reconciliation import StratXReconciliation

H.printt(f"Broker: {BROKER}")

# WAIT FOR INSTRUMENT FILE UPDATE for StratX (8:50 AM)
now = datetime.datetime.now().time()
cutoff = datetime.time(8, 50)

if BROKER == "STRATX":
    if now < cutoff:
        H.printt("Instrument master updates at 8:50 AM. Exiting to avoid stale contracts.")
        exit()

    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    local_instrument_path = os.path.join(repo_root, "options_instruments.csv")
    configured_instrument_path = str(cre.optionInstrumentPath or "").strip()

    if configured_instrument_path and os.path.isfile(configured_instrument_path):
        try:
            if os.path.abspath(configured_instrument_path) != os.path.abspath(local_instrument_path):
                temp_instrument_path = f"{local_instrument_path}.tmp"
                shutil.copy2(configured_instrument_path, temp_instrument_path)
                os.replace(temp_instrument_path, local_instrument_path)
            H.printt(f"Instrument master saved locally: {local_instrument_path}")
        except Exception as e:
            H.printt(f"Instrument master copy failed: {e}")

    if not os.path.isfile(local_instrument_path):
        H.printt(f"Instrument file not found at configured or local path: {configured_instrument_path}, {local_instrument_path}")
        exit()

    cre.optionInstrumentPath = local_instrument_path

# Initialize the selected broker
if BROKER == "GREEK":
    brokerObj = HG.greeksoft()
elif BROKER == "STRATX":
    brokerObj = HG.StratX()
    brokerObj.stratx_reconciliation_enabled = STRATX_RECONCILIATION_ENABLED
else:
    raise ValueError("Invalid broker name in credentials.py")

today = datetime.datetime.today().strftime("%m%d")
csvPathNSE = cre.pathNSE.format(formatted_date=today)
csvPathBSE = cre.pathBSE.format(formatted_date=today)
GREEK_TRADES_FILE = os.path.join("Trades", f"trades_{datetime.datetime.today():%Y%m%d}.csv")

# ================= LICENSE =================
# License validation removed per request.
H.printt("License validation skipped")

# ================= CONFIG =================
MAX_WORKERS = 5
POLL_INTERVAL = 0.25
ALLOWED_SYMBOLS = {'NIFTY', 'BANKNIFTY', 'FINNIFTY', 'MIDCPNIFTY', 'SENSEX', 'BANKEX'}
COPY_SOURCE_ID = str(getattr(cre, "copy_source_id", "")).strip().upper()
source_strategy_names_config = getattr(cre, "source_strategy_names", [])
COPY_SOURCE_STRATEGY_NAMES = {
    str(name).strip().upper()
    for name in source_strategy_names_config
    if str(name).strip()
} if isinstance(source_strategy_names_config, (list, tuple, set)) else set()
COPY_ALLOWED_DELAY_SECONDS = float(os.getenv("COPY_ALLOWED_DELAY_SECONDS", "0") or 0)
RECON_INTERVAL_SECONDS = 5
RECON_REQUIRED_CONFIRMATIONS = 5
RECON_COOLDOWN_SECONDS = 60
RECON_REPORT_ONLY = True
RECON_STATE_FILE = "stratx_recon_state.json"

NSE_EXPECTED_HEADER = (
    "Trade Number", "Trade Status", "Instrument Name", "Symbol", "Expiry date",
    "Strike Price", "Option Type", "SecurityDesc", "Book Type", "Book Type Name",
    "Market Type", "Trader/User Id", "BranchId", "BuySell", "Trade Qty",
    "Trade Price", "Pro/Client", "BrokerId/AccountNo", "Participant/Broker Id",
    "Open/Close Flag", "Cover/Uncover Flag", "Trade DateTime", "Last Modified time",
    "Exch.Order Number", "NIL", "Last Modified time", "StrategyName", "ExchRetailerId",
)

BSE_EXPECTED_HEADER = (
    "Blank", "Blank", "ProductCode", "ProductType", "lToken", "Script", "BuySell",
    "Trade Qty", "Trade Price", "BrokerId or AccountNo", "Pro/Cli", "InstId",
    "Trade Entry Dt", "Trade Entry Time", "Trade Modified Dt", "Trade Modified Time",
    "order number", "BookType", "InstrumentName", "Blank", "GreekClientId",
    "CarryForWard", "StrategyName", "Exch Retailer Id",
)

# Risk limits (commented out for now, can enable later)
# MAX_POSITION_VALUE = 5000000
# DAILY_LOSS_LIMIT = -50000

# ================= HELPER FUNCTIONS =================
def read_csv_safely(path, sep=',', max_retries=3, skiprows=0):
    for attempt in range(max_retries):
        try:
            df = pd.read_csv(path, header=None, engine="python", sep=sep, skiprows=skiprows, on_bad_lines='skip')
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


def validate_source_header(path, sep, expected_header, source):
    try:
        with open(path, "r", encoding="utf-8-sig", errors="replace") as source_file:
            first_line = source_file.readline()

        if not first_line.strip():
            return None

        actual_header = tuple(value.strip() for value in first_line.rstrip("\r\n").split(sep))
        if actual_header != expected_header:
            H.printt(f"{source} header mismatch - copying disabled for this run")
            return False

        H.printt(f"{source} header validated")
        return True

    except Exception as e:
        H.printt(f"{source} header validation error | error={e}")
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


def is_copy_row_allowed(row_id, strategy_name, row_dt, source):
    try:
        if not COPY_SOURCE_ID or not COPY_SOURCE_STRATEGY_NAMES:
            H.printt(f"{source} copy filter configuration missing")
            return False

        actual_id = str(row_id).strip().upper()
        if actual_id != COPY_SOURCE_ID:
            H.printt(f"{source} skip source id | expected={COPY_SOURCE_ID} | actual={actual_id}")
            return False

        actual_strategy_name = str(strategy_name).strip().upper()
        if actual_strategy_name not in COPY_SOURCE_STRATEGY_NAMES:
            H.printt(f"{source} skip strategy name | expected={sorted(COPY_SOURCE_STRATEGY_NAMES)} | actual={actual_strategy_name}")
            return False

        diff = abs((datetime.datetime.now() - row_dt).total_seconds())
        if diff > COPY_ALLOWED_DELAY_SECONDS:
            H.printt(f"{source} skip delay | diff={diff:.2f}s | allowed={COPY_ALLOWED_DELAY_SECONDS}s")
            return False

        return True

    except Exception as e:
        H.printt(f"{source} copy filter error | error={e}")
        return False


def is_market_open():
    now = datetime.datetime.now()
    return datetime.time(9, 15) <= now.time() <= datetime.time(15, 40)


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
            elif BROKER == "GREEK":
                try:
                    brokerObj.retry_failed_greeksoft_orders(data)
                except Exception as retry_error:
                    H.printt(f"GreekSoft orderbook retry processor error: {retry_error}")

            df = pd.DataFrame(data)
            if df.empty:
                time.sleep(0.25)
                continue

            if BROKER == "GREEK":
                os.makedirs("Trades", exist_ok=True)
                df.to_csv(GREEK_TRADES_FILE, index=False)
            else:
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
                        [dt.GreekToken, side, dt.Symbol, int(qty/dt.LotSize), qty, dt, str(t[23]).strip()],
                        dt.LotSize
                    )
            else:
                side_text = 'BUY' if side == 1 else 'SELL'
                execute_with_retry(
                        brokerObj.placeOrderStratX_NSE,
                        [symbol, side_text, t, csv_read_ts, timing_ctx]
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
                        [dt.GreekToken, 'Buy' if side_flag=='B' else 'Sell', dt.Symbol, int(qty/dt.LotSize), qty, dt, str(t[16]).strip()],
                        dt.LotSize
                    )
            else:
                side_text = 'BUY' if side_flag == 'B' else 'SELL'
                execute_with_retry(
                        brokerObj.placeOrderStratX_BSE,
                        [symbol, side_text, t, csv_read_ts, timing_ctx]
                    )

            BSE_QUEUE.task_done()

        except Empty:
            continue
        except Exception as e:
            H.printt(f"BSE Worker Error: {e}")

# ================= PRE-LOAD STRATX INSTRUMENT MASTER =================
if BROKER == "STRATX":
    brokerObj.load_stratx_net_state()
    brokerObj.start_stratx_net_state_saver()
    brokerObj.load_instrument_master()
    brokerObj.sync_stratx_net_from_traded_orders(source="startup")
    brokerObj.start_retry_state_saver()
    brokerObj.warmup_stratx_sessions()
elif BROKER == "GREEK":
    brokerObj.load_greek_net_state()
    brokerObj.start_greek_net_state_saver()
    brokerObj.sync_greek_net_from_traded_orders(source="startup")

# ================= START 40 WORKERS =================
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
nse_header_valid = None
bse_header_valid = None
csv_state_lock = threading.Lock()

# NSE
if os.path.exists(csvPathNSE):
    try:
        nse_header_valid = validate_source_header(csvPathNSE, ",", NSE_EXPECTED_HEADER, "NSE")
        if nse_header_valid:
            df_init = pd.read_csv(csvPathNSE, header=None, engine="python", skiprows=1)
            nse_seen = len(df_init)
            last_nse = df_init
            H.printt(f"NSE copy starts from data row {nse_seen}")
        else:
            nse_seen = 0
        if nse_header_valid is not None:
            nse_last_mtime = os.path.getmtime(csvPathNSE)
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
        bse_header_valid = validate_source_header(csvPathBSE, "|", BSE_EXPECTED_HEADER, "BSE")
        if bse_header_valid:
            df_init = pd.read_csv(csvPathBSE, sep="|", header=None, skiprows=1)
            bse_seen = len(df_init)
            last_bse = df_init
            H.printt(f"BSE copy starts from data row {bse_seen}")
        else:
            bse_seen = 0
        if bse_header_valid is not None:
            bse_last_mtime = os.path.getmtime(csvPathBSE)
    except pd.errors.EmptyDataError:
        bse_seen = 0
    except Exception as e:
        H.printt(f"BSE init read error: {e}")
        bse_seen = 0
else:
    bse_seen = 0


def process_nse_csv():
    global nse_seen, last_nse, nse_last_mtime, nse_header_valid
    if not os.path.exists(csvPathNSE):
        return
    try:
        if nse_header_valid is False:
            return

        current_mtime = os.path.getmtime(csvPathNSE)
        with csv_state_lock:
            if current_mtime <= nse_last_mtime:
                return

        if nse_header_valid is None:
            header_valid = validate_source_header(csvPathNSE, ",", NSE_EXPECTED_HEADER, "NSE")
            if header_valid is None:
                return
            with csv_state_lock:
                if nse_header_valid is None:
                    nse_header_valid = header_valid
            if not nse_header_valid:
                with csv_state_lock:
                    nse_last_mtime = current_mtime
                return

        df = read_csv_safely(csvPathNSE, skiprows=1)
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

        pause_event = globals().get("copy_trade_paused")
        if pause_event is not None and pause_event.is_set():
            H.printt(f"NSE paused: skipped {len(new_rows)} new rows")
            return

        new_rows = new_rows.replace(r'^\s+|\s+$', '', regex=True)

        allowed_rows = []
        for row in new_rows.itertuples(index=False, name=None):
            try:
                instrument_type = str(row[2]).strip().upper()
                if instrument_type != "OPTIDX":
                    H.printt(f"NSE skip instrument type | actual={instrument_type}")
                    continue

                underlying = str(row[3]).strip().upper()
                if underlying != "NIFTY":
                    H.printt(f"NSE skip underlying | actual={underlying}")
                    continue

                row_dt = datetime.datetime.strptime(str(row[25]).strip(), "%d %b %Y %H:%M:%S")
                if is_copy_row_allowed(row[27], row[26], row_dt, "NSE"):
                    allowed_rows.append(row)
            except Exception as e:
                H.printt(f"NSE copy filter error | error={e}")

        if not allowed_rows:
            H.printt(f"NSE: skipped {len(new_rows)} rows by copy filter")
            return

        new_rows = pd.DataFrame(allowed_rows, columns=new_rows.columns)

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
    global bse_seen, last_bse, bse_last_mtime, bse_header_valid
    if not os.path.exists(csvPathBSE):
        return
    try:
        if bse_header_valid is False:
            return

        current_mtime = os.path.getmtime(csvPathBSE)
        with csv_state_lock:
            if current_mtime <= bse_last_mtime:
                return

        if bse_header_valid is None:
            header_valid = validate_source_header(csvPathBSE, "|", BSE_EXPECTED_HEADER, "BSE")
            if header_valid is None:
                return
            with csv_state_lock:
                if bse_header_valid is None:
                    bse_header_valid = header_valid
            if not bse_header_valid:
                with csv_state_lock:
                    bse_last_mtime = current_mtime
                return

        df = read_csv_safely(csvPathBSE, sep="|", skiprows=1)
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

        pause_event = globals().get("copy_trade_paused")
        if pause_event is not None and pause_event.is_set():
            H.printt(f"BSE paused: skipped {len(new_rows)} new rows")
            return

        new_rows = new_rows.replace(r'^\s+|\s+$', '', regex=True)

        allowed_rows = []
        for row in new_rows.itertuples(index=False, name=None):
            try:
                instrument_type = str(row[17]).strip().upper()
                if "OPT" not in instrument_type:
                    H.printt(f"BSE skip instrument type | actual={instrument_type}")
                    continue

                trading_symbol = str(row[5]).strip().upper()
                if not trading_symbol.startswith("SENSEX"):
                    H.printt(f"BSE skip underlying | actual={trading_symbol}")
                    continue

                row_dt = datetime.datetime.strptime(
                    f"{str(row[14]).strip()} {str(row[15]).strip()}",
                    "%d/%m/%Y %H:%M:%S",
                )
                if is_copy_row_allowed(row[-1], row[-2], row_dt, "BSE"):
                    allowed_rows.append(row)
            except Exception as e:
                H.printt(f"BSE copy filter error | error={e}")

        if not allowed_rows:
            H.printt(f"BSE: skipped {len(new_rows)} rows by copy filter")
            return

        new_rows = pd.DataFrame(allowed_rows, columns=new_rows.columns)

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

stratx_reconciliation_manager = None
if BROKER == "STRATX" and STRATX_RECONCILIATION_ENABLED:
    try:
        stratx_reconciliation_manager = StratXReconciliation(
            broker=brokerObj,
            nse_path=csvPathNSE,
            bse_path=csvPathBSE,
            copy_source_id=COPY_SOURCE_ID,
            client_id=getattr(cre, "STRATX_NET_CLIENT_ID", "Y05601"),
            multiplier=getattr(cre, "multiplier", 1),
            strategy_name=getattr(cre, "strategy_name", ""),
            order_url=f"https://{cre.stratX_url}/api/v1/orders/place-order/",
            is_market_open=is_market_open,
            interval_seconds=RECON_INTERVAL_SECONDS,
            required_confirmations=RECON_REQUIRED_CONFIRMATIONS,
            cooldown_seconds=RECON_COOLDOWN_SECONDS,
            report_only=RECON_REPORT_ONLY,
            state_file=RECON_STATE_FILE,
        )
        stratx_reconciliation_manager.start()
    except Exception as e:
        H.printt(f"STRATX_RECON_START_FAILED | error={e}")

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
