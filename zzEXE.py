import tkinter as tk
from tkinter import ttk
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

def run_algo():
    algo_button.config(state='disabled')
    thread = threading.Thread(target=exec_script, args=('zFinalMulti.py', on_algo_complete))
    thread.start()

def on_algo_complete():
    algo_button.config(state='normal')

def on_close():
    try:
        broker_object = globals().get("brokerObj")
        if broker_object is not None and hasattr(broker_object, "save_retry_state_now"):
            broker_object.save_retry_state_now()
    except Exception as e:
        print(f"[WARN] Retry state final save failed: {e}")
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
                           text=f"Greek Mini Admin to Greek : {data}",
                           font=("Segoe UI", 18, 'bold'),
                           foreground="#404750")
subtitle_label.pack(anchor="center", pady=(4, 0))

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

algo_button = ttk.Button(button_frame, text="Start Algo", command=run_algo, style="Start.TButton")
algo_button.grid(row=0, column=0, padx=4, pady=4)

# Redirect stdout/stderr
sys.stdout = RedirectText(text_area)
sys.stderr = RedirectText(text_area)

root.protocol("WM_DELETE_WINDOW", on_close)
root.mainloop()