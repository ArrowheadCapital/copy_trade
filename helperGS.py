import json
import requests
import datetime
import os
import time
import uuid
import atexit
import random
import pandas as pd
from io import StringIO
import credentials as cre
import threading
from concurrent.futures import ThreadPoolExecutor
from collections import deque
from fetch_circuit import get_exchange_instrument_id, get_circuit_limits, get_ltp_avg, get_underlying_ltp
from async_logger import createLogFile as async_create_log_file
from async_logger import printt as async_printt

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
MAX_GREEK_ORDERS_PER_SEC = 9
log_lock = threading.Lock()


def wait_for_greek_order_slot():
    while True:
        with greek_rate_lock:
            now = time.time()

            while greek_order_timestamps and now - greek_order_timestamps[0] >= 1:
                greek_order_timestamps.popleft()

            if len(greek_order_timestamps) < MAX_GREEK_ORDERS_PER_SEC:
                greek_order_timestamps.append(now)
                return

            wait_time = 1 - (now - greek_order_timestamps[0])
            printt(f"RATE LIMIT HIT | waiting {wait_time:.3f}s")

        time.sleep(max(wait_time, 0.01))

def getOrderStatus(orderId):
        try:
            if orderId == 0:
                return('Order Data not avaiable..!')

            for i in range(10):
                try:
                    df = pd.read_csv('trades.csv')
                    res = df[df['gorderid'] == int(orderId)].to_dict(orient='records')[0]
                    return res
                except Exception as e:
                    printt('Error Order()_orderStatus :- ',e,i)
                    time.sleep(1)
        except Exception as e:
            printt(f"Error in getOrderStatus: {e}")
            return None

def printt(*args, **kwargs):
    async_printt(*args, **kwargs)

def saveInLogFile(*args, **kwargs):
    async_printt(*args, **kwargs)

def createLogFile():
    async_create_log_file()

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

def round_to_tick(price: float, tick: float) -> float:
    return round(tick * round(price / tick), 2)

def adjust_price_to_tick(price, tick_size, side, market_order_offset):
    offset = price * (market_order_offset / 100)

    if price <= 50:
        offset = market_order_offset

    if side == "BUY":
        price += offset
    else:
        price = max(tick_size, price - offset)

    return round_to_tick(price, tick_size)


# =========================== GREEKSOFT API ==================================

class greeksoft():
    def __init__(self):
        global username
        global pw
        for i in range(4):
            try:
                url = f"{authurl}/auth/greek/sessiontoken"
                data = {
                    "username": username,
                    "password": pw,
                    "validFor": "10d"
                }
                response = requests.post(url, json=data)

                session_token = response.json().get("sessionToken")
                self.session_token = session_token
                printt(f"Session Token Created")
                self.getInstrument()
                self.login()
                printt(f"Master Copy Downloaded..!")
                break
            except Exception as e:
                printt(f'Error in generating session token : {e}, retrying...')
                time.sleep(2)


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

            response = requests.post(url, json=data, headers=headers)
            data = response.json()
            self.gcid = str(data['response']['data']['gcid'])
            return(response.json())
        except Exception as e:
            printt(f"Error in login: {e}, {data}")
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
            response = requests.get(url, headers=headers)

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
            filtered_df = self.df
            filtered_df = filtered_df[filtered_df['ExchangeToken'] == int(t)]
            return(filtered_df.iloc[0])
        except Exception as e:
            printt(f"Error in getDataBSE: {e}")
            return None


    def placeOrderBSE(self,gtoken,side,name,lot,qua,dt):
        try:
            global multiplier
            global urll
            global username

            global sensexFreeze
            global bankex

            if name.upper() == 'BANKEX':
                freez = bankex
            elif name.upper() == 'SENSEX':
                freez = sensexFreeze

            if side == 'Buy':
                si = 1
            elif side == 'Sell':
                si = 2

            url = f"http://{urll}/NewOrderRequest"
            headers = {
                "Authorization": self.session_token
            }

            quas = getFreezeQua(freez, dt.LotSize, int(qua * multiplier))
            lots = [x / int(dt.LotSize) for x in quas]

            idds = []

            for i in range(len(quas)):
                qua = quas[i]
                lot = lots[i]

                for i in range(1):
                    try:
                        # Request body
                        data = {
                            "request": {
                                "data": {
                                "trigger_price": "0",
                                "gtoken": str(gtoken),
                                "side": str(si),
                                "gcid": self.gcid,
                                "validity": "0",
                                "price": "0",
                                "exchange": "BSE",
                                "disclosed_qty": "0",
                                "tradeSymbol": str(name.upper()),
                                "lot": str(lot),
                                "order_type": "2",
                                "product": "0",
                                "qty": str(qua),
                                "corderid": "3",
                                "amo": "0",
                                "iprocli": iprocli,
                                "AccountNumber": AccountNumber,
                                "gtdExpiry": 0,
                                "is_post_closed": "0",
                                "is_preopen_order": "0",
                                "isSqOffOrder": "false",
                                "offline": "0",
                                "is_restapi":"1",
                                "strategyName": "AlgoSelf"
                                },
                                "response_format": "json",
                                "request_type": "subscribe",
                                "streaming_type": "NewOrderRequest"
                            }
                        }

                        wait_for_greek_order_slot()
                        response = requests.post(url, json=data, headers=headers)
                        d = response.json()
                        printt(f"{d['response']['svcName']} , {d['response']['data']['gscid']} , {d['response']['data']['gorderid']}")
                        idds.append(d['response']['data']['gorderid'])
                        break
                    except Exception as e:
                        printt(d, f"Retrying orderPlacing in 1 Sec | Error: {e}", i)
                        time.sleep(1)

            return(idds)
        except Exception as e:
            printt(f"Error in placeOrderBSE: {e}")
            return []


    def placeOrder(self,gtoken,side,name,lot,qua,dt):
        try:
            global multiplier
            global urll
            global username

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

            quas = getFreezeQua(freez, dt.LotSize, int(qua * multiplier))
            lots = [x / int(dt.LotSize) for x in quas]

            url = f"http://{urll}/NewOrderRequest"
            headers = {
                "Authorization": self.session_token
            }

            idds = []

            for i in range(len(quas)):
                qua = quas[i]
                lot = lots[i]

                for i in range(1):
                    try:
                    # Request body
                        data = {
                            "request": {
                                "data": {
                                "trigger_price": "0",
                                "gtoken": str(gtoken),
                                "side": str(side),
                                "gcid": self.gcid,
                                "validity": "0",
                                "price": "0",
                                "exchange": "NSE",
                                "disclosed_qty": "0",
                                "tradeSymbol": str(name.upper()),
                                "lot": str(lot),
                                "order_type": "2",
                                "product": "0",
                                "qty": str(qua),
                                "corderid": "3",
                                "amo": "0",
                                "iprocli": iprocli,
                                "AccountNumber": AccountNumber,
                                "gtdExpiry": 0,
                                "is_post_closed": "0",
                                "is_preopen_order": "0",
                                "isSqOffOrder": "false",
                                "offline": "0",
                                "is_restapi":"1",
                                "strategyName": "AlgoSelf"
                                },
                                "response_format": "json",
                                "request_type": "subscribe",
                                "streaming_type": "NewOrderRequest"
                            }
                        }

                        wait_for_greek_order_slot()
                        response = requests.post(url, json=data, headers=headers)
                        d = response.json()
                        printt(f"{d['response']['svcName']} , {d['response']['data']['gscid']} , {d['response']['data']['gorderid']}")
                        idds.append(d['response']['data']['gorderid'])
                        break
                    except Exception as e:
                        printt(d, f"Retrying orderPlacing in 1 Sec | Error: {e}", i)
                        time.sleep(1)

            return(idds)
        except Exception as e:
            printt(f"Error in placeOrder: {e}")
            return []


    def getOrderStatus(self,orderId):
        try:
            if not orderId:
                return None

            for i in range(10):
                try:
                    df = pd.read_csv('trades.csv')
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
                    response = requests.get(url,headers=headers)
                    d = response.json()
                    return(d)
                except Exception as e:
                    try:
                        printt(d,'Retrying order status in one sec',i)
                        time.sleep(1)
                    except Exception as e:
                        printt('Error in order status, Retrying',i)
                        time.sleep(1)
        except Exception as e:
            printt(f"Error in getOrderBookALL: {e}")
            return None


# =========================== STRATX API ==================================

class StratX:

    inst_df = None
    inst_df_lock = threading.Lock()
    market_order_offset = 8
    tick_size_by_name = {}
    lot_size_by_name = {}
    bse_contract_by_id_desc = {}
    otm_description_by_key = {}
    retry_instrument_by_key = {}
    expiry_yyyymmdd_cache = {}
    expiry_ddmmmyy_cache = {}
    expiry_cache_lock = threading.Lock()
    instrument_names_to_load = {"NIFTY", "SENSEX"}
    redis_ltp_avg_cache = {}
    redis_ltp_avg_cache_ttl = 0.2
    redis_underlying_ltp_cache = {}
    redis_underlying_ltp_cache_ttl = 0.2
    stratx_order_workers = 20
    stratx_request_timeout = 5
    stratx_http_max_attempts = 2
    stratx_http_retry_sleep = 0.3
    stratx_thread_local = threading.local()
    stratx_order_pool = ThreadPoolExecutor(
        max_workers=stratx_order_workers,
        thread_name_prefix="stratx_order"
    )
    retry_state_file = "state.json"
    retry_state_save_interval = 1
    max_orderbook_retries = 1
    retry_state_lock = threading.Lock()
    retry_state_dirty = False
    retry_state_loaded = False
    retry_state_saver_started = False
    retry_state = {}
    future_root_ids = {}
    future_net_meta = {}
    net_state_file = "stratx_net_state.json"
    net_state_save_interval = 1
    net_state_dirty = False
    net_state_saver_started = False
    net_buckets = ("NIFTY_CE", "NIFTY_PE", "SENSEX_CE", "SENSEX_PE")
    net_lock = threading.Lock()
    net_position = {
        "NIFTY_CE": 0,
        "NIFTY_PE": 0,
        "SENSEX_CE": 0,
        "SENSEX_PE": 0,
    }
    net_released_roots = set()

    def __init__(self):
        mode = str(os.getenv("STRATX_EXPIRY_MODE", "NON_EXPIRY")).strip().upper()
        self.stratx_expiry_mode = mode.replace("-", "_").replace(" ", "_")
        self.impulse_offset = 1 if self.stratx_expiry_mode == "EXPIRY" else 0
        printt(f"STRATX_EXPIRY_MODE | mode={self.stratx_expiry_mode} | impulse_offset={self.impulse_offset}")

    def get_stratx_session(self):
        try:
            session = getattr(StratX.stratx_thread_local, "session", None)
            if session is None:
                session = requests.Session()
                adapter = requests.adapters.HTTPAdapter(
                    pool_connections=10,
                    pool_maxsize=10,
                    pool_block=False,
                )
                session.mount("https://", adapter)
                session.mount("http://", adapter)
                StratX.stratx_thread_local.session = session
            return session
        except Exception as e:
            raise RuntimeError(f"Error creating StratX HTTP session: {e}")

    def warmup_single_stratx_session(self, worker_index, url, headers, payload):
        try:
            session = self.get_stratx_session()
            start_ts = time.perf_counter()
            response = session.post(
                url,
                headers=headers,
                data=payload,
                timeout=StratX.stratx_request_timeout
            )
            elapsed_ms = (time.perf_counter() - start_ts) * 1000
            return {
                "ok": True,
                "worker_index": worker_index,
                "status_code": response.status_code,
                "elapsed_ms": elapsed_ms,
            }
        except Exception as e:
            return {
                "ok": False,
                "worker_index": worker_index,
                "error": str(e),
            }

    def warmup_stratx_sessions(self):
        try:
            url = f"https://{cre.stratX_url}/api/v1/reports/order/fields/?page_size=1&page_number=1"
            payload = json.dumps({
                "id": cre.id,
                "secret_key": cre.secret_key,
            })
            headers = {"Content-Type": "application/json"}

            futures = [
                StratX.stratx_order_pool.submit(
                    self.warmup_single_stratx_session,
                    worker_index,
                    url,
                    headers,
                    payload
                )
                for worker_index in range(StratX.stratx_order_workers)
            ]

            ok_count = 0
            fail_count = 0
            max_http_ms = 0.0
            for future in futures:
                result = future.result()
                if result.get("ok"):
                    ok_count += 1
                    max_http_ms = max(max_http_ms, result.get("elapsed_ms", 0.0))
                else:
                    fail_count += 1
                    printt(f"STRATX_SESSION_WARMUP_FAILED | worker={result.get('worker_index')} | error={result.get('error')}")

            printt(f"STRATX_SESSION_WARMUP_DONE | workers={StratX.stratx_order_workers} | ok={ok_count} | failed={fail_count} | max_http={max_http_ms:.1f}ms")
        except Exception as e:
            printt(f"Error warming StratX sessions: {e}")

    def get_retry_state_date(self):
        return datetime.datetime.now().strftime("%Y%m%d")

    def get_stratx_net_bucket(self, symbol, right):
        normalized_symbol = self.get_retry_pricing_symbol(symbol)
        normalized_right = str(right).strip().upper()

        if normalized_symbol == "NIFTY" and normalized_right in ("CE", "PE"):
            return f"NIFTY_{normalized_right}"

        if normalized_symbol == "SENSEX" and normalized_right in ("CE", "PE"):
            return f"SENSEX_{normalized_right}"

        return None

    def get_stratx_net_limit(self, bucket):
        try:
            pos_limit = int(float(getattr(cre, f"{bucket}_POS_NET")))
        except Exception:
            pos_limit = 0

        try:
            neg_limit = int(float(getattr(cre, f"{bucket}_NEG_NET")))
        except Exception:
            neg_limit = 0

        return max(pos_limit, 0), max(neg_limit, 0)

    def get_signed_qty(self, side, qty):
        side_value = str(side).strip().upper()
        quantity = int(float(qty))

        if side_value in ("BUY", "B", "1"):
            return quantity

        return -quantity
    
    def floor_to_lot_size(self, qty, lot_size):
        try:
            qty = int(float(qty))
            lot_size = int(float(lot_size))

            if lot_size <= 0:
                return qty

            return (qty // lot_size) * lot_size
        except Exception as e:
            printt(f"Error in floor_to_lot_size: {e}")
            return 0

    def get_stratx_traded_quantity(self, row):
        try:
            value = self.get_orderbook_row_value(row, "quantity", None)
            if value is None:
                return 0
            qty = int(float(value))
            return qty if qty > 0 else 0
        except Exception as e:
            printt(f"STRATX_NET_SYNC_QTY_PARSE_FAILED | error={e} | row={row}")
            return 0

    def fetch_stratx_traded_orders(self):
        try:
            page_size = 5000
            page_number = 1
            max_pages = 100
            all_data = []

            payload = json.dumps({
                "id": cre.id,
                "secret_key": cre.secret_key,
                "status": ["TRADED"]
            })
            headers = {"Content-Type": "application/json"}

            while page_number <= max_pages:
                url = f"https://{cre.stratX_url}/api/v1/reports/order/fields/?page_size={page_size}&page_number={page_number}"
                response = requests.request("POST", url, headers=headers, data=payload, timeout=StratX.stratx_request_timeout)
                page_response = response.json()

                if not isinstance(page_response, dict):
                    printt("STRATX_NET_SYNC_FETCH_FAILED | reason=invalid_response_type")
                    return None

                page_data = page_response.get("data")
                if not isinstance(page_data, list):
                    printt("STRATX_NET_SYNC_FETCH_FAILED | reason=missing_data_list")
                    return None

                all_data.extend(page_data)
                if len(page_data) != page_size:
                    return all_data

                page_number += 1

            return all_data
        except Exception as e:
            printt(f"STRATX_NET_SYNC_FETCH_FAILED | error={e}")
            return None

    def build_stratx_net_from_traded_orders(self, rows):
        net_position = {bucket: 0 for bucket in StratX.net_buckets}
        net_client_id = str(getattr(cre, "STRATX_NET_CLIENT_ID", "Y05601")).strip().upper()
        seen_rows = set()
        counted = 0

        if not net_client_id:
            printt("STRATX_NET_SYNC_SKIPPED | reason=missing_client_id")
            return None, 0

        for row in rows:
            try:
                status = str(self.get_orderbook_row_value(row, "status", "")).strip().upper()
                if status and status != "TRADED":
                    continue

                client_id = str(self.get_orderbook_row_value(row, "client_id", "")).strip().upper()
                if client_id != net_client_id:
                    continue

                symbol = self.get_retry_pricing_symbol(self.get_orderbook_row_value(row, "symbol", ""))
                right = str(self.get_orderbook_row_value(row, "right", "")).strip().upper()
                bucket = self.get_stratx_net_bucket(symbol, right)
                if not bucket:
                    continue

                qty = self.get_stratx_traded_quantity(row)
                if qty <= 0:
                    continue

                side = str(self.get_orderbook_row_value(row, "buyorsell", "")).strip().upper()
                row_id = self.get_orderbook_row_value(row, "id", None)
                unique_key = row_id if row_id not in (None, "") else (
                    self.get_orderbook_row_value(row, "reference_id", ""),
                    client_id,
                    bucket,
                    side,
                    qty,
                )
                unique_key = str(unique_key)
                if unique_key in seen_rows:
                    continue
                seen_rows.add(unique_key)

                net_position[bucket] += self.get_signed_qty(side, qty)
                counted += 1
            except Exception as e:
                printt(f"STRATX_NET_SYNC_ROW_SKIPPED | error={e} | row={row}")

        return net_position, counted

    def log_stratx_net_over_limit(self, net_position, source):
        for bucket, current_net in net_position.items():
            pos_limit, neg_limit = self.get_stratx_net_limit(bucket)
            if current_net > pos_limit or current_net < -neg_limit:
                printt(f"STRATX_NET_SYNC_OVER_LIMIT | source={source} | bucket={bucket} | net={current_net} | pos_limit={pos_limit} | neg_limit={neg_limit}")

    def sync_stratx_net_from_traded_orders(self, source="manual"):
        try:
            with StratX.net_lock:
                rows = self.fetch_stratx_traded_orders()
                if rows is None:
                    return False

                net_position, counted = self.build_stratx_net_from_traded_orders(rows)
                if net_position is None:
                    return False

                for bucket in StratX.net_buckets:
                    StratX.net_position[bucket] = int(net_position.get(bucket, 0))
                StratX.net_released_roots.clear()
                self.mark_stratx_net_state_dirty_locked()
                synced_net = dict(StratX.net_position)

            self.log_stratx_net_over_limit(synced_net, source)
            self.save_stratx_net_state_now()
            printt(f"STRATX_NET_SYNC_DONE | source={source} | net={synced_net}")
            return True
        except Exception as e:
            printt(f"STRATX_NET_SYNC_FAILED | source={source} | error={e}")
            return False

    def load_stratx_net_state(self):
        try:
            today_key = self.get_retry_state_date()
            state = None
            if os.path.exists(StratX.net_state_file):
                try:
                    with open(StratX.net_state_file, "r") as state_file:
                        state = json.load(state_file)
                except Exception as e:
                    printt(f"STRATX_NET_STATE_LOAD_FAILED | error={e}")

            with StratX.net_lock:
                if not isinstance(state, dict) or state.get("date") != today_key:
                    for bucket in StratX.net_buckets:
                        StratX.net_position[bucket] = 0
                    StratX.net_released_roots.clear()
                    self.mark_stratx_net_state_dirty_locked()
                    printt("STRATX_NET_STATE_RESET")
                    return

                saved_position = state.get("net_position", {})
                for bucket in StratX.net_buckets:
                    try:
                        StratX.net_position[bucket] = int(float(saved_position.get(bucket, 0)))
                    except Exception:
                        StratX.net_position[bucket] = 0

                StratX.net_released_roots.clear()
                released_roots = state.get("released_roots", [])
                if isinstance(released_roots, list):
                    StratX.net_released_roots.update(str(root_id).strip() for root_id in released_roots if str(root_id).strip())

            printt(f"STRATX_NET_STATE_LOADED | net={dict(StratX.net_position)} | released={len(StratX.net_released_roots)}")
        except Exception as e:
            printt(f"Error in load_stratx_net_state: {e}")

    def get_stratx_net_state_snapshot_locked(self):
        return {
            "date": self.get_retry_state_date(),
            "net_position": dict(StratX.net_position),
            "released_roots": sorted(StratX.net_released_roots),
        }

    def mark_stratx_net_state_dirty_locked(self):
        StratX.net_state_dirty = True

    def save_stratx_net_state_now(self):
        try:
            with StratX.net_lock:
                state = self.get_stratx_net_state_snapshot_locked()
                StratX.net_state_dirty = False

            temp_path = f"{StratX.net_state_file}.tmp"
            with open(temp_path, "w") as state_file:
                json.dump(state, state_file, indent=2)
            os.replace(temp_path, StratX.net_state_file)
        except Exception as e:
            with StratX.net_lock:
                StratX.net_state_dirty = True
            printt(f"STRATX_NET_STATE_SAVE_FAILED | error={e}")

    def stratx_net_state_saver_loop(self):
        while True:
            try:
                time.sleep(StratX.net_state_save_interval)
                with StratX.net_lock:
                    should_save = StratX.net_state_dirty
                if should_save:
                    self.save_stratx_net_state_now()
            except Exception as e:
                printt(f"STRATX_NET_STATE_SAVER_ERROR | error={e}")
                time.sleep(1)

    def start_stratx_net_state_saver(self):
        try:
            with StratX.net_lock:
                if StratX.net_state_saver_started:
                    return
                StratX.net_state_saver_started = True

            saver_thread = threading.Thread(target=self.stratx_net_state_saver_loop, daemon=True)
            saver_thread.start()
            atexit.register(self.save_stratx_net_state_now)
            printt("STRATX_NET_STATE_SAVER_STARTED")
        except Exception as e:
            printt(f"Error starting StratX net state saver: {e}")

    def save_stratx_net_state(self):
        self.save_stratx_net_state_now()

    def reserve_stratx_net(self, symbol, right, side, qty, lot_size):
        try:
            bucket = self.get_stratx_net_bucket(symbol, right)
            original_qty = int(float(qty))

            if not bucket:
                return True, original_qty, None

            if original_qty <= 0:
                printt(f"STRATX_NET_LIMIT_SKIP | bucket={bucket} | side={side} | qty={qty} | reason=non_positive_qty")
                return False, 0, None

            pos_limit, neg_limit = self.get_stratx_net_limit(bucket)
            signed_qty = self.get_signed_qty(side, original_qty)

            with StratX.net_lock:
                current_net = int(StratX.net_position.get(bucket, 0))
                next_net = current_net + signed_qty

                if current_net > pos_limit:
                    if signed_qty >= 0:
                        printt(f"STRATX_NET_LIMIT_SKIP | bucket={bucket} | side={side} | qty={original_qty} | current={current_net} | next={next_net} | pos_limit={pos_limit} | neg_limit={neg_limit} | lot_size={lot_size} | reason=over_positive_increase")
                        return False, 0, None
                    adjusted_qty = min(original_qty, self.floor_to_lot_size(current_net + neg_limit, lot_size))
                    if adjusted_qty <= 0:
                        printt(f"STRATX_NET_LIMIT_SKIP | bucket={bucket} | side={side} | qty={original_qty} | current={current_net} | next={next_net} | pos_limit={pos_limit} | neg_limit={neg_limit} | lot_size={lot_size} | reason=no_valid_reduce")
                        return False, 0, None
                    if adjusted_qty != original_qty:
                        printt(f"STRATX_NET_PARTIAL_ALLOWED | bucket={bucket} | side={side} | original_qty={original_qty} | adjusted_qty={adjusted_qty} | current={current_net} | requested_next={next_net} | pos_limit={pos_limit} | neg_limit={neg_limit} | lot_size={lot_size} | reason=over_positive_reduce")
                elif current_net < -neg_limit:
                    if signed_qty <= 0:
                        printt(f"STRATX_NET_LIMIT_SKIP | bucket={bucket} | side={side} | qty={original_qty} | current={current_net} | next={next_net} | pos_limit={pos_limit} | neg_limit={neg_limit} | lot_size={lot_size} | reason=over_negative_increase")
                        return False, 0, None
                    adjusted_qty = min(original_qty, self.floor_to_lot_size(pos_limit - current_net, lot_size))
                    if adjusted_qty <= 0:
                        printt(f"STRATX_NET_LIMIT_SKIP | bucket={bucket} | side={side} | qty={original_qty} | current={current_net} | next={next_net} | pos_limit={pos_limit} | neg_limit={neg_limit} | lot_size={lot_size} | reason=no_valid_reduce")
                        return False, 0, None
                    if adjusted_qty != original_qty:
                        printt(f"STRATX_NET_PARTIAL_ALLOWED | bucket={bucket} | side={side} | original_qty={original_qty} | adjusted_qty={adjusted_qty} | current={current_net} | requested_next={next_net} | pos_limit={pos_limit} | neg_limit={neg_limit} | lot_size={lot_size} | reason=over_negative_reduce")
                elif -neg_limit <= next_net <= pos_limit:
                    adjusted_qty = original_qty
                else:
                    side_value = str(side).strip().upper()

                    if side_value in ("BUY", "B", "1"):
                        max_allowed_qty = pos_limit - current_net
                    else:
                        max_allowed_qty = current_net + neg_limit

                    adjusted_qty = self.floor_to_lot_size(max_allowed_qty, lot_size)

                    if adjusted_qty <= 0:
                        printt(f"STRATX_NET_LIMIT_SKIP | bucket={bucket} | side={side} | qty={original_qty} | current={current_net} | next={next_net} | pos_limit={pos_limit} | neg_limit={neg_limit} | lot_size={lot_size} | reason=no_valid_partial")
                        return False, 0, None

                    printt(f"STRATX_NET_PARTIAL_ALLOWED | bucket={bucket} | side={side} | original_qty={original_qty} | adjusted_qty={adjusted_qty} | current={current_net} | requested_next={next_net} | pos_limit={pos_limit} | neg_limit={neg_limit} | lot_size={lot_size}")

                adjusted_signed_qty = self.get_signed_qty(side, adjusted_qty)
                adjusted_next_net = current_net + adjusted_signed_qty

                if adjusted_next_net > pos_limit or adjusted_next_net < -neg_limit:
                    if current_net > pos_limit and adjusted_next_net < current_net:
                        pass
                    elif current_net < -neg_limit and adjusted_next_net > current_net:
                        pass
                    else:
                        printt(f"STRATX_NET_LIMIT_SKIP | bucket={bucket} | side={side} | qty={original_qty} | adjusted_qty={adjusted_qty} | current={current_net} | next={adjusted_next_net} | pos_limit={pos_limit} | neg_limit={neg_limit} | lot_size={lot_size} | reason=partial_still_exceeds")
                        return False, 0, None

                StratX.net_position[bucket] = adjusted_next_net
                self.mark_stratx_net_state_dirty_locked()

            printt(f"STRATX_NET_RESERVED | bucket={bucket} | signed_qty={adjusted_signed_qty} | current={adjusted_next_net} | pos_limit={pos_limit} | neg_limit={neg_limit}")

            return True, adjusted_qty, {
                "bucket": bucket,
                "signed_qty": adjusted_signed_qty,
            }

        except Exception as e:
            printt(f"STRATX_NET_RESERVE_ERROR | symbol={symbol} | right={right} | side={side} | qty={qty} | error={e}")
            return False, 0, None

    def release_stratx_net(self, root_order_id, bucket=None, signed_qty=None, reason="unknown"):
        try:
            root_key = str(root_order_id).strip()
            if not root_key:
                return False

            if not bucket or signed_qty is None:
                printt(f"STRATX_NET_RELEASE_SKIPPED | root_id={root_key} | reason=missing_net_data | source_reason={reason}")
                return False

            bucket = str(bucket).strip().upper()
            signed_qty = int(float(signed_qty))
            if bucket not in StratX.net_buckets:
                printt(f"STRATX_NET_RELEASE_SKIPPED | root_id={root_key} | bucket={bucket} | reason=unknown_bucket")
                return False

            with StratX.net_lock:
                if root_key in StratX.net_released_roots:
                    return False

                current_net = int(StratX.net_position.get(bucket, 0))
                next_net = current_net - signed_qty
                StratX.net_position[bucket] = next_net
                StratX.net_released_roots.add(root_key)
                self.mark_stratx_net_state_dirty_locked()

            printt(f"STRATX_NET_RELEASE | root_id={root_key} | bucket={bucket} | signed_qty={signed_qty} | current={next_net} | reason={reason}")
            return True
        except Exception as e:
            printt(f"STRATX_NET_RELEASE_ERROR | root_id={root_order_id} | error={e}")
            return False

    def rollback_stratx_net_meta(self, net_meta, reason="local_submit_failed"):
        try:
            if not isinstance(net_meta, dict):
                return False

            bucket = str(net_meta.get("bucket", "")).strip().upper()
            signed_qty = int(float(net_meta.get("signed_qty", 0)))
            if bucket not in StratX.net_buckets:
                return False

            with StratX.net_lock:
                current_net = int(StratX.net_position.get(bucket, 0))
                next_net = current_net - signed_qty
                StratX.net_position[bucket] = next_net
                self.mark_stratx_net_state_dirty_locked()

            printt(f"STRATX_NET_ROLLBACK | bucket={bucket} | signed_qty={signed_qty} | current={next_net} | reason={reason}")
            return True
        except Exception as e:
            printt(f"STRATX_NET_ROLLBACK_ERROR | error={e}")
            return False

    def release_stratx_net_from_orderbook(self, root_order_id, row, reason="orderbook_terminal"):
        try:
            symbol = str(self.get_orderbook_row_value(row, "symbol", "")).strip().upper()
            right = str(self.get_orderbook_row_value(row, "right", "")).strip().upper()
            side = str(self.get_orderbook_row_value(row, "buyorsell", "")).strip().upper()
            qty = self.get_orderbook_row_value(row, "quantity", None)

            bucket = self.get_stratx_net_bucket(symbol, right)
            if not bucket or qty is None:
                printt(f"STRATX_NET_ORDERBOOK_RELEASE_SKIPPED | root_id={root_order_id} | symbol={symbol} | right={right} | qty={qty}")
                return False

            signed_qty = self.get_signed_qty(side, qty)
            return self.release_stratx_net(root_order_id, bucket, signed_qty, reason)
        except Exception as e:
            printt(f"STRATX_NET_ORDERBOOK_RELEASE_ERROR | root_id={root_order_id} | error={e}")
            return False

    def get_empty_retry_state(self):
        return {
            "date": self.get_retry_state_date(),
            "reference_id_to_root_id": {},
            "retry_by_root": {},
            "order_meta_by_root": {},
        }
    
    def normalize_retry_by_root_state(self, retry_by_root):
        try:
            normalized = {}
            if not isinstance(retry_by_root, dict):
                return normalized

            for root_order_id, root_state in retry_by_root.items():
                if not isinstance(root_state, dict):
                    continue

                retry_count_by_client = root_state.get("retry_count_by_client", {})
                if not isinstance(retry_count_by_client, dict):
                    retry_count_by_client = {}

                processed_refs_by_client = root_state.get("processed_refs_by_client", {})
                if not isinstance(processed_refs_by_client, dict):
                    processed_refs_by_client = {}

                normalized_retry_counts = {}
                for client_id, count in retry_count_by_client.items():
                    client_key = str(client_id).strip()
                    if not client_key:
                        continue
                    try:
                        normalized_retry_counts[client_key] = int(count)
                    except Exception:
                        normalized_retry_counts[client_key] = 0

                normalized_processed_refs = {}
                for client_id, refs in processed_refs_by_client.items():
                    client_key = str(client_id).strip()
                    if not client_key:
                        continue
                    if isinstance(refs, list):
                        normalized_processed_refs[client_key] = set(str(ref).strip() for ref in refs if str(ref).strip())
                    elif isinstance(refs, set):
                        normalized_processed_refs[client_key] = refs
                    else:
                        normalized_processed_refs[client_key] = set()

                normalized[str(root_order_id)] = {
                    "retry_count_by_client": normalized_retry_counts,
                    "processed_refs_by_client": normalized_processed_refs,
                }

            return normalized
        except Exception as e:
            printt(f"STRATX_RETRY_STATE_NORMALIZE_FAILED | error={e}")
            return {}

    def serialize_retry_by_root_state(self, retry_by_root):
        try:
            serialized = {}
            if not isinstance(retry_by_root, dict):
                return serialized

            for root_order_id, root_state in retry_by_root.items():
                if not isinstance(root_state, dict):
                    continue

                retry_count_by_client = root_state.get("retry_count_by_client", {})
                processed_refs_by_client = root_state.get("processed_refs_by_client", {})

                serialized[str(root_order_id)] = {
                    "retry_count_by_client": dict(retry_count_by_client) if isinstance(retry_count_by_client, dict) else {},
                    "processed_refs_by_client": {
                        str(client_id): sorted(list(refs)) if isinstance(refs, set) else list(refs if isinstance(refs, list) else [])
                        for client_id, refs in (processed_refs_by_client.items() if isinstance(processed_refs_by_client, dict) else [])
                    },
                }

            return serialized
        except Exception as e:
            printt(f"STRATX_RETRY_STATE_SERIALIZE_FAILED | error={e}")
            return {}

    def normalize_order_meta_by_root_state(self, order_meta_by_root):
        try:
            normalized = {}
            if not isinstance(order_meta_by_root, dict):
                return normalized

            for root_order_id, meta in order_meta_by_root.items():
                if not isinstance(meta, dict):
                    continue
                root_key = str(root_order_id).strip()
                if not root_key:
                    continue

                cleaned = dict(meta)
                try:
                    cleaned["quantity"] = int(float(cleaned.get("quantity", 0)))
                except Exception:
                    cleaned["quantity"] = 0
                normalized[root_key] = cleaned

            return normalized
        except Exception as e:
            printt(f"STRATX_ORDER_META_NORMALIZE_FAILED | error={e}")
            return {}

    def serialize_order_meta_by_root_state(self, order_meta_by_root):
        try:
            if not isinstance(order_meta_by_root, dict):
                return {}
            return {
                str(root_order_id): dict(meta)
                for root_order_id, meta in order_meta_by_root.items()
                if isinstance(meta, dict)
            }
        except Exception as e:
            printt(f"STRATX_ORDER_META_SERIALIZE_FAILED | error={e}")
            return {}

    def get_retry_root_state(self, root_order_id):
        retry_by_root = StratX.retry_state.setdefault("retry_by_root", {})
        root_state = retry_by_root.setdefault(
            str(root_order_id),
            {
                "retry_count_by_client": {},
                "processed_refs_by_client": {},
            },
        )
        if not isinstance(root_state.get("retry_count_by_client"), dict):
            root_state["retry_count_by_client"] = {}
        if not isinstance(root_state.get("processed_refs_by_client"), dict):
            root_state["processed_refs_by_client"] = {}
        return root_state

    def load_retry_state(self):
        try:
            today = self.get_retry_state_date()
            state = None
            if os.path.exists(StratX.retry_state_file):
                try:
                    with open(StratX.retry_state_file, "r") as state_file:
                        state = json.load(state_file)
                except Exception as e:
                    printt(f"STRATX_RETRY_STATE_LOAD_FAILED | error={e}")

            state_needs_save = False
            if not isinstance(state, dict) or state.get("date") != today:
                state = self.get_empty_retry_state()
                state_needs_save = True
            else:
                state = {
                    "date": today,
                    "reference_id_to_root_id": state.get("reference_id_to_root_id", {}) if isinstance(state.get("reference_id_to_root_id"), dict) else {},
                    "retry_by_root": self.normalize_retry_by_root_state(state.get("retry_by_root", {})),
                    "order_meta_by_root": self.normalize_order_meta_by_root_state(state.get("order_meta_by_root", {})),
                }

            with StratX.retry_state_lock:
                StratX.retry_state = state
                StratX.retry_state_loaded = True
                StratX.retry_state_dirty = state_needs_save or not os.path.exists(StratX.retry_state_file)

            printt(f"STRATX_RETRY_STATE_LOADED | refs={len(state['reference_id_to_root_id'])} | roots={len(state['retry_by_root'])}")
        except Exception as e:
            printt(f"Error loading StratX retry state: {e}")
            with StratX.retry_state_lock:
                StratX.retry_state = self.get_empty_retry_state()
                StratX.retry_state_loaded = True
                StratX.retry_state_dirty = True

    def get_retry_state_snapshot(self):
        with StratX.retry_state_lock:
            if not StratX.retry_state_loaded:
                StratX.retry_state = self.get_empty_retry_state()
                StratX.retry_state_loaded = True
                StratX.retry_state_dirty = True
            return {
                "date": StratX.retry_state.get("date", self.get_retry_state_date()),
                "reference_id_to_root_id": dict(StratX.retry_state.get("reference_id_to_root_id", {})),
                "retry_by_root": self.serialize_retry_by_root_state(StratX.retry_state.get("retry_by_root", {})),
                "order_meta_by_root": self.serialize_order_meta_by_root_state(StratX.retry_state.get("order_meta_by_root", {})),
            }

    def save_retry_state_now(self):
        try:
            with StratX.retry_state_lock:
                if not StratX.retry_state_loaded:
                    StratX.retry_state = self.get_empty_retry_state()
                    StratX.retry_state_loaded = True

                state_snapshot = {
                    "date": StratX.retry_state.get("date", self.get_retry_state_date()),
                    "reference_id_to_root_id": dict(StratX.retry_state.get("reference_id_to_root_id", {})),
                    "retry_by_root": self.serialize_retry_by_root_state(StratX.retry_state.get("retry_by_root", {})),
                    "order_meta_by_root": self.serialize_order_meta_by_root_state(StratX.retry_state.get("order_meta_by_root", {})),
                }
                StratX.retry_state_dirty = False

            temp_path = f"{StratX.retry_state_file}.tmp"
            with open(temp_path, "w") as state_file:
                json.dump(state_snapshot, state_file, indent=2)
            os.replace(temp_path, StratX.retry_state_file)
        except Exception as e:
            with StratX.retry_state_lock:
                StratX.retry_state_dirty = True
            printt(f"STRATX_RETRY_STATE_SAVE_FAILED | error={e}")

    def retry_state_saver_loop(self):
        while True:
            try:
                time.sleep(StratX.retry_state_save_interval)
                with StratX.retry_state_lock:
                    should_save = StratX.retry_state_dirty
                if should_save:
                    self.save_retry_state_now()
            except Exception as e:
                printt(f"STRATX_RETRY_STATE_SAVER_ERROR | error={e}")
                time.sleep(1)

    def start_retry_state_saver(self):
        try:
            if not StratX.retry_state_loaded:
                self.load_retry_state()

            with StratX.retry_state_lock:
                if StratX.retry_state_saver_started:
                    return
                StratX.retry_state_saver_started = True

            saver_thread = threading.Thread(target=self.retry_state_saver_loop, daemon=True)
            saver_thread.start()
            atexit.register(self.save_retry_state_now)
            printt("STRATX_RETRY_STATE_SAVER_STARTED")
        except Exception as e:
            printt(f"Error starting StratX retry state saver: {e}")

    def register_future_root_id(self, future, root_order_id, net_meta=None):
        try:
            with StratX.retry_state_lock:
                StratX.future_root_ids[future] = root_order_id
                if isinstance(net_meta, dict):
                    StratX.future_net_meta[future] = dict(net_meta)
                self.get_retry_root_state(root_order_id)
                StratX.retry_state_dirty = True
        except Exception as e:
            printt(f"STRATX_FUTURE_ROOT_REGISTER_FAILED | root_id={root_order_id} | error={e}")

    def register_order_meta(self, root_order_id, order_meta):
        try:
            root_key = str(root_order_id).strip()
            if not root_key or not isinstance(order_meta, dict):
                return

            cleaned_meta = dict(order_meta)
            try:
                cleaned_meta["quantity"] = int(float(cleaned_meta.get("quantity", 0)))
            except Exception:
                cleaned_meta["quantity"] = 0

            with StratX.retry_state_lock:
                order_meta_by_root = StratX.retry_state.setdefault("order_meta_by_root", {})
                existing_meta = order_meta_by_root.get(root_key)
                if isinstance(existing_meta, dict):
                    existing_meta.update({k: v for k, v in cleaned_meta.items() if k not in existing_meta or existing_meta.get(k) in (None, "")})
                else:
                    order_meta_by_root[root_key] = cleaned_meta
                StratX.retry_state_dirty = True
        except Exception as e:
            printt(f"STRATX_ORDER_META_REGISTER_FAILED | root_id={root_order_id} | error={e}")

    def get_order_meta(self, root_order_id):
        try:
            root_key = str(root_order_id).strip()
            if not root_key:
                return {}
            with StratX.retry_state_lock:
                order_meta_by_root = StratX.retry_state.setdefault("order_meta_by_root", {})
                meta = order_meta_by_root.get(root_key, {})
                return dict(meta) if isinstance(meta, dict) else {}
        except Exception as e:
            printt(f"STRATX_ORDER_META_GET_FAILED | root_id={root_order_id} | error={e}")
            return {}

    def register_reference_root_id(self, future, reference_id):
        try:
            with StratX.retry_state_lock:
                root_order_id = StratX.future_root_ids.pop(future, None)
                StratX.future_net_meta.pop(future, None)
                if not root_order_id:
                    printt(f"STRATX_REFERENCE_ROOT_MISSING | ref_id={reference_id}")
                    return

                reference_map = StratX.retry_state.setdefault("reference_id_to_root_id", {})
                reference_map[str(reference_id)] = root_order_id
                self.get_retry_root_state(root_order_id)
                StratX.retry_state_dirty = True

        except Exception as e:
            printt(f"STRATX_REFERENCE_ROOT_REGISTER_FAILED | ref_id={reference_id} | error={e}")

    def to_yyyymmdd(self, date_str):
        key = str(date_str).strip().upper()
        cached = StratX.expiry_yyyymmdd_cache.get(key)
        if cached is not None:
            return cached
        try:
            if len(key) == 8 and key.isdigit():
                value = key
            else:
                value = datetime.datetime.strptime(key, "%d%b%Y").strftime("%Y%m%d")
        except Exception:
            try:
                value = pd.to_datetime(date_str).strftime("%Y%m%d")
            except Exception as e:
                printt(f"Date conversion error: {e}")
                return None
        with StratX.expiry_cache_lock:
            StratX.expiry_yyyymmdd_cache[key] = value
        return value


    def to_ddmmmyy(self, date_str):
        key = str(date_str).strip().upper()
        cached = StratX.expiry_ddmmmyy_cache.get(key)
        if cached is not None:
            return cached
        try:
            if len(key) == 8 and key.isdigit():
                value = datetime.datetime.strptime(key, "%Y%m%d").strftime("%d%b%y").upper()
            elif len(key) == 7:
                value = datetime.datetime.strptime(key, "%d%b%y").strftime("%d%b%y").upper()
            else:
                value = datetime.datetime.strptime(key, "%d%b%Y").strftime("%d%b%y").upper()
        except Exception:
            try:
                value = pd.to_datetime(date_str).strftime("%d%b%y").upper()
            except Exception as e:
                printt(f"Date conversion error: {e}")
                return None
        with StratX.expiry_cache_lock:
            StratX.expiry_ddmmmyy_cache[key] = value
        return value


    def load_instrument_master(self):
        if StratX.inst_df is not None:
            return
        with StratX.inst_df_lock:
            if StratX.inst_df is not None:
                return
            try:
                printt("Loading StratX instrument master...")
                df = pd.read_csv(cre.optionInstrumentPath)
                df.columns = df.columns.str.strip()
                if "Name" in df.columns and StratX.instrument_names_to_load:
                    names_to_load = {str(name).strip().upper() for name in StratX.instrument_names_to_load}
                    before_filter_rows = len(df)
                    name_normalized = df["Name"].astype(str).str.strip().str.upper()
                    df = df[name_normalized.isin(names_to_load)].copy()
                    printt(f"Instrument master filtered: {before_filter_rows} -> {len(df)} rows for names={','.join(sorted(names_to_load))}")
                df["ExchangeInstrumentID"] = df["ExchangeInstrumentID"].astype(str).str.strip()
                df["Description"] = df["Description"].astype(str).str.strip()
                df["exchange_segment_normalized"] = df["ExchangeSegment"].astype(str).str.strip().str.upper()
                df["name_normalized"] = df["Name"].astype(str).str.strip().str.upper()
                df["tick_size_numeric"] = pd.to_numeric(df["TickSize"], errors="coerce")
                df["lot_size_numeric"] = pd.to_numeric(df["LotSize"], errors="coerce")

                # Precompute normalized lookup columns once for fast repeated filters
                df["underlying_index_name_normalized"] = df["UnderlyingIndexName"].astype(str).str.strip().str.upper()
                df["contract_expiration_yyyymmdd"] = pd.to_datetime(
                    df["ContractExpiration"], errors="coerce"
                ).dt.strftime("%Y%m%d")
                df["strike_price_numeric"] = pd.to_numeric(df["StrikePrice"], errors="coerce")
                df["option_type_normalized"] = df["OptionType"].astype(str).str.strip().str.upper()

                tick_size_by_name = {}
                lot_size_by_name = {}
                for row_name, tick_size in df[["name_normalized", "tick_size_numeric"]].itertuples(index=False, name=None):
                    if row_name and pd.notna(tick_size) and row_name not in tick_size_by_name:
                        tick_size_by_name[row_name] = float(tick_size)

                for row_name, lot_size in df[["name_normalized", "lot_size_numeric"]].itertuples(index=False, name=None):
                    if row_name and pd.notna(lot_size) and row_name not in lot_size_by_name:
                        lot_size_by_name[row_name] = int(float(lot_size))

                bse_contract_by_id_desc = {}
                otm_description_by_key = {}
                retry_instrument_by_key = {}
                for row in df[[
                    "ExchangeSegment", "ExchangeInstrumentID", "Description", "Name", "UnderlyingIndexName",
                    "underlying_index_name_normalized", "contract_expiration_yyyymmdd",
                    "option_type_normalized", "strike_price_numeric", "tick_size_numeric", "lot_size_numeric",
                ]].itertuples(index=False, name=None):
                    (
                        exchange_segment, exchange_instrument_id, description, name, underlying_name, underlying_norm,
                        expiry_yyyymmdd, option_type, strike_price, tick_size, lot_size,
                    ) = row
                    desc = str(description).strip()
                    opt = str(option_type).strip().upper()
                    if opt == "3":
                        right = "CE"
                        strike = float(strike_price) if pd.notna(strike_price) else None
                    elif opt == "4":
                        right = "PE"
                        strike = float(strike_price) if pd.notna(strike_price) else None
                    elif opt == "1":
                        right = "FUT"
                        strike = None
                    else:
                        continue

                    symbol = str(underlying_name).strip().upper()
                    name_symbol = str(name).strip().upper()
                    exchange_segment = str(exchange_segment).strip().upper()
                    expiry = str(expiry_yyyymmdd).strip()
                    tick = float(tick_size) if pd.notna(tick_size) else None
                    lot = int(float(lot_size)) if pd.notna(lot_size) else None
                    if tick is not None and expiry and expiry.lower() != "nan":
                        bse_contract_by_id_desc[(str(exchange_instrument_id).strip(), desc)] = (
                            symbol, strike, expiry, right, tick, lot
                        )
                        retry_key = (exchange_segment, name_symbol, expiry, right, strike)
                        retry_instrument_by_key[retry_key] = (desc, tick)

                    if right in ("CE", "PE") and strike is not None and expiry and expiry.lower() != "nan":
                        otm_description_by_key[(str(underlying_norm).strip().upper(), expiry, right, strike)] = desc

                StratX.tick_size_by_name = tick_size_by_name
                StratX.lot_size_by_name = lot_size_by_name
                StratX.bse_contract_by_id_desc = bse_contract_by_id_desc
                StratX.otm_description_by_key = otm_description_by_key
                StratX.retry_instrument_by_key = retry_instrument_by_key
                StratX.inst_df = df
                printt(f"Instrument master loaded: {len(df)} rows")
            except Exception as e:
                printt(f"Error loading instrument master: {e}")


    def get_bse_contract_details(self, exchange_instrument_id, description):
        try:
            self.load_instrument_master()
            exchange_instrument_id = str(exchange_instrument_id).strip()
            description = str(description).strip()
            cached = StratX.bse_contract_by_id_desc.get((exchange_instrument_id, description))
            if cached is not None:
                return cached

            df = StratX.inst_df

            row = df[
                (df["ExchangeInstrumentID"] == exchange_instrument_id) &
                (df["Description"] == description)
            ]

            if row.empty:
                raise ValueError(f"BSE Instrument not found: {exchange_instrument_id} | {description}")

            row = row.iloc[0]
            expiry = pd.to_datetime(row["ContractExpiration"]).strftime("%Y%m%d")
            tick_size = float(row["TickSize"])

            opt_code = str(row["OptionType"]).strip()
            if opt_code == "3":
                right = "CE"
                strike = float(row["StrikePrice"])
            elif opt_code == "4":
                right = "PE"
                strike = float(row["StrikePrice"])
            elif opt_code == "1":
                right = "FUT"
                strike = None
            else:
                raise ValueError(f"Unknown OptionType code: {opt_code}")

            symbol = str(row["UnderlyingIndexName"]).strip().upper()

            try:
                lot_size = int(float(row["LotSize"]))
            except Exception:
                if symbol == "SENSEX":
                    lot_size = 20
                elif symbol == "NIFTY":
                    lot_size = 65

            return symbol, strike, expiry, right, tick_size, lot_size

        except Exception as e:
            printt(f"Error in get_bse_contract_details: {e}")
            return None, None, None, None, None, None


    def apply_circuit_clamp(self, price, description):
        try:
            instrument_id = get_exchange_instrument_id(description, StratX.inst_df)
            if not instrument_id:
                return price

            limits = get_circuit_limits(instrument_id)
            if not limits:
                return price

            uc = limits.get("UC")
            lc = limits.get("LC")
            ts = limits.get("ts")
            if uc is None or lc is None or ts is None:
                return price

            uc = float(uc)
            lc = float(lc)

            try:
                tick_time = datetime.datetime.strptime(str(ts), "%Y-%m-%d %H:%M:%S.%f").timestamp()
            except Exception:
                tick_time = datetime.datetime.strptime(str(ts), "%Y-%m-%d %H:%M:%S").timestamp()

            if time.time() - tick_time > 300:
                return price

            if price > uc:
                return uc
            if price < lc:
                return lc
            return price
        except Exception as e:
            printt(f"Error in apply_circuit_clamp: {e}")
            return price


    def build_cache_symbol(self, name, expiry, strike, right):
        try:
            strike_val = float(strike)
            if strike_val.is_integer():
                strike_str = str(int(strike_val))
            else:
                strike_str = str(strike).strip()
            return f"{str(name).strip().upper()}{str(expiry).strip().upper()}{strike_str}{str(right).strip().upper()}"
        except Exception:
            return None


    def get_redis_ltp_avg(self, cache_symbol):
        try:
            tt0 = time.perf_counter()
            cache_key = str(cache_symbol).strip().upper()
            cached = StratX.redis_ltp_avg_cache.get(cache_key)
            if cached is not None:
                cached_at, cached_result = cached
                if tt0 - cached_at <= StratX.redis_ltp_avg_cache_ttl:
                    return cached_result

            data = get_ltp_avg(cache_key)
            if not data:
                return 0, 0

            result = (data["ltp"], data["avg"])
            StratX.redis_ltp_avg_cache[cache_key] = (time.perf_counter(), result)
            return result
        except Exception as e:
            printt(f"Redis tick read error ({cache_symbol}): {e}")
            return 0, 0


    def price_from_avg_ltp_or_fallback(self, side, tick_size, description, cache_symbol=None):
        try:
            if cache_symbol:
                ltp, avg = self.get_redis_ltp_avg(cache_symbol)

                if ltp == 0 and avg == 0:
                    return 0

                if ltp is not None:
                    offset_ltp = ltp * (self.market_order_offset / 100)
                    if ltp <= 50:
                        offset_ltp = self.market_order_offset

                    offset_avg = None
                    if avg is not None:
                        offset_avg = avg * (self.market_order_offset / 100)
                        if avg <= 50:
                            offset_avg = self.market_order_offset

                    if avg is None:
                        if str(side).upper() == "BUY":
                            raw = ltp + offset_ltp
                        else:
                            raw = max(float(tick_size), ltp - offset_ltp)
                    elif str(side).upper() == "BUY":
                        raw = (ltp + offset_ltp) if (avg + offset_avg <= ltp) else (avg + offset_avg)
                    else:
                        raw = (ltp - offset_ltp) if (avg - offset_avg >= ltp) else (avg - offset_avg)
                        raw = max(float(tick_size), raw)

                    price = round_to_tick(raw, float(tick_size))
                    if price <= 0:
                        price = float(tick_size)
                    price = self.apply_circuit_clamp(price, description)
                    return price

            return 0
        except Exception as e:
            printt(f"Error in price_from_avg_ltp_or_fallback: {e}")
            return 0


    def get_otm_strike(self, symbol, right, strike, offset):
        try:
            sym = str(symbol).strip().upper()
            opt = str(right).strip().upper()
            base = float(strike)
            off = int(offset)

            if sym == "NIFTY":
                step = 50
            elif sym == "SENSEX":
                step = 100
            else:
                return None

            shift = off * step
            if opt == "CE":
                return base + shift
            if opt == "PE":
                return base - shift
            return None
        except Exception as e:
            printt(f"Error in get_otm_strike: {e}")
            return None


    def get_otm_description(self, symbol, expiry_yyyymmdd, right, strike):
        try:
            self.load_instrument_master()

            sym = str(symbol).strip().upper()
            idx_name_map = {
                "BANKNIFTY": "NIFTY BANK",
                "FINNIFTY": "NIFTY FIN SERVICE",
                "MIDCPNIFTY": "NIFTY MID SELECT",
                "NIFTY": "NIFTY 50",
                "NIFTYNXT50": "NIFTY NEXT 50",
            }
            mapped_sym = idx_name_map.get(sym, sym)
            opt = str(right).strip().upper()
            exp = str(expiry_yyyymmdd).strip()
            stk = float(strike)
            cached = StratX.otm_description_by_key.get((mapped_sym, exp, opt, stk))
            if cached is not None:
                return cached

            df = StratX.inst_df

            filtered = df[
                (df["underlying_index_name_normalized"] == mapped_sym) &
                (df["contract_expiration_yyyymmdd"] == exp) &
                (df["strike_price_numeric"] == stk)
            ]

            if opt == "CE":
                filtered = filtered[filtered["option_type_normalized"] == "3"]
            elif opt == "PE":
                filtered = filtered[filtered["option_type_normalized"] == "4"]
            else:
                return None

            if filtered.empty:
                return None

            return str(filtered.iloc[0]["Description"]).strip()
        except Exception as e:
            printt(f"Error in get_otm_description: {e}")
            return None

    def update_stratx_payload_price(self, payload, price):
        try:
            payload_data = json.loads(payload)
            orders = payload_data.get("orders")
            if not orders or not isinstance(orders, list):
                raise ValueError("Missing orders in StratX payload")
            orders[0]["price"] = price
            return json.dumps(payload_data)
        except Exception as e:
            raise RuntimeError(f"Error updating StratX payload price: {e}")

    def recalculate_stratx_http_retry_price(self, order_info):
        try:
            symbol = str(order_info.get("symbol", "")).strip().upper()
            exchange = str(order_info.get("exchange", "")).strip().upper()
            right = str(order_info.get("right", "")).strip().upper()
            side = str(order_info.get("side", "")).strip().upper()
            expiry = str(order_info.get("expiry", "")).strip()
            strike = order_info.get("strike")

            if not symbol or not exchange or not right or not side or not expiry:
                raise ValueError(f"Missing HTTP retry price fields: {order_info}")

            if right == "FUT":
                strike = None
            else:
                strike = float(strike)

            pricing_symbol = self.get_retry_pricing_symbol(symbol)
            description, tick_size = self.get_retry_instrument_details(
                pricing_symbol,
                exchange,
                expiry,
                right,
                strike,
            )
            if not description or tick_size is None:
                raise ValueError(f"HTTP retry instrument details not found | symbol={pricing_symbol} | exchange={exchange} | expiry={expiry} | right={right} | strike={strike}")

            cache_symbol = None
            if right in ("CE", "PE") and strike is not None:
                expiry_ddmmmyy = self.to_ddmmmyy(expiry)
                cache_symbol = self.build_cache_symbol(pricing_symbol, expiry_ddmmmyy, strike, right)

            new_price = self.price_from_avg_ltp_or_fallback(
                side=side,
                tick_size=tick_size,
                description=description,
                cache_symbol=cache_symbol,
            )
            order_info["price"] = new_price
            return new_price
        except Exception as e:
            raise RuntimeError(f"HTTP retry price recalculation failed: {e}")


    def send_stratx_order_request(self, url, headers, payload, order_info):
        request_start_ts = time.perf_counter()
        submitted_ts = order_info.get("submitted_ts")
        order_queue_ms = ((request_start_ts - submitted_ts) * 1000) if submitted_ts else -1.0

        try:
            session = self.get_stratx_session()
            current_payload = payload
            response = None
            response_text = ""
            http_ms = -1.0

            for attempt in range(1, StratX.stratx_http_max_attempts + 1):
                attempt_start_ts = time.perf_counter()
                response = session.post(
                    url,
                    headers=headers,
                    data=current_payload,
                    timeout=StratX.stratx_request_timeout
                )

                request_end_ts = time.perf_counter()
                http_ms = (request_end_ts - attempt_start_ts) * 1000
                response_text = response.text

                if response.status_code == 200:
                    break

                printt(f"STRATX_HTTP_RETRY_RESPONSE | attempt={attempt} | max={StratX.stratx_http_max_attempts} | status={response.status_code} | sym={order_info.get('symbol')} | side={order_info.get('side')} | qty={order_info.get('quantity')} | price={order_info.get('price')} | description={order_info.get('description')} | http={http_ms:.1f}ms | response={response_text}")

                if attempt >= StratX.stratx_http_max_attempts:
                    break

                new_price = self.recalculate_stratx_http_retry_price(order_info)
                current_payload = self.update_stratx_payload_price(current_payload, new_price)

                printt(f"STRATX_HTTP_RETRY_REPRICE | next_attempt={attempt + 1} | sym={order_info.get('symbol')} | side={order_info.get('side')} | qty={order_info.get('quantity')} | price={new_price} | description={order_info.get('description')}")

                time.sleep(StratX.stratx_http_retry_sleep)

            try:
                response_json = response.json()
            except Exception as json_error:
                raise RuntimeError(f"Invalid JSON response | status={response.status_code} | body={response_text} | error={json_error}")

            if response.status_code < 200 or response.status_code >= 300:
                raise RuntimeError(f"HTTP error | status={response.status_code} | body={response_text}")

            data = response_json.get("data")
            if not data or not isinstance(data, list):
                raise RuntimeError(f"Missing data in StratX response | status={response.status_code} | body={response_text}")

            reference_id = data[0].get("reference_id")
            if not reference_id:
                raise RuntimeError(f"Missing reference_id in StratX response | status={response.status_code} | body={response_text}")

            printt(f"STRATX_HTTP_SUCCESS | sym={order_info.get('symbol')} | side={order_info.get('side')} | qty={order_info.get('quantity')} | price={order_info.get('price')} | description={order_info.get('description')} | ref_id={reference_id} | order_queue={order_queue_ms:.1f}ms | http={http_ms:.1f}ms | response={response_text}")

            return reference_id

        except Exception as e:
            request_end_ts = time.perf_counter()
            http_ms = (request_end_ts - request_start_ts) * 1000

            raise RuntimeError(f"StratX order request failed | sym={order_info.get('symbol')} | side={order_info.get('side')} | qty={order_info.get('quantity')} | price={order_info.get('price')} | order_queue={order_queue_ms:.1f}ms | http={http_ms:.1f}ms | error={e}")


    def log_stratx_future_result(self, future):
        try:
            reference_id = future.result()
            self.register_reference_root_id(future, reference_id)
            printt(f"STRATX_FUTURE_DONE | ref_id={reference_id}")
        except Exception as e:
            with StratX.retry_state_lock:
                root_order_id = StratX.future_root_ids.pop(future, None)
                net_meta = StratX.future_net_meta.pop(future, None)
            if root_order_id and isinstance(net_meta, dict):
                self.release_stratx_net(
                    root_order_id,
                    net_meta.get("bucket"),
                    net_meta.get("signed_qty"),
                    "http_failed",
                )
            printt(f"STRATX_FUTURE_FAILED | {e}")

    def get_orderbook_row_value(self, row, key, default=None):
        try:
            if isinstance(row, dict):
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

    def is_retryable_orderbook_status(self, row):
        try:
            status = str(self.get_orderbook_row_value(row, "status", "")).strip().upper()
            order_message = str(self.get_orderbook_row_value(row, "order_message", "")).strip().upper()

            if status == "CANCEL":
                return True

            if status == "REJECTED":
                return "PRICE" in order_message and "LPP" in order_message

            return False
        except Exception as e:
            printt(f"STRATX_ORDERBOOK_RETRY_STATUS_CHECK_FAILED | error={e} | row={row}")
            return False

    def is_failed_orderbook_status(self, row):
        try:
            status = str(self.get_orderbook_row_value(row, "status", "")).strip().upper()
            return status in ("REJECTED", "CANCEL", "CANCELLED", "ERROR")
        except Exception:
            return False

    def is_net_orderbook_client(self, client_id):
        try:
            net_client_id = str(getattr(cre, "STRATX_NET_CLIENT_ID", "Y05601")).strip().upper()
            if not net_client_id:
                return False
            return str(client_id).strip().upper() == net_client_id
        except Exception:
            return False

    def get_net_meta_from_orderbook_row(self, row):
        try:
            symbol = self.get_retry_pricing_symbol(self.get_orderbook_row_value(row, "symbol", ""))
            right = str(self.get_orderbook_row_value(row, "right", "")).strip().upper()
            side = str(self.get_orderbook_row_value(row, "buyorsell", "")).strip().upper()
            qty = self.get_orderbook_row_value(row, "quantity", None)

            if symbol == "NIFTY" and right in ("CE", "PE"):
                bucket = f"NIFTY_{right}"
            elif symbol == "SENSEX" and right in ("CE", "PE"):
                bucket = f"SENSEX_{right}"
            else:
                return None

            signed_qty = int(float(qty))
            if side not in ("BUY", "B", "1"):
                signed_qty = -signed_qty

            return {
                "bucket": bucket,
                "signed_qty": signed_qty,
            }
        except Exception as e:
            printt(f"STRATX_NET_META_FROM_ORDERBOOK_FAILED | error={e}")
            return None

    def get_retry_freeze_quantity(self, symbol):
        normalized_symbol = str(symbol).strip().upper()
        if normalized_symbol in ("NIFTY", "NIFTY 50"):
            return niftyFreeze
        if normalized_symbol in ("BANKNIFTY", "NIFTY BANK"):
            return bnfFreeze
        if normalized_symbol in ("MIDCPNIFTY", "NIFTY MID SELECT"):
            return midcpniftyFreeze
        if normalized_symbol in ("FINNIFTY", "NIFTY FIN SERVICE"):
            return finniftyFreeze
        if normalized_symbol in ("SENSEX", "BSX"):
            return sensexFreeze
        if normalized_symbol in ("BANKEX", "BKX"):
            return bankex
        return None

    def get_retry_payload_symbol(self, symbol, exchange):
        normalized_symbol = str(symbol).strip().upper()
        normalized_exchange = str(exchange).strip().upper()
        if normalized_exchange == "BSEFO":
            if normalized_symbol == "SENSEX":
                return "BSX"
            if normalized_symbol == "BANKEX":
                return "BKX"
        return normalized_symbol

    def get_retry_pricing_symbol(self, symbol):
        normalized_symbol = str(symbol).strip().upper()
        if normalized_symbol == "BSX":
            return "SENSEX"
        if normalized_symbol == "BKX":
            return "BANKEX"
        return normalized_symbol

    def get_underlying_ltp_for_symbol(self, symbol):
        try:
            normalized_symbol = self.get_retry_pricing_symbol(symbol)

            if normalized_symbol in ("NIFTY", "NIFTY 50"):
                channel = "NIFTY 50"
            elif normalized_symbol == "SENSEX":
                channel = "SENSEX"
            else:
                return None

            tt0 = time.perf_counter()
            cached = StratX.redis_underlying_ltp_cache.get(channel)
            if cached is not None:
                cached_at, cached_result = cached
                if tt0 - cached_at <= StratX.redis_underlying_ltp_cache_ttl:
                    return cached_result

            underlying_ltp = get_underlying_ltp(channel)
            StratX.redis_underlying_ltp_cache[channel] = (time.perf_counter(), underlying_ltp)

            return underlying_ltp
        except Exception as e:
            printt(f"Error in get_underlying_ltp_for_symbol: {e}")
            return None

    def should_skip_itm_order(self, symbol, right, strike):
        try:
            option_type = str(right).strip().upper()
            if option_type not in ("CE", "PE") or strike is None:
                return False

            normalized_symbol = self.get_retry_pricing_symbol(symbol)
            if normalized_symbol not in ("NIFTY", "NIFTY 50", "SENSEX"):
                return False

            underlying_price = self.get_underlying_ltp_for_symbol(normalized_symbol)
            if underlying_price is None:
                printt(f"Skipping ITM check as underlying price not found | symbol={normalized_symbol}")
                return False

            strike_price = float(strike)

            if option_type == "CE" and strike_price < underlying_price:
                printt(
                    f"Skipping Order Placement as strike price is less than underlying price (ITM) "
                    f"for CE {strike_price} < {underlying_price}"
                )
                return True

            if option_type == "PE" and strike_price > underlying_price:
                printt(
                    f"Skipping Order Placement as strike price is greater than underlying price (ITM) "
                    f"for PE {strike_price} > {underlying_price}"
                )
                return True

            return False
        except Exception as e:
            printt(f"Error in ITM check: {e}")
            return False

    def get_retry_instrument_details(self, symbol, exchange, expiry, right, strike):
        try:
            self.load_instrument_master()

            normalized_symbol = self.get_retry_pricing_symbol(symbol)
            normalized_exchange = str(exchange).strip().upper()
            normalized_expiry = str(expiry).strip()
            normalized_right = str(right).strip().upper()
            normalized_strike = None if normalized_right == "FUT" else float(strike)

            cached = StratX.retry_instrument_by_key.get(
                (normalized_exchange, normalized_symbol, normalized_expiry, normalized_right, normalized_strike)
            )
            if cached is not None:
                return cached

            if StratX.inst_df is None:
                return None, None

            if normalized_right == "CE":
                option_type = "3"
            elif normalized_right == "PE":
                option_type = "4"
            elif normalized_right == "FUT":
                option_type = "1"
            else:
                return None, None

            filtered = StratX.inst_df[
                (StratX.inst_df["exchange_segment_normalized"] == normalized_exchange) &
                (StratX.inst_df["name_normalized"] == normalized_symbol) &
                (StratX.inst_df["contract_expiration_yyyymmdd"] == normalized_expiry) &
                (StratX.inst_df["option_type_normalized"] == option_type)
            ]

            if normalized_right != "FUT":
                filtered = filtered[StratX.inst_df.loc[filtered.index, "strike_price_numeric"] == normalized_strike]

            if filtered.empty:
                return None, None

            row = filtered.iloc[0]
            description = str(row["Description"]).strip()
            tick_size = float(row["tick_size_numeric"])
            StratX.retry_instrument_by_key[
                (normalized_exchange, normalized_symbol, normalized_expiry, normalized_right, normalized_strike)
            ] = (description, tick_size)
            return description, tick_size
        except Exception as e:
            printt(f"Error in get_retry_instrument_details: {e}")
            return None, None

    def retry_single_orderbook_row(self, row, root_order_id, client_ids, retry_batch_start_ts=None):
        try:
            url = f"https://{cre.stratX_url}/api/v1/orders/place-order/"
            symbol = str(self.get_orderbook_row_value(row, "symbol", "")).strip().upper()
            exchange = str(self.get_orderbook_row_value(row, "exchange", "")).strip().upper()
            segment = str(self.get_orderbook_row_value(row, "segment", "")).strip().upper()
            right = str(self.get_orderbook_row_value(row, "right", "")).strip().upper()
            side = str(self.get_orderbook_row_value(row, "buyorsell", "")).strip().upper()
            strategy_name = str(self.get_orderbook_row_value(row, "strategy_name", cre.strategy_name)).strip()
            expiry = str(self.get_orderbook_row_value(row, "expiry", "")).strip()

            retry_single_start_ts = time.perf_counter()
            timing_ctx = {
                "worker_dequeue_ts": retry_single_start_ts,
                "broker_entry_ts": retry_single_start_ts,
            }

            if not symbol or not exchange or not segment or not right or not side or not expiry:
                raise ValueError(f"Missing retry row fields: {row}")

            order_meta = self.get_order_meta(root_order_id)
            if not order_meta:
                raise ValueError(f"Original order metadata missing for root_id={root_order_id}")

            quantity = int(float(order_meta.get("quantity", 0)))
            if quantity <= 0:
                raise ValueError(f"Invalid original retry quantity for root_id={root_order_id}: {quantity}")

            strike = self.get_orderbook_row_value(row, "strike", None)
            if right == "FUT":
                strike = None
            else:
                strike = float(strike)

            pricing_symbol = self.get_retry_pricing_symbol(symbol)
            payload_symbol = self.get_retry_payload_symbol(symbol, exchange)
            freez = self.get_retry_freeze_quantity(symbol)
            if freez is None:
                raise ValueError(f"Retry freeze quantity not found for symbol={symbol}")

            description, tick_size = self.get_retry_instrument_details(
                pricing_symbol,
                exchange,
                expiry,
                right,
                strike,
            )
            if not description or tick_size is None:
                raise ValueError(f"Retry instrument details not found | symbol={pricing_symbol} exchange={exchange} expiry={expiry} right={right} strike={strike}")

            cache_symbol = None
            if right in ("CE", "PE") and strike is not None:
                expiry_ddmmmyy = self.to_ddmmmyy(expiry)
                cache_symbol = self.build_cache_symbol(pricing_symbol, expiry_ddmmmyy, strike, right)

            _t0 = time.perf_counter()
            price = self.price_from_avg_ltp_or_fallback(
                side=side,
                tick_size=tick_size,
                description=description,
                cache_symbol=cache_symbol,
            )
            timing_ctx["price_calc_ms"] = (time.perf_counter() - _t0) * 1000

            printt(f"STRATX_ORDERBOOK_RETRY_SUBMIT | root_id={root_order_id} | clients={len(client_ids)} | sym={payload_symbol} | side={side} | qty={quantity} | price={price} | description={description} | retry_ref_source={self.get_orderbook_row_value(row, 'reference_id', '')}")

            net_meta = None
            net_client_id = str(getattr(cre, "STRATX_NET_CLIENT_ID", "Y05601")).strip()
            if net_client_id and net_client_id in [str(client_id).strip() for client_id in client_ids]:
                net_meta = self.get_net_meta_from_orderbook_row(row)

            return self.place_stratx_single_order(
                url,
                strategy_name,
                payload_symbol,
                strike,
                expiry,
                side,
                quantity,
                price,
                exchange,
                segment,
                right,
                freez,
                csv_read_ts=retry_batch_start_ts,
                timing_ctx=timing_ctx,
                root_order_id=root_order_id,
                client_ids=client_ids,
                description=description,
                net_meta=net_meta,
            )
        except Exception as e:
            printt(f"STRATX_ORDERBOOK_RETRY_SUBMIT_FAILED | root_id={root_order_id} | error={e}")
            return []

    def get_retry_group_key(self, root_order_id, reference_id, retry_no, row):
        try:
            strike = self.get_orderbook_row_value(row, "strike", "")
            return (
                str(root_order_id),
                str(reference_id),
                int(retry_no),
                str(self.get_orderbook_row_value(row, "symbol", "")).strip().upper(),
                str(self.get_orderbook_row_value(row, "exchange", "")).strip().upper(),
                str(self.get_orderbook_row_value(row, "segment", "")).strip().upper(),
                str(self.get_orderbook_row_value(row, "right", "")).strip().upper(),
                str(self.get_orderbook_row_value(row, "buyorsell", "")).strip().upper(),
                str(self.get_orderbook_row_value(row, "strategy_name", cre.strategy_name)).strip(),
                str(self.get_orderbook_row_value(row, "expiry", "")).strip(),
                "" if strike is None else str(strike).strip(),
            )
        except Exception as e:
            printt(f"STRATX_ORDERBOOK_RETRY_GROUP_KEY_FAILED | error={e} | row={row}")
            return None
    
    def retry_failed_orderbook_orders(self, rows):
        try:
            if not rows:
                return
            if not StratX.retry_state_loaded:
                self.load_retry_state()
            retry_batch_start_ts = time.perf_counter()

            eligible_groups = {}

            for row in rows:
                try:
                    status = str(self.get_orderbook_row_value(row, "status", "")).strip().upper()
                    if not self.is_failed_orderbook_status(row):
                        continue

                    reference_id = str(self.get_orderbook_row_value(row, "reference_id", "")).strip()
                    if not reference_id:
                        continue

                    client_id = str(self.get_orderbook_row_value(row, "client_id", "")).strip()
                    if not client_id:
                        continue

                    should_release_net = False
                    release_reason = ""
                    retryable_status = self.is_retryable_orderbook_status(row)

                    with StratX.retry_state_lock:
                        reference_map = StratX.retry_state.setdefault("reference_id_to_root_id", {})
                        root_order_id = reference_map.get(reference_id)

                        if not root_order_id:
                            continue

                        if not retryable_status:
                            should_release_net = True
                            release_reason = f"orderbook_terminal_{status.lower()}"
                        else:
                            root_state = self.get_retry_root_state(root_order_id)
                            retry_counts = root_state["retry_count_by_client"]
                            processed_refs_by_client = root_state["processed_refs_by_client"]
                            client_processed_refs = processed_refs_by_client.setdefault(client_id, set())

                            if reference_id in client_processed_refs:
                                continue

                            retry_count = int(retry_counts.get(client_id, 0))
                            if retry_count >= StratX.max_orderbook_retries:
                                client_processed_refs.add(reference_id)
                                StratX.retry_state_dirty = True
                                should_release_net = True
                                release_reason = "orderbook_max_retry_reached"
                            else:
                                retry_no = retry_count + 1
                                client_processed_refs.add(reference_id)
                                retry_counts[client_id] = retry_no
                                StratX.retry_state_dirty = True

                    if should_release_net:
                        if self.is_net_orderbook_client(client_id):
                            self.release_stratx_net_from_orderbook(root_order_id, row, release_reason)
                        continue

                    group_key = self.get_retry_group_key(root_order_id, reference_id, retry_no, row)
                    if group_key is None:
                        if self.is_net_orderbook_client(client_id):
                            self.release_stratx_net_from_orderbook(root_order_id, row, "orderbook_retry_group_failed")
                        continue

                    group = eligible_groups.setdefault(
                        group_key,
                        {
                            "row": row,
                            "root_order_id": root_order_id,
                            "client_ids": [],
                            "client_id_set": set(),
                        },
                    )
                    if client_id not in group["client_id_set"]:
                        group["client_ids"].append(client_id)
                        group["client_id_set"].add(client_id)

                except Exception as row_error:
                    printt(f"STRATX_ORDERBOOK_RETRY_ROW_ERROR | ref_id={self.get_orderbook_row_value(row, 'reference_id', '')} | client_id={self.get_orderbook_row_value(row, 'client_id', '')} | error={row_error}")

            for group in eligible_groups.values():
                try:
                    client_ids = group["client_ids"]
                    if not client_ids:
                        continue
                    retry_orders = self.retry_single_orderbook_row(
                        group["row"],
                        group["root_order_id"],
                        client_ids,
                        retry_batch_start_ts,
                    )
                    if not retry_orders:
                        row_client_id = str(self.get_orderbook_row_value(group["row"], "client_id", "")).strip()
                        if self.is_net_orderbook_client(row_client_id):
                            self.release_stratx_net_from_orderbook(
                                group["root_order_id"],
                                group["row"],
                                "orderbook_retry_submit_failed",
                            )
                except Exception as group_error:
                    row_client_id = str(self.get_orderbook_row_value(group.get("row"), "client_id", "")).strip()
                    if self.is_net_orderbook_client(row_client_id):
                        self.release_stratx_net_from_orderbook(
                            group.get("root_order_id"),
                            group.get("row"),
                            "orderbook_retry_group_error",
                        )
                    printt(f"STRATX_ORDERBOOK_RETRY_GROUP_SUBMIT_ERROR | root_id={group.get('root_order_id')} | clients={len(group.get('client_ids', []))} | error={group_error}")

        except Exception as e:
            printt(f"Error in retry_failed_orderbook_orders: {e}")

    def place_stratx_single_order(self, url, strategy_name, symbol, strike, expiry, side, quantity, price, exchange, segment, right, freez, lot_size=None, csv_read_ts=None, timing_ctx=None, root_order_id=None, client_ids=None, description=None, net_meta=None):
        try:
            submitted_future = False
            reserved_net_meta = None
            is_new_root_order = root_order_id is None
            single_order_entry_ts = time.perf_counter()
            if timing_ctx is not None:
                timing_ctx["single_order_enter_ts"] = single_order_entry_ts

            if self.should_skip_itm_order(symbol, right, strike):
                return []

            if is_new_root_order:
                net_allowed, adjusted_quantity, reserved_net_meta = self.reserve_stratx_net(symbol, right, side, quantity, lot_size)

                if not net_allowed:
                    return []

                if adjusted_quantity != quantity:
                    printt(f"STRATX_NET_ORDER_QTY_ADJUSTED | sym={symbol} | right={right} | side={side} | original_qty={quantity} | adjusted_qty={adjusted_quantity}")
                    quantity = adjusted_quantity

                if net_meta is None:
                    net_meta = reserved_net_meta

            payload_client_ids = [] if client_ids is None else list(client_ids)

            payload = json.dumps({
                "id": cre.id,
                "secret_key": cre.secret_key,
                "orders": [
                    {
                        "client_ids": payload_client_ids,
                        "strategy_name": strategy_name,
                        "symbol": symbol,
                        "strike": strike,
                        "expiry": expiry,
                        "buyorsell": side,
                        "producttype": "DELIVERY",
                        "ordertype": "LIMIT",
                        "quantity": quantity,
                        "price": price,
                        "exchange": exchange,
                        "segment": segment,
                        "validity": "DAY",
                        "amoorder": "N",
                        "disclosedquantity": 0,
                        "triggerprice": 0,
                        "lmt_price_inc": 0,
                        "lmt_price_inc_type": "PTS",
                        "lmt_price_attempt": 0,
                        "lmt_price_atmp_sleep": 1000,
                        "lmt_price_alternative": "CANCEL",
                        "sectype": "IND",
                        "right": right,
                        "trigger": "Entry",
                        "quantity_split": freez,
                        "order_action": ""
                    }
                ]
            })

            headers = {'Content-Type': 'application/json'}

            submitted_ts = time.perf_counter()

            if root_order_id is None:
                root_order_id = str(uuid.uuid4())

            self.register_order_meta(root_order_id, {
                "quantity": int(float(quantity)),
                "symbol": symbol,
                "strike": strike,
                "expiry": expiry,
                "side": side,
                "exchange": exchange,
                "segment": segment,
                "right": right,
                "strategy_name": strategy_name,
                "description": description,
            })

            order_info = {
                "client_ids": payload_client_ids,
                "symbol": symbol,
                "side": side,
                "quantity": quantity,
                "price": price,
                "exchange": exchange,
                "segment": segment,
                "strategy_name": strategy_name,
                "strike": strike,
                "expiry": expiry,
                "right": right,
                "description": description,
                "submitted_ts": submitted_ts,
                "root_order_id": root_order_id,
            }

            future = StratX.stratx_order_pool.submit(
                self.send_stratx_order_request,
                url,
                headers,
                payload,
                order_info,
            )

            self.register_future_root_id(future, root_order_id, net_meta)
            future.add_done_callback(self.log_stratx_future_result)
            submitted_future = True

            if csv_read_ts is not None:
                after_submit_ms = (time.perf_counter() - csv_read_ts) * 1000
                ctx = timing_ctx or {}

                worker_dequeue_ts = ctx.get("worker_dequeue_ts")
                broker_entry_ts = ctx.get("broker_entry_ts")
                single_order_enter_ts = ctx.get("single_order_enter_ts")

                queue_ms = (worker_dequeue_ts - csv_read_ts) * 1000 if worker_dequeue_ts else -1.0
                price_ms = ctx.get("price_calc_ms", -1.0)
                e2e_ms = after_submit_ms

                broker_total_ms = (
                    (single_order_enter_ts - broker_entry_ts) * 1000
                    if broker_entry_ts and single_order_enter_ts
                    else -1.0
                )

                broker_prep_ms = broker_total_ms
                if price_ms > 0:
                    broker_prep_ms -= price_ms

                if broker_prep_ms < 0:
                    broker_prep_ms = 0.0

                printt(f"ORDER_SUBMIT_TIMING | sym={symbol} | side={side} | qty={quantity} | price={price} | total={e2e_ms:.1f}ms | queue={queue_ms:.1f}ms | broker_prep={broker_prep_ms:.1f}ms | price_calc={price_ms:.1f}ms")
            else:
                printt(f"ORDER_SUBMIT_TIMING | sym={symbol} | side={side} | qty={quantity} | price={price} | total=-1.0ms | queue=-1.0ms | broker_prep=-1.0ms | price_calc=-1.0ms")

            return [future]

        except Exception as e:
            if reserved_net_meta and not submitted_future:
                try:
                    self.rollback_stratx_net_meta(reserved_net_meta, "stratx_submit_exception")
                except Exception as rollback_error:
                    printt(f"STRATX_NET_SUBMIT_ROLLBACK_FAILED | error={rollback_error}")
            printt(f"Error submitting {exchange} order future: {e}")
            return []


    def placeOrderStratX_NSE(self, name, side, trade, csv_read_ts=None, timing_ctx=None, strategy_name=getattr(cre, "strategy_name", None)):
        try:
            if timing_ctx is not None:
                timing_ctx["broker_entry_ts"] = time.perf_counter()
            url = f"https://{cre.stratX_url}/api/v1/orders/place-order/"

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

            price = float(trade[15])
            if StratX.inst_df is None:
                self.load_instrument_master()
            normalized_name = str(name).strip().upper()

            tick_size = StratX.tick_size_by_name.get(normalized_name)
            lot_size = StratX.lot_size_by_name.get(normalized_name)
            if lot_size is None:
                if normalized_name == "NIFTY":
                    lot_size = 65
                elif normalized_name == "SENSEX":
                    lot_size = 20
                else:
                    raise ValueError(f"Lot size not found for {name}")
            if tick_size is None:
                row = StratX.inst_df.loc[
                    StratX.inst_df["name_normalized"] == normalized_name,
                    "tick_size_numeric"
                ]
                if row.empty:
                    raise ValueError(f"Tick size not found for {name}")
                tick_size = float(row.iat[0])

            description = str(trade[7]).strip()
            inst_type = str(trade[2]).strip().upper()

            cache_symbol = None
            if not inst_type.startswith("FUT"):
                expiry = self.to_ddmmmyy(trade[4])
                right_tmp = str(trade[6]).strip().upper()
                strike_tmp = float(trade[5])
                cache_symbol = self.build_cache_symbol(name, expiry, strike_tmp, right_tmp)

            _t0 = time.perf_counter()
            price = self.price_from_avg_ltp_or_fallback(
                side=side,
                tick_size=tick_size,
                description=description,
                cache_symbol=cache_symbol,
            )
            if timing_ctx is not None:
                timing_ctx["price_calc_ms"] = timing_ctx.get("price_calc_ms", 0.0) + ((time.perf_counter() - _t0) * 1000)
            # price = 0

            inst_type = str(trade[2]).strip().upper()

            if inst_type.startswith("FUT"):
                right = "FUT"
                segment = "NFO-FUT"
                strike = None
            else:
                right = str(trade[6]).strip().upper()  # CE / PE
                segment = "NFO-OPT"
                strike = float(trade[5])

            iids = []
            strategy_key = str(strategy_name).strip().upper()
            qty = int(trade[14] * multiplier)
            expiry_yyyymmdd = self.to_yyyymmdd(trade[4])

            if strategy_key == "VOLATILITY CORE" and right in ("CE", "PE") and strike is not None:
                vol_qty = qty * 2
                iids.extend(self.place_stratx_single_order(
                    url, strategy_name, name, strike, expiry_yyyymmdd, side, vol_qty, price,
                    "NSEFO", segment, right, freez, lot_size, csv_read_ts, timing_ctx, description=description
                ))

                # otm_strike = self.get_otm_strike(name, right, strike, offset=1)
                # if otm_strike is None:
                #     printt(f"VOLATILITYCORE NSE: OTM strike is None | symbol={name} right={right} strike={strike}")
                # else:
                #     expiry_ddmmmyy = self.to_ddmmmyy(trade[4])
                #     otm_cache_symbol = self.build_cache_symbol(name, expiry_ddmmmyy, otm_strike, right)
                #     otm_description = self.get_otm_description(name, expiry_yyyymmdd, right, otm_strike)
                #     if not otm_description:
                #         raise ValueError(f"VOLATILITYCORE NSE: OTM description not found | symbol={name} expiry={expiry_yyyymmdd} right={right} strike={otm_strike}")
                #     _otm_price_t0 = time.perf_counter()
                #     otm_price = self.price_from_avg_ltp_or_fallback(
                #         side=side,
                #         tick_size=tick_size,
                #         description=otm_description,
                #         cache_symbol=otm_cache_symbol,
                #     )
                #     if timing_ctx is not None:
                #         timing_ctx["price_calc_ms"] = timing_ctx.get("price_calc_ms", 0.0) + ((time.perf_counter() - _otm_price_t0) * 1000)
                #     iids.extend(self.place_stratx_single_order(
                #         url, strategy_name, name, otm_strike, expiry_yyyymmdd, side, qty, otm_price,
                #         "NSEFO", "NFO-OPT", right, freez, lot_size, csv_read_ts, timing_ctx, description=otm_description
                #     ))

            elif strategy_key == "IMPULSE CORE" and right in ("CE", "PE") and strike is not None:
                otm_strike = self.get_otm_strike(name, right, strike, offset=self.impulse_offset)
                if otm_strike is None:
                    raise ValueError(f"IMPULSECORE NSE: OTM strike is None | symbol={name} right={right} strike={strike}")

                expiry_ddmmmyy = self.to_ddmmmyy(trade[4])
                otm_cache_symbol = self.build_cache_symbol(name, expiry_ddmmmyy, otm_strike, right)
                otm_description = self.get_otm_description(name, expiry_yyyymmdd, right, otm_strike)
                if not otm_description:
                    raise ValueError(f"IMPULSECORE NSE: OTM description not found | symbol={name} expiry={expiry_yyyymmdd} right={right} strike={otm_strike}")
                _otm_price_t0 = time.perf_counter()
                otm_price = self.price_from_avg_ltp_or_fallback(
                    side=side,
                    tick_size=tick_size,
                    description=otm_description,
                    cache_symbol=otm_cache_symbol,
                )
                if timing_ctx is not None:
                    timing_ctx["price_calc_ms"] = timing_ctx.get("price_calc_ms", 0.0) + ((time.perf_counter() - _otm_price_t0) * 1000)
                iids.extend(self.place_stratx_single_order(
                    url, strategy_name, name, otm_strike, expiry_yyyymmdd, side, qty, otm_price,
                    "NSEFO", "NFO-OPT", right, freez, lot_size, csv_read_ts, timing_ctx, description=otm_description
                ))

            else:
                iids.extend(self.place_stratx_single_order(
                    url, strategy_name, name, strike, expiry_yyyymmdd, side, qty, price,
                    "NSEFO", segment, right, freez, lot_size, csv_read_ts, timing_ctx, description=description
                ))

            return iids

        except Exception as e:
            printt(f"Error placing StratX NSE order: {e}")
            return []


    def placeOrderStratX_BSE(self, name, side, trade, csv_read_ts=None, timing_ctx=None, strategy_name=getattr(cre, "strategy_name", None)):
        try:
            if timing_ctx is not None:
                timing_ctx["broker_entry_ts"] = time.perf_counter()
            global sensexFreeze
            global bankex

            url = f"https://{cre.stratX_url}/api/v1/orders/place-order/"

            exchange_instrument_id = str(trade[4]).strip()
            description = str(trade[5]).strip()

            symbol, strike, expiry, right, tick_size, lot_size = self.get_bse_contract_details(
                exchange_instrument_id, description
            )

            if not symbol:
                return []

            if symbol == 'BANKEX':
                freez = bankex
                name = 'BKX'
            elif symbol == 'SENSEX':
                freez = sensexFreeze
                name = 'BSX'
            else:
                raise ValueError(f"Unknown BSE symbol for freeze qty: {symbol}")
            
            if lot_size is None:
                if symbol == "SENSEX":
                    lot_size = 20
                elif symbol == "NIFTY":
                    lot_size = 65
                else:
                    raise ValueError(f"Lot size not found for {symbol}")

            price = float(trade[8])

            cache_symbol = None
            if right in ("CE", "PE"):
                expiry_ddmmmyy = self.to_ddmmmyy(expiry)
                cache_symbol = self.build_cache_symbol(symbol, expiry_ddmmmyy, strike, right)

            _t0 = time.perf_counter()
            price = self.price_from_avg_ltp_or_fallback(
                side=side,
                tick_size=tick_size,
                description=description,
                cache_symbol=cache_symbol,
            )
            if timing_ctx is not None:
                timing_ctx["price_calc_ms"] = timing_ctx.get("price_calc_ms", 0.0) + ((time.perf_counter() - _t0) * 1000)
            # price = 0

            iids = []

            # Decide segment based on instrument type
            if right == "FUT":
                segment = "BFO-FUT"
            else:
                segment = "BFO-OPT"

            strategy_key = str(strategy_name).strip().upper()
            qty = int(trade[7] * multiplier)

            if strategy_key == "VOLATILITY CORE" and symbol == "SENSEX" and right in ("CE", "PE") and strike is not None:
                vol_qty = qty * 2
                iids.extend(self.place_stratx_single_order(
                    url, strategy_name, name, strike, expiry, side, vol_qty, price,
                    "BSEFO", segment, right, freez, lot_size, csv_read_ts, timing_ctx, description=description
                ))

                # otm_strike = self.get_otm_strike(symbol, right, strike, offset=1)
                # if otm_strike is None:
                #     printt(f"VOLATILITYCORE BSE: OTM strike is None | symbol={symbol} right={right} strike={strike}")
                # else:
                #     expiry_ddmmmyy = self.to_ddmmmyy(expiry)
                #     otm_cache_symbol = self.build_cache_symbol(symbol, expiry_ddmmmyy, otm_strike, right)
                #     otm_description = self.get_otm_description(symbol, expiry, right, otm_strike)
                #     if not otm_description:
                #         raise ValueError(f"VOLATILITYCORE BSE: OTM description not found | symbol={symbol} expiry={expiry} right={right} strike={otm_strike}")
                #     _otm_price_t0 = time.perf_counter()
                #     otm_price = self.price_from_avg_ltp_or_fallback(
                #         side=side,
                #         tick_size=tick_size,
                #         description=otm_description,
                #         cache_symbol=otm_cache_symbol,
                #     )
                #     if timing_ctx is not None:
                #         timing_ctx["price_calc_ms"] = timing_ctx.get("price_calc_ms", 0.0) + ((time.perf_counter() - _otm_price_t0) * 1000)
                #     iids.extend(self.place_stratx_single_order(
                #         url, strategy_name, name, otm_strike, expiry, side, qty, otm_price,
                #         "BSEFO", "BFO-OPT", right, freez, lot_size, csv_read_ts, timing_ctx, description=otm_description
                #     ))

            elif strategy_key == "IMPULSE CORE" and symbol == "SENSEX" and right in ("CE", "PE") and strike is not None:
                otm_strike = self.get_otm_strike(symbol, right, strike, offset=self.impulse_offset)
                if otm_strike is None:
                    raise ValueError(f"IMPULSECORE BSE: OTM strike is None | symbol={symbol} right={right} strike={strike}")

                expiry_ddmmmyy = self.to_ddmmmyy(expiry)
                otm_cache_symbol = self.build_cache_symbol(symbol, expiry_ddmmmyy, otm_strike, right)
                otm_description = self.get_otm_description(symbol, expiry, right, otm_strike)
                if not otm_description:
                    raise ValueError(f"IMPULSECORE BSE: OTM description not found | symbol={symbol} expiry={expiry} right={right} strike={otm_strike}")
                _otm_price_t0 = time.perf_counter()
                otm_price = self.price_from_avg_ltp_or_fallback(
                    side=side,
                    tick_size=tick_size,
                    description=otm_description,
                    cache_symbol=otm_cache_symbol,
                )
                if timing_ctx is not None:
                    timing_ctx["price_calc_ms"] = timing_ctx.get("price_calc_ms", 0.0) + ((time.perf_counter() - _otm_price_t0) * 1000)
                iids.extend(self.place_stratx_single_order(
                    url, strategy_name, name, otm_strike, expiry, side, qty, otm_price,
                    "BSEFO", "BFO-OPT", right, freez, lot_size, csv_read_ts, timing_ctx, description=otm_description
                ))

            else:
                iids.extend(self.place_stratx_single_order(
                    url, strategy_name, name, strike, expiry, side, qty, price,
                    "BSEFO", segment, right, freez, lot_size, csv_read_ts, timing_ctx, description=description
                ))

            return iids

        except Exception as e:
            printt(f"Error placing StratX BSE order: {e}")
            return []


    def getOrderStatus(self, orderId):
        try:
            if not orderId:
                return None

            for i in range(10):
                try:
                    df = pd.read_csv('trades.csv')
                    res = df[df['reference_id'] == orderId].to_dict(orient='records')
                    if res:
                        return res[0]
                    time.sleep(2)
                except Exception as e:
                    printt(f"StratX order status retry {i}: {e}")
                    time.sleep(2)

            printt(f"No order update for orderId {orderId}")
            return None

        except Exception as e:
            printt(f"Error in StratX getOrderStatus: {e}")
            return None


    def getOrderBookALL(self):
        try:
            page_size = 5000
            page_number = 1
            max_pages = 100
            all_data = []

            payload = json.dumps({
                "id": cre.id,
                "secret_key": cre.secret_key,
                "status": ["REJECTED", "CANCEL", "ERROR"]
                })
            headers = {
            'Content-Type': 'application/json'
            }

            while page_number <= max_pages:
                url = f"https://{cre.stratX_url}/api/v1/reports/order/fields/?page_size={page_size}&page_number={page_number}"
                response = requests.request("POST", url, headers=headers, data=payload)
                page_response = response.json()

                if not isinstance(page_response, dict):
                    return page_response

                page_data = page_response.get("data")
                if not isinstance(page_data, list):
                    return page_response

                all_data.extend(page_data)

                if len(page_data) != page_size:
                    page_response["data"] = all_data
                    return page_response

                page_number += 1

            page_response["data"] = all_data
            return page_response

        except Exception as e:
            printt(f"Error in StratX getOrderBookALL: {e}")
            return None
