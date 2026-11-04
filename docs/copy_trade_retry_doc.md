# Copy Trade Retry Behavior

## StratX

- An order is retried when its status is `CANCEL`, or when it is `REJECTED` and its message contains both `PRICE` and `LPP`.
- Each original order allows **2 retries per client**, targeting only failed clients.
- **The retry price is recalculated using current Redis pricing, with circuit and TER checks. An LPP rejection does not automatically force price `0`.** If pricing is unavailable or fails, the price becomes `0`; the payload still specifies `LIMIT`.
- A non-`200` placement response allows **3 total HTTP attempts**, including the original, with **0.3-second waits**. The price is recalculated before retrying.
- A connection reset `10054` is retried only if the request fails within **10 milliseconds**, using the same HTTP-attempt budget. Such a fast failure is treated as a likely connection failure before order acceptance, reducing duplicate-order risk. This is a timing assumption, not proof that the broker did not receive the order. Error `10054` means connection reset, not timeout; the 10 ms measures time until failure, not a wait before retrying.

## GreekSoft

- An order is retried when it is `CANCELLED`, or when it is `EXCHANGE REJECTED` with **BSE code `10008` or NSE code `17070`**. The remaining pending quantity must be greater than zero.
- Each original order allows **3 retries**, covering only the remaining pending quantity.
- **BSE `10008`, NSE `17070`, and `CANCELLED` with code `202` force retry price `0`.** Other cancellations use recalculated Redis pricing.
- Price also becomes `0` before **09:17**, when pricing is unavailable, or when LTP falls outside the TER range.
- A non-`2xx` placement response or an `IrisRejection` whose reason contains both `throttle` and `reached` allows **4 total HTTP attempts**, including the original, with **0.3-second waits**. Pricing is evaluated again for each attempt.
- A connection reset `10054` is retried only if the request fails within **10 milliseconds**, using the same HTTP-attempt budget. The same timing assumption described for StratX applies.
- A token-related HTTP `401` allows **4 authentication-recovery attempts**, with waits of **2, 4, and 8 seconds**.

For both brokers, eligible orderbook failures are retried on the next fetch. The polling loop waits **0.25 seconds between cycles**, plus API and processing time. Only orders tracked by this copier qualify for orderbook retries.

The orderbook retry limit and HTTP-attempt limit are separate: each orderbook retry submission has its own HTTP-attempt budget.
