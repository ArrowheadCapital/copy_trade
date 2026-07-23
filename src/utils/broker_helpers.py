from src.utils.async_logger import createLogFile as async_create_log_file
from src.utils.async_logger import printt as async_printt


def printt(*args, **kwargs):
    async_printt(*args, **kwargs)


def saveInLogFile(*args, **kwargs):
    async_printt(*args, **kwargs)


def createLogFile():
    async_create_log_file()


def round_to_tick(price: float, tick: float) -> float:
    return round(tick * round(price / tick), 2)


def adjust_price_to_tick(price, tick_size, side, market_order_offset):
    offset = price * (market_order_offset / 100)

    if price <= 50:
        offset = market_order_offset

    if side == "BUY":
        price += offset
    else:
        price = max(tick_size, price - offset)

    return round_to_tick(price, tick_size)
