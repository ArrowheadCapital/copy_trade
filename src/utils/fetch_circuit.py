import datetime
import json
import time
from time import perf_counter
import redis
import threading
from dotenv import load_dotenv
import credentials as cre
from src.utils.async_logger import printt
from redis.backoff import NoBackoff
from redis.retry import Retry

load_dotenv()
redis_clients = {}
redis_lock = threading.Lock()
active_redis_index = 0
circuit_limits_cache = {}
CIRCUIT_LIMITS_CACHE_TTL = 10.0


def get_redis_sources():
    try:
        return getattr(cre, "redis_sources", [
            {"name": "DESKTOP-CLI5HO6", "host": "100.103.231.7", "port": 6379, "db": 1}
        ])
    except Exception as e:
        printt(f"Error in get_redis_sources: {e}")
        return [{"name": "DESKTOP-CLI5HO6", "host": "100.103.231.7", "port": 6379, "db": 1}]


def get_redis_client(source):
    try:
        key = (
            source["host"],
            int(source.get("port", 6379)),
            int(source.get("db", 1)),
        )

        client = redis_clients.get(key)
        if client is not None:
            return client

        with redis_lock:
            client = redis_clients.get(key)
            if client is None:
                client = redis.Redis(
                    host=source["host"],
                    port=int(source.get("port", 6379)),
                    db=int(source.get("db", 1)),
                    decode_responses=True,
                    max_connections=100,
                    socket_connect_timeout=1,
                    socket_timeout=1,
                    retry_on_timeout=False,
                    retry=Retry(NoBackoff(), 0)
                )
                redis_clients[key] = client

        return client

    except Exception as e:
        printt(f"Error in get_redis_client: {e}")
        raise


def get_redis_order():
    global active_redis_index

    sources = get_redis_sources()

    if not sources:
        return sources, []

    if active_redis_index >= len(sources):
        active_redis_index = 0

    order = [active_redis_index]
    for i in range(len(sources)):
        if i != active_redis_index:
            order.append(i)

    return sources, order


def make_redis_active(index, key):
    global active_redis_index

    try:
        sources = get_redis_sources()

        with redis_lock:
            if index != active_redis_index:
                old_source = sources[active_redis_index].get("name", f"redis_{active_redis_index}")
                new_source = sources[index].get("name", f"redis_{index}")
                active_redis_index = index
                printt(f"REDIS_ACTIVE_SWITCH | key={key} | from={old_source} | to={new_source}")

    except Exception as e:
        printt(f"Error in make_redis_active: {e}")


def parse_redis_time(value):
    try:
        value = str(value).strip()

        try:
            return datetime.datetime.strptime(value, "%Y-%m-%d %H:%M:%S.%f").timestamp()
        except Exception:
            pass

        try:
            return datetime.datetime.strptime(value, "%Y-%m-%d %H:%M:%S").timestamp()
        except Exception:
            pass

        return None

    except Exception:
        return None


def get_ltp_avg(cache_symbol):
    try:
        key = f"cache:LTP_{str(cache_symbol).strip().upper()}"
        sources, order = get_redis_order()

        for index in order:
            source = sources[index]
            source_name = source.get("name", f"redis_{index}")

            try:
                client = get_redis_client(source)
                raw_value = client.get(key)

                if raw_value is None:
                    printt(f"REDIS_LTP_FAILED | source={source_name} | key={key} | reason=missing_key")
                    continue

                data = json.loads(raw_value)
                payload = data.get("payload", {})

                tick_time = payload.get("Time")
                ltp = payload.get("LTP")
                reference_price = payload.get("reference_price")

                if tick_time is None or ltp is None:
                    printt(f"REDIS_LTP_FAILED | source={source_name} | key={key} | reason=missing_field")
                    continue

                tick_timestamp = parse_redis_time(tick_time)
                if tick_timestamp is None:
                    printt(f"REDIS_LTP_FAILED | source={source_name} | key={key} | reason=bad_time")
                    continue

                age = time.time() - tick_timestamp
                if age > 5:
                    printt(f"REDIS_LTP_FAILED | source={source_name} | key={key} | reason=stale | age={age:.2f}s")
                    continue

                result = {
                    "ltp": float(ltp),
                    "reference_price": float(reference_price) if reference_price is not None else None,
                    "time": tick_time,
                    "source": source_name,
                }

                if index != active_redis_index:
                    make_redis_active(index, key)

                return result

            except Exception as e:
                printt(f"REDIS_LTP_FAILED | source={source_name} | key={key} | error={e}")

        printt(f"REDIS_LTP_ALL_FAILED | key={key}")
        return None

    except Exception as e:
        printt(f"Error in get_ltp_avg: {e}")
        return None


def get_underlying_ltp(channel):
    try:
        normalized_channel = str(channel).strip().upper()
        key = f"cache:LTP_{normalized_channel}"
        sources, order = get_redis_order()

        for index in order:
            source = sources[index]
            source_name = source.get("name", f"redis_{index}")

            try:
                client = get_redis_client(source)
                raw_value = client.get(key)
                if raw_value is None:
                    printt(f"REDIS_UNDERLYING_FAILED | source={source_name} | key={key} | reason=missing_key")
                    continue

                data = json.loads(raw_value)
                payload = data.get("payload", {})

                tick_time = payload.get("Time")
                ltp = payload.get("LTP")

                if tick_time is None or ltp is None:
                    printt(f"REDIS_UNDERLYING_FAILED | source={source_name} | key={key} | reason=missing_field")
                    continue

                tick_timestamp = parse_redis_time(tick_time)
                if tick_timestamp is None:
                    printt(f"REDIS_UNDERLYING_FAILED | source={source_name} | key={key} | reason=bad_time")
                    continue

                age = time.time() - tick_timestamp
                if age > 10:
                    printt(f"REDIS_UNDERLYING_FAILED | source={source_name} | key={key} | reason=stale | age={age:.2f}s")
                    continue

                if index != active_redis_index:
                    make_redis_active(index, key)

                return float(ltp)

            except Exception as e:
                printt(f"REDIS_UNDERLYING_FAILED | source={source_name} | key={key} | error={e}")

        printt(f"REDIS_UNDERLYING_ALL_FAILED | key={key}")
        return None

    except Exception as e:
        printt(f"Error in get_underlying_ltp: {e}")
        return None


def get_circuit_limits(cache_symbol, host="100.103.231.7", port=6379, db=1):
    """
    Fetch circuit limits (UC and LC) for a given cache symbol from Redis.
    Cache successful responses per cache symbol for 10 seconds.
    
    Args:
        cache_symbol (str): Instrument cache symbol, for example NIFTY14JUL2619400CE
        host (str): Redis host (default: DESKTOP-CLI5HO6)
        port (int): Redis port (default: 6379)
        db (int): Redis DB index (default: 1)
        
    Returns:
        dict: Dictionary with 'UC' and 'LC' keys, or None if not found
    """
    try:
        cache_key = str(cache_symbol).strip().upper()
        if not cache_key:
            return None

        now = perf_counter()

        cached = circuit_limits_cache.get(cache_key)
        if cached is not None:
            cached_at, cached_result = cached
            if now - cached_at <= CIRCUIT_LIMITS_CACHE_TTL:
                return cached_result

        key = f"cache:CIRCUIT_{cache_key}"
        sources, order = get_redis_order()

        for index in order:
            source = sources[index]
            source_name = source.get("name", f"redis_{index}")

            try:
                raw_value = get_redis_client(source).get(key)

                if raw_value is None:
                    printt(f"REDIS_CIRCUIT_FAILED | source={source_name} | key={key} | reason=missing_key")
                    continue

                data = json.loads(raw_value)

                ts = data.get("ts")
                uc = data.get("UC")
                lc = data.get("LC")

                if ts is None or uc is None or lc is None:
                    printt(f"REDIS_CIRCUIT_FAILED | source={source_name} | key={key} | reason=missing_field")
                    continue

                tick_timestamp = parse_redis_time(ts)
                if tick_timestamp is None:
                    printt(f"REDIS_CIRCUIT_FAILED | source={source_name} | key={key} | reason=bad_time")
                    continue

                age = time.time() - tick_timestamp
                if age > 300:
                    printt(f"REDIS_CIRCUIT_FAILED | source={source_name} | key={key} | reason=stale | age={age:.2f}s")
                    continue

                result = {
                    "ts": ts,
                    "UC": float(uc),
                    "LC": float(lc),
                    "source": source_name,
                }

                circuit_limits_cache[cache_key] = (now, result)

                if index != active_redis_index:
                    make_redis_active(index, key)

                return result

            except Exception as e:
                printt(f"REDIS_CIRCUIT_FAILED | source={source_name} | key={key} | error={e}")

        printt(f"REDIS_CIRCUIT_ALL_FAILED | key={key}")
        return None
            
    except Exception as e:
        printt(f"Error in get_circuit_limits: {e}")
        return None
