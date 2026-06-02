import datetime
import logging
import logging.handlers
import os
import queue
import sys


log_queue = queue.SimpleQueue()
listener = None
logger = logging.getLogger("trade")
log_format = "[%(asctime)s] : %(message)s"
date_format = "%H:%M:%S"


def fallback_log(*args, **kwargs):
    try:
        timestamp = datetime.datetime.now().strftime("[%H:%M:%S] :")
        msg = " ".join(map(str, args))
        if kwargs:
            msg += " " + " ".join(f"{key}={value}" for key, value in kwargs.items())
        print(timestamp, msg)

        today = datetime.datetime.now().strftime("%d_%m_%y")
        log_path = os.path.join("logs", f"{today}.txt")
        os.makedirs("logs", exist_ok=True)
        with open(log_path, "a", encoding="utf-8") as file:
            file.write(f"{timestamp} {msg}\n")
    except Exception:
        pass


def setup_async_logging(log_path=None):
    global listener

    try:
        if listener is not None:
            return

        if log_path is None:
            today = datetime.datetime.now().strftime("%d_%m_%y")
            log_path = os.path.join("logs", f"{today}.txt")

        log_dir = os.path.dirname(log_path)
        if log_dir:
            os.makedirs(log_dir, exist_ok=True)

        formatter = logging.Formatter(log_format, datefmt=date_format)

        file_handler = logging.FileHandler(log_path, mode="a", encoding="utf-8")
        file_handler.setFormatter(formatter)

        stdout_handler = logging.StreamHandler(sys.stdout)
        stdout_handler.setFormatter(formatter)

        queue_handler = logging.handlers.QueueHandler(log_queue)
        queue_handler.setLevel(logging.DEBUG)

        listener = logging.handlers.QueueListener(
            log_queue,
            file_handler,
            stdout_handler,
            respect_handler_level=True,
        )
        listener.start()

        logger.setLevel(logging.DEBUG)
        if not logger.handlers:
            logger.addHandler(queue_handler)
        logger.propagate = False
    except Exception as e:
        listener = None
        fallback_log(f"Async logger setup failed: {e}")


def printt(*args, **kwargs):
    try:
        if listener is None:
            setup_async_logging()

        if listener is None:
            fallback_log(*args, **kwargs)
            return

        msg = " ".join(map(str, args))
        if kwargs:
            msg += " " + " ".join(f"{key}={value}" for key, value in kwargs.items())
        logger.info(msg)
    except Exception as e:
        fallback_log(f"Async logger write failed: {e}")
        fallback_log(*args, **kwargs)


def createLogFile():
    try:
        today = datetime.datetime.now().strftime("%d_%m_%y")
        log_path = os.path.join("logs", f"{today}.txt")
        file_exists = os.path.isfile(log_path)
        setup_async_logging(log_path)
        if file_exists:
            printt(f"File already exists: {log_path}")
        else:
            printt(f"Created blank file: {log_path}")
    except Exception as e:
        fallback_log(f"Error in createLogFile: {e}")


def shutdown_logging():
    global listener

    try:
        if listener is not None:
            listener.stop()
            listener = None
    except Exception as e:
        fallback_log(f"Async logger shutdown failed: {e}")
        listener = None
