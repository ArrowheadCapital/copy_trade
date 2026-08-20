# Copy Trade

Copy Trade is a Python trade-copying engine. It watches live NSE and BSE trade files, detects new rows, combines related rows, validates each trade, and sends the order to the selected broker.

The project currently supports two broker paths:

* `GREEK`: GreekSoft API order placement, Redis pricing, orderbook polling, failed-order retry, and runtime positive/negative net-limit control.
* `STRATX`: StratX API order placement, pricing, circuit clamping, orderbook polling, client-aware failed-order retry, and runtime positive/negative net-limit control.

This README explains the complete project flow and the important functions in the codebase.

## Repository Structure

| Path | Purpose |
| --- | --- |
| `src/zFinalMulti.py` | Main runtime. Reads CSV files, starts workers, queues trades, polls orderbooks, and dispatches broker orders. |
| `src/zzEXE.py` | Tkinter GUI wrapper. It starts `src/zFinalMulti.py` and owns the final shutdown hooks. |
| `src/helperGS.py` | Compatibility facade that keeps `HG.greeksoft()` and `HG.StratX()` available after broker separation. |
| `src/greeksoft/broker.py` | Complete GreekSoft authentication, precomputed instrument lookup, pooled order placement, pricing, HTTP/orderbook retry, retry/net-state persistence, net-limit control, rate limiting, and orderbook implementation. |
| `src/stratx/broker.py` | Complete existing StratX implementation, including pricing, retry, net state, instrument lookup, and order placement. |
| `src/stratx/stratx_reconciliation.py` | StratX desired-versus-traded comparison, correction lifecycle, and reconciliation-state persistence. |
| `src/utils/broker_helpers.py` | Small set of genuinely shared broker helpers for logging compatibility and price/tick adjustment. |
| `src/utils/order_pricing.py` | Complete shared GreekSoft/StratX cache-symbol, 200 ms Redis cache, offset-price, tick-rounding, circuit-clamp, error-handling, and logging implementation. |
| `src/utils/fetch_circuit.py` | Redis connections, failover, LTP/average reads, underlying LTP, and circuit limits. |
| `src/utils/file_watcher.py` | Watchdog-based immediate source-file change detection. |
| `src/utils/async_logger.py` | Non-blocking runtime logging. |
| `src/utils/Helper.py` | Existing legacy/general helpers used by the runtime for logging and time waits. |
| `scripts/` | Standalone operational and conversion scripts that are not imported by the live runtime. |
| `metrics/` | Offline execution-delay, HTTP-delay, grouping, and comparison utilities. |
| `docs/` | Supporting documentation, including the simulator guide and historical resolved issues. |
| `credentials.py` | User-specific broker, path, quantity, Redis, and strategy configuration. |
| `run.cmd` | Main Windows launcher. Activates the environment and runs the GUI module. |

Runtime-generated paths remain at the repository root so restart and operational behavior does not change:

```text
logs/
Trades/
trades.csv
state.json
stratx_net_state.json
stratx_recon_state.json
greek_state.json
greek_net_state.json
```

The folders use Python 3 namespace-package imports, so empty `__init__.py` files are not required. Launch commands must be run from the repository root using the documented `python -m ...` form.

## Runtime Overview

The normal live entry point is:

```bat
run.cmd
```

`run.cmd` activates `.venv` or `venv`, then runs from the repository root:

```text
python -m src.zzEXE
```

The GUI opens and the Start Algo button runs:

```text
src/zFinalMulti.py
```

The main flow is:

```text
NSE/BSE trade CSV changes
  -> process_nse_csv() / process_bse_csv()
  -> combine rows by exchange order id
  -> enqueue combined row
  -> NSE/BSE worker validates row
  -> selected broker places order
  -> orderbook thread polls broker orderbook
  -> selected broker retry processor handles retryable failed rows
  -> trades.csv is refreshed
```

## Configuration

Broker and account configuration lives in `credentials.py`. Reconciliation timing and rollout controls are kept beside the runtime settings in `src/zFinalMulti.py`.

The most important settings are:

| Setting                                                                                                                                                                     | Meaning                                                                                                                                                                                                                                                                                                                  |
| --------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `broker`                                                                                                                                                                  | Selects`"STRATX"`or`"GREEK"`.                                                                                                                                                                                                                                                                                        |
| `pathNSE`/`pathBSE`                                                                                                                                                     | Daily source trade-file templates. They must contain`{formatted_date}`.                                                                                                                                                                                                                                                |
| `multiplier`                                                                                                                                                              | Multiplies copied order quantity. Default is`1`.                                                                                                                                                                                                                                                                       |
| `copy_source_id`                                                                                                                                                          | Source id allowed for copied rows. NSE and BSE rows with a different source id are skipped before combining.                                                                                                                                                                                                            |
| `source_strategy_names`                                                                                                                                                   | List of source strategy names allowed for copied NSE and BSE rows.                                                                                                                                                                                                                                                       |
| `niftyFreeze`,`bnfFreeze`,`sensexFreeze`,`bankex`,`midcpnifty`,`finnifty`                                                                                       | Freeze quantity limits used while placing/splitting orders.                                                                                                                                                                                                                                                              |
| `optionInstrumentPath`                                                                                                                                                    | StratX instrument CSV path, loaded from`OPTION_INSTRUMENT_CSV`in`.env`.                                                                                                                                                                                                                                              |
| `strategy_name`                                                                                                                                                           | Strategy name sent in StratX payload. Strategy-specific OTM logic also uses this value.                                                                                                                                                                                                                                  |
| StratX Expiry Mode dropdown                                                                                                                                               | StratX Impulse Core offset mode in the GUI. Default `Non Expiry` uses offset `0`; `Expiry` uses offset `1`.                                                                                                                                                                                                            |
| `NIFTY_CE_POS_NET`,`NIFTY_CE_NEG_NET`,`NIFTY_PE_POS_NET`,`NIFTY_PE_NEG_NET`,`SENSEX_CE_POS_NET`,`SENSEX_CE_NEG_NET`,`SENSEX_PE_POS_NET`,`SENSEX_PE_NEG_NET` | Shared GreekSoft/StratX positive-side and negative-side net quantity limits. BUY increases net toward the positive limit. SELL decreases net toward the negative limit. If full quantity crosses the relevant side limit, the order may be reduced to the maximum valid lot-multiple quantity. |
| `STRATX_NET_CLIENT_ID`                                                                                                                                                    | Client id used for StratX orderbook rollback, default`Y05601`.                                                                                                                                                                                                                                                         |

### Input Files

```python
pathNSE = 'C:/AutoOnlineBackup/NSE/FO/{formatted_date}AUTOTRD.txt'
pathBSE = 'C:/AutoOnlineBackup/BSE/FO/{formatted_date}AUTOTRD.txt'
```

`src/zFinalMulti.py` fills `{formatted_date}` with:

```python
datetime.datetime.today().strftime("%m%d")
```

For example, on June 2 the file name date part is `0602`.

NSE files are comma-separated. BSE files are pipe-separated. Each exchange's first row is validated once against its exact expected header. A mismatch disables copying for that exchange for the current run. After validation, the header is skipped and existing positional trade-row processing continues unchanged.

### Copy Source Filter

Rows are filtered before grouping/combining.

The allowed source id and source strategy names are configured in `credentials.py`:

```python
copy_source_id = "TS739"
source_strategy_names = ["GREEKSOFT"]
```

The allowed row delay is configured in `.env`:

```env
COPY_ALLOWED_DELAY_SECONDS = 120
```

A row is copied only when its source id matches `copy_source_id`, its strategy matches one value in `source_strategy_names`, and the difference between current system time and row time is less than or equal to `COPY_ALLOWED_DELAY_SECONDS`. Source strategy comparison is case-insensitive and ignores surrounding whitespace.

The live option-copy scope is additionally restricted to:

```text
NSE: instrument type OPTIDX and underlying NIFTY
BSE: instrument field containing OPT and trading symbol beginning with SENSEX
```

The same source-id, option-type, and underlying filters are reused by StratX position reconciliation.

### StratX Reconciliation Settings

Reconciliation is disabled by default directly in `src/zFinalMulti.py`; it is not controlled through `credentials.py` or `.env`:

```python
STRATX_RECONCILIATION_ENABLED = False
```

When disabled, the reconciliation module is not imported and no reconciliation manager, thread, report fetch, state handling, mismatch detection, or correction flow runs. The remaining reconciliation settings stay local to `src/zFinalMulti.py`:

```python
RECON_INTERVAL_SECONDS = 5
RECON_REQUIRED_CONFIRMATIONS = 5
RECON_COOLDOWN_SECONDS = 60
RECON_REPORT_ONLY = True
RECON_STATE_FILE = "stratx_recon_state.json"
```

`RECON_REPORT_ONLY` is also `True` by default for safety. If reconciliation is explicitly enabled, confirmed mismatches are logged but correction orders are not submitted until this separate setting is deliberately changed to `False`.

### Broker Selection

```python
broker = "STRATX"  # "STRATX" or "GREEK"
```

This decides which broker implementation is exposed through `src/helperGS.py`:

```python
HG.StratX()
HG.greeksoft()
```

### Quantity Controls

Freeze quantities are configured per symbol:

```python
niftyFreeze = 1800
bnfFreeze = 600
sensexFreeze = 1000
bankex = 900
midcpnifty = 2800
finnifty = 1800
```

The quantity multiplier is:

```python
multiplier = 1
```

Both broker paths multiply copied quantity by `multiplier`.

### Broker Net Limit Partial Quantity

GreekSoft and StratX net limits are checked per bucket:

```python
NIFTY_CE_POS_NET / NIFTY_CE_NEG_NET
NIFTY_PE_POS_NET / NIFTY_PE_NEG_NET
SENSEX_CE_POS_NET / SENSEX_CE_NEG_NET
SENSEX_PE_POS_NET / SENSEX_PE_NEG_NET
```

Each bucket has one running net value. BUY increases the net toward the positive limit. SELL decreases the net toward the negative limit.

For example:

```text
NIFTY_CE_POS_NET = 65
NIFTY_CE_NEG_NET = 130
Allowed final NIFTY_CE net range = -130 to +65
```

If the full order fits within the configured positive/negative range, the full order is submitted.

If the full order would cross the relevant side limit, the system calculates the maximum valid partial quantity that fits within the range and floors it to the instrument lot size.

Example:

```text
NIFTY_CE_POS_NET = 65
NIFTY_CE_NEG_NET = 130
Current net = 0
Incoming NIFTY BUY quantity = 130
NIFTY lot size = 65
Allowed partial quantity = 65
Submitted quantity = 65
Final net = +65
```

Example:

```text
NIFTY_CE_POS_NET = 65
NIFTY_CE_NEG_NET = 130
Current net = 0
Incoming NIFTY SELL quantity = 195
NIFTY lot size = 65
Allowed partial quantity = 130
Submitted quantity = 130
Final net = -130
```

Important note for lot size:

```text
NIFTY_CE_NEG_NET = 130
NIFTY lot size = 65
```

From zero, the maximum valid SELL quantity is `130`, because it is exactly two NIFTY lots.

If no valid lot-multiple quantity fits, the order is skipped.

Example:

```text
NIFTY_CE_POS_NET = 65
Current net = +65
Incoming NIFTY BUY quantity = 65
Remaining positive limit = 0
Allowed partial quantity = 0
Order skipped
```

Reversal orders are allowed if the final net remains within the configured positive/negative range.

Example:

```text
NIFTY_CE_POS_NET = 65
NIFTY_CE_NEG_NET = 130
Current net = +65
Incoming SELL quantity = 195
Final net = -130
Full SELL quantity is allowed
```

Sensex example:

```text
SENSEX_CE_POS_NET = 20
SENSEX_CE_NEG_NET = 40
Allowed final SENSEX_CE net range = -40 to +20
```

Lot size is read from broker instrument data. GreekSoft uses the resolved GreekSoft `LotSize`; StratX retains its existing fallback values when lot size is missing:

```text
NIFTY = 65
SENSEX = 20
```

### StratX Credentials

The active StratX credentials in `credentials.py` should be filled like this:

```python
id = "DUMMYUSER"
secret_key = "SECRETKEY@123"
stratX_url = "uatapi.stratx.in"  # or api.stratx.in for production
strategy_name = "Dummy Strategy"
```

Earlier we also used `client_id`, but the current StratX order payload uses `client_ids` inside each order. For a normal broadcast order the code sends:

```python
"client_ids": []
```

For retry orders, it sends only the failed clients found in the StratX orderbook.

### Greeksoft Credentials

Greeksoft needs these values in `credentials.py`:

```python
urll = "11.111.11.114:3333"
username = "TS111"
pw = "PASSWORD123"
authurl = "http://greekapi.greeksoft.in:3001"
iprocli = "1"
AccountNumber = "C12345"
```

`iprocli` values:

| Value   | Meaning                 |
| ------- | ----------------------- |
| `"0"` | Retailer                |
| `"1"` | Dealer through retailer |
| `"2"` | Dealer                  |

`AccountNumber` is mandatory for dealer-through-retailer orders. For normal retailer flow it should be empty.

### StratX Instrument Master

StratX needs an instrument CSV path:

```python
optionInstrumentPath = os.getenv("OPTION_INSTRUMENT_CSV")
```

Set this in `.env`:

```env
OPTION_INSTRUMENT_CSV=C:/path/to/options_instruments.csv
```

`src/zFinalMulti.py` refuses to start StratX before 8:50 AM, because the daily instrument file is expected to be updated before live trading starts.

The code uses the instrument master to resolve symbol, expiry, strike, right, tick size, lot size, descriptions, and instrument lookup data.

## Input CSV Formats

The system reads two daily trade files:

* NSE: `pathNSE`, comma-separated.
* BSE: `pathBSE`, pipe-separated.

Only specific column indexes are used by the runtime. If the upstream file format changes, these indexes must be updated in `src/zFinalMulti.py`, `src/greeksoft/broker.py`, and/or `src/stratx/broker.py` as appropriate.

### NSE Columns Used

| Column    | Meaning                                                                |
| --------- | ---------------------------------------------------------------------- |
| `t[2]`  | Instrument type, for example`OPTIDX`or`FUTIDX`.                    |
| `t[3]`  | Symbol.                                                                |
| `t[4]`  | Expiry string, for example`14FEB2026`.                               |
| `t[5]`  | Strike, for options.                                                   |
| `t[6]`  | Option type,`CE`or`PE`.                                            |
| `t[7]`  | Description, used by StratX for circuit/instrument lookup.             |
| `t[13]` | Side.`1`means BUY; anything else is treated as SELL.                 |
| `t[14]` | Quantity.                                                              |
| `t[15]` | Source price.                                                          |
| `t[17]` | Client code. Filtering by this is present in comments, but not active. |
| `t[23]` | Exchange order id used by combine logic.                               |
| `t[25]` | Source row timestamp used by copy delay filter, for example`13 APR 2026 09:15:02`. |
| `t[26]` | Source strategy name checked against `source_strategy_names`.                    |
| `t[27]` | Source id used by copy source filter.                                  |

### BSE Columns Used

| Column    | Meaning                                                                |
| --------- | ---------------------------------------------------------------------- |
| `t[4]`  | Exchange instrument id.                                                |
| `t[5]`  | Description.                                                           |
| `t[6]`  | Side flag,`B`or`S`.                                                |
| `t[7]`  | Quantity.                                                              |
| `t[8]`  | Source price.                                                          |
| `t[9]`  | Client code. Filtering by this is present in comments, but not active. |
| `t[14]` | Source row date used by copy delay filter, format`DD/MM/YYYY`.         |
| `t[15]` | Source row time used by copy delay filter, format`HH:MM:SS`.           |
| `t[16]` | Exchange order id used by combine logic.                               |
| `t[17]` | Instrument description/type field; reconciliation and live copying require it to contain `OPT`. |
| `t[-2]` | Source strategy name checked against `source_strategy_names`.          |
| `t[-1]` | Source id used by copy source filter.                                  |

## Main Runtime: `src/zFinalMulti.py`

`src/zFinalMulti.py` coordinates the whole system.

### Startup

At startup it:

1. Reloads `src.utils.Helper`, the separated broker modules exposed through `src.helperGS`, and `credentials`.
2. Creates the daily log file.
3. Reads `BROKER` from `credentials.py`.
4. Performs StratX-specific instrument file checks.
5. Creates the broker object.
6. Builds today's NSE/BSE CSV paths.
7. Starts the orderbook thread.
8. Preloads and synchronizes the selected broker's net state; StratX also loads its instrument data and retry state.
9. Starts NSE/BSE worker pools.
10. Starts the file watcher and fallback poll loop.
11. Starts StratX reconciliation in its own daemon thread only when the selected broker is StratX and `STRATX_RECONCILIATION_ENABLED` is `True`.

### `read_csv_safely(path, sep=',', max_retries=3)`

Reads a CSV file defensively. It handles:

* empty files,
* partially written files,
* parse problems while another process is writing the file.

It retries briefly before logging a failure.

### `validate_trade(symbol, qty, strike=None, max_qty=50000)`

Performs basic validation before an order is sent:

* symbol must not be empty,
* quantity must be positive,
* strike must be positive for option rows.

### `is_market_open()`

Workers only place orders between:

```text
09:15 to 15:40
```

Outside market hours, workers sleep and do not consume queue rows.

### `is_symbol_allowed(symbol)`

Checks the symbol against:

```python
ALLOWED_SYMBOLS = {'NIFTY', 'BANKNIFTY', 'FINNIFTY', 'MIDCPNIFTY', 'SENSEX', 'BANKEX'}
```

Currently this whitelist is active in the NSE worker. The BSE symbol whitelist is present but commented.

### `fetch_order_book()`

Runs forever in a daemon thread.

It calls:

```python
brokerObj.getOrderBookALL()
```

For StratX, before writing `trades.csv`, it also calls:

```python
brokerObj.retry_failed_orderbook_orders(data)
```

For GreekSoft, it calls:

```python
brokerObj.retry_failed_greeksoft_orders(data)
```

Then it writes the latest orderbook data to:

```text
trades.csv
```

This file is a local snapshot used for status lookup and visibility.

### `execute_with_retry(place_fn, args, lot_size=None)`

This wrapper currently calls the broker placement function once:

```python
for _ in range(1):
    orders = place_fn(*args)
```

There is old self-trade retry logic inside the function, but it is commented out.

### `nse_worker()`

Each NSE worker:

1. Waits for market hours.
2. Reads one item from `NSE_QUEUE`.
3. Extracts fields from the NSE row.
4. Validates symbol, quantity, and strike.
5. Dispatches to the selected broker:
   * Greeksoft: `brokerObj.placeOrder(...)`
   * StratX: `brokerObj.placeOrderStratX_NSE(...)`
6. Calls `NSE_QUEUE.task_done()`.

For StratX, the queue item includes an enqueue timestamp:

```python
(row, time.perf_counter())
```

That timestamp is used for order timing logs.

For StratX NIFTY CE/PE rows, the final submit path checks the runtime net limit before payload submission. The check uses the final StratX order quantity and reserves quantity under a lock.

If the full order would exceed the configured positive/negative net range, StratX may reduce the order to the maximum valid lot-multiple quantity that still fits inside the relevant side limit. If no valid lot-multiple quantity fits, the order is skipped.

If synced broker net is already outside the configured range, orders that increase exposure are skipped, but orders that move net back toward the limit are allowed.

### `bse_worker()`

Each BSE worker follows the same pattern as the NSE worker, but reads BSE-specific columns and dispatches:

* Greeksoft: `brokerObj.placeOrderBSE(...)`
* StratX: `brokerObj.placeOrderStratX_BSE(...)`

For StratX SENSEX CE/PE rows, the same runtime net-limit check runs in the final submit path after the BSE contract details, lot size, and final quantity are known.

If the full order would exceed the configured positive/negative net range, StratX may reduce the order to the maximum valid lot-multiple quantity that still fits inside the relevant side limit. If no valid lot-multiple quantity fits, the order is skipped.

The same reduce-only behavior applies when synced broker net is already outside the configured range.

### CSV Processing And Combining

The runtime has two CSV processing functions:

```python
process_nse_csv()
process_bse_csv()
```

They are called by both:

* `src/utils/file_watcher.py` callbacks,
* fallback polling loop.

Shared CSV state is protected by:

```python
csv_state_lock
```

State variables:

```python
nse_seen
bse_seen
last_nse
last_bse
nse_last_mtime
bse_last_mtime
```

This prevents duplicate processing when a file watcher event and fallback poll happen close together.

#### Current Combine Logic

For NSE:

```python
qty_col = 14
exchange_order_id_col = 23
```

For BSE:

```python
qty_col = 7
exchange_order_id_col = 16
```

Before grouping, the code skips rows whose source id does not match `copy_source_id`, whose strategy is not in `source_strategy_names`, whose row timestamp exceeds `COPY_ALLOWED_DELAY_SECONDS`, or which fall outside the NIFTY/SENSEX option scope described above.

The code then groups allowed new rows by exchange order id, keeps the first value for all columns, and sums only the quantity column. The combined rows are then queued.

Important behavior:

* Only rows seen in the same CSV processing batch can combine together.
* If related rows appear in different batches, they are processed separately.

### File Watcher And Fallback Polling

`src/zFinalMulti.py` tries to start:

```python
start_file_watcher(csvPathNSE, csvPathBSE, process_nse_csv, process_bse_csv)
```

If the watcher starts, CSV changes are detected immediately by watchdog events.

The fallback loop still runs every:

```python
FALLBACK_POLL_INTERVAL = 5.0
```

This is a safety net in case a file event is missed.

## StratX Position Reconciliation

StratX reconciliation compares the full current-day source position with the TRADED position of reference client `STRATX_NET_CLIENT_ID` (normally `Y05601`). It runs independently from live file detection and order workers.

### Reconciliation Cycle

Each cycle follows this order:

1. Return without doing reconciliation when the market is closed.
2. Read or reuse the cached NSE and BSE source snapshots and build the transformed desired net position for each exact option contract.
3. Skip an exchange whose source file is missing, empty, or unreadable; that exchange is not interpreted as having a zero desired position.
4. Fetch the reference client's current TRADED order rows and aggregate the actual net position.
5. Settle normal copied orders and pending corrections whose root quantities are now present as TRADED.
6. Compare desired and actual positions independently for every active contract.
7. Freeze correction confirmation while a normal order for that contract is unsettled, or suppress it while a correction is pending or in cooldown.
8. After the configured consecutive confirmations, calculate a fresh price and submit the difference through the normal StratX placement pipeline.

The loop targets one cycle every `RECON_INTERVAL_SECONDS`, including the work performed in that cycle. For example, with a 5-second interval, if reading, fetching, and comparison take 1.2 seconds, the loop sleeps for approximately 3.8 seconds. If the work itself takes at least the full interval, the next cycle starts immediately.

### Desired Position

The reconciliation manager reads current snapshots of the NSE and BSE source files. If a file changes during reading, the successfully read snapshot is used without caching and the next cycle reads the file again.

Unchanged source files reuse a cached desired-position calculation. This avoids reparsing full files on every configured reconciliation cycle.

A missing, empty, or unreadable NSE/BSE source file is treated as unavailable for that exchange. It is not treated as a zero desired position, so existing actual positions are not incorrectly closed. Other available exchanges continue normally. When at least one exchange is available and comparison proceeds, confirmations belonging to an unavailable exchange are cleared; when neither exchange is available, the cycle returns without comparison.

Selected source rows are transformed using the same relevant StratX rules:

* configured quantity multiplier;
* Volatility Core quantity doubling;
* Impulse Core strike offset;
* BSE exchange-instrument lookup;
* existing expiry and symbol normalization;
* BUY as positive quantity and SELL as negative quantity.

Positions are aggregated using an exact canonical contract key:

```text
Exchange | NIFTY/SENSEX | YYYYMMDD expiry | Strike | CE/PE
```

Examples:

```text
NSEFO|NIFTY|20260714|24350|CE
BSEFO|SENSEX|20260709|78400|PE
```

### Actual Position

`fetch_stratx_traded_orders()` requests TRADED rows for the reference client. Reconciliation retains the local client-id validation and normalizes report symbols such as `BSX` back to `SENSEX` before aggregation.

Reconciliation does not call `sync_stratx_net_from_traded_orders()` and does not overwrite the live reserved-net value. Desired and actual comparison dictionaries are local to the reconciliation manager.

### Stable Mismatch Confirmation

For each exact contract:

```text
difference = desired net - actual net
```

The same non-zero difference must appear for the configured number of consecutive successful checks. A changed difference restarts confirmation at one; a zero difference clears it. If comparison proceeds for another available exchange, an unavailable source exchange's confirmations are cleared. A failed StratX report fetch skips the complete comparison and preserves existing confirmation counts without increasing them. A successfully read source snapshot is used even if the file is updated during that read; that snapshot is not cached, so the next cycle reads the file again.

Each contract is tracked independently, so differences in multiple instruments are confirmed and corrected separately. Correction orders use the existing StratX order executor and the same placement pipeline as live orders. Reconciliation checks continue even while new NSE or BSE input is being processed; consecutive confirmations protect against temporary differences.

### Unsettled Normal Orders

A new normal copied order is recorded in `state.json` under its root id and exact reconciliation contract key. It remains unsettled through its original HTTP request and any orderbook retry. Reconciliation freezes the contract's existing confirmation count and does not place a correction while a normal order or retry for that exact contract is unsettled. After all normal roots settle, an unchanged difference continues from the frozen count, a changed difference restarts from one, and a zero difference clears confirmation.

The unsettled root is cleared when the reference client is found as TRADED, when all HTTP attempts finally fail, or when a cancelled/rejected order reaches final retry failure. A TRADED order keeps its reserved net; a final failure clears the unsettled root and releases reserved net. On the next successful comparison, confirmation continues only if the final difference is unchanged; otherwise it restarts from one or clears when positions match. Correction orders are not added to this mapping because their lifecycle is already protected by reconciliation's pending state.

On restart, an unsettled root without any saved reference-id mapping is cleared because it cannot be matched to a future orderbook row. Startup first rebuilds actual net from traded orders, and any remaining mismatch must still pass the normal consecutive reconciliation confirmations before a correction can be submitted. Unsettled roots that have a saved reference mapping remain protected and settle through the normal traded or terminal-failure flow.

This guard prevents a normal CANCEL/REJECT retry and reconciliation from both replacing the same missing trade. It uses only an in-memory locked lookup on the live path and does not add an HTTP call or wait to order placement.

### Correction Placement

The reference client is used to detect mismatches, but a correction is submitted with an empty `client_ids` list, matching normal broadcast behavior for all configured clients.

Correction pricing reuses the existing instrument-master, Redis LTP/average, tick rounding, market offset, and circuit-clamp helpers. The exact transformed contract is sent through `place_stratx_single_order()` so strategy transformation is not applied a second time.

Corrections also reuse existing:

* ITM protection;
* lot-size and freeze-quantity handling;
* net reservation and partial-quantity rules;
* StratX HTTP handling and repricing;
* root/reference tracking;
* rejected/cancelled order retry;
* reserved-net release after final failure.

The reconciliation module is imported and started only when `BROKER == "STRATX"` and `STRATX_RECONCILIATION_ENABLED` is `True`. Disabled StratX runs and all GreekSoft runs do not import it, create its background threads, fetch StratX reports, initialize its state, or track reconciliation-only unsettled contracts.

### Pending Corrections, Retry, And Cooldown

Once a correction is submitted, its exact contract is marked pending. Confirmation stops for that contract until the correction or its retry settles.

The existing retry policy remains authoritative. Reconciliation does not create a second retry mechanism. A retryable cancellation or PRICE/LPP rejection remains under the same correction root and does not reserve net again.

When the complete submitted correction quantity appears under its root in the reference client's TRADED report, pending state is cleared and the contract enters the configured cooldown. On final failure, existing code releases reserved net and reconciliation clears pending state and starts cooldown. After cooldown expires, any remaining mismatch must pass a fresh set of confirmations before another correction.

### Reconciliation State Persistence

Only pending corrections and unexpired cooldowns are stored in `stratx_recon_state.json`. Confirmation counts are intentionally not persisted and restart from zero after application restart.

Normal unsettled roots are stored in the existing `state.json` retry state so the retry-versus-reconciliation guard survives an application restart.

The saver follows the same pattern as the existing retry and net-state savers:

```text
state change
  -> mark dirty
  -> take a locked snapshot
  -> write stratx_recon_state.json.tmp
  -> atomically replace stratx_recon_state.json
```

A daemon saver checks dirty state every second, critical correction transitions are saved immediately, and GUI shutdown requests one final save. State from a previous trading date is discarded. Restored pending corrections remain blocked until their saved root/reference can be resolved as traded or finally failed.

Retry-state and net-state file writes use separate save locks around their temporary-file write and atomic replacement. Their in-memory locks are held only while taking a snapshot, so disk I/O does not block live net reservation or order submission.

### Reconciliation Logs

Report-only mismatch example:

```text
STRATX_RECON_MISMATCH | contract=NSEFO|NIFTY|20260714|24350|CE | desired=195 | actual=130 | diff=65 | action=BUY 65 | confirmation=2/5 | report_only=True
```

Correction lifecycle logs include:

```text
STRATX_RECON_CORRECTION_SUBMITTED
STRATX_RECON_CORRECTION_TRADED
STRATX_RECON_CORRECTION_FAILED
STRATX_RECON_CORRECTION_SKIPPED
```

## Logging

Logging is routed through `src/utils/async_logger.py`.

The log format is:

```text
[HH:MM:SS] : message
```

Logs are written to:

```text
logs/<DD_MM_YY>.txt
```

and also printed to stdout / GUI output.

### Important Live Logs

CSV ingestion:

```text
NSE: Added X combined trades from Y rows
BSE: Added X combined trades from Y rows
```

Order submit timing:

```text
ORDER_SUBMIT_TIMING | sym=... | side=... | qty=... | price=... | total=...ms | queue=...ms | broker_prep=...ms | price_calc=...ms
```

Meaning:

* `total`: time from CSV enqueue to submitting the HTTP future.
* `queue`: time spent waiting in `NSE_QUEUE` or `BSE_QUEUE`.
* `broker_prep`: broker-side preparation excluding price calculation.
* `price_calc`: price calculation time, including OTM price calculation if that strategy creates an OTM leg.

StratX net-limit logs:

```text
STRATX_NET_PARTIAL_ALLOWED | bucket=... | side=... | original_qty=... | adjusted_qty=... | current=... | requested_next=... | pos_limit=... | neg_limit=... | lot_size=...
STRATX_NET_LIMIT_SKIP | bucket=... | side=... | qty=... | current=... | next=... | pos_limit=... | neg_limit=... | lot_size=... | reason=...
STRATX_NET_RESERVED | bucket=... | signed_qty=... | current=... | pos_limit=... | neg_limit=...
STRATX_NET_RELEASE | root_id=... | bucket=... | signed_qty=... | current=... | reason=...
STRATX_NET_ROLLBACK | bucket=... | signed_qty=... | current=... | reason=...
```

StratX HTTP result:

```text
STRATX_HTTP_SUCCESS | sym=... | side=... | qty=... | price=... | description=... | ref_id=... | order_queue=...ms | http=...ms | response=...
```

Meaning:

* `order_queue`: time after submitting to the StratX HTTP thread pool before the worker starts the request.
* `http`: StratX POST request duration for that attempt.

StratX failed-order retry:

```text
STRATX_ORDERBOOK_RETRY_SUBMIT | root_id=... | clients=... | sym=... | side=... | qty=... | price=... | description=... | retry_ref_source=...
```

This logs once per retry batch, not once per client.

## Shared And GreekSoft Broker Helpers

### `printt()`, `saveInLogFile()`, And `createLogFile()`

These live in `src/utils/broker_helpers.py` and are re-exported by `src/helperGS.py` for compatibility. They route logs through `src/utils/async_logger.py`.

* `printt()` is the normal project log function.
* `saveInLogFile()` is retained for compatibility and routes to the same async logger.
* `createLogFile()` creates/opens today's log file and initializes async logging.

### `wait_for_greek_order_slot()`

This remains in `src/greeksoft/broker.py` because it is GreekSoft-specific. It implements the existing GreekSoft order rate limiter.

Current rate:

```python
MAX_GREEK_ORDERS_PER_WINDOW = 9
GREEK_RATE_WINDOW_SECONDS = 1.2
```

The function uses a timestamp deque and sleeps until a new order slot is available.

### `getFreezeQua(freeze_limit, lot_size, total_quantity)`

This also remains in `src/greeksoft/broker.py`. It splits a large quantity into freeze-limit-safe chunks.

It makes sure each chunk is aligned to lot size:

```python
qty = (qty // int(lot_size)) * int(lot_size)
```

Greeksoft uses this for split order placement.

### `round_to_tick(price, tick)`

Rounds a price to the nearest tick size.

### `adjust_price_to_tick(price, tick_size, side, market_order_offset)`

Applies a marketable-limit offset to a fallback price:

* BUY: price is moved up.
* SELL: price is moved down.

If the price is less than or equal to 50, the fixed point offset is `market_order_offset`. Otherwise, percentage offset is used.

### Shared Order Pricing

`src/utils/order_pricing.py` contains the complete shared pricing functions used by GreekSoft and StratX. The original pricing logic remains together: Redis cache-symbol construction, 200 millisecond LTP/average caching, Redis reads, LTP/average offset calculation, tick rounding, circuit lookup/clamping, try/except handling, and logging.

Both broker classes call these functions directly. Broker-specific instrument lookup, payload construction, retries, and order submission remain in the respective broker implementations.

## Greeksoft Broker Flow

The GreekSoft broker implementation is the `greeksoft` class in `src/greeksoft/broker.py`. `src/helperGS.py` re-exports it so the runtime can continue calling `HG.greeksoft()`.

### Initialization

When `greeksoft()` is created:

1. It calls the Greeksoft auth API to get a session token.
2. It downloads the Greeksoft instrument master.
3. It logs in to get `gcid`.
4. It filters the instrument master to NIFTY and SENSEX options, then precomputes the NIFTY/NSE contract-key map and SENSEX/BSE exchange-token map.
5. It loads the current day's retry state from `greek_state.json`.
6. It starts the dirty-state saver.
7. It creates and warms five reusable GreekSoft order-worker sessions.

Before NSE/BSE order workers start, `src/zFinalMulti.py` also loads `greek_net_state.json`, starts its net-state saver, and replaces the saved net with a fresh GreekSoft orderbook sync when that sync succeeds. If startup sync fails, the same-day saved net remains active.

Authentication, login, instrument download, warmup, order submission, and orderbook requests use bounded request timeouts. Initialization fails after four unsuccessful authentication/startup attempts instead of continuing with an unusable broker object.

### GreekSoft TCP Keepalive

Each worker keeps its existing thread-local `requests.Session`, connection-pool sizes, and session warmup. `GreekKeepAliveAdapter` preserves urllib3's default socket options and additionally enables Windows TCP keepalive on newly created pooled connections:

```python
GREEK_KEEPALIVE_IDLE_SECONDS = 30
GREEK_KEEPALIVE_INTERVAL_SECONDS = 10
GREEK_KEEPALIVE_PROBE_COUNT = 3
```

After 30 seconds without TCP traffic, Windows checks the idle connection and repeats the check every 10 seconds. After three unanswered probes, the socket is marked dead so urllib3 does not continue treating it as a reusable live connection. Probes contain no HTTP request or order data, do not consume the GreekSoft order-rate limit, and do not occupy order workers. This changes only pooled-connection health checking; workers, sessions, pricing, payloads, HTTP attempts, orderbook retry and net protection remain unchanged. The application must restart for newly created connections to receive these socket settings.

### `login()`

Calls:

```text
http://<urll>/getLoginInfo
```

It stores:

```python
self.gcid
```

This value is required for order placement and orderbook APIs.

### `getInstrument()`

Calls:

```text
http://<urll>/getAllContract
```

The response is parsed into:

```python
self.df
```

It also writes:

```text
abc.csv
```

for local inspection.

### `getData(t)`

Finds the matching NSE instrument row from a precomputed map keyed by:

```text
Symbol + YYYYMMDD expiry + StrikePrice + OptionType
```

It matches:

* expiry from `t[4]`,
* symbol from `t[3]`,
* strike from `t[5]`,
* option type from `t[6]`.

The returned row contains the Greek token, lot size, symbol, and other contract data needed by `placeOrder()`.

The NSE source expiry such as `23JUL2026` and GreekSoft master expiry such as `23-Jul-26` are normalized to `YYYYMMDD`. Existing DataFrame filtering remains as a fallback if a precomputed key is unavailable.

### `getDataBSE(t)`

Finds the matching BSE instrument from the precomputed exchange-token map.

The BSE worker passes:

```python
t[4]
```

as the exchange token.

### `placeOrder(...)`

Places Greeksoft NSE orders.

Inputs:

* Greek token,
* side,
* symbol,
* lot count,
* quantity,
* instrument row.

Flow:

1. Select freeze limit by symbol.
2. Split total quantity using `getFreezeQua()`.
3. Convert each quantity chunk to lots.
4. Build the Redis cache symbol from the resolved GreekSoft instrument row using `Symbol + DDMMMYY expiry + StrikePrice + OptionType`.
5. Check and reserve the child's NIFTY/SENSEX CE/PE net under `greek_net_lock`; reduce to the maximum valid lot multiple or skip when the configured range cannot accept the full quantity.
6. Give every accepted child order its own root id and persist its original metadata and net metadata in memory.
7. Enqueue each child into the shared five-worker GreekSoft order pool.
8. In the worker, wait for the GreekSoft rate-limit slot.
9. After the wait, use price `0` before `09:17:00` local machine time. From `09:17:00` onward, read fresh Redis LTP/average; values may be reused only within the 200 millisecond cache window.
10. From `09:17:00` onward, apply the same offset, tick-rounding, and circuit-clamp calculation used by StratX.
11. Before `09:17:00`, send a market order (`order_type = "2"`, `price = "0"`). From `09:17:00` onward, send a limit order (`order_type = "1"`) with the calculated price, or the existing market fallback if pricing fails.
12. Validate the response and map the returned `gorderid` to the child's root id.

The payload uses:

* exchange: `NSE`,
* order type: market `2` before `09:17:00` local machine time; from `09:17:00` onward, `1` when Redis pricing succeeds, otherwise market fallback `2`,
* validity: `1`, so GreekSoft original and retry orders use IOC validity,
* product: `0`,
* strategyName: `AlgoSelf`,
* `tag` and `userTag`: copied source exchange order id as a string (`t[23]` for NSE and `t[16]` for BSE),
* `iprocli` and `AccountNumber` from `credentials.py`.

### `placeOrderBSE(...)`

Same idea as `placeOrder()`, but for BSE:

* exchange: `BSE`,
* symbols use SENSEX/BANKEX freeze limits,
* side is converted to Greeksoft numeric side.

BSE instrument resolution continues to use `ExchangeToken`. Redis keys are built only after the exact GreekSoft row is resolved, so monthly-expiry differences in `TradingSymbol`, `SymbolWithExpiry`, or source description do not affect pricing.

For both Greeksoft NSE and BSE orders, `iprocli` and `AccountNumber` come from `credentials.py`. Use:

* `iprocli = "0"` for retailer,
* `iprocli = "1"` for dealer through retailer,
* `iprocli = "2"` for dealer.

`AccountNumber` is required for dealer-through-retailer orders. Otherwise it can be kept empty.

### GreekSoft HTTP Attempts

GreekSoft order workers use:

```python
greek_http_max_attempts = 4
greek_http_retry_sleep = 0.3
greek_request_timeout = 15
```

This permits one original HTTP request and at most three additional attempts. Another attempt is allowed for a received non-success HTTP response or an immediate connection reset matching the narrow safe-reset condition. The worker waits for another rate-limit slot and recalculates price before each additional request.

A successful HTTP response with `streaming_type = "IrisRejection"` and a reason containing both `throttle` and `reached` (case-insensitive) is treated as a rejected order rather than a successful submission. The rejected `gorderid`, complete option symbol and reason are logged, and another available HTTP attempt is used without registering the rejected order id.

Read timeouts, delayed uncertain connection failures, and successful HTTP responses missing a `gorderid` are not automatically repeated because the broker may already have received the order.

### `getOrderStatus(orderId)`

Reads `trades.csv` and finds a matching Greeksoft order id:

```python
gorderid == orderId
```

### `getOrderBookALL()`

Calls Greeksoft orderbook API:

```text
getOrderBookDetailWithLegV2
```

The orderbook thread writes the returned data into `trades.csv`.

### GreekSoft Net Limit And Synchronization

GreekSoft protects the same four option buckets and uses the same settings in `credentials.py` as StratX:

```text
NIFTY_CE
NIFTY_PE
SENSEX_CE
SENSEX_PE
```

Each bucket contains one signed running quantity. Side `1`/BUY adds quantity and side `2`/SELL subtracts quantity. The lock-protected reservation happens once for each original freeze-split child before it enters the order pool. A retry keeps the same root and reservation, so retry quantity is not added again.

The full child is accepted when its final net remains between `-NEG_NET` and `+POS_NET`. Otherwise the quantity is reduced to the largest valid lot multiple. The child is skipped when no valid lot-multiple quantity fits. If the current broker net is already outside a configured limit, only orders that reduce that exposure are allowed.

GreekSoft runtime net is stored separately from retry state in:

```text
greek_net_state.json
```

The date-scoped file contains `net_position` and `released_roots`. Order placement changes only locked in-memory state and marks it dirty; a one-second background saver writes through `greek_net_state.json.tmp` and atomically replaces the state file. GUI shutdown saves it immediately.

Startup and the GUI Sync Net button call `sync_greek_net_from_traded_orders()`. The sync fetches `getOrderBookDetailWithLegV2`, accepts `OPTIDX` rows with `traded_qty > 0`, deduplicates them by `gorderid`, and aggregates `scripName + optionType + side` into the four buckets. Counting `traded_qty` also includes partially traded orders instead of relying only on the final `order_status` text. A successful sync replaces all four local values and clears old release markers; a failed sync leaves the loaded same-day state unchanged.

If an original child cannot be enqueued or finishes HTTP submission without a `gorderid`, its full reservation is rolled back once. If a retry cannot be enqueued/submitted, or a cancelled order reaches the configured orderbook retry limit, only that retry/final `pending_qty` is released once. A tracked `Exchange Rejected` row with `pending_qty > 0` is terminal and releases that pending quantity immediately without retry. Existing `processed_gorderids` and `released_roots` guards prevent duplicate handling. These actions use the existing root metadata and do not change the GreekSoft retry condition.

Important GreekSoft net logs:

```text
GREEK_NET_SYNC_DONE
GREEK_NET_SYNC_FAILED
GREEK_NET_SYNC_OVER_LIMIT
GREEK_NET_RESERVED
GREEK_NET_PARTIAL_ALLOWED
GREEK_NET_LIMIT_SKIP
GREEK_NET_ROLLBACK
GREEK_NET_RELEASE
```

### GreekSoft Orderbook Retry

GreekSoft orderbook retry is separate from HTTP attempts. Retry state is stored in:

```text
greek_state.json
```

The state is date-scoped and contains:

```text
gorderid -> root_order_id
original order metadata by root
retry count by root
processed failed gorderids by root
```

The live order path updates state in memory and marks it dirty. A background saver writes through `greek_state.json.tmp` and atomically replaces `greek_state.json`.

The current retry conditions require positive `pending_qty` and either:

```text
order_status == CANCELLED
or BSE EXCHANGE REJECTED with errorCode 10008
or NSE EXCHANGE REJECTED with errorCode 17070
```

`is_retryable_greek_orderbook_row()` owns these rules.

For an eligible row, `retry_failed_greeksoft_orders()`:

1. Reads and normalizes `gorderid`.
2. Ignores orders not registered by this copy-trade process.
3. Resolves the original root.
4. Skips already processed failed order ids.
5. Enforces `max_greek_orderbook_retries` per root, currently `3`.
6. Loads the saved contract metadata and uses `pending_qty` after validating it against original quantity and lot size.
7. Enqueues a retry task through the same five-worker pool.
8. Recalculates price after the rate-limit wait.
9. Maps the newly returned retry `gorderid` to the same root.

When a later retryable row reaches `max_greek_orderbook_retries`, its remaining `pending_qty` is released from GreekSoft net once. Retry enqueue/HTTP failure also releases that retry quantity once. The retry counter is still intentionally consumed and is not rolled back.

Other `EXCHANGE REJECTED` rows remain non-retryable. For an order mapped to a GreekSoft root, `pending_qty > 0` is released once and its `gorderid` is marked processed. Active/unknown statuses are not treated as terminal failures.

GreekSoft position reconciliation is not implemented by this retry feature.

## StratX Broker Flow

The StratX broker implementation is the `StratX` class in `src/stratx/broker.py`. `src/helperGS.py` re-exports it so the runtime can continue calling `HG.StratX()`.

StratX has more parts because it handles:

* instrument master preloading,
* Redis LTP/average lookup,
* circuit limit clamping,
* HTTP session pooling,
* runtime positive/negative net-limit reservation,
* orderbook-based retry,
* broadcast-client retry tracking.

### Complete StratX Flow

The live StratX path works like this:

1. `src/zFinalMulti.py` starts and checks that `OPTION_INSTRUMENT_CSV` is configured.
2. `StratX()` is created.
3. StratX net state is loaded from `stratx_net_state.json`.
4. The StratX net-state background saver is started.
5. The instrument master is loaded from `cre.optionInstrumentPath`.
6. The retry-state background saver is started.
7. The instrument master is filtered and cached so BSE contracts, tick sizes, lot sizes, OTM descriptions, and retry lookups are fast.
8. The orderbook polling thread starts and repeatedly calls `getOrderBookALL()`.
9. When a new NSE or BSE source trade row is detected, `src/zFinalMulti.py` combines rows by exchange order id and pushes the combined row into the NSE or BSE queue.
10. A worker validates market hours, symbol, quantity, and basic option fields.
11. The worker calls either `placeOrderStratX_NSE()` or `placeOrderStratX_BSE()`.
12. NSE fields are read directly from the NSE trade row. BSE fields are resolved from the instrument master using `ExchangeInstrumentID` and `Description`.
13. The code decides exchange, segment, symbol, expiry, right, strike, quantity, lot size, and freeze split.
14. Price is recalculated from Redis average/last 30 sec avg LTP, rounded to tick, and clamped to circuit limits.
15. `place_stratx_single_order()` checks ITM rules, checks and reserves net quantity for option buckets, builds the final StratX payload, and submits it to the StratX HTTP worker pool.
16. `send_stratx_order_request()` posts the payload to StratX and reads the returned `reference_id`.
17. The returned `reference_id` is mapped to the internal `root_order_id`.
18. The orderbook thread writes the latest rows into `trades.csv`.
19. If a row is `CANCEL`, or `REJECTED` with both `PRICE` and `LPP` in `order_message` for the Price not in LPP range issue, `retry_failed_orderbook_orders()` checks whether that specific client is still eligible for retry.
20. Retry orders reuse the same root id but send only the failed `client_ids`, so late-arriving failed clients can still retry independently.
21. Runtime net is released only when a terminal failed row is processed for `STRATX_NET_CLIENT_ID`, or rolled back if local HTTP submission fails before a reference id is received.

Original StratX orders normally broadcast with:

```python
"client_ids": []
```

Retry orders are client-specific:

```python
"client_ids": ["FAILED_CLIENT_1", "FAILED_CLIENT_2"]
```

### StratX Class Settings

Important class-level settings:

```python
market_order_offset = 8
instrument_names_to_load = {"NIFTY", "SENSEX"}
redis_ltp_avg_cache_ttl = 0.2
stratx_order_workers = 20
stratx_request_timeout = 15
stratx_http_max_attempts = 3
stratx_http_retry_sleep = 0.3
retry_state_file = "state.json"
retry_state_save_interval = 1
max_orderbook_retries = 2
net_state_file = "stratx_net_state.json"
net_state_save_interval = 1
net_buckets = ("NIFTY_CE", "NIFTY_PE", "SENSEX_CE", "SENSEX_PE")
```

Notes:

* `stratx_http_max_attempts = 3` means one original HTTP request plus at most two additional attempts.
* `max_orderbook_retries = 2` means each client under a root order gets at most two orderbook-level retries.
* `instrument_names_to_load = {"NIFTY", "SENSEX"}` means the StratX instrument master is filtered to those names.
* `net_buckets` keeps only the running net buckets. It should not be split into positive and negative buckets.
* Positive/negative net limits are config values in `credentials.py`, not separate state keys.

### `load_instrument_master()`

Loads the StratX instrument CSV from:

```python
cre.optionInstrumentPath
```

It builds normalized dataframe columns and precomputed maps:

```python
tick_size_by_name
lot_size_by_name
bse_contract_by_exchange_id
otm_description_by_key
retry_instrument_by_key
```

These maps avoid repeated dataframe scans in live order paths.

### `to_yyyymmdd(date_str)` And `to_ddmmmyy(date_str)`

Cached date conversion helpers.

`to_yyyymmdd()` is used for StratX payload expiry:

```text
YYYYMMDD
```

`to_ddmmmyy()` is used for Redis cache symbols:

```text
DDMMMYY
```

### `get_bse_contract_details(exchange_instrument_id)`

Converts BSE order rows into usable StratX fields.

It returns:

```python
(symbol, strike, expiry, right, tick_size, lot_size)
```

It first checks `bse_contract_by_exchange_id`, then falls back to dataframe filtering by `ExchangeInstrumentID`.

### `get_otm_strike(symbol, right, strike, offset)`

Calculates OTM strike:

* NIFTY step: 50
* SENSEX step: 100

For CE, strike increases. For PE, strike decreases.

### `get_otm_description(symbol, expiry_yyyymmdd, right, strike)`

Finds the StratX compact instrument `Description` for OTM legs.

It first checks `otm_description_by_key`, then falls back to dataframe filtering.

### Redis And Circuit Helpers

Redis sources are configured in `credentials.py`:

```python
redis_sources = [
    {"name": "primary", "host": "100.103.231.7", "port": 6379, "db": 1},
    # {"name": "secondary", "host": "SECONDARY_REDIS_IP", "port": 6379, "db": 1},
]
```

`src/utils/fetch_circuit.py` keeps one Redis client per configured source and tracks the currently active source. If the active Redis fails, returns no key, returns bad data, or returns stale data, the next configured Redis source is tried. When another source succeeds, it becomes active for future reads.

`get_redis_ltp_avg(cache_symbol)` reads:

```text
cache:LTP_<CACHE_SYMBOL>
```

from Redis and returns:

```python
(ltp, avg)
```

The LTP payload must contain fresh `payload.Time` and `payload.LTP`; `payload.avg` is optional. If `payload.Time` is more than 5 seconds old, that Redis response is treated as stale and the next Redis source is tried. If all Redis sources fail for LTP, StratX sends price `0` for that leg.

`get_underlying_ltp(channel)` reads the latest underlying index tick for the StratX ITM check. It reads Redis keys matching:

```text
cache:LTP_NIFTY 50
cache:LTP_SENSEX
```

It parses `payload.LTP` and uses the value only if `payload.Time` is not older than 10 seconds. Redis source failover works the same way as `get_redis_ltp_avg()`. StratX also keeps a 0.2 second in-memory cache for this underlying ITM lookup.

`apply_circuit_clamp(price, cache_symbol)`:

1. Reads circuit limits from Redis using the same cache symbol format as LTP.
2. Uses limits only if Redis timestamp is not older than 300 seconds.
3. Clamps price to LC/UC when required.

Circuit Redis keys use:

```text
cache:CIRCUIT_<CACHE_SYMBOL>
```

Example:

```text
cache:CIRCUIT_NIFTY14JUL2619400CE
```

If all Redis sources fail for circuit data, circuit clamping is skipped and the calculated price is left unchanged.

### `price_from_avg_ltp_or_fallback(...)`

This is the central StratX price calculation part.

For normal copied orders:

* it reads Redis avg or LTP when available for instrument symbol,
* if Redis LTP is unavailable, stale, invalid, or no Redis symbol is available, price is sent as `0`,
* it then applies offset for market order,
* it rounds to tick size,
* at last clamps to circuit limits.

Retry and OTM pricing also try the active Redis source first, fail over to another configured source, and send price `0` if all Redis LTP sources fail.

Current live offset behavior:

* BUY: price moves above LTP/avg.
* SELL: price moves below LTP/avg.

### `get_stratx_net_bucket(symbol, right)`

Returns the runtime net bucket for supported option orders.

Supported buckets:

```text
NIFTY_CE
NIFTY_PE
SENSEX_CE
SENSEX_PE
```

NSE NIFTY options map to `NIFTY_CE` / `NIFTY_PE`.

BSE SENSEX/BSX options map to `SENSEX_CE` / `SENSEX_PE`.

If the symbol/right does not belong to these buckets, net-limit checking is skipped for that order.

### `get_stratx_net_limit(bucket)`

Reads positive and negative limits from `credentials.py`.

For a bucket such as:

```text
NIFTY_CE
```

the function reads:

```python
NIFTY_CE_POS_NET
NIFTY_CE_NEG_NET
```

It returns:

```python
(pos_limit, neg_limit)
```

The final allowed net range is:

```text
-neg_limit <= current_net <= +pos_limit
```

### `reserve_stratx_net(symbol, right, side, qty, lot_size)`

Checks and reserves runtime net before the StratX order is submitted.

Rules:

* BUY adds quantity to net.
* SELL subtracts quantity from net.
* Full order is allowed if final net remains inside `-NEG_NET` to `+POS_NET`.
* If full order crosses the relevant side limit, the function calculates the maximum allowed quantity.
* Allowed partial quantity is floored to the instrument lot size.
* If the floored partial quantity is `0`, the order is skipped.
* If current net is already above `POS_NET`, BUY is skipped and SELL is allowed only because it reduces exposure.
* If current net is already below `-NEG_NET`, SELL is skipped and BUY is allowed only because it reduces exposure.
* The reservation is protected by `net_lock`, so concurrent workers cannot cross the configured net range.
* After reservation, `stratx_net_state.json` is marked dirty and saved by the background saver.

Example:

```text
NIFTY_CE_POS_NET = 65
NIFTY_CE_NEG_NET = 130
Current net = 0
Incoming BUY quantity = 130
Allowed partial quantity = 65
Final net = +65
```

Example:

```text
NIFTY_CE_POS_NET = 65
NIFTY_CE_NEG_NET = 130
Current net = 0
Incoming SELL quantity = 195
Allowed partial quantity = 130
Final net = -130
```

Example reversal:

```text
NIFTY_CE_POS_NET = 65
NIFTY_CE_NEG_NET = 130
Current net = +65
Incoming SELL quantity = 195
Final net = -130
Full SELL quantity is allowed
```

Example synced over-limit reduction:

```text
NIFTY_CE_POS_NET = 130
Current broker net = +260
Incoming SELL quantity = 65
Final net = +195
SELL is allowed because it reduces exposure
```

Sensex example:

```text
SENSEX_PE_POS_NET = 20
SENSEX_PE_NEG_NET = 40
Current net = 0
Incoming SELL quantity = 60
Allowed partial quantity = 40
Final net = -40
```

### `release_stratx_net(...)`

Releases a previously reserved net quantity once a terminal failed orderbook row is confirmed for the tracked `STRATX_NET_CLIENT_ID`.

It subtracts the original signed reserved quantity from the bucket net.

Example:

```text
Reserved BUY signed_qty = +20
Current net = +20
Release subtracts +20
Final net = 0
```

Each root id is added to `released_roots`, so the same root reservation cannot be released twice.

### `rollback_stratx_net_meta(...)`

Rolls back a local reservation if the HTTP submission fails before a valid StratX `reference_id` is received.

It is different from orderbook release:

* rollback is for local submit failure,
* release is for accepted orders that later become terminal failed orders in orderbook.

### `load_stratx_net_state()` And `save_stratx_net_state_now()`

Runtime net is saved in:

```text
stratx_net_state.json
```

Shape:

```json
{
  "date": "YYYYMMDD",
  "net_position": {
    "NIFTY_CE": 0,
    "NIFTY_PE": 0,
    "SENSEX_CE": 0,
    "SENSEX_PE": 0
  },
  "released_roots": []
}
```

On a new day, net state resets automatically.

`net_position` should remain one value per bucket. It should not be changed into positive/negative keys. Positive/negative values are limits, not state.

### `place_stratx_single_order(...)`

Builds the final StratX JSON payload and submits it asynchronously to the StratX HTTP thread pool.

Before building the payload, StratX checks whether an option order is ITM using the fresh underlying Redis tick:

* NIFTY options use `cache:LTP_NIFTY 50`
* SENSEX/BSX options use `cache:LTP_SENSEX`
* spot is rounded to the nearest valid strike, with an exact midpoint rounded upward
* NIFTY uses a 50-point strike step and SENSEX/BSX uses a 100-point strike step
* NIFTY CE/PE is allowed up to two strike steps ITM; anything deeper is skipped
* SENSEX CE/PE is allowed up to six strike steps ITM; anything deeper is skipped
* if fresh underlying LTP is unavailable from all Redis sources, the ITM check is skipped and the order continues

Important payload fields:

```python
"client_ids": payload_client_ids
"strategy_name": strategy_name
"symbol": symbol
"strike": strike
"expiry": expiry
"buyorsell": side
"producttype": "DELIVERY"
"ordertype": "LIMIT"
"quantity": quantity
"price": price
"exchange": exchange
"segment": segment
"right": right
"trigger": source_order_id
"quantity_split": freez
```

For copied orders, `trigger` contains the combined source row's exchange order id as a string (`t[23]` for NSE and `t[16]` for BSE). The value is stored in the existing root metadata so an orderbook retry sends the same source order id without any additional lookup.

For original broadcast orders:

```python
client_ids=None
```

becomes:

```python
"client_ids": []
```

StratX expands that to all mapped clients.

For retry orders, the function receives a specific `client_ids` list and retries only those failed clients.

The function also creates a `root_order_id` UUID if one was not provided. That root id is used by the retry system.

The runtime net reservation is attached to the root order so retry orders do not add quantity again.

### `send_stratx_order_request(...)`

Runs in the StratX HTTP thread pool.

Flow:

1. Gets a thread-local `requests.Session`.
2. Posts the payload to StratX.
3. If HTTP status is not 200 and more attempts are allowed (`stratx_http_max_attempts > 1`), recalculates price and retries.
4. Parses response JSON.
5. Extracts `reference_id`.
6. Logs `STRATX_HTTP_SUCCESS`.
7. Returns the `reference_id`.

### `log_stratx_future_result(future)`

Runs when the HTTP future completes.

If the request succeeded:

1. Reads the returned `reference_id`.
2. Maps that reference id to the original `root_order_id`.
3. Logs `STRATX_FUTURE_DONE`.

If the request failed:

1. Removes the future from pending root tracking.
2. Rolls back the reserved net quantity if a net reservation exists for that future.
3. Logs `STRATX_FUTURE_FAILED`.

### `placeOrderStratX_NSE(...)`

Places StratX NSE orders.

NSE source columns used:

| Field           | Column                                  |
| --------------- | --------------------------------------- |
| Instrument type | `trade[2]`                            |
| Symbol          | `trade[3]`                            |
| Expiry          | `trade[4]`                            |
| Strike          | `trade[5]`                            |
| Right           | `trade[6]`                            |
| Description     | `trade[7]`                            |
| Side            | worker converts`trade[13]`to BUY/SELL |
| Quantity        | `trade[14] * multiplier`              |
| Source price    | `trade[15]`                           |

Segments:

* options: `NFO-OPT`
* futures: `NFO-FUT`

Exchange:

```text
NSEFO
```

Payload-level details:

* product type: `DELIVERY`
* order type: `LIMIT`
* right: `CE`, `PE`, or `FUT`
* expiry is converted to `YYYYMMDD`
* quantity is `trade[14] * multiplier`
* source price starts from `trade[15]`, then StratX price logic recalculates/clamps it
* quantity split uses the configured freeze limit for the symbol
* NIFTY CE/PE option rows use the runtime positive/negative net-limit check before placement

Strategy-specific behavior:

* `VOLATILITY CORE`: places main leg and OTM leg with offset 2.
* `IMPULSE CORE`: places OTM leg with offset from the StratX Expiry Mode dropdown. `Non Expiry` uses offset 0; `Expiry` uses offset 1.
* Other strategy names: places the original leg.

### `placeOrderStratX_BSE(...)`

Places StratX BSE orders.

BSE source columns used:

| Field                | Column                    |
| -------------------- | ------------------------- |
| ExchangeInstrumentID | `trade[4]`              |
| Description          | `trade[5]`              |
| Side                 | `trade[6]`, B/S         |
| Quantity             | `trade[7] * multiplier` |
| Source price         | `trade[8]`              |

BSE contract details are resolved from the instrument master.

Payload symbol mapping:

* `SENSEX` becomes `BSX`
* `BANKEX` becomes `BKX`

Segments:

* options: `BFO-OPT`
* futures: `BFO-FUT`

Exchange:

```text
BSEFO
```

Payload-level details:

* product type: `DELIVERY`
* order type: `LIMIT`
* right: `CE`, `PE`, or `FUT`
* expiry, strike, right, tick size, and lot size are resolved from the instrument master using `ExchangeInstrumentID` and `Description`
* quantity is `trade[7] * multiplier`
* source price starts from `trade[8]`, then StratX price logic recalculates/clamps it
* quantity split uses the freeze limit for the resolved underlying index
* SENSEX CE/PE option rows use the runtime positive/negative net-limit check before placement

Strategy-specific behavior mirrors NSE for SENSEX options:

* `VOLATILITY CORE`: main leg plus OTM leg with offset 2.
* `IMPULSE CORE`: OTM leg with offset from the StratX Expiry Mode dropdown. `Non Expiry` uses offset 0; `Expiry` uses offset 1.
* Other strategy names: original leg.

## StratX Orderbook Retry

The StratX retry system is for orders that were accepted by the placement API, received a `reference_id`, and later appeared in the orderbook as failed.

It is not the same as HTTP retry.

### Retryable Status

Implemented in:

```python
is_retryable_orderbook_status(row)
```

Retry is allowed for:

```text
status == CANCEL
```

or:

```text
status == REJECTED
and order_message contains PRICE
and order_message contains LPP
```

This avoids retrying every rejection blindly. Margin/RMS/broker rejections should generally not be retried automatically.

### StratX Net Limit

StratX keeps a live net guard for these four buckets:

```text
NIFTY_CE
NIFTY_PE
SENSEX_CE
SENSEX_PE
```

Each bucket has one running net value. BUY adds quantity to the net. SELL subtracts quantity from the net.

The configured positive/negative limits live in `credentials.py`:

```python
NIFTY_CE_POS_NET = 65
NIFTY_CE_NEG_NET = 130

NIFTY_PE_POS_NET = 65
NIFTY_PE_NEG_NET = 130

SENSEX_CE_POS_NET = 20
SENSEX_CE_NEG_NET = 40

SENSEX_PE_POS_NET = 20
SENSEX_PE_NEG_NET = 40

STRATX_NET_CLIENT_ID = "Y05601"
```

For example, this configuration means:

```text
NIFTY_CE allowed final net range = -130 to +65
NIFTY_PE allowed final net range = -130 to +65
SENSEX_CE allowed final net range = -40 to +20
SENSEX_PE allowed final net range = -40 to +20
```

The check is independent of strike and uses the final quantity passed into `place_stratx_single_order()`, so strategy changes such as `2 * qty` are included.

If the full order fits within the configured positive/negative range, the full order is submitted. If the full order would exceed the relevant side limit, the system may reduce the order to the maximum valid lot-multiple quantity that still fits inside the range. If no valid lot-multiple quantity fits, the order is skipped before StratX placement.

Reversal orders are allowed when the final net remains within the configured positive/negative range. For example, with `NIFTY_CE_POS_NET = 65` and `NIFTY_CE_NEG_NET = 130`, current net `+65` and SELL `195` gives final net `-130`, so the full SELL quantity is allowed.

On startup, StratX fetches `TRADED` rows for `STRATX_NET_CLIENT_ID`, rebuilds `NIFTY_CE`, `NIFTY_PE`, `SENSEX_CE`, and `SENSEX_PE`, and replaces runtime net with the broker-calculated value. A valid no-data response is logged as `STRATX_NET_SYNC_EMPTY` and produces zero for all four buckets instead of a fetch failure. The GUI `Sync Net` button runs the same sync under `net_lock`.

Runtime net is saved in `stratx_net_state.json` by a background saver, so order placement only updates in-memory net and marks state dirty. This keeps the limit check fast while still allowing an intraday restart to continue from the last saved net if broker sync fails. If StratX HTTP placement fails before a reference id is received, the reservation is rolled back. If orderbook later shows a terminal failed row for `STRATX_NET_CLIENT_ID`, the reservation is released once. Retry orders do not add quantity again; they keep the original reservation until the retry succeeds or reaches final failure.

### Why Retry Is Client-Aware

A normal live StratX broadcast order uses:

```python
"client_ids": []
```

That tells StratX to place the order for all mapped clients. The app does not know every client at placement time.

The orderbook later returns one row per client. Some clients may appear earlier than others.

So retry count cannot be stored only on `reference_id`. If the first fetch shows 60 failed clients and the second fetch shows 20 more under the same reference, those 20 must still be eligible.

The current model stores retry count by:

```text
root_order_id + client_id
```

### Root And Reference Mapping

Every intended StratX order gets an internal root id:

```text
root_order_id
```

When StratX returns a reference:

```text
reference_id -> root_order_id
```

Retries reuse the same root id and create new StratX references.

Example:

```text
R1 -> U1
R2 -> U1
R3 -> U1
```

The reference tells the retry processor which root order the failed row belongs to.

### State File

Retry state is saved in:

```text
state.json
```

Shape:

```json
{
  "date": "YYYYMMDD",
  "reference_id_to_root_id": {
    "REFERENCE_ID": "ROOT_UUID"
  },
  "retry_by_root": {
    "ROOT_UUID": {
      "retry_count_by_client": {
        "CLIENT_ID": 1
      },
      "processed_refs_by_client": {
        "CLIENT_ID": ["REFERENCE_ID"]
      }
    }
  },
  "order_meta_by_root": {
    "ROOT_UUID": {
      "quantity": 20,
      "symbol": "NIFTY",
      "strike": 25100,
      "expiry": "YYYYMMDD",
      "side": "BUY",
      "exchange": "NSEFO",
      "segment": "NFO-OPT",
      "right": "CE",
      "strategy_name": "STRATEGY",
      "description": "INSTRUMENT DESCRIPTION"
    }
  }
}
```

On a new day, state resets automatically.

The background saver writes state only when dirty. It writes to `state.json.tmp` and then uses `os.replace()` so the state file is not left half-written.

`src/zzEXE.py` also calls `save_stratx_net_state_now()` and `save_retry_state_now()` before closing the app.

### `retry_failed_orderbook_orders(rows)`

Runs inside the orderbook thread.

For each orderbook row:

1. Check if status is retryable.
2. Read `reference_id`.
3. Read `client_id`.
4. Find root id using `reference_id_to_root_id`.
5. Skip if this client already processed this reference.
6. Skip if this client reached `max_orderbook_retries`.
7. Mark the reference processed for this client.
8. Increment this client's retry count.
9. Group failed rows by root/reference/order details without using orderbook quantity.
10. Submit one retry per group.

### `get_retry_group_key(...)`

Builds a grouping key so one retry order can cover many failed clients that share the same root, failed reference, retry number, and order details.

The grouping key does not include orderbook `quantity`, because StratX orderbook quantity can already include API-side client multipliers.

### `retry_single_orderbook_row(...)`

Reconstructs a retry order from the orderbook row:

* symbol,
* exchange,
* segment,
* right,
* side,
* strategy name,
* expiry,
* strike,
* price / initiated price.

Retry quantity is loaded from `order_meta_by_root[root_order_id]["quantity"]`, which is the original quantity this code submitted to StratX before API-side multipliers. It does not fall back to orderbook quantity, because that can multiply the retry quantity a second time.

It recalculates price from fresh Redis LTP/avg and circuit data. It does not retry all clients. It passes only the failed `client_ids` for that group.

## Standalone StratX Orderbook Export

`scripts/fetch_order_book.py` is a separate utility script.

It:

1. Calls StratX report API page by page.
2. Fetches up to `MAX_PAGES`.
3. Saves the result to:

```text
Trades/YYYYMMDD.csv
```

It also logs to:

```text
fetch_order_book.log
```

Use this when you want a separate historical/orderbook export outside the live engine.

Run it from the repository root with:

```bat
scripts\fetch_order_book.cmd
```

The launcher changes back to the repository root and runs `python -m scripts.fetch_order_book`, so the script continues to use root-level `credentials.py` and writes to the existing `Trades/` directory.

## Standalone Scripts And Metrics

The files under `scripts/` and `metrics/` are not imported by the live runtime.

Operational and conversion scripts:

| File | Purpose |
| --- | --- |
| `scripts/fetch_order_book.py` | Downloads the StratX report orderbook into `Trades/YYYYMMDD.csv`. |
| `scripts/fetch_order_book.cmd` | Windows launcher for the standalone orderbook export. |
| `scripts/convert_trade_txt_to_csv.py` | Converts and groups an NSE/BSE source trade text file. |

Offline metrics:

| File | Purpose |
| --- | --- |
| `metrics/execute_delay.py` | Calculates StratX execution delay from exported TRADED rows. |
| `metrics/http_delay.py` | Extracts slow StratX HTTP entries from a log file. |
| `metrics/trades_min_max_filter.py` | Calculates the execution-time spread for each reference id. |
| `metrics/compare_latency_outputs.py` | Compares grouped source, GreekSoft, and StratX latency outputs. |

Run Python utilities from the repository root using module form, for example:

```bat
python -m scripts.convert_trade_txt_to_csv
python -m metrics.execute_delay
python -m metrics.compare_latency_outputs
```

## Circuit And Redis Support

`src/utils/fetch_circuit.py` contains:

### `get_redis_client(source)`

Creates and reuses one Redis client per configured Redis source. Current default source:

```python
{"name": "primary", "host": "100.103.231.7", "port": 6379, "db": 1}
```

The Redis client uses connect/read timeouts of 1 second. Clients are cached and reused; they are not recreated for every read.

### `get_circuit_limits(cache_symbol, ...)`

Reads:

```text
cache:CIRCUIT_<CACHE_SYMBOL>
```

from Redis and returns:

```python
{"ts": ..., "UC": ..., "LC": ...}
```

Successful responses are cached for 10 seconds.

Circuit data also uses the active Redis failover flow. If all sources fail, `get_circuit_limits()` returns `None`, and StratX continues without circuit clamping.

## File Watcher

`src/utils/file_watcher.py` uses `watchdog`.

It watches the directories containing the NSE and BSE trade files and reacts to:

* modified events,
* created events,
* moved events.

`CsvChangeHandler` uses per-file `threading.Event()` flags to avoid re-entering the same processing function while it is already running.

## Async Logger

`src/utils/async_logger.py` keeps log writes out of the order hot path.

It uses:

```python
logging.handlers.QueueHandler
logging.handlers.QueueListener
```

The caller queues the message and continues. A background listener writes to stdout and the daily log file.

If async logging fails, `fallback_log()` writes directly to stdout and file.

## GUI Wrapper

`src/zzEXE.py` creates a small Tkinter GUI.

The heading shows the selected broker, `copy_source_id`, and the destination GreekSoft username or StratX strategy name. Before startup, the GUI requires `copy_source_id`, requires `source_strategy_names` to be a list, tuple or set containing at least one nonblank strategy, validates all eight shared GreekSoft/StratX POS/NEG net limits as present and numeric, and additionally requires `STRATX_NET_CLIENT_ID` for StratX. All detected configuration errors are shown together and the algo is not started until they are corrected.

The top-right information icon shows broker, copy source, multiplier, and the four configured net ranges for both brokers. For StratX it also shows the net client id and, for Impulse Core, the selected Expiry/Non-Expiry mode and resulting OTM offset. While StratX is running, the popup retains the mode that was used at startup.

The Start Algo button runs:

```python
exec_script('src/zFinalMulti.py', on_algo_complete)
```

GUI output is routed through an unbounded thread-safe queue into separate `Logs` and `Errors (N)` tabs. Normal entries appear only in `Logs`; stderr, warnings, failed/rejected/error/failure prefixes, failed HTTP responses, connection-reset and orderbook retries, net-limit skips and quantity adjustments, ITM skips, pricing fallbacks, rate-limit hits, skipped paused/stale trades, queue overload, net rollback/release, Redis source switches, malformed-row errors and other audited attention prefixes appear only in `Errors (N)`. The count increases once per nonblank error entry. Prefix classification runs on the Tkinter thread in batches, while the existing daily log file keeps the complete mixed chronological sequence.

The Sync Net button is available for both brokers after the algo starts. It runs the selected broker's sync method in a daemon worker, disables the button during the sync, and restores it afterward. StratX continues using its existing TRADED-report sync; GreekSoft uses its GreekSoft orderbook `traded_qty` sync.

On close:

1. For StratX, it saves net and retry state; reconciliation state is saved only when reconciliation is enabled and its manager exists.
2. For GreekSoft, it saves `greek_net_state.json` and `greek_state.json` if the broker object is active.
3. It destroys the Tkinter root.
4. It calls `os._exit(0)` to terminate background threads.

## Setup

1. Create and activate a virtual environment.
2. Install requirements:

```bash
pip install -r requirements.txt
```

3. Configure `.env`:

```env
OPTION_INSTRUMENT_CSV=C:/path/to/options_instruments.csv
```

4. Edit `credentials.py`:

* choose `broker`,
* confirm NSE/BSE CSV paths,
* fill broker credentials,
* confirm freeze quantities,
* set `strategy_name` for `STRATX`,
* set `multiplier`,
* set StratX positive/negative net limits if using `STRATX`.

5. Start with:

```bat
run.cmd
```

## Common Troubleshooting

### StratX says instrument file not found

Check `.env`:

```env
OPTION_INSTRUMENT_CSV=...
```

and confirm the file exists before starting.

### Orders are not consumed

Check market time. Workers sleep outside:

```text
09:15 to 15:40
```

### StratX net limit order skipped

Check the relevant bucket range in `credentials.py`.

Example:

```python
NIFTY_CE_POS_NET = 65
NIFTY_CE_NEG_NET = 130
```

This means the final `NIFTY_CE` net must remain between:

```text
-130 and +65
```

Also check lot size. If the remaining limit is smaller than one valid lot, the order is skipped.

Example:

```text
Remaining positive limit = 35
NIFTY lot size = 65
Allowed partial quantity = 0
Order skipped
```

### StratX net file shows zero after order

Check whether the order was later released or rolled back.

Search logs for:

```text
STRATX_NET_RESERVED
STRATX_NET_RELEASE
STRATX_NET_ROLLBACK
```

`STRATX_NET_RESERVED` means quantity was reserved.

`STRATX_NET_RELEASE` means the order later reached a terminal failed orderbook state for `STRATX_NET_CLIENT_ID` and the reserved quantity was released.

`STRATX_NET_ROLLBACK` means local HTTP submission failed before a valid reference id was received, so the reservation was removed.

### StratX retry is not happening

Check:

* row status is `CANCEL`, or `REJECTED` with both `PRICE` and `LPP` in `order_message`,
* `reference_id` exists,
* `client_id` exists,
* `reference_id` is mapped in `state.json`,
* client has not reached `max_orderbook_retries`.

### StratX OTM or retry price fails

OTM/retry pricing uses Redis LTP data through the active Redis failover flow. If all configured Redis sources fail or return stale LTP data, the retry/OTM price is sent as `0` instead of using stale source-price fallback.

## XTS And Greeksoft Data Standardization

The StratX path is standardized so XTS-style and Greeksoft-style instrument data can both work when the structured fields are correct.

### Expiry Parsing

Instrument `ContractExpiration` is parsed flexibly:

```python
pd.to_datetime(df["ContractExpiration"], errors="coerce").dt.strftime("%Y%m%d")
```

This supports ISO datetime values such as:

```text
2026-07-14T14:30:00
2026-07-14T15:30:00
```

### BSE Contract Lookup

BSE contract details use `ExchangeInstrumentID`, not `Description`.

The cache is:

```python
StratX.bse_contract_by_exchange_id[exchange_instrument_id]
```

`placeOrderStratX_BSE()` reads:

```python
exchange_instrument_id = str(trade[4]).strip()
description = str(trade[5]).strip()
```

and resolves contract details with:

```python
get_bse_contract_details(exchange_instrument_id)
```

The `description` value is retained for logs/local metadata only.

### Monthly Expiry Descriptions

Vendor description formats can differ for monthly expiry, for example:

```text
NIFTY26JUL24500PE
NIFTY2672824500PE
```

Pricing and circuit lookup do not depend on these description strings. Redis keys are generated from structured fields:

```text
Name + DDMMMYY expiry + StrikePrice + CE/PE
```

Example:

```text
cache:LTP_NIFTY28JUL2624500PE
cache:CIRCUIT_NIFTY28JUL2624500PE
```
