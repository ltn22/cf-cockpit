#!/usr/bin/env python3
"""
Live viewer for history data stored in InfluxDB v3.
Refreshes every 30 seconds automatically.
"""

import tkinter as tk
from tkinter import ttk
import threading
import time
from datetime import datetime, timezone

import matplotlib
matplotlib.use("TkAgg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure

from influxdb_client_3 import InfluxDBClient3

INFLUX_HOST  = "http://localhost:8181"
INFLUX_TOKEN = "apiv3_ev3ZbXfHI0ZiHhk2B3ykpWfbF4V7DGpHgjywG_e-3G5qB6gJD5swqRCxHFrPD21BBFipO8rQG3CDjsjx7ZR_Jg"
INFLUX_DB    = "cockpit"
REFRESH_S    = 30

DARK_BG   = "#13131f"
DARK_AX   = "#1e1e2e"
GRID_COL  = "#2a2a3e"
LINE_COLS = ["#4fc3f7", "#81c784", "#ffb74d", "#f48fb1", "#ce93d8", "#80cbc4"]



def fetch_series(measurement: str, window_h: int):
    """Fetch time series data for a given measurement over the last window_h hours."""
    client = InfluxDBClient3(host=INFLUX_HOST, token=INFLUX_TOKEN, database=INFLUX_DB)
    query = f"""
        SELECT time, id, value
        FROM "{measurement}"
        WHERE time > now() - interval '{window_h} hours'
        ORDER BY time
    """
    try:
        table = client.query(query)
        d = table.to_pydict()
        return d
    except Exception as e:
        print(f"fetch_series error: {e}")
        return {}


class InfluxViewer(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("InfluxDB History Viewer")
        self.configure(bg=DARK_BG)
        self.geometry("1000x600")

        self._measurements = []
        self._selected = tk.StringVar()
        self._window_h = tk.IntVar(value=1)
        self._after_id = None

        self._build_ui()
        self.after(100, self._load_measurements)

    def _build_ui(self):
        # Top toolbar
        bar = tk.Frame(self, bg=DARK_BG, pady=6, padx=10)
        bar.pack(fill=tk.X)

        tk.Label(bar, text="Mesure :", bg=DARK_BG, fg="white",
                 font=("Arial", 11)).pack(side=tk.LEFT, padx=(0, 4))

        self._combo = ttk.Combobox(bar, textvariable=self._selected,
                                   state="readonly", width=24,
                                   font=("Arial", 11))
        self._combo.pack(side=tk.LEFT, padx=(0, 16))
        self._combo.bind("<<ComboboxSelected>>", lambda _: self._refresh())

        tk.Label(bar, text="Fenêtre :", bg=DARK_BG, fg="white",
                 font=("Arial", 11)).pack(side=tk.LEFT, padx=(0, 4))
        for h, label in [(1, "1h"), (6, "6h"), (24, "24h"), (168, "7j")]:
            tk.Radiobutton(bar, text=label, variable=self._window_h, value=h,
                           bg=DARK_BG, fg="white", selectcolor="#333355",
                           activebackground=DARK_BG, font=("Arial", 10),
                           command=self._refresh).pack(side=tk.LEFT, padx=2)

        self._status = tk.Label(bar, text="", bg=DARK_BG, fg="#aaaacc",
                                font=("Arial", 9))
        self._status.pack(side=tk.RIGHT)

        tk.Button(bar, text="⟳", bg="#223", fg="white", relief=tk.FLAT,
                  font=("Arial", 13), command=self._refresh,
                  padx=6).pack(side=tk.RIGHT, padx=4)

        # Chart area
        self._fig = Figure(figsize=(10, 5), facecolor=DARK_BG)
        self._ax  = self._fig.add_subplot(111)
        self._ax.set_facecolor(DARK_AX)
        self._canvas = FigureCanvasTkAgg(self._fig, master=self)
        self._canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))

    def _load_measurements(self):
        def task():
            try:
                client = InfluxDBClient3(host=INFLUX_HOST, token=INFLUX_TOKEN,
                                         database=INFLUX_DB)
                result = client.query("SHOW TABLES")
                d = result.to_pydict()
                schemas = d.get("table_schema", [])
                names   = d.get("table_name", [])
                tables  = [n for n, s in zip(names, schemas) if s == "iox"]
            except Exception as e:
                print(f"load_measurements error: {e}")
                tables = []
            self.after(0, lambda: self._on_measurements_loaded(tables))

        threading.Thread(target=task, daemon=True).start()

    def _on_measurements_loaded(self, tables):
        self._measurements = tables
        self._combo["values"] = tables
        if tables:
            self._combo.current(0)
            self._refresh()

    def _refresh(self):
        if self._after_id:
            self.after_cancel(self._after_id)
        measurement = self._selected.get()
        if not measurement:
            return
        self._status.config(text="Chargement…")
        window_h = self._window_h.get()

        def task():
            data = fetch_series(measurement, window_h)
            self.after(0, lambda: self._on_data(measurement, data))

        threading.Thread(target=task, daemon=True).start()

    def _on_data(self, measurement: str, data: dict):
        self._draw(measurement, data)
        ts = datetime.now().strftime("%H:%M:%S")
        self._status.config(text=f"Mis à jour {ts}")
        self._after_id = self.after(REFRESH_S * 1000, self._refresh)

    def _draw(self, measurement: str, data: dict):
        ax = self._ax
        ax.clear()
        ax.set_facecolor(DARK_AX)

        times  = data.get("time", [])
        values = data.get("value", [])
        ids    = data.get("id", [])

        if not times:
            ax.text(0.5, 0.5, "Pas de données", transform=ax.transAxes,
                    ha="center", va="center", color="#aaaacc", fontsize=13)
        else:
            # Group by sensor id
            groups = {}
            for t, v, sid in zip(times, values, ids):
                groups.setdefault(sid, ([], []))
                groups[sid][0].append(t)
                groups[sid][1].append(v)

            for i, (sid, (ts, vs)) in enumerate(sorted(groups.items())):
                col = LINE_COLS[i % len(LINE_COLS)]
                label = f"id={sid}" if len(groups) > 1 else measurement
                ax.plot(ts, vs, color=col, linewidth=1.5, label=label, marker=".")

            ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
            self._fig.autofmt_xdate()
            if len(groups) > 1:
                ax.legend(facecolor=DARK_AX, edgecolor=GRID_COL, labelcolor="white")

        ax.set_title(measurement, color="white", fontsize=12, pad=8)
        ax.tick_params(colors="#aaaacc")
        ax.spines[:].set_color(GRID_COL)
        ax.grid(color=GRID_COL, linestyle="--", linewidth=0.5)
        ax.set_xlabel("Heure", color="#aaaacc", fontsize=9)
        ax.set_ylabel("Valeur", color="#aaaacc", fontsize=9)

        self._fig.tight_layout()
        self._canvas.draw()


if __name__ == "__main__":
    app = InfluxViewer()
    app.mainloop()
