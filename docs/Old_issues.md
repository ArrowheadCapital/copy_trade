
```md
# StratX Issues Discussion Context

## 1. StratX Session / Connection Reset Issue

### Error Observed

```text
STRATX_FUTURE_FAILED | StratX order request failed | ... | http=2.8ms | error=('Connection aborted.', ConnectionResetError(10054, 'An existing connection was forcibly closed by the remote host'...))
```

### What This Means

This error means the HTTPS/TCP connection to StratX was closed/reset before our code received any HTTP response.

It is not an HTTP rejection like `400`, `500`, etc. No response body or status code was received.

### How Session Is Used

In `helperGS.py`, StratX uses a thread-local `requests.Session()`:

```python
session = self.get_stratx_session()
response = session.post(...)
```

`requests.Session()` is not one single connection. It is a reusable HTTP client that manages a pool of connections.

So:

```text
Session = connection manager
Connection = actual TCP/TLS socket inside that session
```

The session can reuse old keep-alive connections. If StratX/load balancer closes an idle connection, our next request may try to reuse that stale connection and get:

```text
ConnectionResetError(10054)
```

### Why Later Requests Can Still Work

Even if one connection inside the session is closed, the `Session` object still exists. Later `session.post()` calls may open a fresh connection and work.

### Practical Fix Discussed

For this specific error only:

```text
ConnectionResetError / requests ConnectionError
```

we can:

```text
1. Catch the connection error inside retry loop.
2. Close/reset the current thread-local session.
3. Create a fresh session.
4. Retry the same payload once.
```

### Why Reset Session

Resetting session clears stale pooled connections and forces a fresh TCP/TLS connection.

### What Not To Retry Blindly

Do not blindly retry:

```text
ReadTimeout
```

because the order request may have reached StratX and may later execute, so retrying can duplicate orders.

### Remaining Edge Case

Even with `ConnectionResetError`, duplicate risk is not mathematically zero.

Possible rare case:

```text
request reached StratX
order got placed
connection reset before response came back
retry sends same order again
```

But for our observed case:

```text
http=2.8ms / 3.2ms
```

it is more likely the request hit a stale/closed connection before processing.

### Final Policy Discussed

```text
ConnectionResetError:
  reset session + retry same payload once

ReadTimeout:
  do not retry blindly

HTTP non-200:
  keep existing retry/reprice logic
```

---

## 2. StratX Position Mismatch / Reconciliation Issue

### Goal

We want to detect mismatch between expected copy-trade position and actual StratX traded position for client:

```text
Y05601
```

Then optionally place correction orders for specific instruments to match position.

### Important Existing Code Reality

Current `trades.csv` is written by `fetch_order_book()` every `0.25s`.

But for StratX, current `getOrderBookALL()` fetches only:

```text
REJECTED
CANCEL
ERROR
```

So current `trades.csv` is not enough for actual traded position.

For actual StratX position, use:

```python
fetch_stratx_traded_orders()
```

which fetches:

```text
status: ["TRADED"]
```

### Position-Based Matching Preferred

We decided row-by-row/event matching is not preferred.

Preferred approach:

```text
Expected net position from source .txt / copy source
vs
Actual net position from StratX TRADED orders
```

Use signed quantity:

```text
BUY  = +qty
SELL = -qty
```

Compare instrument-wise:

```text
diff = expected_net - actual_net
```

Correction direction:

```text
diff > 0 -> BUY diff
diff < 0 -> SELL abs(diff)
```

### Why Simple Time Buffer Is Not Enough

We discussed using rows older than 30s/60s, but rejected that as the only safety mechanism.

Reason:

StratX trade updates can be delayed unpredictably. Even older rows can still appear as mismatch if StratX traded report is late.

So timing reduces false mismatches but cannot eliminate them.

### Safer Approach Discussed

Use repeated stable mismatch confirmation.

Run reconciliation in a separate slow thread:

```text
every 15-20 seconds
```

For each instrument:

```text
expected = source net position
actual = StratX TRADED net position
diff = expected - actual
```

Only correction eligible if:

```text
same instrument + same diff appears in 3 consecutive successful checks
```

If diff changes, reset counter.

Example:

```text
Check 1: diff=-65
Check 2: diff=-65
Check 3: diff=-65
=> eligible to correct SELL 65
```

If trading changes diff:

```text
Check 1: diff=-65
Check 2: diff=-65
Check 3: diff=-130
=> no correction, reset counter
```

### Starvation Possibility

Strict consecutive matching can starve forever.

Example:

```text
diff=-65
diff=-65
diff=-130
diff=-65
diff=-65
diff=-195
```

No 3 consecutive same diff, so no auto-correction.

We accepted this as safer because mismatch correction is not time-critical.

Optional handling:

```text
If mismatch exists for long time but never stabilizes:
  log/report STARVING_MISMATCH
  do not auto-correct
```

### Auto-Correction Safety

Correction should be done from a separate correction worker, not the live copy queues.

Do not use:

```text
NSE_QUEUE
BSE_QUEUE
```

Use separate reconciliation/correction path so live copy trading is not slowed.

### Recommended Guards

Before placing correction:

```text
- StratX TRADED fetch succeeded
- source read succeeded
- same instrument + same diff seen 3 consecutive checks
- correction qty is lot-size aligned
- correction qty is within max correction limit
- no active correction for same instrument
- same correction was not already sent recently
```

After correction:

```text
cooldown same instrument for 90-120 seconds
```

This avoids repeated correction while StratX trade book is still updating.

### Start Mode

First run in:

```text
REPORT_ONLY=True
```

Log mismatches only:

```text
STRATX_RECON_MISMATCH | instrument=... | expected=-195 | actual=-130 | diff=-65 | action=SELL 65 | mode=report_only
```

Only after validating logs, enable auto-correction.

### Remaining Edge Cases

There is no zero-false automatic correction using position snapshots only.

Remaining risks:

```text
1. StratX TRADED report delayed for long time.
2. Manual StratX trades for Y05601.
3. Source parsing/mapping mistake.
4. Volatility/Impulse transformation mismatch.
5. Partial fills.
6. Correction order itself delayed.
7. StratX API fetch failure.
8. Same instrument keeps trading, causing starvation.
```

### Important Policy Point

If manual StratX trades happen, reconciliation will see actual StratX position different from source position.

Need business decision:

```text
Should source .txt be absolute truth?
```

If yes, reconciliation may undo manual StratX trades.

If no, manual trades need reliable tagging/exclusion, otherwise system cannot know intention.

---

## Final Practical Recommendation

### Session Issue

```text
Retry only ConnectionResetError once.
Reset thread-local StratX session before retry.
Do not retry ReadTimeout blindly.
```

### Position Mismatch Issue

```text
Use source position vs StratX TRADED position.
Run separate reconciliation thread every 15-20s.
Require same instrument + same diff for 3 consecutive successful checks.
Start report-only.
Use separate correction worker.
Cooldown same instrument after correction.
Log starvation, do not force correction unless explicitly allowed.
```

```

```
