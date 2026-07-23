import json
import requests
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
            return build_cache_symbol(
                dt.Symbol,
                expiry,
                dt.StrikePrice,
                dt.OptionType,
            )
        except Exception as e:
            printt(f"GREEK_PRICE_CACHE_SYMBOL_FAILED | error={e}")
            return None


    def get_greek_order_price(self, dt, side, cache_symbol):
        try:
            if not cache_symbol:
                printt("GREEK_PRICE_FALLBACK | reason=missing_cache_symbol")
                return 0

            normalized_side = self.normalize_order_side(side)
            price = price_from_avg_ltp_or_fallback(
                normalized_side,
                float(dt.TickSize),
                cache_symbol,
            )
            if price <= 0:
                printt(f"GREEK_PRICE_FALLBACK | symbol={cache_symbol} | reason=pricing_unavailable")
                return 0

            return price
        except Exception as e:
            printt(f"GREEK_PRICE_FALLBACK | symbol={cache_symbol} | error={e}")
            return 0


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
            cache_symbol = self.build_greek_cache_symbol(dt)

            idds = []

            for i in range(len(quas)):
                qua = quas[i]
                lot = lots[i]

                for i in range(1):
                    try:
                        wait_for_greek_order_slot()
                        order_price = self.get_greek_order_price(dt, side, cache_symbol)
                        if order_price > 0:
                            order_type = "1"
                            payload_price = str(order_price)
                        else:
                            order_type = "2"
                            payload_price = "0"

                        # Request body
                        data = {
                            "request": {
                                "data": {
                                "trigger_price": "0",
                                "gtoken": str(gtoken),
                                "side": str(si),
                                "gcid": self.gcid,
                                "validity": "0",
                                "price": payload_price,
                                "exchange": "BSE",
                                "disclosed_qty": "0",
                                "tradeSymbol": str(name.upper()),
                                "lot": str(lot),
                                "order_type": order_type,
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

                        response = requests.post(url, json=data, headers=headers)
                        d = response.json()
                        printt(f"{d['response']['svcName']} , {d['response']['data']['gscid']} , {d['response']['data']['gorderid']} , price={payload_price} , order_type={order_type}")
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
            cache_symbol = self.build_greek_cache_symbol(dt)

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
                        wait_for_greek_order_slot()
                        order_price = self.get_greek_order_price(dt, side, cache_symbol)
                        if order_price > 0:
                            order_type = "1"
                            payload_price = str(order_price)
                        else:
                            order_type = "2"
                            payload_price = "0"

                    # Request body
                        data = {
                            "request": {
                                "data": {
                                "trigger_price": "0",
                                "gtoken": str(gtoken),
                                "side": str(side),
                                "gcid": self.gcid,
                                "validity": "0",
                                "price": payload_price,
                                "exchange": "NSE",
                                "disclosed_qty": "0",
                                "tradeSymbol": str(name.upper()),
                                "lot": str(lot),
                                "order_type": order_type,
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

                        response = requests.post(url, json=data, headers=headers)
                        d = response.json()
                        printt(f"{d['response']['svcName']} , {d['response']['data']['gscid']} , {d['response']['data']['gorderid']} , price={payload_price} , order_type={order_type}")
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
