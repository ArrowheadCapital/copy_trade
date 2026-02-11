# Copy Trade System Documentation

This document explains how the Copy Trade system works.

The core files are:

- `zFinalMulti.py` (main engine and workflow)
- `helperGS.py` (broker API adapters)
- `credentials.py` (configurations)

`zzEXE.py` is only a GUI wrapper to start `zFinalMulti.py`. As we start `zzEXE.py`, a window opens with a 'Start Algo' button. And as we click it, it calls `zFinalMulti.py` and our copy tade system starts running.

---

## 1) High‑Level Purpose

The system watches two CSV files (NSE and BSE trade files "{mmdd}AUTOTRD.txt") and copies new trades to a selected broker. It supports two brokers:

- `GREEK` (Greeksoft API)
- `STRATX` (StratX API for Motilal)

When a new trade row appears in the input CSV, the system validates it, checks basic rules, and then places an order with the selected broker. It uses multiple worker threads for speed and also tracks order latency.

---

## 2) File Roles

### `zFinalMulti.py`

This is the main runtime script:

- Sets up logging and timing checks.
- Chooses the broker based on `credentials.py`.
- Starts background threads:
  - Order book polling thread (writes `trades.csv`).
  - Worker threads for NSE and BSE queues.
  - Latency monitor thread.
- Continuously reads the NSE/BSE trade files and pushes new rows into the queues.

### `helperGS.py`

This is the broker interface layer. It contains:

- Common utility functions: logging, log file creation, freeze quantity splitting.
- `greeksoft` class: handles authentication, instrument master, and order placement for Greeksoft.
- `StratX` class: handles instrument lookup, StratX order placement and order status.

`zFinalMulti.py` uses these classes to place orders according to broker.

### `credentials.py`

Stores configuration and secret keys:

- Broker selection (`broker`)
- File paths for NSE/BSE input files
- API credentials for StratX or Greeksoft
- Freeze quantity limits
- `multiplier` (applies to quantity)
- StratX instrument master path from `OPTION_INSTRUMENT_CSV`

To change any environment settings, this is the file that needs to be edited.

---

## 3) Main Flow in `zFinalMulti.py`

### 3.1 Startup and Validation

1. Logging is initialized (`logs/<dd_mm_yy>.txt`) and config variables are set.
2. Broker is read from `credentials.py` as `BROKER`.
3. If broker is `STRATX`, a safety check ensures:
   - The current time is after 8:50 AM because the `options_instrument.csv` is updated every day around 8:45 AM.
   - `optionInstrumentPath` exists (instrument master required for StratX).
4. Broker object is created:
   - `HG.greeksoft()` for Greeksoft. In Greeksoft, it initialises, login and get instruments data.
   - `HG.StratX()` for StratX.
5. NSE and BSE file paths are built using today’s date and the `pathNSE`/`pathBSE` templates.

### 3.2 Threads and Queues

The system uses two queues:

- `NSE_QUEUE`
- `BSE_QUEUE`

And three main thread groups:

1. **Order book thread**
   - Calls `brokerObj.getOrderBookALL()` in a loop.
   - Writes the response to `trades.csv`.
   - This file is used later to query order status.
2. **Worker threads**
   - `MAX_WORKERS` threads for NSE and `MAX_WORKERS` for BSE.
   - Each worker pulls a row from its queue and attempts to place the order.
3. **Latency monitor**
   - Every 5 minutes prints average/min/max latency of recent order placements.

### 3.3 Reading Input CSVs

The main loop continuously checks both input files:

- It uses file modification time (`mtime`) to detect changes, only reads the file if `mtime `is updated.
- It reads the full CSV and then only processes rows after the last seen index.
- Each new row is pushed into the appropriate queue.
- Uses `read_csv_safely()` to tolerate partially written files.
- Tracks `nse_seen` and `bse_seen` to prevent double-processing.

### 3.4 Trade Validation and Risk Checks

Before placing an order, each worker does:

1. **Basic validation**
   - Symbol not empty
   - Quantity > 0
   - Strike > 0 (for options)
2. **Symbol whitelist**
   - Only index symbols in `ALLOWED_SYMBOLS` are allowed for NSE.
3. **Market hours check**
   - Only trades during 9:15 AM to 3:30 PM are executed.
4. **Order rate limit**
   - Max 10 orders per second across the whole system.

There are also commented risk checks for:

- Position limits
- Daily loss circuit breaker

They have been kept for future use and not tested yet.

### 3.5 Order Placement and Retry Logic

Orders are placed using `execute_with_retry()`:

- It attempts the order up to 3 times.
- After each placement it checks order status.
- If broker returns self-trade error code `17080`:
  - It adjusts the quantity and retries.
  - For Greeksoft, it uses lot size to correct pending quantities.

### 3.6 Latency Tracking

Each successful order placement records elapsed time in `latency_records`.
Every 5 minutes, the system prints a summary:

- Average latency
- Min latency
- Max latency

---

## 4) Broker Implementations in `helperGS.py`

### 4.1 Common Helpers

These are used by both brokers:

- `printt()` and `saveInLogFile()` for logging.
- `createLogFile()` to ensure daily log file exists.
- `getFreezeQua()` splits a large quantity into smaller chunks based on the exchange freeze limit.

### 4.2 Greeksoft (`greeksoft` class)

This class wraps the Greeksoft REST API. It is responsible for authenticating, loading instruments, and placing orders with proper freeze‑quantity handling. The main steps are:

1. **Session token creation**
   - POST request to `authurl` to generate session token. Done only once when object is initialised.
2. **Login**
   - Login using session token and fetches `gcid`. (This also done on initialisation only)
3. **Instrument master download**
   - Reads a full contract list into `self.df`. (Only on initialisation)
   - This data is later used to map symbols, expiry, strike, and option type into a tradable contract.
4. **Order placement**
   - NSE: `placeOrder()`
   - BSE: `placeOrderBSE()`
   - Quantity is split by exchange freeze limits using `getFreezeQua()`.
   - Each split lot is sent as a separate order.
5. **Order status**
   - Reads `trades.csv` and matches `gorderid`.
6. **Order book**
   - `getOrderBookALL()` pulls order book updates.

#### Greeksoft NSE order (`placeOrder`)

- Input values: Greek token, side, symbol, lot size, quantity, and instrument details (`dt`).
- The symbol decides the freeze limit (`NIFTY`, `BANKNIFTY`, `FINNIFTY`, `MIDCPNIFTY`).
- The request uses exchange `"NSE"`, order type `"2"` (market order), and product `"0"` (DELIVERY).
- Quantity is split based on freeze limits, then orders are sent in parts.

#### Greeksoft BSE order (`placeOrderBSE`)

- Similar to NSE but for BSE contracts.
- Uses exchange `"BSE"` and separate freeze limits (`SENSEX`, `BANKEX`).
- Side is mapped to `1` for Buy and `2` for Sell.

**Important:**

For both NSE and BSE place order, check below for iprocli and account number in credentials.py

iprocli:"0" (for retailer)

iprocli:"1" (for dealer through retailer)

iprocli:"2" (for dealer)

account number (AccountNumber="DUMMY1") is mandaotory for dealer thorugh retailer orders only, else account number should be "" (empty).

### 4.3 StratX (`StratX` class)

This class wraps the StratX REST API. It focuses on building the exact JSON payload required by StratX, mapping contract details, and splitting quantity by freeze limits. The main steps are:

1. **Load instrument master**
   - Reads `OPTION_INSTRUMENT_CSV` (required for BSE).
   - BSE trades depend on instrument lookup to resolve symbol, expiry, strike, and option type.
2. **Order placement**
   - NSE: `placeOrderStratX_NSE()`
   - BSE: `placeOrderStratX_BSE()`
3. **Order status**
   - Reads `trades.csv` and matches `reference_id`.
4. **Order book**
   - `getOrderBookALL()` polls StratX reports API to get order book.

#### StratX NSE order (`placeOrderStratX_NSE`)

- **Exchange** must be `NSEFO`.
- **Segment** must be:
  - `NFO-OPT` for options
  - `NFO-FUT` for futures
- **Product type** must be `DELIVERY`.
- **Right**:
  - `CE` or `PE` for options
  - `FUT` for futures
- **Expiry** is converted to `YYYYMMDD`.
- **Quantity** uses `trade[14] * multiplier`.
- **Price** comes from `trade[15]`.
- **Quantity split** uses freeze limit for the symbol.

#### StratX BSE order (`placeOrderStratX_BSE`)

- **Exchange** must be `BSEFO`.
- **Segment** must be:
  - `BFO-OPT` for options
  - `BFO-FUT` for futures
- **Product type** must be `DELIVERY`.
- For **SENSEX**, the symbol sent must be `BSX`.
- For **BANKEX**, the symbol sent must be `BSX`.
- **Right**:
  - `CE` or `PE` for options
  - `FUT` for futures
- **Expiry**, **strike**, and **right** are resolved from the instrument master using `ExchangeInstrumentID` and `Description`.
- **Quantity** uses `trade[7] * multiplier`.
- **Price** comes from `trade[8]`.
- **Quantity split** uses the freeze limit for the underlying index.

---

## 5) Input CSV Formats

The system reads from two daily files:

- NSE: `pathNSE` (comma-separated)
- BSE: `pathBSE` (pipe-separated)

Only specific column indexes are used:

### NSE columns used

- `t[2]`: Instrument type (`OPTIDX`, `FUTIDX `)
- `t[3]`: Symbol
- `t[4]`: Expiry (string like `14FEB2026`)
- `t[5]`: Strike (for options)
- `t[6]`: Option type (`CE` / `PE`)
- `t[13]`: Side (1 = BUY, else SELL)
- `t[14]`: Quantity
- `t[15]`: Price
- `t[17]`: Client code (commented filter in code)

### BSE columns used

- `t[4]`: Exchange instrument id
- `t[5]`: Description
- `t[6]`: Side flag (`B` or `S`)
- `t[7]`: Quantity
- `t[8]`: Price
- `t[9]`: Client code (commented filter in code)

If the CSV format changes, these indexes must be updated.

---

## 6) Options vs Futures Differences

### NSE

- **Options**
  - `right` is `CE` or `PE`.
  - `segment` is `NFO-OPT`.
  - `strike` is required.
- **Futures**
  - `right` is `FUT`.
  - `segment` is `NFO-FUT`.
  - `strike` is not used.

### BSE

- **Options**
  - `right` is `CE` or `PE`.
  - `segment` is `BFO-OPT`.
  - `strike` is required.
- **Futures**
  - `right` is `FUT`.
  - `segment` is `BFO-FUT`.
  - `strike` is not used.

In all StratX orders:

- `exchange` must be `NSEFO` or `BSEFO` as appropriate.
- `producttype` must be `DELIVERY`.

---

## 7) Configuration in `credentials.py`

Key settings:

- `broker`: `"STRATX"` or `"GREEK"`
- `pathNSE` / `pathBSE`: File path templates with `{formatted_date}` (`pathNSE='C:/AutoOnlineBackup/NSE/FO/{formatted_date}AUTOTRD.txt'`, `pathBSE='C:/AutoOnlineBackup/BSE/FO/{formatted_date}AUTOTRD.txt'`)
- `multiplier`: Multiplies order quantity (default `1`)
- Freeze limits:

  - `niftyFreeze`, `bnfFreeze`, `sensexFreeze`, `bankex`, `midcpnifty`, `finnifty`
- StratX credentials:

  - `id = "DUMMYUSER" `
  - `secret_key = "SECRETKEY@123"`
  - `client_id = "C97263"`
  - `stratX_url = "uatapi.stratx.in"`
- Greeksoft credentials (currently commented in file):

  - `urll = "11.111.11.114:3333"`
  - `username = "TS111"`
  - `pw = "PASSWORD123"`
  - `authurl = "http://greekapi.greeksoft.in:3001"`
  - `iprocli="1"`
  - `AccountNumber="C12345"`
- `optionInstrumentPath`:

  - Comes from `OPTION_INSTRUMENT_CSV` in .env.
  - Required for `STRATX`, especially BSE order placement.

  ---

## 8) Logs and Outputs

- Logs are written to `logs/<dd_mm_yy>.txt`.
- `trades.csv` is continuously rewritten with the broker’s order book.
- Console output is printed with timestamps and also written to logs.

---

## 9) Running the System

1. Run the GUI wrapper:
   - `python zzEXE.py`
2. Click 'Start Algo'

The GUI just starts `zFinalMulti.py` in a background thread and shows logs in a window.

---

## 10) Common Failure Points to Watch

- Missing or wrong `OPTION_INSTRUMENT_CSV` (StratX will fail at startup).
- CSV input files not updating or incorrect formats.
- Wrong broker selection in `credentials.py`.
- Broker API credentials not valid.
- Market closed: trades will be skipped.
