import datetime
import time

from src.utils.broker_helpers import printt, round_to_tick
from src.utils.fetch_circuit import get_circuit_limits, get_ltp_avg


today_expiry_token = datetime.date.today().strftime("%d%b%y").upper()
redis_ltp_avg_cache = {}
redis_ltp_avg_cache_ttl = 0.2


def apply_circuit_clamp(price, cache_symbol):
    try:
        if not cache_symbol:
            return price

        limits = get_circuit_limits(cache_symbol)
        if not limits:
            return price

        uc = limits.get("UC")
        lc = limits.get("LC")
        ts = limits.get("ts")
        if uc is None or lc is None or ts is None:
            return price

        uc = float(uc)
        lc = float(lc)

        try:
            tick_time = datetime.datetime.strptime(str(ts), "%Y-%m-%d %H:%M:%S.%f").timestamp()
        except Exception:
            tick_time = datetime.datetime.strptime(str(ts), "%Y-%m-%d %H:%M:%S").timestamp()

        if time.time() - tick_time > 300:
            return price

        if price > uc:
            return uc
        if price < lc:
            return lc
        return price
    except Exception as e:
        printt(f"Error in apply_circuit_clamp: {e}")
        return price


def build_cache_symbol(name, expiry, strike, right):
    try:
        strike_val = float(strike)
        if strike_val.is_integer():
            strike_str = str(int(strike_val))
        else:
            strike_str = str(strike).strip()
        return f"{str(name).strip().upper()}{str(expiry).strip().upper()}{strike_str}{str(right).strip().upper()}"
    except Exception:
        return None


def get_redis_ltp_avg(cache_symbol):
    try:
        tt0 = time.perf_counter()
        cache_key = str(cache_symbol).strip().upper()
        cached = redis_ltp_avg_cache.get(cache_key)
        if cached is not None:
            cached_at, cached_result = cached
            if tt0 - cached_at <= redis_ltp_avg_cache_ttl:
                return cached_result

        data = get_ltp_avg(cache_key)
        if not data:
            return 0, 0

        result = (data["ltp"], data["reference_price"])
        redis_ltp_avg_cache[cache_key] = (time.perf_counter(), result)
        return result
    except Exception as e:
        printt(f"Redis tick read error ({cache_symbol}): {e}")
        return 0, 0


def price_from_avg_ltp_or_fallback(side, tick_size, cache_symbol=None):
    try:
        if cache_symbol:
            ltp, reference_price = get_redis_ltp_avg(cache_symbol)

            if ltp == 0 and reference_price == 0:
                return 0

            if ltp is not None:
                cache_key = str(cache_symbol).strip().upper()
                is_bse_expiry = cache_key.startswith(("SENSEX", "BANKEX")) and today_expiry_token in cache_key

                def get_offset(value):
                    if is_bse_expiry:
                        return max(value * 0.30, 7.5)
                    return max(value * 0.30, 15)

                offset_ltp = get_offset(ltp)

                if reference_price is None:
                    if str(side).upper() == "BUY":
                        raw = ltp + offset_ltp
                    else:
                        raw = max(float(tick_size), ltp - offset_ltp)
                elif str(side).upper() == "BUY":
                    reference_price_calculated = reference_price + get_offset(reference_price)
                    raw = (ltp + offset_ltp) if (reference_price_calculated <= ltp) else reference_price_calculated
                else:
                    reference_price_calculated = reference_price - get_offset(reference_price)
                    raw = (ltp - offset_ltp) if (reference_price_calculated >= ltp) else reference_price_calculated
                    raw = max(float(tick_size), raw)

                price = round_to_tick(raw, float(tick_size))
                if price <= 0:
                    price = float(tick_size)
                price = apply_circuit_clamp(price, cache_symbol)
                return price

        return 0
    except Exception as e:
        printt(f"Error in price_from_avg_ltp_or_fallback: {e}")
        return 0
