# StratX Simulation Guide

This guide describes how to temporarily add back a local StratX simulator while keeping the normal copying, reconciliation, retry, net-limit, pricing, and state pipelines intact.

The simulator should replace only external StratX API input and output:

- order placement response;
- TRADED report fetch;
- failed orderbook fetch.

All internal production processing should continue through the real functions.

## Safety Rules

1. Keep simulation disabled by default.
2. Display a clear simulation banner at startup when it is enabled.
3. Never send a real StratX request while simulation is enabled.
4. Do not comment out or rewrite the normal `session.post()` implementation. Use an early simulator return before it so production code remains intact.
5. Do not change reconciliation, retry, net-limit, pricing, or state logic to make a test pass.
6. Remove every simulator import and branch after testing.

## Files To Add

### `stratx_simulator.py`

Create one temporary module with:

```text
ENABLED = False
ORDER_RESPONSE_DELAY_SECONDS
REPORT_FETCH_DELAY_SECONDS
TRADED_FETCH_FAILURES
OUTCOMES
STATE_FILE = "stratx_simulator_state.json"
```

It should expose these functions:

```python
place_order(payload, order_info, default_client_id)
get_traded_orders(client_id)
get_failed_orderbook()
```

`place_order()` should:

1. Read the first order from the normal StratX payload.
2. Use its explicit `client_ids`, or the reference client when the list is empty.
3. Generate a unique dummy `reference_id`.
4. Select the next configured outcome, preferably from a deterministic repeating sequence.
5. Wait for `ORDER_RESPONSE_DELAY_SECONDS`.
6. Store a TRADED row or a failed row using the same field names returned by the StratX orderbook.
7. Raise an exception for a configured dropped HTTP response.
8. Return `(reference_id, outcome)` for accepted responses.

Each dummy orderbook row should provide at least:

```text
id, reference_id, client_id, status, order_message,
exchange, segment, symbol, expiry, strike, right,
buyorsell, quantity, price, strategy_name, created_at, executed_on
```

Use a lock around shared rows and save them atomically through a temporary JSON file followed by `os.replace()`.

### `simulate_nifty_source.py`

Create a small NSE source generator that:

1. Reads `credentials.optionInstrumentPath`.
2. Selects NIFTY options from the nearest expiry on or after today.
3. Uses a short hardcoded contract list such as `("25000CE", "24000PE")`.
4. Writes only the fields consumed by the live NSE and reconciliation pipelines.
5. Appends rows to `credentials.pathNSE` using the current `{formatted_date}`.

The important NSE columns are:

```text
2=OPTIDX, 3=NIFTY, 4=expiry, 5=strike, 6=CE/PE,
7=description, 13=side, 14=quantity, 15=source price,
23=exchange order id, 25=trade time, 27=copy source id
```

Keep hardcoded controls near the top for contracts, pre-start orders, live orders, row count, interval, startup wait, and source price.

### `simulate_sensex_source.py`

Create the equivalent BSE generator using the nearest non-expired SENSEX option contracts.

The important BSE columns are:

```text
4=exchange instrument id, 5=description, 6=B/S,
7=quantity, 8=source price, 14=date, 15=time,
16=exchange order id, 17=field containing OPT,
last column=copy source id
```

Write pipe-separated rows to `credentials.pathBSE`.

## Temporary Integration Points

### `src/stratx/broker.py`

Import `stratx_simulator`, then add only these guarded branches:

1. At the start of `warmup_stratx_sessions()`, skip session warmup when enabled.
2. At the start of `fetch_stratx_traded_orders()`, return `get_traded_orders(STRATX_NET_CLIENT_ID)` when enabled.
3. At the start of `send_stratx_order_request()`, call `place_order()` and return its dummy reference when enabled.
4. At the start of StratX `getOrderBookALL()`, return `get_failed_orderbook()` when enabled.

Leave the normal code immediately after each branch unchanged, especially the real `session.post()` call and its HTTP retry logic.

### `src/zFinalMulti.py`

Import `stratx_simulator` and, only while it is enabled:

1. Print a prominent warning that real StratX API calls are disabled.
2. Allow testing before the normal 8:50 instrument cutoff.
3. Let `is_market_open()` return true for offline testing.
4. Give `COPY_ALLOWED_DELAY_SECONDS` a convenient test default if required.
5. Set `RECON_REPORT_ONLY` to false so simulated corrections are submitted to the fake endpoint.

Do not alter GreekSoft behavior.

## Suggested Test Controls

Prefer an explicit repeating outcome sequence instead of uncontrolled randomness. Useful sequences include:

```text
TRADED
REJECTED, TRADED
CANCEL, TRADED
DROP
TRADED, CANCEL, REJECTED
```

Useful delay controls:

```text
Fast functional run: 1 second order response and report fetch
Lifecycle inspection: 4-5 second response and report fetch
Source rows: 4-6 seconds apart
```

For continuous-trading pressure, start the source generator first, let it add several pre-start rows, then start `src/zFinalMulti.py` through the normal GUI and continue appending live rows.

## Running A Test

1. Set `ENABLED = True`.
2. Configure deterministic outcomes and delays.
3. Configure the source script's contracts and order sequence.
4. Clear only the intended test input, log, and JSON state files.
5. Run the selected NSE or BSE source generator.
6. Start the normal application.
7. Verify logs and `state.json`, `stratx_net_state.json`, `stratx_recon_state.json`, and `stratx_simulator_state.json`.
8. Stop both processes before changing the next scenario.

## Removal Checklist

After testing:

1. Remove the simulator import and all four guarded branches from `src/stratx/broker.py`.
2. Remove the simulator import, banner, cutoff bypass, market-hours bypass, and test-derived settings from `src/zFinalMulti.py`.
3. Confirm the real `session.post()` call is active.
4. Restore the intended production reconciliation values.
5. Delete `stratx_simulator.py`, both source-generator scripts, and `stratx_simulator_state.json`.
6. Search the repository for `simulator`, `simulate`, and `stratx_simulator`.
7. Compile the production Python files before running live.
