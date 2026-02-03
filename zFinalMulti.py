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

gsobj = HG.greeksoft()

today = datetime.datetime.today().strftime("%m%d")
csvPathNSE = cre.pathNSE.format(formatted_date=today)
csvPathBSE = cre.pathBSE.format(formatted_date=today)

# ================= LICENSE =================
# License validation removed per request.
H.printt("License validation skipped")

# ================= ORDERBOOK THREAD =================
def fetch_order_book():
    while True:
        try:
            book = gsobj.getOrderBookALL()
            pd.DataFrame(book["data"]).to_csv("trades.csv", index=False)
            time.sleep(0.25)
        except:
            time.sleep(1)

threading.Thread(target=fetch_order_book, daemon=True).start()

# ================= QUEUES =================
NSE_QUEUE = Queue(maxsize=4000)
BSE_QUEUE = Queue(maxsize=4000)

# ================= SELF-TRADE SAFE EXECUTION =================
def execute_with_retry(place_fn, args, lot_size):
    for _ in range(3):
        orders = place_fn(*args)
        time.sleep(0.5)

        for o in orders:
            d = gsobj.getOrderStatus(o)
            H.printt(
                f"Symbol:{d.get('symbol')} | "
                f"Status:{d.get('order_status')} | "
                f"Pending:{d.get('pending_qty')}"
            )

            if d.get("errorCode") == 17080:
                args = list(args)
                args[3] = int(d["pending_qty"] / lot_size)
                args[4] = int(d["pending_qty"])
            else:
                return

    H.printt("Self-trade retry failed")

# ================= NSE WORKER =================
def nse_worker():
    while True:
        try:
            t = NSE_QUEUE.get(timeout=1)
            dt = gsobj.getData(t)

            execute_with_retry(
                gsobj.placeOrder,
                [
                    dt.GreekToken,
                    t[13],
                    dt.Symbol,
                    int(t[14] / dt.LotSize),
                    int(t[14]),
                    dt
                ],
                dt.LotSize
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
            t = BSE_QUEUE.get(timeout=1)

            action = 'Buy' if t[6] == 'B' else 'Sell'
            dt = gsobj.getDataBSE(t[4])

            execute_with_retry(
                gsobj.placeOrderBSE,
                [
                    dt.GreekToken,
                    action,
                    dt.Symbol,
                    int(t[7] / dt.LotSize),
                    int(t[7]),
                    dt
                ],
                dt.LotSize
            )

            BSE_QUEUE.task_done()

        except Empty:
            continue
        except Exception as e:
            H.printt(f"BSE Worker Error: {e}")

# ================= START 100 WORKERS =================
NSE_EXECUTOR = ThreadPoolExecutor(max_workers=400)
BSE_EXECUTOR = ThreadPoolExecutor(max_workers=400)

for _ in range(400):
    NSE_EXECUTOR.submit(nse_worker)
    BSE_EXECUTOR.submit(bse_worker)

H.printt("Started 200 NSE workers and 200 BSE workers")

# ================= CSV TRACKERS =================
# nse_seen = 0
# bse_seen = 0
# last_nse = pd.DataFrame()
# last_bse = pd.DataFrame()

# ================= CSV TRACKERS =================
last_nse = pd.DataFrame()
last_bse = pd.DataFrame()

# NSE
if os.path.exists(csvPathNSE):
    try:
        df_init = pd.read_csv(csvPathNSE, header=None, engine="python")
        # df_init = df_init[df_init[17].str.strip() == cre.clientCodeToCopy]
        nse_seen = len(df_init)
        last_nse = df_init
        H.printt(f"NSE copy starts from row {nse_seen}")
    except:
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
        H.printt(f"BSE copy starts from row {bse_seen}")
    except:
        bse_seen = 0
else:
    bse_seen = 0


# ================= MAIN PRODUCER LOOP =================
while True:
    try:
        # -------- NSE --------
        if os.path.exists(csvPathNSE):
            try:
                df = pd.read_csv(csvPathNSE, header=None, engine="python")
                # df = df[df[17].str.strip() == cre.clientCodeToCopy]
                last_nse = df
            except:
                df = last_nse

            if len(df) > nse_seen:
                for _, row in df.iloc[nse_seen:].iterrows():
                    NSE_QUEUE.put(row)
                nse_seen = len(df)

        # -------- BSE --------
        if os.path.exists(csvPathBSE):
            try:
                df = pd.read_csv(csvPathBSE, sep="|", header=None)
                # df = df[df[9].str.strip() == cre.clientCodeToCopy]
                last_bse = df
            except:
                df = last_bse

            if len(df) > bse_seen:
                for _, row in df.iloc[bse_seen:].iterrows():
                    BSE_QUEUE.put(row)
                bse_seen = len(df)

        # -------- HEALTH LOG --------
        if NSE_QUEUE.qsize() > 200 or BSE_QUEUE.qsize() > 200:
            H.printt(
                f"Queue Load | NSE:{NSE_QUEUE.qsize()} | BSE:{BSE_QUEUE.qsize()}"
            )

        time.sleep(0.25)

    except Exception as e:
        H.printt(f"Main Loop Error: {e}")
        time.sleep(1)
