import json
import requests
import datetime
import os
import time
import pandas as pd
from io import StringIO
import credentials as cre
import threading
from collections import deque
from fetch_circuit import get_exchange_instrument_id, get_circuit_limits, get_redis_client

urll = cre.urll
username = cre.username
pw = cre.pw
multiplier = cre.multiplier
authurl = cre.authurl

niftyFreeze = cre.niftyFreeze
bnfFreeze = cre.bnfFreeze
sensexFreeze = cre.sensexFreeze
bankex = cre.bankex
midcpniftyFreeze = cre.midcpnifty
finniftyFreeze = cre.finnifty

iprocli = cre.iprocli
AccountNumber = cre.AccountNumber

# =========================== COMMON FUNCTIONS ==================================
greek_rate_lock = threading.Lock()
greek_order_timestamps = deque()
MAX_GREEK_ORDERS_PER_SEC = 9


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
    timestamp = datetime.datetime.now().strftime("[%H:%M:%S] :")
    print(timestamp, *args, **kwargs)
    saveInLogFile(*args, **kwargs)

def saveInLogFile(*args, **kwargs):
    try:
        timestamp = datetime.datetime.now().strftime("[%H:%M:%S] :")
        today = datetime.datetime.now().strftime("%d_%m_%y")
        file_path = f'logs/{today}.txt'
        args_str = ' '.join(map(str, args))
        kwargs_str = ' '.join(f'{k}={v}' for k, v in kwargs.items())
        content = f'{timestamp} {args_str} {kwargs_str}'
        with open(file_path, 'a') as file:
            file.write(content + '\n')
    except Exception as e:
        pass

def createLogFile():
    try:
        today = datetime.datetime.now().strftime("%d_%m_%y")
        directory = 'logs'
        filename = f'{today}.txt'
        # Ensure the directory exists
        if not os.path.exists(directory):
            os.makedirs(directory)
        
        # Full path to the file
        filepath = os.path.join(directory, filename)
        
        if not os.path.isfile(filepath):
            # Create a blank file
            with open(filepath, 'w') as file:
                pass
            printt(f"Created blank file: {filepath}")
        else:
            printt(f"File already exists: {filepath}")
    except Exception as e:
        printt(f"Error in createLogFile: {e}")

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
        offset = 8

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
    market_order_offset = 8

    def to_yyyymmdd(self, date_str):
        try:
            return datetime.datetime.strptime(date_str.strip().upper(), "%d%b%Y").strftime("%Y%m%d")
        except Exception as e:
            printt(f"Date conversion error: {e}")
            return None


    def load_instrument_master(self):
        try:
            if StratX.inst_df is None:
                printt("Loading StratX instrument master...")
                df = pd.read_csv(cre.optionInstrumentPath)
                df.columns = df.columns.str.strip()
                df["ExchangeInstrumentID"] = df["ExchangeInstrumentID"].astype(str).str.strip()
                df["Description"] = df["Description"].astype(str).str.strip()
                StratX.inst_df = df
                printt(f"Instrument master loaded: {len(df)} rows")
        except Exception as e:
            printt(f"Error loading instrument master: {e}")


    def get_bse_contract_details(self, exchange_instrument_id, description):
        try:
            self.load_instrument_master()
            df = StratX.inst_df

            row = df[
                (df["ExchangeInstrumentID"] == str(exchange_instrument_id)) &
                (df["Description"] == str(description))
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
            return symbol, strike, expiry, right, tick_size

        except Exception as e:
            printt(f"Error in get_bse_contract_details: {e}")
            return None, None, None, None, None


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
            client = get_redis_client()
            pattern = f"cache:{cache_symbol}:*"
            keys = client.keys(pattern)
            if not keys:
                return None, None

            latest_key = max(keys, key=lambda k: int(k.split(":")[-1]))
            data_list = client.lrange(latest_key, 0, -1)
            if not data_list:
                return None, None

            last_item = json.loads(data_list[-1])
            payload = last_item.get("payload", {})
            ltp = payload.get("LTP")
            avg = payload.get("avg")

            if ltp is None or avg is None:
                return None, None

            return float(ltp), float(avg)
        except Exception as e:
            printt(f"Redis tick read error ({cache_symbol}): {e}")
            return None, None


    def price_from_avg_ltp_or_fallback(self, side, base_price, tick_size, description, cache_symbol=None):
        try:
            fallback = adjust_price_to_tick(float(base_price), float(tick_size), side, self.market_order_offset)
            fallback = self.apply_circuit_clamp(fallback, description)

            if not cache_symbol:
                return fallback

            ltp, avg = self.get_redis_ltp_avg(cache_symbol)
            if ltp is None and avg is None:
                return fallback

            offset_ltp = None
            if ltp is not None:
                offset_ltp = ltp * (self.market_order_offset / 100)
                if ltp <= 50:
                    offset_ltp = 8

            offset_avg = None
            if avg is not None:
                offset_avg = avg * (self.market_order_offset / 100)
                if avg <= 50:
                    offset_avg = 8

            if avg is None and ltp is not None:
                if str(side).upper() == "BUY":
                    raw = ltp + offset_ltp
                else:
                    raw = max(float(tick_size), ltp - offset_ltp)
            elif ltp is None and avg is not None:
                if str(side).upper() == "BUY":
                    raw = avg + offset_avg
                else:
                    raw = max(float(tick_size), avg - offset_avg)
            elif str(side).upper() == "BUY":
                raw = (ltp + offset_ltp) if (avg + offset_avg <= ltp) else (avg + offset_avg)
            else:
                raw = (ltp - offset_ltp) if (avg - offset_avg >= ltp) else (avg - offset_avg)
                raw = max(float(tick_size), raw)

            price = round_to_tick(raw, float(tick_size))
            price = self.apply_circuit_clamp(price, description)
            return price
        except Exception as e:
            printt(f"Error in price_from_avg_ltp_or_fallback: {e}")
            price = adjust_price_to_tick(float(base_price), float(tick_size), side, self.market_order_offset)
            return self.apply_circuit_clamp(price, description)


    def placeOrderStratX_NSE(self, name, side, trade, strategy_name="Volatility Core"):
        try:
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
            self.load_instrument_master()
            row = StratX.inst_df.loc[StratX.inst_df["Name"].str.upper() == name.upper(),"TickSize"]
            if row.empty:
                raise ValueError(f"Tick size not found for {name}")
            tick_size = float(row.iat[0])

            description = str(trade[7]).strip()
            inst_type = str(trade[2]).strip().upper()

            cache_symbol = None
            if not inst_type.startswith("FUT"):
                expiry = pd.to_datetime(trade[4]).strftime("%d%b%y").upper()
                right_tmp = str(trade[6]).strip().upper()
                strike_tmp = float(trade[5])
                cache_symbol = self.build_cache_symbol(name, expiry, strike_tmp, right_tmp)

            price = self.price_from_avg_ltp_or_fallback(
                side=side,
                base_price=price,
                tick_size=tick_size,
                description=description,
                cache_symbol=cache_symbol
            )
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

            producttype = "DELIVERY" 
            iids = []

            payload = json.dumps({
                "id": cre.id,
                "secret_key": cre.secret_key,
                "orders": [
                    {
                        "client_ids": [],
                        "strategy_name": strategy_name,
                        "symbol": name,
                        "strike": strike,
                        "expiry": self.to_yyyymmdd(trade[4]),
                        "buyorsell": side,
                        "producttype": producttype,
                        "ordertype": "LIMIT",
                        "quantity": int(trade[14]*multiplier), 
                        "price": price,
                        "exchange": "NSEFO",
                        "segment": segment,
                        "validity": "DAY",
                        "amoorder": "N",
                        "disclosedquantity": 0,
                        "triggerprice": 0,
                        # "lmt_price_inc": 1,
                        # "lmt_price_inc_type": "PTS",
                        # "lmt_price_attempt": 3,
                        # "lmt_price_atmp_sleep": 1000,
                        # "lmt_price_alternative": "CANCEL",
                        "sectype": "IND",
                        "right": right, # CE/PE/FUT/EQ
                        "trigger": "Entry",
                        "quantity_split": freez,
                        "order_action": ""
                    }
                ]
            })
            
            headers = {
                'Content-Type': 'application/json'
            }

            try:
                response = requests.request("POST", url, headers=headers, data=payload)
                printt(f"NSE Order Response: {response.text}")
                r = response.json()
                iids.append(r['data'][0]['reference_id'])
            except Exception as e:
                printt(f"Error placing NSE order: {e}")
                return []
            
            return iids

        except Exception as e:
            printt(f"Error placing StratX NSE order: {e}")
            return []


    def placeOrderStratX_BSE(self, name, side, trade, strategy_name="Volatility Core"):
        try:
            global sensexFreeze
            global bankex

            url = f"https://{cre.stratX_url}/api/v1/orders/place-order/"

            exchange_instrument_id = str(trade[4]).strip()
            description = str(trade[5]).strip()

            symbol, strike, expiry, right, tick_size = self.get_bse_contract_details(
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

            price = float(trade[8])

            cache_symbol = None
            if right in ("CE", "PE"):
                expiry_ddmmmyy = pd.to_datetime(expiry, format="%Y%m%d").strftime("%d%b%y").upper()
                cache_symbol = self.build_cache_symbol(symbol, expiry_ddmmmyy, strike, right)

            price = self.price_from_avg_ltp_or_fallback(
                side=side,
                base_price=price,
                tick_size=tick_size,
                description=description,
                cache_symbol=cache_symbol
            )
            # price = 0

            producttype = "DELIVERY" 
            iids = []

            # Decide segment based on instrument type
            if right == "FUT":
                segment = "BFO-FUT"
            else:
                segment = "BFO-OPT"

            payload = json.dumps({
                "id": cre.id,
                "secret_key": cre.secret_key,
                "orders": [
                    {
                        "client_ids": [],
                        "strategy_name": strategy_name,
                        "symbol": name,
                        "strike": strike,
                        "expiry": expiry, 
                        "buyorsell": side,
                        "producttype": producttype,
                        "ordertype": "LIMIT",
                        "quantity": int(trade[7]*multiplier),
                        "price": price,
                        "exchange": "BSEFO",
                        "segment": segment,
                        "validity": "DAY",
                        "amoorder": "N",
                        "disclosedquantity": 0,
                        "triggerprice": 0,
                        # "lmt_price_inc": 1,
                        # "lmt_price_inc_type": "PTS",
                        # "lmt_price_attempt": 3,
                        # "lmt_price_atmp_sleep": 1000,
                        # "lmt_price_alternative": "CANCEL",
                        "sectype": "IND",
                        "right": right, # CE/PE/FUT/EQ
                        "trigger": "Entry",
                        "quantity_split": freez,
                        "order_action": ""
                    }
                ]
            })
            
            headers = {
                'Content-Type': 'application/json'
            }
            
            try:
                response = requests.request("POST", url, headers=headers, data=payload)
                printt(f"BSE Order Response: {response.text}")
                r = response.json()
                iids.append(r['data'][0]['reference_id'])
            except Exception as e:
                printt(f"Error placing BSE order: {e}")
                return []
            
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
            url = f"https://{cre.stratX_url}/api/v1/reports/order/fields/?page_size=1000000"
            payload = json.dumps({
                "id": cre.id,
                "secret_key": cre.secret_key,
                })
            headers = {
            'Content-Type': 'application/json'
            }

            for i in range(10):
                try:
                    response = requests.request("POST", url, headers=headers, data=payload)
                    return response.json()
                except Exception as e:
                    printt(f"StratX orderbook retry {i}: {e}")
                    time.sleep(1)

        except Exception as e:
            printt(f"Error in StratX getOrderBookALL: {e}")
            return None