import json
import requests
import datetime
import os
import time
import pandas as pd
from io import StringIO
import credentials as cre

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
            # df = df.reset_index()
            df.to_csv('abc.csv', index=False)
            df.columns = ['GreekToken', 'ExchangeToken', 'ExchangeSegMent', 'Series/InstType',
            'Symbol', 'Description', 'ExpiryDate', 'OptionType', 'StrikePrice',
            'TickSize', 'LotSize', 'TradingSymbol', 'SymbolWithExpiry']

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


# =========================== STARTX API ==================================

class StartX:

    inst_df = None

    def to_yyyymmdd(self, date_str):
        try:
            return datetime.datetime.strptime(date_str.strip().upper(), "%d%b%Y").strftime("%Y%m%d")
        except Exception as e:
            printt(f"Date conversion error: {e}")
            return None


    def load_instrument_master(self):
        try:
            if StartX.inst_df is None:
                printt("Loading StartX instrument master...")
                df = pd.read_csv(cre.optionInstrumentPath)
                df.columns = df.columns.str.strip()
                df["ExchangeInstrumentID"] = df["ExchangeInstrumentID"].astype(str).str.strip()
                df["Description"] = df["Description"].astype(str).str.strip()
                StartX.inst_df = df
                printt(f"Instrument master loaded: {len(df)} rows")
        except Exception as e:
            printt(f"Error loading instrument master: {e}")


    def get_bse_contract_details(self, exchange_instrument_id, description):
        try:
            self.load_instrument_master()
            df = StartX.inst_df

            row = df[
                (df["ExchangeInstrumentID"] == str(exchange_instrument_id)) &
                (df["Description"] == str(description))
            ]

            if row.empty:
                raise ValueError(f"BSE Instrument not found: {exchange_instrument_id} | {description}")

            row = row.iloc[0]
            strike = float(row["StrikePrice"])
            expiry = pd.to_datetime(row["ContractExpiration"]).strftime("%Y%m%d")

            opt_code = str(row["OptionType"]).strip()
            if opt_code == "3":
                right = "CE"
            elif opt_code == "4":
                right = "PE"
            else:
                raise ValueError(f"Unknown OptionType code: {opt_code}")

            symbol = str(row["UnderlyingIndexName"]).strip().upper()
            return symbol, strike, expiry, right

        except Exception as e:
            printt(f"Error in get_bse_contract_details: {e}")
            return None, None, None, None


    def placeOrderStratX_NSE(self, name, side, trade, strategy_name="PrimeTorque"):
        try:
            url = f"https://{cre.startX_url}/api/v1/orders/place-order/"

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

            producttype = "DELIVERY" 
            iids = []

            payload = json.dumps({
                "id": cre.id,
                "secret_key": cre.secret_key,
                "orders": [
                    {
                        "client_ids": [cre.client_id],
                        "strategy_name": strategy_name,
                        "symbol": name,
                        "strike": float(trade[5]),
                        "expiry": self.to_yyyymmdd(trade[4]),
                        "buyorsell": side,
                        "producttype": producttype,
                        "ordertype": "LIMIT",
                        "quantity": int(trade[14]), 
                        "price": None,
                        "exchange": "NSEFO",
                        "segment": "NFO-OPT",
                        "validity": "DAY",
                        "amoorder": "N",
                        "disclosedquantity": 0,
                        "triggerprice": 0,
                        "lmt_price_inc": 1,
                        "lmt_price_inc_type": "PTS",
                        "lmt_price_attempt": 3,
                        "lmt_price_atmp_sleep": 1000,
                        "lmt_price_alternative": "CANCEL",
                        "sectype": "IND",
                        "right": trade[6], # CE/PE/FUT/EQ
                        "trigger": "Entry",
                        "quantity_split": freez,
                        "order_action": "EXECUTION-WITHOUT-MULTIPLER"
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
            printt(f"Error placing StartX NSE order: {e}")
            return []


    def placeOrderStratX_BSE(self, name, side, trade, strategy_name="PrimeTorque"):
        try:
            global sensexFreeze
            global bankex

            url = f"https://{cre.startX_url}/api/v1/orders/place-order/"

            exchange_instrument_id = str(trade[4]).strip()
            description = str(trade[5]).strip()

            symbol, strike, expiry, right = self.get_bse_contract_details(
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

            producttype = "DELIVERY" 
            iids = []

            payload = json.dumps({
                "id": cre.id,
                "secret_key": cre.secret_key,
                "orders": [
                    {
                        "client_ids": [cre.client_id],
                        "strategy_name": strategy_name,
                        "symbol": name,
                        "strike": strike,
                        "expiry": expiry, 
                        "buyorsell": side,
                        "producttype": producttype,
                        "ordertype": "LIMIT",
                        "quantity": int(trade[7]),
                        "price": price,
                        "exchange": "BSEFO",
                        "segment": "BFO-OPT",
                        "validity": "DAY",
                        "amoorder": "N",
                        "disclosedquantity": 0,
                        "triggerprice": 0,
                        "lmt_price_inc": 1,
                        "lmt_price_inc_type": "PTS",
                        "lmt_price_attempt": 3,
                        "lmt_price_atmp_sleep": 1000,
                        "lmt_price_alternative": "CANCEL",
                        "sectype": "IND",
                        "right": right, # CE/PE/FUT/EQ
                        "trigger": "Entry",
                        "quantity_split": freez,
                        "order_action": "EXECUTION-WITHOUT-MULTIPLER"
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
            printt(f"Error placing StartX BSE order: {e}")
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
                    printt(f"StartX order status retry {i}: {e}")
                    time.sleep(2)

            printt(f"No order update for orderId {orderId}")
            return None

        except Exception as e:
            printt(f"Error in StartX getOrderStatus: {e}")
            return None


    def getOrderBookALL(self):
        try:
            url = f"https://{cre.startX_url}/api/v1/reports/order/fields/?page_size=10&page_number=1"
            payload = json.dumps({
                "id": cre.id,
                "secret_key": cre.secret_key,
                "client_id": cre.client_id,
                })
            headers = {
            'Content-Type': 'application/json'
            }

            for i in range(10):
                try:
                    response = requests.request("POST", url, headers=headers, data=payload)
                    return response.json()
                except Exception as e:
                    printt(f"StartX orderbook retry {i}: {e}")
                    time.sleep(1)

        except Exception as e:
            printt(f"Error in StartX getOrderBookALL: {e}")
            return None