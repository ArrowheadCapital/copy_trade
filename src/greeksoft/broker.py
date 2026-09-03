import json
import requests
import socket
import datetime
import os
import time
import uuid
import atexit
import pandas as pd
from io import StringIO
import credentials as cre
import threading
from concurrent.futures import ThreadPoolExecutor
from collections import deque
from urllib3.connection import HTTPConnection
from src.utils.broker_helpers import createLogFile, printt, saveInLogFile
from src.utils.order_pricing import build_cache_symbol, price_from_avg_ltp_or_fallback

urll = getattr(cre, "urll", None)
username = getattr(cre, "username", None)
pw = getattr(cre, "pw", None)
multiplier = getattr(cre, "multiplier", None)
authurl = getattr(cre, "authurl", None)

niftyFreeze = getattr(cre, "niftyFreeze", None)
bnfFreeze = getattr(cre, "bnfFreeze", None)
sensexFreeze = getattr(cre, "sensexFreeze", None)
bankex = getattr(cre, "bankex", None)
midcpniftyFreeze = getattr(cre, "midcpnifty", None)
finniftyFreeze = getattr(cre, "finnifty", None)

iprocli = getattr(cre, "iprocli", None)
AccountNumber = getattr(cre, "AccountNumber", None)

# =========================== COMMON FUNCTIONS ==================================
greek_rate_lock = threading.Lock()
greek_order_timestamps = deque()
MAX_GREEK_ORDERS_PER_WINDOW = 9
GREEK_RATE_WINDOW_SECONDS = 1.2
GREEK_KEEPALIVE_IDLE_SECONDS = 30
GREEK_KEEPALIVE_INTERVAL_SECONDS = 10
GREEK_KEEPALIVE_PROBE_COUNT = 3


def get_greek_trades_file():
    return os.path.join("Trades", f"trades_{datetime.datetime.today():%Y%m%d}.csv")


class GreekKeepAliveAdapter(requests.adapters.HTTPAdapter):
    def init_poolmanager(self, connections, maxsize, block=False, **pool_kwargs):
        pool_kwargs["socket_options"] = HTTPConnection.default_socket_options + [
            (socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1),
            (socket.IPPROTO_TCP, socket.TCP_KEEPIDLE, GREEK_KEEPALIVE_IDLE_SECONDS),
            (socket.IPPROTO_TCP, socket.TCP_KEEPINTVL, GREEK_KEEPALIVE_INTERVAL_SECONDS),
            (socket.IPPROTO_TCP, socket.TCP_KEEPCNT, GREEK_KEEPALIVE_PROBE_COUNT),
        ]
        return super().init_poolmanager(connections, maxsize, block=block, **pool_kwargs)


def wait_for_greek_order_slot():
    while True:
        with greek_rate_lock:
            now = time.time()

            while greek_order_timestamps and now - greek_order_timestamps[0] >= GREEK_RATE_WINDOW_SECONDS:
                greek_order_timestamps.popleft()

            if len(greek_order_timestamps) < MAX_GREEK_ORDERS_PER_WINDOW:
                greek_order_timestamps.append(now)
                return

            wait_time = GREEK_RATE_WINDOW_SECONDS - (now - greek_order_timestamps[0])
            printt(f"RATE LIMIT HIT | waiting {wait_time:.3f}s")

        time.sleep(max(wait_time, 0.01))

def getOrderStatus(orderId):
        try:
            if orderId == 0:
                return('Order Data not avaiable..!')

            for i in range(10):
                try:
                    df = pd.read_csv(get_greek_trades_file())
                    res = df[df['gorderid'] == int(orderId)].to_dict(orient='records')[0]
                    return res
                except Exception as e:
                    printt('Error Order()_orderStatus :- ',e,i)
                    time.sleep(1)
        except Exception as e:
            printt(f"Error in getOrderStatus: {e}")
            return None

def getFreezeQua(freeze_limit, lot_size, total_quantity):
    try:
        total_quantity = int(total_quantity)
        result = []
        while total_quantity > 0:
            qty = min(total_quantity, int(freeze_limit))
            qty = (qty // int(lot_size)) * int(lot_size)
            if qty == 0:
                break
            result.append(qty)
            total_quantity -= qty
        return result
    except Exception as e:
        printt(f"Error in getFreezeQua: {e}")
        return []

# =========================== GREEKSOFT API ==================================

class greeksoft:
    greek_instrument_names_to_load = {"NIFTY", "SENSEX"}
    greek_order_workers = 5
    greek_request_timeout = 15
    greek_http_max_attempts = 4
    greek_http_retry_sleep = 0.3
    greek_retry_state_file = "greek_state.json"
    greek_retry_state_save_interval = 1
    max_greek_orderbook_retries = 3
    greek_net_state_file = "greek_net_state.json"
    greek_net_state_save_interval = 1
    greek_net_buckets = ("NIFTY_CE", "NIFTY_PE", "SENSEX_CE", "SENSEX_PE")

    def __init__(self):
        global username
        global pw
        self.greek_thread_local = threading.local()
        self.greek_order_pool = ThreadPoolExecutor(max_workers=self.greek_order_workers, thread_name_prefix="greek_order")
        self.greek_retry_state_lock = threading.RLock()
        self.greek_retry_state_save_lock = threading.Lock()
        self.greek_retry_state_dirty = False
        self.greek_retry_state_loaded = False
        self.greek_retry_state_saver_started = False
        self.greek_retry_state = {}
        self.greek_net_lock = threading.Lock()
        self.greek_net_state_save_lock = threading.Lock()
        self.greek_net_state_dirty = False
        self.greek_net_state_saver_started = False
        self.greek_net_position = {bucket: 0 for bucket in self.greek_net_buckets}
        self.greek_net_released_roots = set()
        self.greek_nse_contract_by_key = {}
        self.greek_bse_contract_by_token = {}
        initialized = False
        last_error = None

        for i in range(4):
            try:
                url = f"{authurl}/auth/greek/sessiontoken"
                data = {
                    "username": username,
                    "password": pw,
                    "validFor": "10d"
                }
                response = requests.post(url, json=data, timeout=self.greek_request_timeout)

                session_token = response.json().get("sessionToken")
                if not session_token:
                    raise RuntimeError("GreekSoft authentication did not return sessionToken")

                self.session_token = session_token
                printt("Session Token Created")
                self.getInstrument()
                if getattr(self, "df", None) is None or self.df.empty:
                    raise RuntimeError("GreekSoft instrument master is empty")

                self.login()
                if not getattr(self, "gcid", None):
                    raise RuntimeError("GreekSoft login did not return gcid")

                self.build_contract_lookup_maps()
                self.load_greek_retry_state()
                self.start_greek_retry_state_saver()
                self.warmup_greek_sessions()
                printt("Master Copy Downloaded..!")
                initialized = True
                break
            except Exception as e:
                last_error = e
                printt(f'Error in generating session token : {e}, retrying...')
                time.sleep(2)

        if not initialized:
            raise RuntimeError(f"GreekSoft initialization failed after 4 attempts: {last_error}")


    def normalize_expiry_yyyymmdd(self, value):
        try:
            parsed = pd.to_datetime(value, dayfirst=True, errors="coerce")
            if pd.isna(parsed):
                return ""
            return parsed.strftime("%Y%m%d")
        except Exception as e:
            printt(f"GREEK_EXPIRY_NORMALIZE_FAILED | value={value} | error={e}")
            return ""


    def get_greek_session(self):
        try:
            session = getattr(self.greek_thread_local, "session", None)
            if session is None:
                session = requests.Session()
                adapter = GreekKeepAliveAdapter(pool_connections=10, pool_maxsize=10, pool_block=False)
                session.mount("http://", adapter)
                session.mount("https://", adapter)
                self.greek_thread_local.session = session
            return session
        except Exception as e:
            raise RuntimeError(f"Error creating GreekSoft HTTP session: {e}")


    def reset_greek_session(self):
        try:
            session = getattr(self.greek_thread_local, "session", None)
            if session is not None:
                try:
                    session.close()
                except Exception as close_error:
                    printt(f"GREEK_SESSION_CLOSE_FAILED | error={close_error}")
            self.greek_thread_local.session = None
        except Exception as e:
            printt(f"GREEK_SESSION_RESET_FAILED | error={e}")


    def is_greek_connection_reset(self, error):
        if isinstance(error, ConnectionResetError):
            error_code = getattr(error, "winerror", None) or getattr(error, "errno", None)
            return error_code == 10054 or (error.args and error.args[0] == 10054)

        return any(
            self.is_greek_connection_reset(arg)
            for arg in getattr(error, "args", ())
            if isinstance(arg, BaseException)
        )


    def build_contract_lookup_maps(self):
        try:
            if getattr(self, "df", None) is None or self.df.empty:
                raise ValueError("GreekSoft instrument master is empty")

            before_filter_rows = len(self.df)
            symbol_filter = self.df["Symbol"].astype(str).str.strip().str.upper()
            lookup_df = self.df[symbol_filter.isin(self.greek_instrument_names_to_load)].copy()
            printt(f"GREEK_CONTRACT_PRECOMPUTE_START | rows={before_filter_rows} | filtered={len(lookup_df)}")

            lookup_df["symbol_key"] = lookup_df["Symbol"].astype(str).str.strip().str.replace(" ", "", regex=False).str.upper()
            lookup_df["expiry_key"] = pd.to_datetime(lookup_df["ExpiryDate"], format="%d%b%Y", errors="coerce").dt.strftime("%Y%m%d")
            lookup_df["option_type_key"] = lookup_df["OptionType"].astype(str).str.strip().str.replace(" ", "", regex=False).str.upper()
            lookup_df["exchange_segment_key"] = lookup_df["ExchangeSegMent"].astype(str).str.strip().str.upper()
            lookup_df["instrument_type_key"] = lookup_df["Series/InstType"].astype(str).str.strip().str.upper()
            lookup_df["strike_value"] = pd.to_numeric(lookup_df["StrikePrice"], errors="coerce")
            lookup_df["exchange_token_key"] = lookup_df["ExchangeToken"].astype(str).str.strip()

            nse_lookup_df = lookup_df[
                (lookup_df["symbol_key"] == "NIFTY")
                & (lookup_df["exchange_segment_key"] == "NSEFO")
                & (lookup_df["instrument_type_key"] == "OPTIDX")
                & (lookup_df["option_type_key"].isin(["CE", "PE"]))
            ]
            bse_lookup_df = lookup_df[
                (lookup_df["symbol_key"] == "SENSEX")
                & (lookup_df["exchange_segment_key"] == "BSEFO")
                & (lookup_df["instrument_type_key"] == "OPTIDX")
                & (lookup_df["option_type_key"].isin(["CE", "PE"]))
            ]

            nse_contract_by_key = {}
            bse_contract_by_token = {}
            for row in nse_lookup_df.itertuples(index=False):
                if row.symbol_key and pd.notna(row.expiry_key) and row.option_type_key and pd.notna(row.strike_value):
                    nse_contract_by_key[(row.symbol_key, row.expiry_key, float(row.strike_value), row.option_type_key)] = row
            for row in bse_lookup_df.itertuples(index=False):
                if row.exchange_token_key:
                    bse_contract_by_token[row.exchange_token_key] = row

            self.greek_nse_contract_by_key = nse_contract_by_key
            self.greek_bse_contract_by_token = bse_contract_by_token

            printt(f"GREEK_CONTRACT_PRECOMPUTE_DONE | nse={len(nse_contract_by_key)} | bse={len(bse_contract_by_token)}")
        except Exception as e:
            printt(f"GREEK_CONTRACT_PRECOMPUTE_FAILED | error={e}")
            raise


    def get_greek_retry_state_date(self):
        return datetime.datetime.now().strftime("%Y%m%d")


    def get_greek_net_bucket(self, symbol, option_type):
        try:
            normalized_symbol = str(symbol).strip().replace(" ", "").upper()
            normalized_option_type = str(option_type).strip().upper()
            if normalized_symbol in ("NIFTY", "SENSEX") and normalized_option_type in ("CE", "PE"):
                return f"{normalized_symbol}_{normalized_option_type}"
            return None
        except Exception as e:
            printt(f"GREEK_NET_BUCKET_ERROR | symbol={symbol} | option_type={option_type} | error={e}")
            return None


    def get_greek_net_limit(self, bucket):
        try:
            pos_limit = max(int(float(getattr(cre, f"{bucket}_POS_NET"))), 0)
        except Exception:
            pos_limit = 0
        try:
            neg_limit = max(int(float(getattr(cre, f"{bucket}_NEG_NET"))), 0)
        except Exception:
            neg_limit = 0
        return pos_limit, neg_limit


    def get_greek_signed_qty(self, side, qty):
        normalized_side = self.normalize_order_side(side)
        quantity = int(float(qty))
        return quantity if normalized_side == "BUY" else -quantity


    def floor_greek_qty_to_lot(self, qty, lot_size):
        try:
            quantity = int(float(qty))
            lot_quantity = int(float(lot_size))
            if lot_quantity <= 0:
                return 0
            return max((quantity // lot_quantity) * lot_quantity, 0)
        except Exception as e:
            printt(f"GREEK_NET_LOT_FLOOR_ERROR | qty={qty} | lot_size={lot_size} | error={e}")
            return 0


    def load_greek_net_state(self):
        try:
            today = self.get_greek_retry_state_date()
            state = None
            if os.path.exists(self.greek_net_state_file):
                try:
                    with open(self.greek_net_state_file, "r") as state_file:
                        state = json.load(state_file)
                except Exception as e:
                    printt(f"GREEK_NET_STATE_LOAD_FAILED | error={e}")

            with self.greek_net_lock:
                if not isinstance(state, dict) or state.get("date") != today:
                    self.greek_net_position = {bucket: 0 for bucket in self.greek_net_buckets}
                    self.greek_net_released_roots.clear()
                    self.greek_net_state_dirty = True
                    printt("GREEK_NET_STATE_RESET")
                    return

                saved_position = state.get("net_position", {})
                for bucket in self.greek_net_buckets:
                    try:
                        self.greek_net_position[bucket] = int(float(saved_position.get(bucket, 0)))
                    except Exception:
                        self.greek_net_position[bucket] = 0

                released_roots = state.get("released_roots", [])
                self.greek_net_released_roots = {str(root_id).strip() for root_id in released_roots if str(root_id).strip()} if isinstance(released_roots, list) else set()

            printt(f"GREEK_NET_STATE_LOADED | net={dict(self.greek_net_position)} | released={len(self.greek_net_released_roots)}")
        except Exception as e:
            printt(f"Error loading GreekSoft net state: {e}")


    def get_greek_net_state_snapshot_locked(self):
        return {"date": self.get_greek_retry_state_date(), "net_position": dict(self.greek_net_position), "released_roots": sorted(self.greek_net_released_roots)}


    def save_greek_net_state_now(self):
        with self.greek_net_state_save_lock:
            try:
                with self.greek_net_lock:
                    state_snapshot = self.get_greek_net_state_snapshot_locked()
                    self.greek_net_state_dirty = False

                temp_path = f"{self.greek_net_state_file}.tmp"
                with open(temp_path, "w") as state_file:
                    json.dump(state_snapshot, state_file, indent=2)
                os.replace(temp_path, self.greek_net_state_file)
            except Exception as e:
                with self.greek_net_lock:
                    self.greek_net_state_dirty = True
                printt(f"GREEK_NET_STATE_SAVE_FAILED | error={e}")


    def greek_net_state_saver_loop(self):
        while True:
            try:
                time.sleep(self.greek_net_state_save_interval)
                with self.greek_net_lock:
                    should_save = self.greek_net_state_dirty
                if should_save:
                    self.save_greek_net_state_now()
            except Exception as e:
                printt(f"GREEK_NET_STATE_SAVER_ERROR | error={e}")
                time.sleep(1)


    def start_greek_net_state_saver(self):
        try:
            with self.greek_net_lock:
                if self.greek_net_state_saver_started:
                    return
                self.greek_net_state_saver_started = True

            threading.Thread(target=self.greek_net_state_saver_loop, daemon=True, name="greek_net_state_saver").start()
            atexit.register(self.save_greek_net_state_now)
            printt("GREEK_NET_STATE_SAVER_STARTED")
        except Exception as e:
            printt(f"Error starting GreekSoft net state saver: {e}")


    def get_greek_traded_quantity(self, row):
        try:
            quantity = int(float(self.get_orderbook_row_value(row, "traded_qty", 0)))
            return quantity if quantity > 0 else 0
        except Exception as e:
            printt(f"GREEK_NET_SYNC_QTY_PARSE_FAILED | error={e} | row={row}")
            return 0


    def build_greek_net_from_orderbook(self, rows):
        net_position = {bucket: 0 for bucket in self.greek_net_buckets}
        seen_gorderids = set()
        counted = 0

        if not isinstance(rows, list):
            return None, 0

        for row in rows:
            try:
                if str(self.get_orderbook_row_value(row, "instrument", "")).strip().upper() != "OPTIDX":
                    continue

                gorderid = str(self.get_orderbook_row_value(row, "gorderid", "")).strip()
                if not gorderid or gorderid in seen_gorderids:
                    continue

                quantity = self.get_greek_traded_quantity(row)
                if quantity <= 0:
                    continue

                bucket = self.get_greek_net_bucket(self.get_orderbook_row_value(row, "scripName", ""), self.get_orderbook_row_value(row, "optionType", ""))
                if not bucket:
                    continue

                net_position[bucket] += self.get_greek_signed_qty(self.get_orderbook_row_value(row, "side", ""), quantity)
                seen_gorderids.add(gorderid)
                counted += 1
            except Exception as e:
                printt(f"GREEK_NET_SYNC_ROW_SKIPPED | error={e} | row={row}")

        return net_position, counted


    def log_greek_net_over_limit(self, net_position, source):
        for bucket, current_net in net_position.items():
            pos_limit, neg_limit = self.get_greek_net_limit(bucket)
            if current_net > pos_limit or current_net < -neg_limit:
                printt(f"GREEK_NET_SYNC_OVER_LIMIT | source={source} | bucket={bucket} | net={current_net} | pos_limit={pos_limit} | neg_limit={neg_limit}")


    def sync_greek_net_from_traded_orders(self, source="manual"):
        try:
            with self.greek_net_lock:
                orderbook = self.getOrderBookALL()
                rows = orderbook.get("data") if isinstance(orderbook, dict) else None
                net_position, counted = self.build_greek_net_from_orderbook(rows)
                if net_position is None:
                    printt(f"GREEK_NET_SYNC_FAILED | source={source} | reason=missing_data_list")
                    return False

                self.greek_net_position = {bucket: int(net_position.get(bucket, 0)) for bucket in self.greek_net_buckets}
                self.greek_net_released_roots.clear()
                self.greek_net_state_dirty = True
                synced_net = dict(self.greek_net_position)

            self.log_greek_net_over_limit(synced_net, source)
            self.save_greek_net_state_now()
            printt(f"GREEK_NET_SYNC_DONE | source={source} | rows={counted} | net={synced_net}")
            return True
        except Exception as e:
            printt(f"GREEK_NET_SYNC_FAILED | source={source} | error={e}")
            return False


    def reserve_greek_net(self, symbol, option_type, side, qty, lot_size):
        try:
            bucket = self.get_greek_net_bucket(symbol, option_type)
            original_qty = int(float(qty))
            if not bucket:
                return True, original_qty, None
            if original_qty <= 0:
                printt(f"GREEK_NET_LIMIT_SKIP | bucket={bucket} | side={side} | qty={qty} | reason=non_positive_qty")
                return False, 0, None

            pos_limit, neg_limit = self.get_greek_net_limit(bucket)
            signed_qty = self.get_greek_signed_qty(side, original_qty)
            with self.greek_net_lock:
                current_net = int(self.greek_net_position.get(bucket, 0))
                requested_next_net = current_net + signed_qty

                if current_net > pos_limit:
                    if signed_qty >= 0:
                        printt(f"GREEK_NET_LIMIT_SKIP | bucket={bucket} | side={side} | qty={original_qty} | current={current_net} | next={requested_next_net} | pos_limit={pos_limit} | neg_limit={neg_limit} | reason=over_positive_increase")
                        return False, 0, None
                    adjusted_qty = min(original_qty, self.floor_greek_qty_to_lot(current_net + neg_limit, lot_size))
                elif current_net < -neg_limit:
                    if signed_qty <= 0:
                        printt(f"GREEK_NET_LIMIT_SKIP | bucket={bucket} | side={side} | qty={original_qty} | current={current_net} | next={requested_next_net} | pos_limit={pos_limit} | neg_limit={neg_limit} | reason=over_negative_increase")
                        return False, 0, None
                    adjusted_qty = min(original_qty, self.floor_greek_qty_to_lot(pos_limit - current_net, lot_size))
                elif -neg_limit <= requested_next_net <= pos_limit:
                    adjusted_qty = original_qty
                else:
                    max_allowed_qty = pos_limit - current_net if signed_qty > 0 else current_net + neg_limit
                    adjusted_qty = self.floor_greek_qty_to_lot(max_allowed_qty, lot_size)

                if adjusted_qty <= 0:
                    printt(f"GREEK_NET_LIMIT_SKIP | bucket={bucket} | side={side} | qty={original_qty} | current={current_net} | next={requested_next_net} | pos_limit={pos_limit} | neg_limit={neg_limit} | lot_size={lot_size} | reason=no_valid_partial")
                    return False, 0, None

                adjusted_signed_qty = self.get_greek_signed_qty(side, adjusted_qty)
                adjusted_next_net = current_net + adjusted_signed_qty
                if adjusted_next_net > pos_limit and adjusted_next_net >= current_net:
                    printt(f"GREEK_NET_LIMIT_SKIP | bucket={bucket} | side={side} | qty={original_qty} | adjusted_qty={adjusted_qty} | current={current_net} | next={adjusted_next_net} | pos_limit={pos_limit} | neg_limit={neg_limit} | reason=partial_still_exceeds")
                    return False, 0, None
                if adjusted_next_net < -neg_limit and adjusted_next_net <= current_net:
                    printt(f"GREEK_NET_LIMIT_SKIP | bucket={bucket} | side={side} | qty={original_qty} | adjusted_qty={adjusted_qty} | current={current_net} | next={adjusted_next_net} | pos_limit={pos_limit} | neg_limit={neg_limit} | reason=partial_still_exceeds")
                    return False, 0, None

                self.greek_net_position[bucket] = adjusted_next_net
                self.greek_net_state_dirty = True

            if adjusted_qty != original_qty:
                printt(f"GREEK_NET_PARTIAL_ALLOWED | bucket={bucket} | side={side} | original_qty={original_qty} | adjusted_qty={adjusted_qty} | current={current_net} | requested_next={requested_next_net} | pos_limit={pos_limit} | neg_limit={neg_limit} | lot_size={lot_size}")
            printt(f"GREEK_NET_RESERVED | bucket={bucket} | signed_qty={adjusted_signed_qty} | current={adjusted_next_net} | pos_limit={pos_limit} | neg_limit={neg_limit}")
            return True, adjusted_qty, {"bucket": bucket, "signed_qty": adjusted_signed_qty}
        except Exception as e:
            printt(f"GREEK_NET_RESERVE_ERROR | symbol={symbol} | option_type={option_type} | side={side} | qty={qty} | error={e}")
            return False, 0, None


    def adjust_greek_net_for_failed_task(self, task, quantity, reason, log_name):
        try:
            root_order_id = str(task.get("root_order_id", "")).strip()
            net_meta = task.get("net_meta")
            if not root_order_id or not isinstance(net_meta, dict):
                return False

            bucket = str(net_meta.get("bucket", "")).strip().upper()
            if bucket not in self.greek_net_buckets:
                return False

            signed_qty = self.get_greek_signed_qty(task.get("side"), quantity)
            with self.greek_net_lock:
                if root_order_id in self.greek_net_released_roots:
                    return False
                current_net = int(self.greek_net_position.get(bucket, 0))
                next_net = current_net - signed_qty
                self.greek_net_position[bucket] = next_net
                self.greek_net_released_roots.add(root_order_id)
                self.greek_net_state_dirty = True

            printt(f"{log_name} | root_id={root_order_id} | bucket={bucket} | signed_qty={signed_qty} | current={next_net} | reason={reason}")
            return True
        except Exception as e:
            printt(f"GREEK_NET_FAILURE_ADJUST_ERROR | root_id={task.get('root_order_id')} | reason={reason} | error={e}")
            return False


    def handle_greek_order_future_result(self, future, task):
        try:
            if future.result():
                return
            source = str(task.get("source", "")).strip().lower()
            log_name = "GREEK_NET_RELEASE" if source == "retry" else "GREEK_NET_ROLLBACK"
            self.adjust_greek_net_for_failed_task(task, task.get("qty", 0), f"{source}_submit_failed", log_name)
        except Exception as e:
            printt(f"GREEK_ORDER_FUTURE_RESULT_ERROR | root_id={task.get('root_order_id')} | source={task.get('source')} | error={e}")


    def get_empty_greek_retry_state(self):
        return {
            "date": self.get_greek_retry_state_date(),
            "gorderid_to_root_id": {},
            "order_meta_by_root": {},
            "retry_by_root": {},
        }


    def normalize_greek_retry_state(self, state):
        try:
            today = self.get_greek_retry_state_date()
            if not isinstance(state, dict) or state.get("date") != today:
                return self.get_empty_greek_retry_state()

            gorderid_to_root_id = state.get("gorderid_to_root_id", {})
            if not isinstance(gorderid_to_root_id, dict):
                gorderid_to_root_id = {}

            order_meta_by_root = state.get("order_meta_by_root", {})
            if not isinstance(order_meta_by_root, dict):
                order_meta_by_root = {}

            normalized_order_meta = {}
            for root_order_id, order_meta in order_meta_by_root.items():
                root_key = str(root_order_id).strip()
                if not root_key or not isinstance(order_meta, dict):
                    continue
                normalized_order_meta[root_key] = dict(order_meta)

            normalized_retry_by_root = {}
            retry_by_root = state.get("retry_by_root", {})
            if isinstance(retry_by_root, dict):
                for root_order_id, root_state in retry_by_root.items():
                    root_key = str(root_order_id).strip()
                    if not root_key or not isinstance(root_state, dict):
                        continue

                    try:
                        retry_count = int(root_state.get("retry_count", 0))
                    except Exception:
                        retry_count = 0

                    processed = root_state.get("processed_gorderids", [])
                    if isinstance(processed, set):
                        processed_gorderids = set(processed)
                    elif isinstance(processed, list):
                        processed_gorderids = {str(gorderid).strip() for gorderid in processed if str(gorderid).strip()}
                    else:
                        processed_gorderids = set()

                    normalized_retry_by_root[root_key] = {
                        "retry_count": retry_count,
                        "processed_gorderids": processed_gorderids,
                    }

            return {
                "date": today,
                "gorderid_to_root_id": {
                    str(gorderid).strip(): str(root_id).strip()
                    for gorderid, root_id in gorderid_to_root_id.items()
                    if str(gorderid).strip() and str(root_id).strip()
                },
                "order_meta_by_root": normalized_order_meta,
                "retry_by_root": normalized_retry_by_root,
            }
        except Exception as e:
            printt(f"GREEK_RETRY_STATE_NORMALIZE_FAILED | error={e}")
            return self.get_empty_greek_retry_state()


    def get_greek_retry_root_state(self, root_order_id):
        root_key = str(root_order_id).strip()
        retry_by_root = self.greek_retry_state.setdefault("retry_by_root", {})
        root_state = retry_by_root.setdefault(
            root_key,
            {
                "retry_count": 0,
                "processed_gorderids": set(),
            },
        )
        return root_state


    def get_greek_retry_state_snapshot(self):
        try:
            with self.greek_retry_state_lock:
                state = self.greek_retry_state
                retry_by_root = {}
                for root_order_id, root_state in state.get("retry_by_root", {}).items():
                    if not isinstance(root_state, dict):
                        continue
                    retry_by_root[str(root_order_id)] = {
                        "retry_count": int(root_state.get("retry_count", 0)),
                        "processed_gorderids": sorted(list(root_state.get("processed_gorderids", set()))),
                    }

                return {
                    "date": state.get("date", self.get_greek_retry_state_date()),
                    "gorderid_to_root_id": dict(state.get("gorderid_to_root_id", {})),
                    "order_meta_by_root": {
                        str(root_order_id): dict(order_meta)
                        for root_order_id, order_meta
                        in state.get("order_meta_by_root", {}).items()
                        if isinstance(order_meta, dict)
                    },
                    "retry_by_root": retry_by_root,
                }
        except Exception as e:
            printt(f"GREEK_RETRY_STATE_SNAPSHOT_FAILED | error={e}")
            return self.get_empty_greek_retry_state()


    def load_greek_retry_state(self):
        try:
            state = None
            state_file_exists = os.path.exists(self.greek_retry_state_file)
            if state_file_exists:
                try:
                    with open(self.greek_retry_state_file, "r") as state_file:
                        state = json.load(state_file)
                except Exception as e:
                    printt(f"GREEK_RETRY_STATE_LOAD_FAILED | error={e}")

            normalized_state = self.normalize_greek_retry_state(state)
            with self.greek_retry_state_lock:
                self.greek_retry_state = normalized_state
                self.greek_retry_state_loaded = True
                self.greek_retry_state_dirty = not state_file_exists or not isinstance(state, dict) or state.get("date") != self.get_greek_retry_state_date()

            printt(f"GREEK_RETRY_STATE_LOADED | orders={len(normalized_state['gorderid_to_root_id'])} | roots={len(normalized_state['retry_by_root'])}")
        except Exception as e:
            printt(f"Error loading GreekSoft retry state: {e}")
            with self.greek_retry_state_lock:
                self.greek_retry_state = self.get_empty_greek_retry_state()
                self.greek_retry_state_loaded = True
                self.greek_retry_state_dirty = True


    def save_retry_state_now(self):
        with self.greek_retry_state_save_lock:
            try:
                with self.greek_retry_state_lock:
                    state_snapshot = self.get_greek_retry_state_snapshot()
                    self.greek_retry_state_dirty = False

                temp_path = f"{self.greek_retry_state_file}.tmp"
                with open(temp_path, "w") as state_file:
                    json.dump(state_snapshot, state_file, indent=2)
                os.replace(temp_path, self.greek_retry_state_file)
            except Exception as e:
                with self.greek_retry_state_lock:
                    self.greek_retry_state_dirty = True
                printt(f"GREEK_RETRY_STATE_SAVE_FAILED | error={e}")


    def greek_retry_state_saver_loop(self):
        while True:
            try:
                time.sleep(self.greek_retry_state_save_interval)
                with self.greek_retry_state_lock:
                    should_save = self.greek_retry_state_dirty
                if should_save:
                    self.save_retry_state_now()
            except Exception as e:
                printt(f"GREEK_RETRY_STATE_SAVER_ERROR | error={e}")
                time.sleep(1)


    def start_greek_retry_state_saver(self):
        try:
            with self.greek_retry_state_lock:
                if self.greek_retry_state_saver_started:
                    return
                self.greek_retry_state_saver_started = True

            saver_thread = threading.Thread(target=self.greek_retry_state_saver_loop, daemon=True, name="greek_retry_state_saver")
            saver_thread.start()
            atexit.register(self.save_retry_state_now)
            printt("GREEK_RETRY_STATE_SAVER_STARTED")
        except Exception as e:
            printt(f"Error starting GreekSoft retry state saver: {e}")


    def register_greek_order_meta(self, root_order_id, order_meta):
        try:
            root_key = str(root_order_id).strip()
            if not root_key or not isinstance(order_meta, dict):
                return

            with self.greek_retry_state_lock:
                self.greek_retry_state.setdefault("order_meta_by_root", {})[root_key] = dict(order_meta)
                self.get_greek_retry_root_state(root_key)
                self.greek_retry_state_dirty = True
        except Exception as e:
            printt(f"GREEK_ORDER_META_REGISTER_FAILED | root_id={root_order_id} | error={e}")


    def get_greek_order_meta(self, root_order_id):
        try:
            root_key = str(root_order_id).strip()
            with self.greek_retry_state_lock:
                order_meta = self.greek_retry_state.setdefault("order_meta_by_root", {}).get(root_key, {})
                return dict(order_meta) if isinstance(order_meta, dict) else {}
        except Exception as e:
            printt(f"GREEK_ORDER_META_GET_FAILED | root_id={root_order_id} | error={e}")
            return {}


    def register_greek_order_id(self, root_order_id, gorderid):
        try:
            root_key = str(root_order_id).strip()
            order_id = str(gorderid).strip()
            if not root_key or not order_id:
                return

            with self.greek_retry_state_lock:
                self.greek_retry_state.setdefault("gorderid_to_root_id", {})[order_id] = root_key
                self.get_greek_retry_root_state(root_key)
                self.greek_retry_state_dirty = True
        except Exception as e:
            printt(f"GREEK_ORDER_ID_REGISTER_FAILED | root_id={root_order_id} | gorderid={gorderid} | error={e}")

    def normalize_order_side(self, side):
        side_text = str(side).strip().upper()
        if side_text in ("1", "BUY"):
            return "BUY"
        if side_text in ("2", "SELL"):
            return "SELL"
        raise ValueError(f"Unknown GreekSoft order side: {side}")


    def build_greek_cache_symbol(self, dt):
        try:
            expiry = pd.to_datetime(dt.ExpiryDate).strftime("%d%b%y").upper()
            return build_cache_symbol(dt.Symbol, expiry, dt.StrikePrice, dt.OptionType)
        except Exception as e:
            printt(f"GREEK_PRICE_CACHE_SYMBOL_FAILED | error={e}")
            return None


    def get_greek_task_price(self, task):
        try:
            if task.get("force_market_price"):
                return 0

            if datetime.datetime.now().time() < datetime.time(9, 17):
                return 0

            cache_symbol = str(task.get("cache_symbol", "")).strip().upper()
            if not cache_symbol:
                printt(f"GREEK_PRICE_FALLBACK | root_id={task.get('root_order_id')} | reason=missing_cache_symbol")
                return 0

            normalized_side = self.normalize_order_side(task.get("side"))
            price = price_from_avg_ltp_or_fallback(normalized_side, float(task.get("tick_size", 0)), cache_symbol)
            if price <= 0:
                printt(f"GREEK_PRICE_FALLBACK | root_id={task.get('root_order_id')} | symbol={cache_symbol} | reason=pricing_unavailable")
                return 0
            return price
        except Exception as e:
            printt(f"GREEK_PRICE_FALLBACK | root_id={task.get('root_order_id')} | symbol={task.get('cache_symbol')} | error={e}")
            return 0


    def create_original_greek_order_task(self, exchange, gtoken, side, trade_symbol, qty, dt, source_order_id=""):
        root_order_id = str(uuid.uuid4())
        net_meta = None
        try:
            quantity = int(qty)
            lot_size = int(dt.LotSize)
            tick_size = float(dt.TickSize)
            strike = float(dt.StrikePrice)
            expiry = self.normalize_expiry_yyyymmdd(dt.ExpiryDate)
            option_type = str(dt.OptionType).strip().upper()
            symbol = str(dt.Symbol).strip().upper()
            cache_symbol = self.build_greek_cache_symbol(dt)

            net_allowed, adjusted_quantity, net_meta = self.reserve_greek_net(symbol, option_type, side, quantity, lot_size)
            if not net_allowed:
                return None
            if adjusted_quantity != quantity:
                printt(f"GREEK_NET_ORDER_QTY_ADJUSTED | sym={symbol} | option_type={option_type} | side={side} | original_qty={quantity} | adjusted_qty={adjusted_quantity}")
                quantity = adjusted_quantity

            task = {
                "root_order_id": root_order_id,
                "source": "original",
                "exchange": str(exchange).strip().upper(),
                "gtoken": str(gtoken).strip(),
                "side": str(side).strip(),
                "tradeSymbol": str(trade_symbol).strip().upper(),
                "symbol": symbol,
                "qty": quantity,
                "lot_size": lot_size,
                "lot": quantity / lot_size,
                "expiry": expiry,
                "option_type": option_type,
                "strike": strike,
                "tick_size": tick_size,
                "cache_symbol": cache_symbol,
                "source_order_id": str(source_order_id).strip(),
                "net_meta": net_meta,
            }
            self.register_greek_order_meta(root_order_id, task)
            return task
        except Exception as e:
            if isinstance(net_meta, dict):
                failed_task = {"root_order_id": root_order_id, "side": side, "net_meta": net_meta}
                self.adjust_greek_net_for_failed_task(failed_task, quantity, "original_task_build_failed", "GREEK_NET_ROLLBACK")
            printt(f"GREEK_ORIGINAL_TASK_BUILD_FAILED | exchange={exchange} | sym={trade_symbol} | qty={qty} | error={e}")
            return None


    def build_greek_payload(self, task, order_price):
        try:
            if order_price > 0:
                order_type = "1"
                payload_price = str(order_price)
            else:
                order_type = "2"
                payload_price = "0"

            payload = {
                "request": {
                    "data": {
                        "trigger_price": "0",
                        "gtoken": str(task["gtoken"]),
                        "side": str(task["side"]),
                        "gcid": self.gcid,
                        "validity": "1",
                        "price": payload_price,
                        "exchange": str(task["exchange"]),
                        "disclosed_qty": "0",
                        "tradeSymbol": str(task["tradeSymbol"]).upper(),
                        "tag": str(task.get("source_order_id", "")),
                        "userTag": str(task.get("source_order_id", "")),
                        "lot": str(task["lot"]),
                        "order_type": order_type,
                        "product": "0",
                        "qty": str(task["qty"]),
                        "corderid": "3",
                        "amo": "0",
                        "iprocli": iprocli,
                        "AccountNumber": AccountNumber,
                        "gtdExpiry": 0,
                        "is_post_closed": "0",
                        "is_preopen_order": "0",
                        "isSqOffOrder": "false",
                        "offline": "0",
                        "is_restapi": "1",
                        "strategyName": "AlgoSelf"
                    },
                    "response_format": "json",
                    "request_type": "subscribe",
                    "streaming_type": "NewOrderRequest"
                }
            }
            return payload, payload_price, order_type
        except Exception as e:
            raise RuntimeError(f"Error building GreekSoft payload: {e}")


    def submit_greek_order_task(self, task):
        request_start_ts = time.perf_counter()
        try:
            url = f"http://{urll}/NewOrderRequest"
            headers = {"Authorization": self.session_token}
            session = self.get_greek_session()

            for attempt in range(1, self.greek_http_max_attempts + 1):
                wait_for_greek_order_slot()
                order_price = self.get_greek_task_price(task)
                payload, payload_price, order_type = self.build_greek_payload(task, order_price)

                attempt_start_ts = time.perf_counter()
                try:
                    response = session.post(url, json=payload, headers=headers, timeout=self.greek_request_timeout)
                except Exception as request_error:
                    http_ms = (time.perf_counter() - attempt_start_ts) * 1000
                    should_retry_reset = attempt < self.greek_http_max_attempts and http_ms <= 10.0 and self.is_greek_connection_reset(request_error)
                    if not should_retry_reset:
                        raise

                    printt(f"GREEK_CONNECTION_RESET_RETRY | attempt={attempt} | max={self.greek_http_max_attempts} | error_code=10054 | root_id={task.get('root_order_id')} | source={task.get('source')} | sym={task.get('tradeSymbol')} | side={task.get('side')} | qty={task.get('qty')} | http={http_ms:.1f}ms | action=reset_session_reprice_retry")
                    self.reset_greek_session()
                    session = self.get_greek_session()
                    continue

                http_ms = (time.perf_counter() - attempt_start_ts) * 1000
                response_text = getattr(response, "text", "")
                status_code = int(getattr(response, "status_code", 200))

                if status_code < 200 or status_code >= 300:
                    printt(f"GREEK_HTTP_RETRY_RESPONSE | attempt={attempt} | max={self.greek_http_max_attempts} | status={status_code} | root_id={task.get('root_order_id')} | source={task.get('source')} | sym={task.get('tradeSymbol')} | side={task.get('side')} | qty={task.get('qty')} | price={payload_price} | order_type={order_type} | http={http_ms:.1f}ms | response={response_text}")
                    if attempt < self.greek_http_max_attempts:
                        time.sleep(self.greek_http_retry_sleep)
                        continue
                    raise RuntimeError(f"GreekSoft HTTP error: status={status_code}, body={response_text}")

                response_json = response.json()
                response_root = response_json.get("response", {})
                response_data = response_root.get("data", {})
                gorderid = response_data.get("gorderid")
                streaming_type = str(response_root.get("streaming_type", "")).strip()

                if streaming_type == "IrisRejection":
                    rejection_reason = str(response_data.get("reason", "")).strip()
                    normalized_reason = rejection_reason.casefold()
                    if "throttle" in normalized_reason and "reached" in normalized_reason:
                        retry_available = attempt < self.greek_http_max_attempts
                        action = "retry" if retry_available else "stop"
                        printt(f"GREEK_ORDER_FAILED | attempt={attempt} | max={self.greek_http_max_attempts} | rejected_gorderid={gorderid} | root_id={task.get('root_order_id')} | source={task.get('source')} | sym={task.get('cache_symbol') or task.get('tradeSymbol')} | side={task.get('side')} | qty={task.get('qty')} | price={payload_price} | order_type={order_type} | http={http_ms:.1f}ms | reason={rejection_reason} | action={action}")
                        if retry_available:
                            printt(f"GREEK_HTTP_RETRY | next_attempt={attempt + 1} | max={self.greek_http_max_attempts} | root_id={task.get('root_order_id')} | source={task.get('source')} | sym={task.get('cache_symbol') or task.get('tradeSymbol')} | side={task.get('side')} | qty={task.get('qty')} | reason=throttle_rejection")
                            time.sleep(self.greek_http_retry_sleep)
                            continue
                        raise RuntimeError(f"GreekSoft throttle rejection after {self.greek_http_max_attempts} attempts: gorderid={gorderid}, reason={rejection_reason}")

                if not gorderid:
                    raise RuntimeError(f"GreekSoft response missing gorderid: {response_json}")

                self.register_greek_order_id(task.get("root_order_id"), gorderid)
                total_ms = (time.perf_counter() - request_start_ts) * 1000
                printt(f"GREEK_ORDER_SUBMIT_DONE | root_id={task.get('root_order_id')} | source={task.get('source')} | gorderid={gorderid} | sym={task.get('cache_symbol') or task.get('tradeSymbol')} | side={task.get('side')} | qty={task.get('qty')} | price={payload_price} | order_type={order_type} | http={http_ms:.1f}ms | total={total_ms:.1f}ms")
                return gorderid

            return None
        except Exception as e:
            total_ms = (time.perf_counter() - request_start_ts) * 1000
            printt(f"GREEK_ORDER_SUBMIT_FAILED | root_id={task.get('root_order_id')} | source={task.get('source')} | sym={task.get('cache_symbol') or task.get('tradeSymbol')} | side={task.get('side')} | qty={task.get('qty')} | total={total_ms:.1f}ms | error={e}")
            return None


    def enqueue_greek_order_task(self, task):
        try:
            future = self.greek_order_pool.submit(self.submit_greek_order_task, task)
            future.add_done_callback(lambda completed_future, order_task=dict(task): self.handle_greek_order_future_result(completed_future, order_task))
            return future
        except Exception as e:
            printt(f"GREEK_ORDER_ENQUEUE_FAILED | root_id={task.get('root_order_id')} | source={task.get('source')} | error={e}")
            source = str(task.get("source", "")).strip().lower()
            log_name = "GREEK_NET_RELEASE" if source == "retry" else "GREEK_NET_ROLLBACK"
            self.adjust_greek_net_for_failed_task(task, task.get("qty", 0), f"{source}_enqueue_failed", log_name)
            return None


    def warmup_greek_worker_session(self, worker_index):
        try:
            session = self.get_greek_session()
            url = f"http://{urll}/getOrderBookDetailWithLegV2?exchangeType=ALL&ClientCode={self.gcid}&Order_Status=ALL&Ordertype=All&gscid={username}"
            headers = {"Authorization": self.session_token}
            start_ts = time.perf_counter()
            response = session.get(url, headers=headers, timeout=self.greek_request_timeout)
            elapsed_ms = (time.perf_counter() - start_ts) * 1000
            printt(f"GREEK_SESSION_WARMUP_DONE | worker={worker_index} | status={getattr(response, 'status_code', 'unknown')} | http={elapsed_ms:.1f}ms")
        except Exception as e:
            printt(f"GREEK_SESSION_WARMUP_FAILED | worker={worker_index} | error={e}")


    def warmup_greek_sessions(self):
        try:
            futures = [self.greek_order_pool.submit(self.warmup_greek_worker_session, worker_index) for worker_index in range(self.greek_order_workers)]
            for future in futures:
                future.result()
            printt(f"GREEK_SESSION_WARMUP_ALL_DONE | workers={self.greek_order_workers}")
        except Exception as e:
            printt(f"Error warming GreekSoft sessions: {e}")


    def get_orderbook_row_value(self, row, key, default=None):
        try:
            if isinstance(row, dict):
                value = row.get(key, default)
            elif hasattr(row, "get"):
                value = row.get(key, default)
            else:
                value = getattr(row, key, default)

            if value is None:
                return default
            if isinstance(value, float) and pd.isna(value):
                return default
            return value
        except Exception:
            return default


    def is_retryable_greek_orderbook_row(self, row):
        try:
            status = str(self.get_orderbook_row_value(row, "order_status", "")).strip().upper()
            pending_qty = int(float(self.get_orderbook_row_value(row, "pending_qty", 0)))
            if pending_qty <= 0:
                return False
            if status == "CANCELLED":
                return True
            if status != "EXCHANGE REJECTED":
                return False

            exchange = str(self.get_orderbook_row_value(row, "exchange", "")).strip().upper()
            error_code = int(float(self.get_orderbook_row_value(row, "errorCode", 0)))
            return (exchange == "BSE" and error_code == 10008) or (exchange == "NSE" and error_code == 17070)
        except Exception as e:
            printt(f"GREEK_RETRY_STATUS_CHECK_FAILED | error={e} | row={row}")
            return False


    def is_terminal_failed_greek_orderbook_row(self, row, retryable_status):
        try:
            status = str(self.get_orderbook_row_value(row, "order_status", "")).strip().upper()
            pending_qty = int(float(self.get_orderbook_row_value(row, "pending_qty", 0)))
            return status == "EXCHANGE REJECTED" and pending_qty > 0 and not retryable_status
        except Exception as e:
            printt(f"GREEK_TERMINAL_STATUS_CHECK_FAILED | error={e} | row={row}")
            return False


    def build_greek_retry_task(self, row, root_order_id):
        try:
            order_meta = self.get_greek_order_meta(root_order_id)
            if not order_meta:
                raise ValueError(f"Original order metadata missing for root_id={root_order_id}")

            pending_qty = int(float(self.get_orderbook_row_value(row, "pending_qty", 0)))
            original_qty = int(order_meta["qty"])
            lot_size = int(order_meta["lot_size"])
            if pending_qty > original_qty:
                raise ValueError(f"Pending quantity exceeds original child quantity: pending_qty={pending_qty}, original_qty={original_qty}")
            if pending_qty % lot_size != 0:
                raise ValueError(f"Pending quantity is not a lot multiple: pending_qty={pending_qty}, lot_size={lot_size}")

            status = str(self.get_orderbook_row_value(row, "order_status", "")).strip().upper()
            exchange = str(self.get_orderbook_row_value(row, "exchange", "")).strip().upper()
            error_code = int(float(self.get_orderbook_row_value(row, "errorCode", 0)))
            force_market_price = (
                (status == "EXCHANGE REJECTED" and (
                    (exchange == "BSE" and error_code == 10008) or (exchange == "NSE" and error_code == 17070)
                ))
                or (status == "CANCELLED" and error_code == 202)
            )

            task = dict(order_meta)
            task.update({
                "root_order_id": str(root_order_id),
                "source": "retry",
                "qty": pending_qty,
                "lot": pending_qty / lot_size,
                "force_market_price": force_market_price,
            })
            return task
        except Exception as e:
            printt(f"GREEK_RETRY_TASK_BUILD_FAILED | root_id={root_order_id} | gorderid={self.get_orderbook_row_value(row, 'gorderid', '')} | error={e}")
            return None


    def retry_failed_greeksoft_orders(self, rows):
        try:
            if not isinstance(rows, list) or not rows:
                return
            if not self.greek_retry_state_loaded:
                self.load_greek_retry_state()

            for row in rows:
                try:
                    retryable_status = self.is_retryable_greek_orderbook_row(row)
                    terminal_failure = self.is_terminal_failed_greek_orderbook_row(row, retryable_status)
                    if not retryable_status and not terminal_failure:
                        continue

                    gorderid = str(self.get_orderbook_row_value(row, "gorderid", "")).strip()
                    if not gorderid:
                        continue

                    with self.greek_retry_state_lock:
                        root_order_id = self.greek_retry_state.get("gorderid_to_root_id", {}).get(gorderid)
                        if not root_order_id:
                            continue

                        root_state = self.get_greek_retry_root_state(root_order_id)
                        processed_gorderids = root_state["processed_gorderids"]
                        if gorderid in processed_gorderids:
                            continue

                        if terminal_failure:
                            processed_gorderids.add(gorderid)
                            self.greek_retry_state_dirty = True
                            order_meta = self.get_greek_order_meta(root_order_id)
                            released = self.adjust_greek_net_for_failed_task(order_meta, self.get_orderbook_row_value(row, "pending_qty", 0), "orderbook_exchange_rejected", "GREEK_NET_RELEASE")
                            printt(f"GREEK_ORDERBOOK_TERMINAL_FAILURE | status=EXCHANGE_REJECTED | root_id={root_order_id} | gorderid={gorderid} | pending_qty={self.get_orderbook_row_value(row, 'pending_qty', 0)} | released={released}")
                            continue

                        retry_count = int(root_state.get("retry_count", 0))
                        if retry_count >= self.max_greek_orderbook_retries:
                            processed_gorderids.add(gorderid)
                            self.greek_retry_state_dirty = True
                            order_meta = self.get_greek_order_meta(root_order_id)
                            self.adjust_greek_net_for_failed_task(order_meta, self.get_orderbook_row_value(row, "pending_qty", 0), "orderbook_retry_exhausted", "GREEK_NET_RELEASE")
                            printt(f"GREEK_ORDERBOOK_RETRY_SKIP | reason=max_retries | root_id={root_order_id} | gorderid={gorderid}")
                            continue

                    retry_task = self.build_greek_retry_task(row, root_order_id)
                    if not retry_task:
                        continue

                    with self.greek_retry_state_lock:
                        root_state = self.get_greek_retry_root_state(root_order_id)
                        processed_gorderids = root_state["processed_gorderids"]
                        processed_gorderids.add(gorderid)
                        root_state["retry_count"] = retry_count + 1
                        self.greek_retry_state_dirty = True

                    printt(f"GREEK_ORDERBOOK_RETRY_ENQUEUE | root_id={root_order_id} | failed_gorderid={gorderid} | sym={retry_task.get('tradeSymbol')} | side={retry_task.get('side')} | qty={retry_task.get('qty')}")
                    self.enqueue_greek_order_task(retry_task)
                except Exception as row_error:
                    printt(f"GREEK_ORDERBOOK_RETRY_ROW_ERROR | gorderid={self.get_orderbook_row_value(row, 'gorderid', '')} | error={row_error}")
        except Exception as e:
            printt(f"Error in retry_failed_greeksoft_orders: {e}")


    def login(self):
        try:
            global urll
            global username
            url = f"http://{urll}/getLoginInfo"
            headers = {
                "Authorization": self.session_token
            }

            # Request body
            data = {
                "request": {
                    "svcVersion": "1.0.0",
                    "svcGroup": "Login",
                    "svcName": "getLoginInfo",
                    "assetType": "",
                    "data": {
                        "gscid": username
                    }
                }
            }

            response = requests.post(url, json=data, headers=headers, timeout=self.greek_request_timeout)
            data = response.json()
            self.gcid = str(data['response']['data']['gcid'])
            return(response.json())
        except Exception as e:
            printt(f"Error in login: {e}")
            return None


    def getInstrument(self):
        try:
            global urll
            url = f"http://{urll}/getAllContract"
            authorization_string = self.session_token

            # Headers with Authorization
            headers = {
                "Authorization": authorization_string
            }
            # Make the GET request
            response = requests.get(url, headers=headers, timeout=self.greek_request_timeout)

            raw_data = response.text.strip()

            # Convert to a Pandas DataFrame
            df = pd.read_csv(StringIO(raw_data))
            df = df.reset_index()
            df.to_csv('abc.csv', index=False)
            # df.columns = ['GreekToken', 'ExchangeToken', 'ExchangeSegMent', 'Series/InstType',
            # 'Symbol', 'Description', 'ExpiryDate', 'OptionType', 'StrikePrice',
            # 'TickSize', 'LotSize', 'TradingSymbol', 'SymbolWithExpiry']
            self.df = df
            return(df)
        except Exception as e:
            printt(f"Error in getInstrument: {e}")
            return None


    def getData(self,t):
        try:
            symbol = str(t[3]).strip().replace(" ", "").upper()
            expiry = self.normalize_expiry_yyyymmdd(t[4])
            strike = float(t[5])
            option_type = str(t[6]).strip().replace(" ", "").upper()
            cached = self.greek_nse_contract_by_key.get((symbol, expiry, strike, option_type))
            if cached is not None:
                return cached

            d = self.df
            filtered_df = d[d['ExpiryDate'].str.contains(t[4], case=False, na=False)]
            filtered_df = filtered_df[filtered_df['Symbol'] == t[3].replace(' ','')]
            filtered_df = filtered_df[filtered_df['StrikePrice'] == float(t[5])]
            filtered_df = filtered_df[filtered_df['OptionType'].str.contains(t[6], case=False, na=False)]
            return(filtered_df.iloc[0])
        except Exception as e:
            printt(f"Error in getData: {e}")
            return None


    def getDataBSE(self,t):
        try:
            exchange_token = str(t).strip()
            cached = self.greek_bse_contract_by_token.get(exchange_token)
            if cached is not None:
                return cached

            filtered_df = self.df
            filtered_df = filtered_df[filtered_df['ExchangeToken'] == int(t)]
            return(filtered_df.iloc[0])
        except Exception as e:
            printt(f"Error in getDataBSE: {e}")
            return None


    def placeOrderBSE(self,gtoken,side,name,lot,qua,dt,source_order_id=""):
        try:
            global multiplier

            global sensexFreeze
            global bankex

            if name.upper() == 'BANKEX':
                freez = bankex
            elif name.upper() == 'SENSEX':
                freez = sensexFreeze
            else:
                raise ValueError(f"GreekSoft BSE freeze quantity not found for {name}")

            if side == 'Buy':
                si = 1
            elif side == 'Sell':
                si = 2
            else:
                raise ValueError(f"Unknown GreekSoft BSE side: {side}")

            quas = getFreezeQua(freez, dt.LotSize, int(qua * multiplier))
            for split_qty in quas:
                task = self.create_original_greek_order_task("BSE", gtoken, si, name, split_qty, dt, source_order_id)
                if task:
                    self.enqueue_greek_order_task(task)
            return []
        except Exception as e:
            printt(f"Error in placeOrderBSE: {e}")
            return []


    def placeOrder(self,gtoken,side,name,lot,qua,dt,source_order_id=""):
        try:
            global multiplier

            global niftyFreeze
            global bnfFreeze
            global midcpniftyFreeze
            global finniftyFreeze

            if name.upper() == 'NIFTY':
                freez = niftyFreeze
            elif name.upper() == 'BANKNIFTY':
                freez = bnfFreeze
            elif name.upper() == 'MIDCPNIFTY':
                freez = midcpniftyFreeze
            elif name.upper() == 'FINNIFTY':
                freez = finniftyFreeze
            else:
                raise ValueError(f"GreekSoft NSE freeze quantity not found for {name}")

            quas = getFreezeQua(freez, dt.LotSize, int(qua * multiplier))
            for split_qty in quas:
                task = self.create_original_greek_order_task("NSE", gtoken, side, name, split_qty, dt, source_order_id)
                if task:
                    self.enqueue_greek_order_task(task)
            return []
        except Exception as e:
            printt(f"Error in placeOrder: {e}")
            return []


    def getOrderStatus(self,orderId):
        try:
            if not orderId:
                return None

            for i in range(10):
                try:
                    df = pd.read_csv(get_greek_trades_file())
                    res = df[df['gorderid'] == int(orderId)].to_dict(orient='records')
                    if res:
                        return res[0]
                    time.sleep(2)
                except Exception as e:
                    printt(f"Greeksoft order status retry {i}: {e}")
                    time.sleep(2)

            printt(f"No order update for orderId {orderId}")
            return None

        except Exception as e:
            printt(f"Error in Greeksoft getOrderStatus: {e}")
            return None


    def getOrderBookALL(self):
        try:
            for i in range(10):

                global urll
                global username

                url = f"http://{urll}/getOrderBookDetailWithLegV2?exchangeType=ALL&ClientCode={self.gcid}&Order_Status=ALL&Ordertype=All&gscid={username}"

                headers = {
                    "Authorization": self.session_token
                }

                try:
                    session = self.get_greek_session()
                    response = session.get(url, headers=headers, timeout=self.greek_request_timeout)
                    d = response.json()
                    return(d)
                except Exception as e:
                    printt(f"Error in GreekSoft order book, retrying | attempt={i + 1} | error={e}")
                    self.reset_greek_session()
                    time.sleep(1)
        except Exception as e:
            printt(f"Error in getOrderBookALL: {e}")
            return None
