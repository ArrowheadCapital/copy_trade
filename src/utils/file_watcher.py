import os
import threading

from src.utils.async_logger import printt
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer


class CsvChangeHandler(FileSystemEventHandler):
    def __init__(self, nse_path, bse_path, on_nse_change, on_bse_change):
        super().__init__()
        self.nse_path = os.path.abspath(nse_path)
        self.bse_path = os.path.abspath(bse_path)
        self.on_nse_change = on_nse_change
        self.on_bse_change = on_bse_change
        self.nse_pending = threading.Event()
        self.bse_pending = threading.Event()

    def dispatch_nse(self):
        try:
            if self.nse_pending.is_set():
                return
            self.nse_pending.set()
            try:
                self.on_nse_change()
            finally:
                self.nse_pending.clear()
        except Exception as e:
            self.nse_pending.clear()
            printt(f"File watcher NSE dispatch error: {e}")

    def dispatch_bse(self):
        try:
            if self.bse_pending.is_set():
                return
            self.bse_pending.set()
            try:
                self.on_bse_change()
            finally:
                self.bse_pending.clear()
        except Exception as e:
            self.bse_pending.clear()
            printt(f"File watcher BSE dispatch error: {e}")

    def on_modified(self, event):
        try:
            if event.is_directory:
                return
            path = os.path.abspath(event.src_path)
            if path == self.nse_path:
                self.dispatch_nse()
            elif path == self.bse_path:
                self.dispatch_bse()
        except Exception as e:
            printt(f"File watcher modified-event error: {e}")
            return

    def on_created(self, event):
        try:
            self.on_modified(event)
        except Exception as e:
            printt(f"File watcher created-event error: {e}")
            return

    def on_moved(self, event):
        try:
            if event.is_directory:
                return
            path = os.path.abspath(event.dest_path)
            if path == self.nse_path:
                self.dispatch_nse()
            elif path == self.bse_path:
                self.dispatch_bse()
        except Exception as e:
            printt(f"File watcher moved-event error: {e}")
            return


def start_file_watcher(nse_path, bse_path, on_nse_change, on_bse_change):
    try:
        nse_abs = os.path.abspath(nse_path)
        bse_abs = os.path.abspath(bse_path)
        nse_dir = os.path.dirname(nse_abs) or "."
        bse_dir = os.path.dirname(bse_abs) or "."

        handler = CsvChangeHandler(nse_abs, bse_abs, on_nse_change, on_bse_change)
        observer = Observer()
        observer.schedule(handler, nse_dir, recursive=False)
        if os.path.abspath(bse_dir) != os.path.abspath(nse_dir):
            observer.schedule(handler, bse_dir, recursive=False)
        observer.daemon = True
        observer.start()
        return observer
    except Exception as e:
        printt(f"File watcher startup error: {e}")
        return None
