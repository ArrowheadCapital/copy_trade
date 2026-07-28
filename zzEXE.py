import tkinter as tk
from tkinter import ttk, messagebox
from tkinter.scrolledtext import ScrolledText
import threading
import sys
import io
import os
import importlib
import credentials as cre
importlib.reload(cre)

import heading as hed

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

class RedirectText(io.StringIO):
    def __init__(self, text_widget):
        super().__init__()
        self.text_widget = text_widget

    def write(self, string):
        self.text_widget.configure(state='normal')
        self.text_widget.insert(tk.END, string)
        self.text_widget.see(tk.END)
        self.text_widget.configure(state='disabled')

    def flush(self):
        pass

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

    if cre.broker.upper() == "STRATX":
        if not str(getattr(cre, "STRATX_NET_CLIENT_ID", "") or "").strip():
            errors.append("STRATX_NET_CLIENT_ID is missing or empty")

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
        messagebox.showerror(
            "Configuration Error",
            "Please fix these settings in credentials.py:\n\n" + "\n".join(config_errors),
            parent=root,
        )
        return

    algo_button.config(state='disabled')
    if cre.broker.upper() == "STRATX":
        selected_mode = stratx_expiry_var.get().strip().upper().replace(" ", "_")
        stratx_started_mode = selected_mode
        os.environ["STRATX_EXPIRY_MODE"] = selected_mode
        print(f"[INFO] StratX expiry mode: {stratx_expiry_var.get()}")
    thread = threading.Thread(target=exec_script, args=('zFinalMulti.py', on_algo_complete))
    thread.start()

def on_algo_complete():
    global stratx_started_mode
    stratx_started_mode = None
    algo_button.config(state='normal')

def get_config_info():
    lines = [f"Multiplier: {cre.multiplier}"]

    if cre.broker.upper() == "STRATX":
        net_client_id = str(getattr(cre, "STRATX_NET_CLIENT_ID", "") or "").strip() or "Missing"

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

        lines.extend([
            "",
            f"Net Client ID: {net_client_id}",
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

def sync_stratx_net():
    broker_object = globals().get("brokerObj")
    if broker_object is None or not hasattr(broker_object, "sync_stratx_net_from_traded_orders"):
        print("[WARN] Start algo before syncing StratX net")
        return

    def sync_worker():
        try:
            root.after(0, lambda: sync_button.config(state='disabled'))
            ok = broker_object.sync_stratx_net_from_traded_orders(source="manual")
            if ok:
                print("[INFO] StratX net sync completed")
            else:
                print("[WARN] StratX net sync failed")
        except Exception as e:
            print(f"[WARN] StratX net sync error: {e}")
        finally:
            root.after(0, lambda: sync_button.config(state='normal'))

    threading.Thread(target=sync_worker, daemon=True).start()

def on_close():
    try:
        broker_object = globals().get("brokerObj")
        if broker_object is not None and hasattr(broker_object, "save_stratx_net_state_now"):
            broker_object.save_stratx_net_state_now()
        if broker_object is not None and hasattr(broker_object, "save_retry_state_now"):
            broker_object.save_retry_state_now()
    except Exception as e:
        print(f"[WARN] StratX state final save failed: {e}")
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

text_area = ScrolledText(
    logs_card,
    wrap=tk.WORD,
    font=("Consolas", 12),
    background="#f9fafb",
    foreground="#111827",
    borderwidth=0,
    relief="flat"
)
text_area.grid(row=0, column=0, sticky='nsew', padx=0, pady=0)
text_area.configure(height=20)

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

if cre.broker.upper() == "STRATX":
    sync_button = ttk.Button(button_frame, text="Sync Net", command=sync_stratx_net, style="Start.TButton")
    sync_button.grid(row=0, column=action_column + 2, padx=4, pady=4)

# Redirect stdout/stderr
sys.stdout = RedirectText(text_area)
sys.stderr = RedirectText(text_area)

root.protocol("WM_DELETE_WINDOW", on_close)
root.mainloop()
