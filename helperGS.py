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
        # printt("Response:", response)
        return(response.json())
    
    def getInstrument(self):
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
    
    def getData(self,t):
        d = self.df
        filtered_df = d[d['ExpiryDate'].str.contains(t[4], case=False, na=False)]
        filtered_df = filtered_df[filtered_df['Symbol'] == t[3].replace(' ','')]
        filtered_df = filtered_df[filtered_df['StrikePrice'] == float(t[5])]
        filtered_df = filtered_df[filtered_df['OptionType'].str.contains(t[6], case=False, na=False)]
        return(filtered_df.iloc[0])
    
    def getDataBSE(self,t):
        filtered_df = self.df
        filtered_df = filtered_df[filtered_df['ExchangeToken'] == int(t)]
        return(filtered_df.iloc[0])

    def placeOrderBSE(self,gtoken,side,name,lot,qua,dt):
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

    def placeOrder(self,gtoken,side,name,lot,qua,dt):
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


    def getOrderStatus(self,orderId):

        if orderId == 0:
            return('Order Data not avaiable..!')

        for i in range(10):
            try:
                df = pd.read_csv('trades.csv')
                res = df[df['gorderid'] == int(orderId)].to_dict(orient='records')[0]
                return res
            except Exception as e:
                printt('Error Order()_orderStatus :- ',e,i)
                time.sleep(2)
        
    def getOrderBookALL(self):
        
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

def getOrderStatus(orderId):
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

def getFreezeQua(freeze_limit, lot_size, total_quantity):
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