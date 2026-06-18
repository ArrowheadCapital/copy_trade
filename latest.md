# Latest Changes

## helperGS.py

- Added Greeksoft order worker settings and runtime state:
  - `greek_order_workers`
  - request timeout
  - retry state file path
  - retry-state save interval
  - max orderbook retry count
- Added a `ThreadPoolExecutor` for Greeksoft order placement so split orders are submitted asynchronously instead of blocking in the main order flow.
- Added per-worker `requests.Session` reuse with connection pooling for Greeksoft HTTP calls.
- Added Greeksoft session warmup after login so worker sessions are initialized before live orders start.
- Added timeouts to Greeksoft auth, login, instrument download, order submit, warmup, and orderbook HTTP calls.
- Added precomputed contract lookup maps after instrument download:
  - NSE lookup by symbol, expiry, strike, and option type
  - BSE lookup by exchange token
  - Greek token lookup for lot-size recovery
- Updated `getData()` and `getDataBSE()` to use the precomputed lookup maps before falling back to DataFrame filtering.
- Reworked Greeksoft `placeOrder()` and `placeOrderBSE()`:
  - still split quantities by freeze quantity
  - now build order tasks
  - enqueue tasks into the Greeksoft worker pool
  - return immediately with an empty list instead of returning submitted order ids synchronously
- Added common Greeksoft order task/payload helpers:
  - original order task creation
  - payload construction
  - async order submit
  - future-result logging
- Added persistent Greeksoft retry tracking in `greek_state.json`:
  - maps Greeksoft `gorderid` to root order id
  - tracks retry count per root order
  - tracks already-processed failed order ids
  - normalizes state daily
  - saves state through a background saver thread and at process exit
- Added Greeksoft orderbook retry handling:
  - detects cancelled orderbook rows with pending quantity
  - finds the original root order by `gorderid`
  - skips already processed failures
  - caps retry count using `max_greek_orderbook_retries`
  - rebuilds retry order tasks from orderbook row fields
  - enqueues retry orders through the same Greeksoft order pool
- Added helper methods for retry row parsing, freeze quantity lookup, lot-size lookup from Greek token, and retry task construction.
- Changed Greeksoft login error logging so it no longer references possibly undefined response data.

## zFinalMulti.py

- Extended `fetch_order_book()` retry processing.
- Existing StratX retry handling remains unchanged.
- Added Greeksoft branch:
  - when `BROKER == "GREEK"`, calls `brokerObj.retry_failed_greeksoft_orders(data)`
  - wraps the retry call in its own try/except and logs `Greeksoft orderbook retry processor error` on failure.

## Important Behavior Notes

- Greeksoft order placement is now fire-and-forget from `placeOrder()` / `placeOrderBSE()` because order ids are registered asynchronously when each worker receives a `gorderid`.
- The retry system depends on successfully registering original `gorderid` values into `greek_state.json`.
- The retry state is date-scoped; old state is discarded when the date changes.
- Current retry limit is one retry per root order through `max_greek_orderbook_retries = 1`.

## To Continue Later

- Verify live Greeksoft order submission after the async worker change.
- Verify `greek_state.json` is created and updated with original order ids.
- Verify cancelled Greeksoft orderbook rows expose the expected fields:
  - `order_status`
  - `pending_qty`
  - `gorderid`
  - `regular_lot`
  - `token`
  - `scripName`
  - `exchange`
  - `side`
- Confirm retry order side values from orderbook rows match the values expected by Greeksoft `NewOrderRequest`.
- Confirm returning `[]` from `placeOrder()` and `placeOrderBSE()` does not break any caller that previously expected order ids.
- Consider whether async order submission needs shutdown handling for pending futures before process exit.
