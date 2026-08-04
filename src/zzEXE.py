import tkinter as tk
from tkinter import ttk, messagebox
from tkinter.scrolledtext import ScrolledText
import threading
import sys
import io
import os
import importlib
import queue
from pathlib import Path

repository_root = str(Path(__file__).resolve().parent.parent)
if repository_root not in sys.path:
    sys.path.insert(0, repository_root)

import credentials as cre
importlib.reload(cre)

from src import heading as hed

data = hed.data
copy_trade_paused = threading.Event()
stratx_started_mode = None
STRATX_NET_LIMIT_NAMES = (
    "NIFTY_CE_POS_NET",
    "NIFTY_CE_NEG_NET",
    "NIFTY_PE_POS_NET",
    "NIFTY_PE_NEG_NET",
    "SENSEX_CE_POS_NET",
    "SENSEX_CE_NEG_NET",
    "SENSEX_PE_POS_NET",
    "SENSEX_PE_NEG_NET",
)

GUI_LOG_QUEUE = queue.SimpleQueue()
GUI_LOG_BATCH_SIZE = 500
GUI_LOG_IDLE_POLL_MS = 10
ERROR_PREFIX_MARKERS = ("ERROR", "FAILED", "REJECTED", "FAILURE")
ERROR_EXACT_PREFIXES = {
    "GREEK_CONNECTION_RESET_RETRY",
    "GREEK_HTTP_RETRY",
    "GREEK_HTTP_RETRY_RESPONSE",
    "GREEK_NET_LIMIT_SKIP",
    "GREEK_NET_ORDER_QTY_ADJUSTED",
    "GREEK_NET_PARTIAL_ALLOWED",
    "GREEK_NET_RELEASE",
    "GREEK_NET_ROLLBACK",
    "GREEK_ORDERBOOK_RETRY_SKIP",
    "GREEK_ORDERBOOK_RETRY_ENQUEUE",
    "GREEK_PRICE_FALLBACK",
    "ORDERID SAVING SKIP",
    "QUEUE LOAD",
    "RATE LIMIT HIT",
    "REDIS_ACTIVE_SWITCH",
    "STRATX_NET_SYNC_SKIPPED",
    "STRATX_CONNECTION_RESET_RETRY",
    "STRATX_HTTP_RETRY_REPRICE",
    "STRATX_HTTP_RETRY_RESPONSE",
    "STRATX_NET_LIMIT_SKIP",
    "STRATX_NET_ORDERBOOK_RELEASE_SKIPPED",
    "STRATX_NET_ORDER_QTY_ADJUSTED",
    "STRATX_NET_PARTIAL_ALLOWED",
    "STRATX_NET_RELEASE",
    "STRATX_NET_RELEASE_SKIPPED",
    "STRATX_NET_ROLLBACK",
    "STRATX_ORDERBOOK_RETRY_SUBMIT",
    "STRATX_RECON_CORRECTION_SKIPPED",
    "STRATX_RECON_SKIPPED",
    "STRATX_RECON_STATE_COOLDOWN_SKIPPED",
    "STRATX_RECON_STATE_PENDING_SKIPPED",
}


def get_log_prefix(line):
    message = str(line).strip()
    if message.startswith("[") and "] : " in message:
        message = message.split("] : ", 1)[1].strip()
    return message.split(" | ", 1)[0].strip()


def is_error_log_line(line, is_stderr=False):
    if is_stderr:
        return True

    prefix = get_log_prefix(line).upper()
    if not prefix:
        return False
    if prefix.startswith(("[WARN]", "[ERROR")):
        return True
    if any(marker in prefix for marker in ERROR_PREFIX_MARKERS):
        return True
    if prefix in ERROR_EXACT_PREFIXES:
        return True
    if prefix.endswith(("_ROW_SKIPPED", "_OVER_LIMIT", "_MISSING", "_MISMATCH")):
        return True
    if prefix.startswith(("INSTRUMENT MASTER UPDATES", "INVALID TRADE DATA", "INVALID BSE TRADE DATA", "INSTRUMENT FILE NOT FOUND", "NO ORDER UPDATE", "PRICE NOT PRESENT", "SKIPPING CE BEYOND", "SKIPPING ITM CHECK", "SKIPPING PE BEYOND", "SYMBOL NOT WHITELISTED", "THE FOLDER", "THIS IS FINAL STATUS OF ORDER")):
        return True
    if "HEADER MISMATCH" in prefix or prefix.endswith("COPY FILTER CONFIGURATION MISSING"):
        return True
    if prefix.endswith(" PAUSED: SKIPPED") or " PAUSED: SKIPPED " in prefix or prefix.endswith(" SKIP DELAY"):
        return True
    return "ORDER STATUS RETRY" in prefix


class RedirectText(io.StringIO):
    def __init__(self, stream_name):
        super().__init__()
        self.stream_name = stream_name

    def write(self, string):
        if string:
            GUI_LOG_QUEUE.put((self.stream_name, str(string)))
        return len(string)

    def flush(self):
        GUI_LOG_QUEUE.put((self.stream_name, None))

def exec_script(script_name, on_complete):
    try:
        with open(script_name, 'r') as f:
            code = f.read()
        exec(code, globals())
    except Exception as e:
        print(f"[Error executing {script_name}]: {e}")
    finally:
        on_complete()

def get_start_config_errors():
    errors = []

    if not str(getattr(cre, "copy_source_id", "") or "").strip():
        errors.append("copy_source_id is missing or empty")

    source_strategy_names = getattr(cre, "source_strategy_names", [])
    if not isinstance(source_strategy_names, (list, tuple, set)) or not any(str(name).strip() for name in source_strategy_names):
        errors.append("source_strategy_names must contain at least one strategy")

    if cre.broker.upper() == "STRATX" and not str(getattr(cre, "STRATX_NET_CLIENT_ID", "") or "").strip():
        errors.append("STRATX_NET_CLIENT_ID is missing or empty")

    if cre.broker.upper() in ("STRATX", "GREEK"):
        for name in STRATX_NET_LIMIT_NAMES:
            value = getattr(cre, name, None)
            if value is None or not str(value).strip():
                errors.append(f"{name} is missing or empty")
                continue
            try:
                int(float(value))
            except (TypeError, ValueError, OverflowError):
                errors.append(f"{name} must be numeric")

    return errors

def run_algo():
    global stratx_started_mode
    config_errors = get_start_config_errors()
    if config_errors:
        messagebox.showerror("Configuration Error", "Please fix these settings in credentials.py:\n\n" + "\n".join(config_errors), parent=root)
        return

    algo_button.config(state='disabled')
    if cre.broker.upper() == "STRATX":
        selected_mode = stratx_expiry_var.get().strip().upper().replace(" ", "_")
        stratx_started_mode = selected_mode
        os.environ["STRATX_EXPIRY_MODE"] = selected_mode
        print(f"[INFO] StratX expiry mode: {stratx_expiry_var.get()}")
    thread = threading.Thread(target=exec_script, args=('src/zFinalMulti.py', on_algo_complete))
    thread.start()

def on_algo_complete():
    global stratx_started_mode
    stratx_started_mode = None
    algo_button.config(state='normal')

def get_config_info():
    broker_name = cre.broker.upper()
    lines = [
        f"Broker: {broker_name}",
        f"Copy Source ID: {str(getattr(cre, 'copy_source_id', '') or '').strip() or 'Missing'}",
        f"Multiplier: {cre.multiplier}",
    ]

    if broker_name == "STRATX":
        net_client_id = str(getattr(cre, "STRATX_NET_CLIENT_ID", "") or "").strip() or "Missing"
        lines.append(f"Net Client ID: {net_client_id}")

        if str(cre.strategy_name).strip().upper() == "IMPULSE CORE":
            mode = stratx_started_mode or stratx_expiry_var.get().strip().upper().replace(" ", "_")
            offset = 1 if mode == "EXPIRY" else 0
            lines.append(f"OTM Offset: {offset} ({mode.replace('_', ' ').title()})")

    def net_range(bucket):
        try:
            pos_limit = max(int(float(getattr(cre, f"{bucket}_POS_NET"))), 0)
            neg_limit = max(int(float(getattr(cre, f"{bucket}_NEG_NET"))), 0)
            return f"-{neg_limit} to +{pos_limit}"
        except (AttributeError, TypeError, ValueError, OverflowError):
            return "Missing/invalid"

    if broker_name in ("STRATX", "GREEK"):
        lines.extend([
            "",
            "Allowed Net Quantity:",
            f"NIFTY CE:  {net_range('NIFTY_CE')}",
            f"NIFTY PE:  {net_range('NIFTY_PE')}",
            f"SENSEX CE: {net_range('SENSEX_CE')}",
            f"SENSEX PE: {net_range('SENSEX_PE')}",
        ])

    return "\n".join(lines)

info_popup = None

def show_config_info(event):
    global info_popup
    if info_popup is not None:
        return

    info_popup = tk.Toplevel(root)
    info_popup.wm_overrideredirect(True)
    info_label = tk.Label(
        info_popup,
        text=get_config_info(),
        justify=tk.LEFT,
        background="#fffbea",
        foreground="#111827",
        relief="solid",
        borderwidth=1,
        padx=10,
        pady=8,
        font=("Segoe UI", 10),
    )
    info_label.pack()
    info_popup.update_idletasks()
    x = event.widget.winfo_rootx() + event.widget.winfo_width() + 4
    y = event.widget.winfo_rooty() + event.widget.winfo_height() + 4
    info_popup.wm_geometry(f"+{x}+{y}")

def hide_config_info(_event):
    global info_popup
    if info_popup is not None:
        info_popup.destroy()
        info_popup = None

def toggle_pause():
    if copy_trade_paused.is_set():
        copy_trade_paused.clear()
        pause_button.config(text="Pause")
        print("[INFO] Copy trade resumed")
    else:
        copy_trade_paused.set()
        pause_button.config(text="Resume")
        print("[INFO] Copy trade paused")

def sync_broker_net():
    broker_object = globals().get("brokerObj")
    broker_name = cre.broker.upper()
    sync_method_name = "sync_stratx_net_from_traded_orders" if broker_name == "STRATX" else "sync_greek_net_from_traded_orders"
    if broker_object is None or not hasattr(broker_object, sync_method_name):
        print(f"[WARN] Start algo before syncing {broker_name} net")
        return

    def sync_worker():
        try:
            root.after(0, lambda: sync_button.config(state='disabled'))
            ok = getattr(broker_object, sync_method_name)(source="manual")
            if ok:
                print(f"[INFO] {broker_name} net sync completed")
            else:
                print(f"[WARN] {broker_name} net sync failed")
        except Exception as e:
            print(f"[WARN] {broker_name} net sync error: {e}")
        finally:
            root.after(0, lambda: sync_button.config(state='normal'))

    threading.Thread(target=sync_worker, daemon=True).start()

def on_close():
    try:
        broker_object = globals().get("brokerObj")
        if cre.broker.upper() == "STRATX":
            if broker_object is not None and hasattr(broker_object, "save_stratx_net_state_now"):
                broker_object.save_stratx_net_state_now()
            if broker_object is not None and hasattr(broker_object, "save_retry_state_now"):
                broker_object.save_retry_state_now()
            if bool(globals().get("STRATX_RECONCILIATION_ENABLED", False)):
                reconciliation_manager = globals().get("stratx_reconciliation_manager")
                if reconciliation_manager is not None:
                    reconciliation_manager.save_state_now()
        elif cre.broker.upper() == "GREEK":
            if broker_object is not None and hasattr(broker_object, "save_greek_net_state_now"):
                broker_object.save_greek_net_state_now()
            if broker_object is not None and hasattr(broker_object, "save_retry_state_now"):
                broker_object.save_retry_state_now()
    except Exception as e:
        print(f"[WARN] Broker state final save failed: {e}")
    print("[INFO] Exiting application and terminating all threads.")
    root.destroy()
    os._exit(0)

# GUI Setup
root = tk.Tk()
root.title("Easy Automation")
root.geometry("750x500")
root.configure(bg="#ffffff")

# Style configuration
style = ttk.Style()
style.theme_use("clam")

primary_color = "#3b82f6"
hover_color = "#2563eb"
text_color = "#ffffff"

style.configure("TButton",
                font=("Segoe UI", 12, "bold"),
                padding=14,
                background=primary_color,
                foreground=text_color)
style.map("TButton",
          background=[("active", hover_color), ("disabled", "#a0aec0")],
          foreground=[("disabled", "#f0f0f0")])
style.configure("TFrame", background="#ffffff")
style.configure("TLabel", background="#ffffff", font=("Segoe UI", 12))

style.configure("Card.TFrame", background="#f0f4f8", relief="raised", borderwidth=1)
style.configure("Save.TButton",
                font=("Segoe UI", 12, "bold"),
                padding=(12, 8),
                background="#10b981",
                foreground="white",
                borderwidth=0)
style.map("Save.TButton",
          background=[("active", "#059669"), ("disabled", "#9ca3af")])
style.configure("Start.TButton",
                font=("Segoe UI", 12, "bold"),
                padding=(12, 8),
                background="#3b82f6",
                foreground="white",
                borderwidth=0)
style.map("Start.TButton",
          background=[("active", "#2563eb"), ("disabled", "#a0aec0")])

# --- Title and Logo ---
title_frame = ttk.Frame(root)
title_frame.pack(pady=(20, 10))

inner_frame = ttk.Frame(title_frame)
inner_frame.pack()


text_container = ttk.Frame(inner_frame)
text_container.pack(side=tk.LEFT)

subtitle_label = ttk.Label(text_container,
                           text=data,
                           font=("Segoe UI", 18, 'bold'),
                           foreground="#404750")
subtitle_label.pack(anchor="center", pady=(4, 0))

info_icon = ttk.Label(root, text="ⓘ", font=("Segoe UI", 16), foreground="#3b82f6", cursor="hand2")
info_icon.place(relx=1.0, x=-16, y=12, anchor="ne")
info_icon.bind("<Enter>", show_config_info)
info_icon.bind("<Leave>", hide_config_info)

# --- Logs Display ---
logs_card = ttk.Frame(root, padding=20, style="Card.TFrame")
logs_card.pack(expand=True, fill='both', padx=20, pady=(0, 10))
logs_card.columnconfigure(0, weight=1)
logs_card.rowconfigure(0, weight=1)

logs_notebook = ttk.Notebook(logs_card)
logs_notebook.grid(row=0, column=0, sticky='nsew', padx=0, pady=0)

normal_logs_tab = ttk.Frame(logs_notebook)
error_logs_tab = ttk.Frame(logs_notebook)
logs_notebook.add(normal_logs_tab, text="Logs")
logs_notebook.add(error_logs_tab, text="Errors (0)")

normal_logs_tab.columnconfigure(0, weight=1)
normal_logs_tab.rowconfigure(0, weight=1)
error_logs_tab.columnconfigure(0, weight=1)
error_logs_tab.rowconfigure(0, weight=1)

text_area = ScrolledText(
    normal_logs_tab,
    wrap=tk.WORD,
    font=("Consolas", 12),
    background="#f9fafb",
    foreground="#111827",
    borderwidth=0,
    relief="flat"
)
text_area.grid(row=0, column=0, sticky='nsew', padx=0, pady=0)
text_area.configure(height=20)

error_text_area = ScrolledText(
    error_logs_tab,
    wrap=tk.WORD,
    font=("Consolas", 12),
    background="#fff7f7",
    foreground="#991b1b",
    borderwidth=0,
    relief="flat"
)
error_text_area.grid(row=0, column=0, sticky='nsew', padx=0, pady=0)
error_text_area.configure(height=20)

gui_log_buffers = {"stdout": "", "stderr": ""}
gui_error_count = 0


def append_gui_log_batch(widget, lines):
    if not lines:
        return
    widget.configure(state='normal')
    widget.insert(tk.END, "".join(lines))
    widget.see(tk.END)
    widget.configure(state='disabled')


def process_gui_log_queue():
    global gui_error_count
    normal_lines = []
    error_lines = []
    processed = 0

    while processed < GUI_LOG_BATCH_SIZE:
        try:
            stream_name, chunk = GUI_LOG_QUEUE.get_nowait()
        except queue.Empty:
            break

        processed += 1
        buffered = gui_log_buffers.get(stream_name, "")
        if chunk is None:
            complete_lines = [buffered] if buffered else []
            gui_log_buffers[stream_name] = ""
        else:
            combined = buffered + chunk
            complete_lines = combined.splitlines(keepends=True)
            if complete_lines and not complete_lines[-1].endswith(("\n", "\r")):
                gui_log_buffers[stream_name] = complete_lines.pop()
            else:
                gui_log_buffers[stream_name] = ""

        for line in complete_lines:
            if is_error_log_line(line, is_stderr=stream_name == "stderr"):
                error_lines.append(line)
                if line.strip():
                    gui_error_count += 1
            else:
                normal_lines.append(line)

    append_gui_log_batch(text_area, normal_lines)
    append_gui_log_batch(error_text_area, error_lines)
    if error_lines:
        logs_notebook.tab(error_logs_tab, text=f"Errors ({gui_error_count})")

    if processed == GUI_LOG_BATCH_SIZE:
        root.after_idle(process_gui_log_queue)
    else:
        root.after(GUI_LOG_IDLE_POLL_MS, process_gui_log_queue)

# --- Action Button ---
button_frame = ttk.Frame(logs_card)
button_frame.grid(row=1, column=0, pady=10)

stratx_expiry_var = tk.StringVar(value="Non Expiry")
action_column = 0
if cre.broker.upper() == "STRATX":
    expiry_label = ttk.Label(button_frame, text="Expiry Mode")
    expiry_label.grid(row=0, column=0, padx=(4, 2), pady=4)

    expiry_dropdown = ttk.Combobox(
        button_frame,
        textvariable=stratx_expiry_var,
        values=("Non Expiry", "Expiry"),
        state="readonly",
        width=12
    )
    expiry_dropdown.grid(row=0, column=1, padx=(2, 8), pady=4)
    action_column = 2

algo_button = ttk.Button(button_frame, text="Start Algo", command=run_algo, style="Start.TButton")
algo_button.grid(row=0, column=action_column, padx=4, pady=4)

pause_button = ttk.Button(button_frame, text="Pause", command=toggle_pause, style="Start.TButton")
pause_button.grid(row=0, column=action_column + 1, padx=4, pady=4)

if cre.broker.upper() in ("STRATX", "GREEK"):
    sync_button = ttk.Button(button_frame, text="Sync Net", command=sync_broker_net, style="Start.TButton")
    sync_button.grid(row=0, column=action_column + 2, padx=4, pady=4)

# Redirect stdout/stderr
sys.stdout = RedirectText("stdout")
sys.stderr = RedirectText("stderr")
root.after(GUI_LOG_IDLE_POLL_MS, process_gui_log_queue)

root.protocol("WM_DELETE_WINDOW", on_close)
root.mainloop()
