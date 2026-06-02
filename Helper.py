import credentials as cre
import importlib
import pandas as pd
pd.set_option('mode.chained_assignment', None)
import datetime
import time
import json
import mibian
import requests
import concurrent.futures
import threading
import os
from datetime import timedelta
from async_logger import createLogFile as async_create_log_file
from async_logger import printt as async_printt

importlib.reload(cre)
lock = threading.Lock()
lock1 = threading.Lock()

llock = threading.Lock()
llock1 = threading.Lock()

savelock = threading.Lock()

def checkTime(Time):
    while True:
        current_time = datetime.datetime.now().time()
        if current_time >= Time:
            break
        time.sleep(2)

def checkTimeBoth(Time,Time2):
    while True:
        current_time = datetime.datetime.now().time()
        if current_time >= Time:
            return('Main')
        elif current_time >= Time2:
            return('Trailing')
        time.sleep(2)
        
def getATMStrike(obj,index):
    price = obj.indexLTP(index)
    
    if index.lower() == 'banknifty':
        return(round(price / 100) * 100)
    elif index.lower() == 'nifty':
        return(round(price / 50) * 50)
    elif index.lower() == 'finnifty':
        return(round(price / 50) * 50)
    
def removeZeroQuantityTrade(list):
    data = [sub_list for sub_list in list if sub_list[-1] != 0]
    return(data)

def days(date):
    current_date = datetime.datetime.today()
    target_date = datetime.datetime.strptime(date, "%d%b%Y")
    days_left = (target_date - current_date).days +1
    if days_left == 0:
        days_left = 0.5
    return (days_left)

def delta20strikeCE(obj,index,ATMstrike,expiry):
    
    strike = []
    ids = []
    price = []
    delta = []
    
    if index.lower() == 'banknifty':
        
        strike = [ATMstrike + (100* i) for i in range(cre.Delta_Check_Strike)]
        ids = [obj.getSymbol(index,expiry,'ce',i) for i in strike]
        price = [obj.StrikeLTP(i) for i in ids]
        spot_price = obj.indexLTP('banknifty')
        day = days(expiry)
        
            
        for i in range(len(strike)):
            try:
                call_option = mibian.BS([spot_price, strike[i], 3.4, day], callPrice=price[i])
                iv = call_option.impliedVolatility

                call_option = mibian.BS([spot_price, strike[i], 3.4, day], volatility=iv)
                call_delta = int(call_option.callDelta * 100)

                delta.append(call_delta)
            except:
                printt('Price Not Present for delta calulation for strike:-',strike[i])
                delta.append(0)
        closest_index = min(range(len(delta)), key=lambda i: abs(delta[i] - 20))
        printt('Strike CE :- ',strike)
        printt('Price CE :- ',price)
        printt('Delta CE :- ',delta)
        return(ids[closest_index],strike[closest_index])
    
    
    elif index.lower() == 'nifty':
        
        strike = [ATMstrike + (50* i) for i in range(cre.Delta_Check_Strike)]
        ids = [obj.getSymbol(index,expiry,'ce',i) for i in strike]
        price = [obj.StrikeLTP(i) for i in ids]
        spot_price = obj.indexLTP('nifty')
        day = days(expiry)
            
        for i in range(len(strike)):
            try:
                call_option = mibian.BS([spot_price, strike[i], 3.4, day], callPrice=price[i])
                iv = call_option.impliedVolatility

                call_option = mibian.BS([spot_price, strike[i], 3.4, day], volatility=iv)
                call_delta = int(call_option.callDelta * 100)

                delta.append(call_delta)
            except:
                printt('Price Not Present for delta calulation for strike:-',strike[i])
                delta.append(0)
        closest_index = min(range(len(delta)), key=lambda i: abs(delta[i] - 20))
        printt('Strike CE :- ',strike)
        printt('Price CE :- ',price)
        printt('Delta CE :- ',delta)
        return(ids[closest_index],strike[closest_index])
    
    
    elif index.lower() == 'finnifty':
        
        strike = [ATMstrike + (50* i) for i in range(cre.Delta_Check_Strike)]
        ids = [obj.getSymbol(index,expiry,'ce',i) for i in strike]
        price = [obj.StrikeLTP(i) for i in ids]
        spot_price = obj.indexLTP('finnifty')
        day = days(expiry)
        
        for i in range(len(strike)):
            try:
                call_option = mibian.BS([spot_price, strike[i], 3.4, day], callPrice=price[i])
                iv = call_option.impliedVolatility

                call_option = mibian.BS([spot_price, strike[i], 3.4, day], volatility=iv)
                call_delta = int(call_option.callDelta * 100)
                delta.append(call_delta)
            except:
                printt('Price Not Present for delta calulation for strike:-',strike[i])
                delta.append(0)
            
        closest_index = min(range(len(delta)), key=lambda i: abs(delta[i] - 20))
        printt('Strike CE :- ',strike)
        printt('Price CE :- ',price)
        printt('Delta CE :- ',delta)
        return(ids[closest_index],strike[closest_index])
    
    
def delta20strikePE(obj,index,ATMstrike,expiry):
    
    strike = []
    ids = []
    price = []
    delta = []
    
    if index.lower() == 'banknifty':
        
        strike = [ATMstrike - (100* i) for i in range(cre.Delta_Check_Strike)]
        ids = [obj.getSymbol(index,expiry,'pe',i) for i in strike]
        price = [obj.StrikeLTP(i) for i in ids]
        spot_price = obj.indexLTP('banknifty')
        day = days(expiry)
            
        for i in range(len(strike)):
            try:
                
                put_option = mibian.BS([spot_price, strike[i], 3.4, day], putPrice=price[i])
                iv = put_option.impliedVolatility

                put_option = mibian.BS([spot_price, strike[i], 3.4, day], volatility=iv)
                put_delta = int(put_option.putDelta * -100)

                delta.append(put_delta)
            except:
                printt('Price Not Present for delta calulation for strike:-',strike[i])
                delta.append(0)
        closest_index = min(range(len(delta)), key=lambda i: abs(delta[i] - 20))
        printt('Delta PE :- ',delta)
        return(ids[closest_index],strike[closest_index])
    
    
    elif index.lower() == 'nifty':
        
        strike = [ATMstrike - (50* i) for i in range(cre.Delta_Check_Strike)]
        ids = [obj.getSymbol(index,expiry,'pe',i) for i in strike]
        price = [obj.StrikeLTP(i) for i in ids]
        spot_price = obj.indexLTP('nifty')
        day = days(expiry)
            
        for i in range(len(strike)):
            try:
                
                put_option = mibian.BS([spot_price, strike[i], 3.4, day], putPrice=price[i])
                iv = put_option.impliedVolatility

                put_option = mibian.BS([spot_price, strike[i], 3.4, day], volatility=iv)
                put_delta = int(put_option.putDelta * -100)

                delta.append(put_delta)
            except:
                printt('Price Not Present for delta calulation for strike:-',strike[i])
                delta.append(0)
        closest_index = min(range(len(delta)), key=lambda i: abs(delta[i] - 20))
        printt('Delta PE :- ',delta)
        return(ids[closest_index],strike[closest_index])
    
    
    elif index.lower() == 'finnifty':
        strike = [ATMstrike - (50* i) for i in range(cre.Delta_Check_Strike)]
        ids = [obj.getSymbol(index,expiry,'pe',i) for i in strike]
        price = [obj.StrikeLTP(i) for i in ids]
        spot_price = obj.indexLTP('finnifty')
        day = days(expiry)
        
        for i in range(len(strike)):
            try:
                put_option = mibian.BS([spot_price, strike[i], 3.4, day], putPrice=price[i])
                iv = put_option.impliedVolatility

                put_option = mibian.BS([spot_price, strike[i], 3.4, day], volatility=iv)
                put_delta = int(put_option.putDelta * -100)
                delta.append(put_delta)
            except:
                printt('Price Not Present for delta calulation for strike:-',strike[i])
                delta.append(0)
            
        closest_index = min(range(len(delta)), key=lambda i: abs(delta[i] - 20))
        printt('Delta PE :- ',delta)
        return(ids[closest_index],strike[closest_index])

def saveTradesOpenPosition(objOrder,id):
    # Open Position Saved
    tempData = objOrder.orderStatus(int(id))
    dftrade = pd.read_csv("OpenPosition.csv")

    printt(f"{id} :- {tempData['TradingSymbol']}, Status : {tempData['OrderStatus']}, Quantity : {tempData['OrderQuantity']}, Side : {tempData['OrderSide']}")

    data = {'Date': datetime.datetime.now().strftime('%d_%m_%Y %H:%M'),
        'OrderId': int(id),
        'Status': tempData['OrderStatus'],
        'TradingSymbol': tempData['TradingSymbol'],
        'Quantity': tempData['OrderQuantity'],
        'Price': tempData['OrderAverageTradedPrice'],
        'Action': tempData['OrderSide'],
        }
    dftrade.loc[len(dftrade)] = data
    dftrade.to_csv("OpenPosition.csv", index=False)
    saveTradesInBook(tempData)

def saveTradesOpenPositionPaper(sym,qua,pri,act):
    dftrade = pd.read_csv("OpenPositionPaper.csv")

    data = {'Date': datetime.datetime.now().strftime('%d_%m_%Y %H:%M'),
        'OrderId': '----',
        'Status': 'Paper',
        'TradingSymbol': sym,
        'Quantity': qua,
        'Price': pri,
        'Action': act,
        }
    dftrade.loc[len(dftrade)] = data
    dftrade.to_csv("OpenPositionPaper.csv", index=False)

def removeExitTrade(sym):
    nameSym = sym.split()[0]
    df = pd.read_csv('OpenPosition.csv')
    df = df[~df['TradingSymbol'].str.contains(nameSym)]
    df.to_csv('OpenPosition.csv',index=False)

def removeExitTradePaper(sym):
    nameSym = sym.split()[0]
    df = pd.read_csv('OpenPositionPaper.csv')
    df = df[~df['TradingSymbol'].str.contains(nameSym)]
    df.to_csv('OpenPositionPaper.csv',index=False)

def saveTradesInBook(tempData):
    # TradeBook Save
    today = datetime.datetime.now().strftime("%d_%m_%y")
    filee = f"Trades/{today}.csv"
    
    data = {'EntryDateTime': datetime.datetime.now().strftime('%d_%m_%y %H:%M:%S'),
        'OrderID': tempData['AppOrderID'],
        'Status': tempData['OrderStatus'],
        'Token': tempData['ExchangeInstrumentID'],
        'SymbolData': tempData['TradingSymbol'],
        'Quantity': tempData['OrderQuantity'],
        'Price': tempData['OrderAverageTradedPrice'],
        'Action': tempData['OrderSide']
        }
    
    with savelock:
        dftrade = pd.read_csv(filee)
        dftrade.loc[len(dftrade)] = data
        dftrade.to_csv(filee, index=False)

def saveTradesInBookPaper(sym,qua,pri,act):
    # TradeBook Save
    today = datetime.datetime.now().strftime("%d_%m_%y")
    filee = f"TradesPaper/{today}.csv"
    
    dftrade = pd.read_csv(filee)
    
    data = {'EntryDateTime': datetime.datetime.now().strftime('%d_%m_%y %H:%M:%S'),
        'OrderID': '----',
        'Status': 'Paper',
        'SymbolData': sym,
        'Quantity': qua,
        'Price': pri,
        'Action': act
        }
    
    dftrade.loc[len(dftrade)] = data
    dftrade.to_csv(filee, index=False)

def deleteEachTradeSLTPHit():
    waitUnlock(llock,3)
    with llock1:
        return('In Progress')

def errorMsg(msg,*args):
    try:
        pass
        # def to_str(value):
        #     return str(value) if not isinstance(value, str) else value

        # if args:
        #     msg = " ".join([msg] + [to_str(arg) for arg in args])
        # msg = msg.replace('.', '\.')
        # msg = msg.replace('-', '\-')
        # msg = msg.replace('_', '\_')
        # msg = msg.replace('@', '\@')
        # msg = msg.replace('!', '\!')
        # msg = msg.replace('#', '\#')
        # msg = msg.replace('$', '\$')
        # msg = msg.replace('%', '\%')
        # msg = msg.replace('^', '\^')
        # msg = msg.replace('&', '\&')
        # msg = msg.replace('*', '\*')
        # msg = msg.replace(',', '\,') 
        # msg = msg.replace('(', '\(') 
        # msg = msg.replace(')', '\)') 
        # rajesh_url = 'https://api.telegram.org/bot6855681481:AAHJFE1JR9jt5UkEqINA3xIwWgEQu_K5ePM/sendMessage?chat_id=134686027&parse_mode=MarkdownV2&text='+msg
        # arpit_url = 'https://api.telegram.org/bot6855681481:AAHJFE1JR9jt5UkEqINA3xIwWgEQu_K5ePM/sendMessage?chat_id=134686027&parse_mode=MarkdownV2&text='+msg
        # session = requests.Session()
        # response = session.get(rajesh_url)
        # response = session.get(arpit_url)
    except Exception as e:
        printt('Error in sending error telegram msg',e)
    
def msg(msg,*args):
    try:
        pass
        # def to_str(value):
        #     return str(value) if not isinstance(value, str) else value

        # if args:
        #     msg = " ".join([msg] + [to_str(arg) for arg in args])
        # msg = msg.replace('.', '\.')
        # msg = msg.replace('-', '\-')
        # msg = msg.replace('_', '\_')
        # msg = msg.replace('@', '\@')
        # msg = msg.replace('!', '\!')
        # msg = msg.replace('#', '\#')
        # msg = msg.replace('$', '\$')
        # msg = msg.replace('%', '\%')
        # msg = msg.replace('^', '\^')
        # msg = msg.replace('&', '\&')
        # msg = msg.replace('*', '\*')
        # msg = msg.replace(',', '\,')
        # rajesh_url = 'https://api.telegram.org/bot5992337003:AAH_eLFFULZarZiVzQKCHuieyE38wpYG3Pk/sendMessage?chat_id=134686027&parse_mode=MarkdownV2&text='+msg
        # session = requests.Session()
        # response = session.get(rajesh_url)
        #response2 = session.get(arpit_url)
        # arpit_url = 'https://api.telegram.org/bot6227749600:AAHc7zAV7e6SR_TIMVcLQOc_eFOntaiV1ZM/sendMessage?chat_id=6115662292&parse_mode=MarkdownV2&text='+msg
    except Exception as e:
        printt('Error in sending telegram msg',e)

def chatinkMsg(msg,*args):
    try:
        pass
        # def to_str(value):
        #     return str(value) if not isinstance(value, str) else value

        # if args:
        #     msg = " ".join([msg] + [to_str(arg) for arg in args])
        # msg = msg.replace('.', '\.')
        # msg = msg.replace('-', '\-')
        # msg = msg.replace('_', '\_')
        # msg = msg.replace('@', '\@')
        # msg = msg.replace('!', '\!')
        # msg = msg.replace('#', '\#')
        # msg = msg.replace('$', '\$')
        # msg = msg.replace('%', '\%')
        # msg = msg.replace('^', '\^')
        # msg = msg.replace('&', '\&')
        # msg = msg.replace('*', '\*')
        # msg = msg.replace(',', '\,')
        # 7181085618:AAHOJSK9RrLcmtm6wiigyiy0903Flxo1uQk
        # rajesh_url = 'https://api.telegram.org/bot7181085618:AAHOJSK9RrLcmtm6wiigyiy0903Flxo1uQk/sendMessage?chat_id=134686027&parse_mode=MarkdownV2&text='+msg
        # session = requests.Session()
        # arpit_url = 'https://api.telegram.org/bot7181085618:AAHOJSK9RrLcmtm6wiigyiy0903Flxo1uQk/sendMessage?chat_id=6115662292&parse_mode=MarkdownV2&text='+msg
        # response = session.get(rajesh_url)
        # response2 = session.get(arpit_url)
    except Exception as e:
        printt('Error in sending telegram msg',e)

def tallyMsg(msg,*args):
    try:
        pass
        # def to_str(value):
        #     return str(value) if not isinstance(value, str) else value

        # if args:
        #     msg = " ".join([msg] + [to_str(arg) for arg in args])
        # msg = msg.replace('.', '\.')
        # msg = msg.replace('-', '\-')
        # msg = msg.replace('_', '\_')
        # msg = msg.replace('@', '\@')
        # msg = msg.replace('!', '\!')
        # msg = msg.replace('#', '\#')
        # msg = msg.replace('$', '\$')
        # msg = msg.replace('%', '\%')
        # msg = msg.replace('^', '\^')
        # msg = msg.replace('&', '\&')
        # msg = msg.replace('*', '\*')
        # msg = msg.replace(',', '\,')
        # rajesh_url = 'https://api.telegram.org/bot6805976384:AAHVp84WrvjmcS-9gxrXrS9S_IDLlOwusS8/sendMessage?chat_id=134686027&parse_mode=MarkdownV2&text='+msg
        # session = requests.Session()
        # arpit_url = 'https://api.telegram.org/bot6805976384:AAHVp84WrvjmcS-9gxrXrS9S_IDLlOwusS8/sendMessage?chat_id=6115662292&parse_mode=MarkdownV2&text='+msg
        # response = session.get(rajesh_url)
        # response2 = session.get(arpit_url)
    except Exception as e:
        printt('Error in sending telegram msg',e)
    
def msgss(msg,*args):
    try:
        pass
        # def to_str(value):
        #     return str(value) if not isinstance(value, str) else value

        # if args:
        #     msg = " ".join([msg] + [to_str(arg) for arg in args])
        # msg = msg.replace('.', '\.')
        # msg = msg.replace('-', '\-')
        # msg = msg.replace('_', '\_')
        # msg = msg.replace('@', '\@')
        # msg = msg.replace('!', '\!')
        # msg = msg.replace('#', '\#')
        # msg = msg.replace('$', '\$')
        # msg = msg.replace('%', '\%')
        # msg = msg.replace('^', '\^')
        # msg = msg.replace('&', '\&')
        # msg = msg.replace('*', '\*')
        # msg = msg.replace(',', '\,')
        # rajesh_url = 'https://api.telegram.org/bot6545936197:AAHMMvtsTZ_u9wBE8wRCQTx5UUK9G58xn78/sendMessage?chat_id=134686027&parse_mode=MarkdownV2&text='+msg
        # session = requests.Session()
        # response = session.get(rajesh_url)
        #response2 = session.get(arpit_url)
        # arpit_url = 'https://api.telegram.org/bot6545936197:AAHMMvtsTZ_u9wBE8wRCQTx5UUK9G58xn78/sendMessage?chat_id=6115662292&parse_mode=MarkdownV2&text='+msg
    except Exception as e:
        printt('Error in sending telegram msg ss',e)
        
def msgsten(msg,*args):
    try:
        pass
        # def to_str(value):
        #     return str(value) if not isinstance(value, str) else value

        # if args:
        #     msg = " ".join([msg] + [to_str(arg) for arg in args])
        # msg = msg.replace('.', '\.')
        # msg = msg.replace('-', '\-')
        # msg = msg.replace('_', '\_')
        # msg = msg.replace('@', '\@')
        # msg = msg.replace('!', '\!')
        # msg = msg.replace('#', '\#')
        # msg = msg.replace('$', '\$')
        # msg = msg.replace('%', '\%')
        # msg = msg.replace('^', '\^')
        # msg = msg.replace('&', '\&')
        # msg = msg.replace('*', '\*')
        # msg = msg.replace(',', '\,')
        # rajesh_url = 'https://api.telegram.org/bot6201607005:AAES-e2xYwFbKjh9UTXf_px8ikDAP2RunCk/sendMessage?chat_id=134686027&parse_mode=MarkdownV2&text='+msg
        # session = requests.Session()
        # response = session.get(rajesh_url)
        #response2 = session.get(arpit_url)
        # arpit_url = 'https://api.telegram.org/bot6201607005:AAES-e2xYwFbKjh9UTXf_px8ikDAP2RunCk/sendMessage?chat_id=6115662292&parse_mode=MarkdownV2&text='+msg
    except Exception as e:
        printt('Error in sending telegram msg s10',e)

def printt(*args, **kwargs):
    async_printt(*args, **kwargs)

def saveInLogFile(*args, **kwargs):
    async_printt(*args, **kwargs)

def read_file_to_string(filename):
    with open(filename, 'r') as file:
        content = file.read()
    return content

def combineQuantity(quantity,id):
    df = pd.DataFrame({'id': id, 'quantity': quantity})
    grouped_df = df.groupby('id')['quantity'].sum().reset_index()
    unique_ids = grouped_df['id'].tolist()
    unique_quantities = grouped_df['quantity'].tolist()
    return(unique_quantities,unique_ids)

def waitUnlock(lock,time):
    for i in range(30):
        if lock.locked():
            time.sleep(time)
        else:
            break

def saveOrderId(orderId,unique):
    with lock:
        waitUnlock(lock1,1)
        try:
            data = {'Time': datetime.datetime.now().strftime('%H:%M:%S'),
                'OrderID': orderId,
                'Status': '--',
                'ExcID': '--',
                'TradingSymbol': '--',
                'SymbolData': '--',
                'Price': '--',
                'Quantity': '--',
                'Action': '--'
                }
            
            if unique == 'AlgoS10':
                dftrade = pd.read_csv('Trades/S10.csv')
                dftrade.loc[len(dftrade)] = data
                dftrade.to_csv("Trades/S10.csv", index=False)
            
            elif unique == 'AlgoIndividual':
                dftrade = pd.read_csv('Trades/Individual.csv')
                dftrade.loc[len(dftrade)] = data
                dftrade.to_csv("Trades/Individual.csv", index=False)
                
            elif unique == 'AlgoCombine':
                dftrade = pd.read_csv('Trades/Combine.csv')
                dftrade.loc[len(dftrade)] = data
                dftrade.to_csv("Trades/Combine.csv", index=False)
            
            else:
                printt('OrderId Saving Skip')
                
            printt(datetime.datetime.now().strftime('%H:%M:%S : ')+'OrderID Saved')
        except Exception as e:
            printt('--**--Error in saveOrderId--**--',e)
        
def orderStatusUpdate(algo,objOrder):
    waitUnlock(lock,3)
    with lock1:
        try:
            if algo == 'AlgoS10':
                trade_data = pd.read_csv('Trades/S10.csv')
                
            elif algo == 'AlgoIndividual':
                trade_data = pd.read_csv('Trades/Individual.csv')
                
            elif algo == 'AlgoCombine':
                trade_data = pd.read_csv('Trades/Combine.csv')
                
            else:
                trade_data = pd.DataFrame()
                
            for i in range(len(trade_data)):
                orderData = trade_data.iloc[i]
                if orderData.Status == 'New' or orderData.Status == '--':
                    o = objOrder.orderStatus(orderData.OrderID)
                    trade_data.at[i, 'Status'] = o['OrderStatus']
                    trade_data.at[i, 'ExcID'] = o['ExchangeInstrumentID']
                    trade_data.at[i, 'TradingSymbol'] = o['TradingSymbol'].split()[0]
                    trade_data.at[i, 'SymbolData'] = o['TradingSymbol']
                    trade_data.at[i, 'Price'] = o['OrderAverageTradedPrice']

                    if o['OrderSide'] == 'BUY':
                        trade_data.at[i, 'Quantity'] = int(o['OrderQuantity'])
                    elif o['OrderSide'] == 'SELL':
                        trade_data.at[i, 'Quantity'] = int(o['OrderQuantity']) * -1
                    else:
                        trade_data.at[i, 'Quantity'] = 0

                    trade_data.at[i, 'Action'] = o['OrderSide']
                
            if algo == 'AlgoS10':
                trade_data.to_csv("Trades/S10.csv", index=False)
                
            elif algo == 'AlgoIndividual':
                trade_data.to_csv("Trades/Individual.csv", index=False)
                
            elif algo == 'AlgoCombine':
                trade_data.to_csv("Trades/Combine.csv", index=False)
            
        except Exception as e:
            printt('--**--Error in orderStatusUpdate--**--',e)

def filterqunatity(trades,buyindex,sellindex):
    
    quantity_buy_1 = trades[buyindex][0]
    token_buy_1 = trades[buyindex][1]

    quantity_sell_1 = trades[sellindex][0]
    token_sell_1 = trades[sellindex][1]
    
    my_dict_1 = {}
    for token, quantity in zip(token_buy_1, quantity_buy_1):
        if token in my_dict_1:
            my_dict_1[token] += quantity  
        else:
            my_dict_1[token] = quantity  
    
    my_dict_2 = {}
    quantity_sell_1 = [-value for value in quantity_sell_1]
    for token, quantity in zip(token_sell_1, quantity_sell_1):
        if token in my_dict_2:
            my_dict_2[token] += quantity  
        else:
            my_dict_2[token] = quantity  
            
    merged_dict = my_dict_1.copy()
    for key, value in my_dict_2.items():
        if key in merged_dict:
            merged_dict[key] += value  
        else:
            merged_dict[key] = value  
            
    positive_dict = {}
    negative_dict = {}

    for key, value in merged_dict.items():
        if value > 0:
            positive_dict[key] = value
        elif value < 0:
            negative_dict[key] = value
            
    keys_array_buy = list(positive_dict.keys())
    values_array_buy = list(positive_dict.values())
    buy = [values_array_buy,keys_array_buy]
    
    keys_array_sell = list(negative_dict.keys())
    values_array_sell = list(negative_dict.values())
    values_array_sell = [-value for value in values_array_sell]
    sell = [values_array_sell,keys_array_sell]
    
    return [buy,sell]

def deleteYesTrades(path):
    df = pd.read_csv(path)
    df.drop(df.index, inplace=True)
    df.to_csv(path, index=False)
    printt("Yesterday's Trades Deleted: "+str(path))

def getOpenSym():
    dfOpen = pd.read_csv('OpenPosition.csv')
    openSym = dfOpen['TradingSymbol'].to_list()

    openSymbol = []
    for sy in openSym:
        openSymbol.append(sy.split()[0])
    
    return(openSymbol)

def getOpenSymPaper():
    dfOpen = pd.read_csv('OpenPositionPaper.csv')
    openSym = dfOpen['TradingSymbol'].to_list()

    openSymbol = []
    for sy in openSym:
        openSymbol.append(sy.split()[0])
    
    return(openSymbol)

def createLogFile():
    async_create_log_file()

def createTradebook():
    folder_name = 'Trades'

    today = datetime.datetime.now().strftime("%d_%m_%y")

    try:
        files = os.listdir(folder_name)
        files = [file for file in files if os.path.isfile(os.path.join(folder_name, file))]
        files = [file.replace('.csv', '') for file in files]
    except FileNotFoundError:
        printt(f'The folder {folder_name} does not exist.')

    if today in files:
        printt('TradeBook Present')
        column_headings = ['EntryDateTime','OrderID','Status','Token','SymbolData','Quantity','Price','Action']
        df = pd.DataFrame(columns=column_headings)
        df.to_csv('Trades/'+today+'.csv',index=False)
        printt('TradeBook Erased : '+today+'.csv')
    else:
        printt('Creating TradeBook Trade')
        column_headings = ['EntryDateTime','OrderID','Status','Token','SymbolData','Quantity','Price','Action']
        df = pd.DataFrame(columns=column_headings)
        df.to_csv('Trades/'+today+'.csv',index=False)
        printt('TradeBook Created : '+today+'.csv')

def createTradebookPaper():
    folder_name = 'TradesPaper'

    today = datetime.datetime.now().strftime("%d_%m_%y")

    try:
        files = os.listdir(folder_name)
        files = [file for file in files if os.path.isfile(os.path.join(folder_name, file))]
        files = [file.replace('.csv', '') for file in files]
    except FileNotFoundError:
        printt(f'The folder {folder_name} does not exist.')

    if today in files:
        printt('TradeBook Present')
    else:
        printt('Creating TradeBook Trade')
        column_headings = ['EntryDateTime','OrderID','Status','SymbolData','Quantity','Price','Action']
        df = pd.DataFrame(columns=column_headings)
        df.to_csv('TradesPaper/'+today+'.csv',index=False)
        printt('TradeBook Created : '+today+'.csv')

def getTotalOpen():
    dfOpen = pd.read_csv('OpenPosition.csv')
    return(len(dfOpen))

def getTotalOpenPaper():
    dfOpen = pd.read_csv('OpenPositionPaper.csv')
    return(len(dfOpen))

def cleanSheet(sheet):
    for i in range(4):
        try:
            sheet.range("B7").value = ['','','','',0,'','']
            sheet.range("B8").value = ['','','','',0,'','']
            sheet.range("B9").value = ['','','','',0,'','']
            sheet.range("B10").value = ['','','','',0,'','']

            sheet.range("E15").value = ['','','','']
            sheet.range("E16").value = ['','','','']
            sheet.range("L7").value = ['','']
            sheet.range("L9").value = ['','']

            sheet.range("M3").value = [0]
            sheet.range("M4").value = [0]
            # sheet.range("I17").value = ['']
            sheet.range("E22").value = ['']
            sheet.range("E23").value = ['']

            sheet.range("L16").value = ['Off']
            sheet.range("L23").value = ['Off']

            printt('Sheet Cleanup Done..!')
            return()
        except Exception as e:
            printt(f'Error in cleanSheet : {e}, Retrying')
            time.sleep(2)

def updateDataExcel(sheet,mainCE,mainPE,crossCE,crossPE):
    for i in range(4):
        try:
            sheet.range("F7").value = getAvgPrice(mainCE)
            sheet.range("F8").value = getAvgPrice(mainPE)
            sheet.range("F9").value = getAvgPrice(crossCE)
            sheet.range("F10").value = getAvgPrice(crossPE)
            return()
        except Exception as e:
            printt(f'Error in cleanSheet : {e}, Retrying')
            time.sleep(2)

def checkPriceStraddle(objData,side,tk1,tk2):
    for i in range(4):
        try:
            index = objData.getInstNameByToken(int(tk1))
            if index.lower() == 'sensex' or index.lower() == 'bankex':
                seg1 = 12
            else:
                seg1 = 2

            index2 = objData.getInstNameByToken(int(tk2))
            if index2.lower() == 'sensex' or index2.lower() == 'bankex':
                seg2 = 12
            else:
                seg2 = 2

            response = objData.xtd.get_quote(
                Instruments=[{'exchangeSegment': seg1, 'exchangeInstrumentID': tk1},{'exchangeSegment': seg2, 'exchangeInstrumentID': tk2}],
                xtsMessageCode=1502,
                publishFormat='JSON')
            # print(response)
            
            data = response['result']['listQuotes']
            json_data = json.loads(data[0])
            oneb = json_data['Bids']
            onea = json_data['Asks']

            json_data = json.loads(data[1])
            twob = json_data['Bids']
            twoa = json_data['Asks']

            # print(oneb[0]['Price'],twob[0]['Price'],onea[0]['Price'],twoa[0]['Price'])

            if side.lower() == 'sell':
                return(oneb[0]['Price'] + twob[0]['Price'])
            
            if side.lower() == 'buy':
                return(onea[0]['Price'] + twoa[0]['Price'])
            
        except Exception as e:
            printt(f'Error in checkPriceStraddle : {e}, Retrying')
            time.sleep(2)

def updateData(objData,location,token,side,sheet):
    t = objData.df[objData.df['ExchangeInstrumentID'] == str(token)]
    sheet.range(location).value = [t.iloc[0]['LotSize'],t.iloc[0]['ExchangeInstrumentID'],t.iloc[0]['Description'],side]

def getOpenQua(token):
    for i in range(4):
        try:
            today = datetime.datetime.now().strftime("%d_%m_%y")
            filee = f"Trades/{today}.csv"
            df = pd.read_csv(filee)

            df = df[df['Token'] == token]
            net_quantity = df.apply(lambda row: row['Quantity'] if row['Action'] == 'BUY' else -row['Quantity'], axis=1).sum()
            return(int(net_quantity))
        except Exception as e:
            printt(f'Error in getOpenQua : {e}, Retrying')

def getAvgPrice(token):
    for i in range(4):
        try:
            today = datetime.datetime.now().strftime("%d_%m_%y")
            filee = f"Trades/{today}.csv"
            df = pd.read_csv(filee)

            df = df[df['Token'] == token]
            net_quantity = df.apply(lambda row: row['Quantity'] if row['Action'] == 'BUY' else -row['Quantity'], axis=1).sum()
        
            avg_price = (df.eval('Quantity * Price * (Action == "BUY")').sum() - 
            df.eval('Quantity * Price * (Action == "SELL")').sum()) / net_quantity if net_quantity else 0
            return(int(net_quantity),round(avg_price,2))
        except Exception as e:
            printt(f'Error in getAvgPrice : {e}, Retrying')

def days(date):
    current_date = datetime.datetime.today()
    target_date = datetime.datetime.strptime(date, "%d%b%Y")
    days_left = (target_date - current_date).days +1
    if days_left == 0:
        days_left = 0.5
    return (days_left)

def deltaValue(ce_pe,spot_price,strike,date,price,sheet,maincross):
    # print(ce_pe,spot_price,strike,date,price)
    
    day = days(date)


    if ce_pe.lower() == 'ce':
        call_option = mibian.BS([spot_price, strike, 0, day], callPrice=price)
        iv = call_option.impliedVolatility
        call_option = mibian.BS([spot_price, strike, 0, day], volatility=iv)
        call_delta = round(call_option.callDelta,4)
        call_theta = round(call_option.callTheta,2)
        call_vega = round(call_option.vega,2)
        if maincross.lower() == 'main':
            sheet.range("N7").value = [round(iv,3)]
        elif maincross.lower() == 'cross':
            sheet.range("N9").value = [round(iv,3)]

        return(call_delta,call_theta,call_vega)
    
    if ce_pe.lower() == 'pe':
        put_option = mibian.BS([spot_price, strike, 0, day], putPrice=price)
        iv = put_option.impliedVolatility
        put_option = mibian.BS([spot_price, strike, 0, day], volatility=iv)
        put_delta = round(put_option.putDelta,4)
        put_theta = round(put_option.putTheta,2)
        put_vega = round(put_option.vega,2)
        if maincross.lower() == 'main':
            sheet.range("N8").value = [round(iv,3)]
        elif maincross.lower() == 'cross':
            sheet.range("N10").value = [round(iv,3)]
        return(put_delta,put_theta,put_vega)
    

def greekCal(side1,side2,strike1,exp1,strike2,exp2,liveLTP,sheet):
    # nfLTPindex = liveLTP[4]
    # bnfLTPindex = liveLTP[5]

    # nfLTP = liveLTP[6]
    # bnfLTP = liveLTP[7]
    # 
    # mainIdx =  sheet.range("D3").value

    mainLTP = liveLTP[6]
    crossLTP = liveLTP[7]
    mainLTPidx = liveLTP[4]
    crossLTPidx = liveLTP[5]

    # if mainIdx.lower() == 'nifty':
    #     mainLTP = nfLTP
    #     crossLTP = bnfLTP
    #     mainLTPidx = nfLTPindex
    #     crossLTPidx = bnfLTPindex
    # else:
    #     mainLTP = bnfLTP
    #     crossLTP = nfLTP
    #     mainLTPidx = bnfLTPindex
    #     crossLTPidx = nfLTPindex
    # 
    mainLotOrignal = int(sheet.range("B7").value)
    crossLotOrignal = int(sheet.range("B9").value)

    qua1 = abs(sheet.range("F7").value)
    qua11 = abs(sheet.range("F8").value)
    qua2 = abs(sheet.range("F9").value)
    qua22 = abs(sheet.range("F10").value)

    # print('Qua: ',qua1,qua11,qua2,qua22)

    lots1 = qua1/mainLotOrignal
    lots11 = qua11/mainLotOrignal
    lots2 = qua2/crossLotOrignal
    lots22 = qua22/crossLotOrignal

    delta,theta,vega = deltaValue('ce',mainLTP,strike1,exp1,liveLTP[0],sheet,'main')
    delta1,theta1,vega1 = deltaValue('pe',mainLTP,strike1,exp1,liveLTP[1],sheet,'main')

    if side1.lower() == 'buy':
        delta = abs(delta) * lots1
        theta = abs(theta) * -1 * lots1
        vega = abs(vega) * lots1

        delta1 = abs(delta1) * -1 * lots11
        theta1 = abs(theta1) * -1 * lots11
        vega1 = abs(vega1) * lots11

    elif side1.lower() == 'sell':
        delta = abs(delta) * -1 * lots1
        theta = abs(theta) * lots1
        vega = abs(vega) * -1 * lots1

        delta1 = abs(delta1) * lots11
        theta1 = abs(theta1) * lots11
        vega1 = abs(vega1) * -1 * lots11

    sheet.range("F15").value = ((delta+delta1),theta+theta1,vega+vega1)
    # sheet.range("F15").value = ((delta+delta1)*100,theta+theta1,vega+vega1)
    sheet.range("L7").value = [mainLTPidx,mainLTP]

    delta,theta,vega = deltaValue('ce',crossLTP,strike2,exp2,liveLTP[2],sheet,'cross')
    delta1,theta1,vega1 = deltaValue('pe',crossLTP,strike2,exp2,liveLTP[3],sheet,'cross')

    if side2.lower() == 'buy':
        delta = abs(delta) * lots2
        theta = abs(theta) * -1 * lots2
        vega = abs(vega) * lots2

        delta1 = abs(delta1) * -1 * lots22
        theta1 = abs(theta1) * -1 * lots22
        vega1 = abs(vega1) * lots22

    elif side2.lower() == 'sell':
        delta = abs(delta) * -1 * lots2
        theta = abs(theta) * lots2
        vega = abs(vega) * -1 * lots2

        delta1 = abs(delta1) * lots22
        theta1 = abs(theta1) * lots22
        vega1 = abs(vega1) * -1 * lots22

    # sheet.range("F16").value = ((delta+delta1)*100,theta+theta1,vega+vega1)
    sheet.range("F16").value = ((delta+delta1),theta+theta1,vega+vega1)
    sheet.range("L9").value = [crossLTPidx,crossLTP]

def getAdjQua(side1,side2,strike1,exp1,strike2,exp2,liveLTP,sheet):
    nfLTP = liveLTP[6]
    bnfLTP = liveLTP[7]
    mainIdx =  sheet.range("D3").value
    crossIdx =  sheet.range("D4").value

    mainLTP = liveLTP[6]
    crossLTP = liveLTP[7]

    # if mainIdx.lower() == 'nifty':
    #     mainLTP = nfLTP
    #     crossLTP = bnfLTP
    # else:
    #     mainLTP = bnfLTP
    #     crossLTP = nfLTP
        
    mainLotOrignal = int(sheet.range("B7").value)
    crossLotOrignal = int(sheet.range("B9").value)

    qua1 = abs(sheet.range("F7").value)
    qua11 = abs(sheet.range("F8").value)
    qua2 = abs(sheet.range("F9").value)
    qua22 = abs(sheet.range("F10").value)

    tqua1 = qua1
    tqua11 = qua11
    tqua2 = qua2
    tqua22 = qua22

    ft = round(abs(sheet.range("I19").value))

    if sheet.range("L14").value.lower() == 'main':
        quaa = sheet.range("K27").value
        qua1 = qua1 + quaa
        qua11 = qua11 - quaa

        tqua1 = tqua1 - quaa
        tqua11 = tqua11 + quaa

    elif sheet.range("L14").value.lower() == 'cross':
        quaa = sheet.range("K27").value
        qua2 = qua2 + quaa
        qua22 = qua22 - quaa

        tqua2 = tqua2 - quaa
        tqua22 = tqua22 + quaa

    # print('Qua: ',qua1,qua11,qua2,qua22)

    lots1 = qua1/mainLotOrignal
    lots11 = qua11/mainLotOrignal
    lots2 = qua2/crossLotOrignal
    lots22 = qua22/crossLotOrignal

    # print('Lots :',lots1,lots11,lots2,lots22)


    delta,theta,vega = deltaValue('ce',mainLTP,strike1,exp1,liveLTP[0],sheet,'main')
    delta1,theta1,vega1 = deltaValue('pe',mainLTP,strike1,exp1,liveLTP[1],sheet,'main')
    if side1.lower() == 'buy':
        delta = abs(delta) * lots1
        delta1 = abs(delta1) * -1 * lots11
    elif side1.lower() == 'sell':
        delta = abs(delta) * -1 * lots1
        delta1 = abs(delta1) * lots11
    dl1 = (delta+delta1)
    # print('deltas Main :',delta,delta1)


    delta,theta,vega = deltaValue('ce',crossLTP,strike2,exp2,liveLTP[2],sheet,'cross')
    delta1,theta1,vega1 = deltaValue('pe',crossLTP,strike2,exp2,liveLTP[3],sheet,'cross')
    if side2.lower() == 'buy':
        delta = abs(delta) * lots2
        delta1 = abs(delta1) * -1 * lots22
    elif side2.lower() == 'sell':
        delta = abs(delta) * -1 * lots2
        delta1 = abs(delta1) * lots22

    dl2 = (delta+delta1)
    # print('deltas Cross :',delta,delta1)
    # print('dl2 :',dl2)

    ft2 = (dl1*mainLotOrignal)/sheet.range("L18").value + (dl2*crossLotOrignal)/sheet.range("L19").value

    # print('-::- old:',ft,':: new:',ft2)
    # print('-----')

    if abs(ft2) < abs(ft):
        if sheet.range("L14").value.lower() == 'main':
            return(qua1,qua11)
        elif sheet.range("L14").value.lower() == 'cross':
            return(qua2,qua22)


    elif abs(ft2) > abs(ft):
        if sheet.range("L14").value.lower() == 'main':
            return(tqua1,tqua11)
        elif sheet.range("L14").value.lower() == 'cross':
            return(tqua2,tqua22)
        
def getAction(side1,side2,strike1,exp1,strike2,exp2,liveLTP,sheet):
    q1,q2 = getAdjQua(side1,side2,strike1,exp1,strike2,exp2,liveLTP,sheet)
    printt(f"Final Qua : {q1}, {q2}")

    if sheet.range("L14").value.lower() == 'main':
        oldq1 = abs(sheet.range("F7").value)
        oldq2 = abs(sheet.range("F8").value)

        mainSide = sheet.range("E3").value
        if mainSide.lower() == 'sell':
            return((q1-oldq1)*-1,(q2-oldq2)*-1,sheet.range("C7").value,sheet.range("C8").value)
        else:
            return((q1-oldq1),(q2-oldq2),sheet.range("C7").value,sheet.range("C8").value)

    elif sheet.range("L14").value.lower() == 'cross':
        oldq1 = abs(sheet.range("F9").value)
        oldq2 = abs(sheet.range("F10").value)

        crossSide = sheet.range("E4").value
        if crossSide.lower() == 'sell':
            return((q1-oldq1)*-1,(q2-oldq2)*-1,sheet.range("C9").value,sheet.range("C10").value)
        else:
            return((q1-oldq1),(q2-oldq2),sheet.range("C9").value,sheet.range("C10").value)
        
def adjustPositions(action1,action2,tk1,tk2,objOrder,sheet,mainCE,mainPE,crossCE,crossPE,objData):
    if action1 < 0:
        id = objOrder.sell(objData,int(tk1),abs(int(action1)))
        time.sleep(1)
        tempData = objOrder.orderStatus(int(id))
        printt(f"{id} :- {tempData['TradingSymbol']}, Status : {tempData['OrderStatus']}, Quantity : {tempData['OrderQuantity']}, Side : {tempData['OrderSide']}")
        
        if tempData['OrderStatus'] == 'Cancelled' or tempData['OrderStatus'] == 'Rejected':
            id = objOrder.sell(objData,int(tk1),abs(int(action1)))
            time.sleep(1)
            tempData = objOrder.orderStatus(int(id))
            printt(f"{id} :- {tempData['TradingSymbol']}, Status : {tempData['OrderStatus']}, Quantity : {tempData['OrderQuantity']}, Side : {tempData['OrderSide']}")
            saveTradesInBook(tempData)
        elif tempData['OrderStatus'] != 'Filled':
            time.sleep(1)
            tempData = objOrder.orderStatus(int(id))
            printt(f"{id} :- {tempData['TradingSymbol']}, Status : {tempData['OrderStatus']}, Quantity : {tempData['OrderQuantity']}, Side : {tempData['OrderSide']}")
            printt(f"This is final Status of order, now handle this order manually")
            saveTradesInBook(tempData)
        elif tempData['OrderStatus'] == 'Filled':
            saveTradesInBook(tempData)

    elif action1 > 0:
        id = objOrder.buy(objData,int(tk1),abs(int(action1)))
        time.sleep(1)
        tempData = objOrder.orderStatus(int(id))
        printt(f"{id} :- {tempData['TradingSymbol']}, Status : {tempData['OrderStatus']}, Quantity : {tempData['OrderQuantity']}, Side : {tempData['OrderSide']}")
        
        if tempData['OrderStatus'] == 'Cancelled' or tempData['OrderStatus'] == 'Rejected':
            id = objOrder.buy(objData,int(tk1),abs(int(action1)))
            time.sleep(1)
            tempData = objOrder.orderStatus(int(id))
            printt(f"{id} :- {tempData['TradingSymbol']}, Status : {tempData['OrderStatus']}, Quantity : {tempData['OrderQuantity']}, Side : {tempData['OrderSide']}")
            saveTradesInBook(tempData)
        elif tempData['OrderStatus'] != 'Filled':
            time.sleep(1)
            tempData = objOrder.orderStatus(int(id))
            printt(f"{id} :- {tempData['TradingSymbol']}, Status : {tempData['OrderStatus']}, Quantity : {tempData['OrderQuantity']}, Side : {tempData['OrderSide']}")
            printt(f"This is final Status of order, now handle this order manually")
            saveTradesInBook(tempData)
        elif tempData['OrderStatus'] == 'Filled':
            saveTradesInBook(tempData)

    if action2 < 0:
        id = objOrder.sell(objData,int(tk2),abs(int(action2)))
        time.sleep(1)
        tempData = objOrder.orderStatus(int(id))
        printt(f"{id} :- {tempData['TradingSymbol']}, Status : {tempData['OrderStatus']}, Quantity : {tempData['OrderQuantity']}, Side : {tempData['OrderSide']}")
        
        if tempData['OrderStatus'] == 'Cancelled' or tempData['OrderStatus'] == 'Rejected':
            id = objOrder.sell(objData,int(tk2),abs(int(action2)))
            time.sleep(1)
            tempData = objOrder.orderStatus(int(id))
            printt(f"{id} :- {tempData['TradingSymbol']}, Status : {tempData['OrderStatus']}, Quantity : {tempData['OrderQuantity']}, Side : {tempData['OrderSide']}")
            saveTradesInBook(tempData)
        elif tempData['OrderStatus'] != 'Filled':
            time.sleep(1)
            tempData = objOrder.orderStatus(int(id))
            printt(f"{id} :- {tempData['TradingSymbol']}, Status : {tempData['OrderStatus']}, Quantity : {tempData['OrderQuantity']}, Side : {tempData['OrderSide']}")
            printt(f"This is final Status of order, now handle this order manually")
            saveTradesInBook(tempData)
        elif tempData['OrderStatus'] == 'Filled':
            saveTradesInBook(tempData)

    elif action2 > 0:
        id = objOrder.buy(objData,int(tk2),abs(int(action2)))
        time.sleep(1)
        tempData = objOrder.orderStatus(int(id))
        printt(f"{id} :- {tempData['TradingSymbol']}, Status : {tempData['OrderStatus']}, Quantity : {tempData['OrderQuantity']}, Side : {tempData['OrderSide']}")
        
        if tempData['OrderStatus'] == 'Cancelled' or tempData['OrderStatus'] == 'Rejected':
            id = objOrder.buy(objData,int(tk2),abs(int(action2)))
            time.sleep(1)
            tempData = objOrder.orderStatus(int(id))
            printt(f"{id} :- {tempData['TradingSymbol']}, Status : {tempData['OrderStatus']}, Quantity : {tempData['OrderQuantity']}, Side : {tempData['OrderSide']}")
            saveTradesInBook(tempData)
        elif tempData['OrderStatus'] != 'Filled':
            time.sleep(1)
            tempData = objOrder.orderStatus(int(id))
            printt(f"{id} :- {tempData['TradingSymbol']}, Status : {tempData['OrderStatus']}, Quantity : {tempData['OrderQuantity']}, Side : {tempData['OrderSide']}")
            printt(f"This is final Status of order, now handle this order manually")
            saveTradesInBook(tempData)
        elif tempData['OrderStatus'] == 'Filled':
            saveTradesInBook(tempData)

    printt(f'Positions Adjusted')

    updateDataExcel(sheet,mainCE,mainPE,crossCE,crossPE)

def quaArray(quantityPlace,lotsizeplace,sheet):
    sec = int(sheet.range("L21").value)
    q1 = sheet.range(quantityPlace).value
    lotsize = sheet.range(lotsizeplace).value
    interval = sheet.range("L24").value

    interval = sec/interval
    lots = q1/lotsize
    lotsInterval = lots/interval
    ordersQua = [int(lotsInterval)*lotsize] * int(interval)
    ordersQua = ordersQua[:-1]
    last = q1-sum(ordersQua)
    ordersQua.append(last)
    return(ordersQua)

def sqoff(sheet,mainCE,mainPE,crossCE,crossPE,objOrder,objData):
    main1 = quaArray("F7","B7",sheet)
    main2 = quaArray("F8","B8",sheet)
    cross1 = quaArray("F9","B9",sheet)
    cross2 = quaArray("F10","B10",sheet)

    interval = int(sheet.range("L24").value)

    tkn = [int(sheet.range("C7").value),int(sheet.range("C8").value),int(sheet.range("C9").value),int(sheet.range("C10").value)]
    for i in range(len(main1)):
        qua = [int(main1[i]),int(main2[i]),int(cross1[i]),int(cross2[i])]
        for x in range(4):
            tk = tkn[x]
            q = qua[x]

            if q < 0:
                printt('buy')
                id = objOrder.buy(objData,tk,abs(int(q)))
                time.sleep(1)
                tempData = objOrder.orderStatus(int(id))
                printt(f"{id} :- {tempData['TradingSymbol']}, Status : {tempData['OrderStatus']}, Quantity : {tempData['OrderQuantity']}, Side : {tempData['OrderSide']}")
                if tempData['OrderStatus'] == 'Cancelled' or tempData['OrderStatus'] == 'Rejected':
                    id = objOrder.buy(objData,tk,abs(int(q)))
                    time.sleep(1)
                    tempData = objOrder.orderStatus(int(id))
                    printt(f"{id} :- {tempData['TradingSymbol']}, Status : {tempData['OrderStatus']}, Quantity : {tempData['OrderQuantity']}, Side : {tempData['OrderSide']}")
                    saveTradesInBook(tempData)
                elif tempData['OrderStatus'] != 'Filled':
                    time.sleep(1)
                    tempData = objOrder.orderStatus(int(id))
                    printt(f"{id} :- {tempData['TradingSymbol']}, Status : {tempData['OrderStatus']}, Quantity : {tempData['OrderQuantity']}, Side : {tempData['OrderSide']}")
                    printt(f"This is final Status of order, now handle this order manually")
                    saveTradesInBook(tempData)
                elif tempData['OrderStatus'] == 'Filled':
                    saveTradesInBook(tempData)

            elif q > 0:
                printt('sell')
                id = objOrder.sell(objData,tk,abs(int(q)))
                time.sleep(1)
                tempData = objOrder.orderStatus(int(id))
                printt(f"{id} :- {tempData['TradingSymbol']}, Status : {tempData['OrderStatus']}, Quantity : {tempData['OrderQuantity']}, Side : {tempData['OrderSide']}")
                if tempData['OrderStatus'] == 'Cancelled' or tempData['OrderStatus'] == 'Rejected':
                    id = objOrder.sell(objData,tk,abs(int(q)))
                    time.sleep(1)
                    tempData = objOrder.orderStatus(int(id))
                    printt(f"{id} :- {tempData['TradingSymbol']}, Status : {tempData['OrderStatus']}, Quantity : {tempData['OrderQuantity']}, Side : {tempData['OrderSide']}")
                    saveTradesInBook(tempData)
                elif tempData['OrderStatus'] != 'Filled':
                    time.sleep(1)
                    tempData = objOrder.orderStatus(int(id))
                    printt(f"{id} :- {tempData['TradingSymbol']}, Status : {tempData['OrderStatus']}, Quantity : {tempData['OrderQuantity']}, Side : {tempData['OrderSide']}")
                    printt(f"This is final Status of order, now handle this order manually")
                    saveTradesInBook(tempData)
                elif tempData['OrderStatus'] == 'Filled':
                    saveTradesInBook(tempData)

        updateDataExcel(sheet,mainCE,mainPE,crossCE,crossPE)
        printt(f'Waiting for {interval} sec to place next order...!')
        time.sleep(interval)

def shiftPosition():
    start_date = datetime.datetime.today()
    for i in range(1,20):
        dt = (start_date - timedelta(days=i)).strftime("%d_%m_%y")
        try:
            df = pd.read_csv(f'Trades/{dt}.csv')
            if len(df) > 0:
                df.to_csv(f'Trades/{start_date.strftime("%d_%m_%y")}.csv',index=False)
                print('Positions Shifted to today')
                break
        except:
            continue
