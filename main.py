import asyncio
import aiocoap
from pycoreconf import CORECONFModel
import cbor2 as cbor
import json
import logging
import time
import argparse
import threading
import tkinter as tk
from tkinter import ttk
from queue import Queue

def _parse_float_or_none(s: str):
    """Parse a string to float, returning None if blank or non-numeric."""
    s = s.strip()
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s: %(message)s')
log = logging.getLogger("cockpit")


class RemoteDevice:
    def __init__(self, server_host: str, server_port: int, yang_model_name: str):
        self.server_host = server_host
        self.server_port = server_port
        self.yang_model_name = yang_model_name
        self.model = None
        self.db = None
        self.protocol = None
        self._observations = {}  # f -> asyncio.Task

    async def init_model(self):
        sid_file = self.yang_model_name if self.yang_model_name.endswith('.sid') else f"{self.yang_model_name}.sid"
        log.debug("Loading SID file: %s", sid_file)
        self.model = CORECONFModel(sid_file)
        log.debug("Creating CoAP client context")
        self.protocol = await aiocoap.Context.create_client_context()
        log.info("CoAP client ready, target: coap://%s", self.server_host + (f":{self.server_port}" if self.server_port else ""))

    async def bootstrap_db(self):
        module_name = self.yang_model_name.split('@')[0].replace(".sid", "")
        xpath = f"/{module_name}:measurements/measurement"

        if xpath not in self.model.sids:
            log.error("xpath not found in SIDs: %s", xpath)
            return False

        measurements_sid = self.model.sids[xpath]
        port_str = f":{self.server_port}" if self.server_port else ""
        uri = f"coap://{self.server_host}{port_str}/c?d=0"

        log.info("FETCH %s  (SID=%s, content-format=142)", uri, measurements_sid)
        payload = cbor.dumps(measurements_sid)
        log.debug("FETCH payload (CBOR hex): %s (%d bytes)", payload.hex(), len(payload))

        request = aiocoap.Message(
            code=aiocoap.FETCH,
            uri=uri,
            payload=payload
        )
        request.opt.content_format = 142
        request.opt.accept = 142

        try:
            response = await asyncio.wait_for(self.protocol.request(request).response, timeout=5.0)
            log.info("Response code: %s  payload: %d bytes", response.code, len(response.payload))
            log.debug("Response payload (CBOR hex): %s (%d bytes)", response.payload.hex(), len(response.payload))
            self.db = self.model.loadDB(response.payload)
            log.debug("DB as JSON:\n%s", json.dumps(json.loads(self.db.to_json()), indent=2))
        except Exception as e:
            log.error("CoAP request failed: %s", e)
            return False

        db_xpath = f"{module_name}:measurements/measurement"

        try:
            filters = self.db.get_keys(db_xpath)
        except Exception as e:
            log.error("get_keys failed: %s", e)
            return False

        log.info("Bootstrap: %d measurement(s) found: %s", len(filters), filters)
        for f in filters:
            self.db[db_xpath + f] = {'internal': {'last-update': int(time.time())}}

        return True

    async def fetch_measurement(self, f: str) -> bool:
        module_name = self.yang_model_name.split('@')[0].replace(".sid", "")
        db_xpath = f"{module_name}:measurements/measurement"
        xpath = f"/{db_xpath}{f}/value"

        try:
            target_sid, key_values = self.db._resolve_path(xpath)
        except (KeyError, ValueError) as e:
            log.error("fetch_measurement: cannot resolve xpath %s: %s", xpath, e)
            return False

        port_str = f":{self.server_port}" if self.server_port else ""
        uri = f"coap://{self.server_host}{port_str}/c"

        instance_id = [target_sid] + key_values
        log.info("FETCH %s  (instance=%s)", uri, instance_id)
        payload = cbor.dumps(instance_id)
        log.debug("FETCH payload (CBOR hex): %s (%d bytes)", payload.hex(), len(payload))

        request = aiocoap.Message(
            code=aiocoap.FETCH,
            uri=uri,
            payload=payload
        )
        request.opt.content_format = 142
        request.opt.accept = 142

        try:
            response = await asyncio.wait_for(self.protocol.request(request).response, timeout=5.0)
            log.info("Response code: %s  payload: %d bytes", response.code, len(response.payload))
            log.debug("Response payload (CBOR hex): %s (%d bytes)", response.payload.hex(), len(response.payload))
            new_db = self.model.loadDB(response.payload)
            log.debug("Measurement JSON:\n%s", json.dumps(json.loads(new_db.to_json()), indent=2))
            data = new_db[db_xpath + f]
            self.db[db_xpath + f + "/value"] = data
            self.db[db_xpath + f] = {'internal': {'last-update': int(time.time())}}
        except Exception as e:
            log.error("fetch_measurement failed: %s", e)
            return False

        return True

    async def fetch_statistics(self, f: str) -> bool:
        module_name = self.yang_model_name.split('@')[0].replace(".sid", "")
        db_xpath = f"{module_name}:measurements/measurement"
        xpath = f"/{db_xpath}{f}/statistics"

        try:
            target_sid, key_values = self.db._resolve_path(xpath)
        except (KeyError, ValueError) as e:
            log.error("fetch_statistics: cannot resolve xpath %s: %s", xpath, e)
            return False

        port_str = f":{self.server_port}" if self.server_port else ""
        uri = f"coap://{self.server_host}{port_str}/c"

        instance_id = [target_sid] + key_values
        log.info("FETCH %s  (instance=%s)", uri, instance_id)
        payload = cbor.dumps(instance_id)
        log.debug("FETCH payload (CBOR hex): %s (%d bytes)", payload.hex(), len(payload))

        request = aiocoap.Message(
            code=aiocoap.FETCH,
            uri=uri,
            payload=payload
        )
        request.opt.content_format = 142
        request.opt.accept = 142

        try:
            response = await asyncio.wait_for(self.protocol.request(request).response, timeout=5.0)
            log.info("Response code: %s  payload: %d bytes", response.code, len(response.payload))
            log.debug("Response payload (CBOR hex): %s (%d bytes)", response.payload.hex(), len(response.payload))

            data = json.loads(self.model.toJSON(response.payload))

            self.db[db_xpath + f] = {'statistics': data[db_xpath + "/statistics"]}
        except Exception as e:
            log.error("fetch_statistics failed: %s", e)
            return False

        return True

    async def observe_threshold(self, f: str, t_min, t_max, hysteresis: int = 5) -> bool:
        # TODO: implement CoAP iPATCH to set notification-parameters/t-min and t-max
        log.info("observe_threshold: f=%s t_min=%s t_max=%s hysteresis=%s%%", f, t_min, t_max, hysteresis)

        if t_min is None and t_max is None:
            log.info("observe_threshold: no thresholds set, do nothing")
            return False

        module_name = self.yang_model_name.split('@')[0].replace(".sid", "")
        db_xpath = f"{module_name}:measurements/measurement"
        xpath = f"/{db_xpath}{f}/notification-parameters"

        precision = self.db[db_xpath + f].get('precision', 0)

        notif_params = {}
        if t_max:
            notif_params ["t-max"] = int(t_max * (10 ** precision))
        if t_min:
            notif_params["t-min"] = int(t_min * (10 ** precision))
        if hysteresis != 5:
            notif_params["hysteresis"] = hysteresis
        
        qualified_payload = {db_xpath+'/notification-parameters': notif_params}
        payload = self.model.toCORECONF(json.dumps(qualified_payload))

        xpath_key= self.db._resolve_path(xpath)
        ipatch_key = [xpath_key[0]] + xpath_key[1]

        ipatch_payload_struct = cbor.loads(payload)
        ipatch_query = cbor.dumps({tuple(ipatch_key): ipatch_payload_struct})

        log.info("iPATCH %s  payload (%d bytes): %s", xpath, len(ipatch_query), ipatch_query.hex())

        port_str = f":{self.server_port}" if self.server_port else ""
        uri = f"coap://{self.server_host}{port_str}/c"

        request = aiocoap.Message(
            code=aiocoap.numbers.codes.Code(7),  # iPATCH
            uri=uri,
            payload=ipatch_query
        )
        request.opt.content_format = 142

        try:
            response = await asyncio.wait_for(self.protocol.request(request).response, timeout=5.0)
            log.info("observe_threshold: response %s", response.code)
            return response.code.is_successful()
        except Exception as e:
            log.error("observe_threshold: request failed: %s", e)
            return False

    async def observe_sensor_alert(self, f: str) -> bool:
        module_name = self.yang_model_name.split('@')[0].replace(".sid", "")
        xpath = f"/{module_name}:sensor-alert/target{f}"

        if not self.db:
            log.error("observe_sensor_alert: db not initialized")
            return False

        try:
            target_sid, key_values = self.db._resolve_path(xpath)
        except (KeyError, ValueError) as e:
            log.error("observe_sensor_alert: cannot resolve xpath %s: %s", xpath, e)
            return False

        instance_id = [target_sid] + key_values
        port_str = f":{self.server_port}" if self.server_port else ""
        uri = f"coap://{self.server_host}{port_str}/s"
        payload = cbor.dumps(instance_id)

        log.info("FETCH+Observe %s  (instance=%s)", uri, instance_id)

        request = aiocoap.Message(code=aiocoap.FETCH, uri=uri, payload=payload)
        request.opt.content_format = 142
        request.opt.accept = 142
        request.opt.observe = 0

        if 'sensor-alert' in self._observations:
            self._observations['sensor-alert'].cancel()

        obs = self.protocol.request(request)
        try:
            first = await asyncio.wait_for(obs.response, timeout=5.0)
            log.info("observe_sensor_alert: first response %s", first.code)
        except Exception as e:
            log.error("observe_sensor_alert: first response failed: %s", e)
            return False

        self._observations['sensor-alert'] = asyncio.ensure_future(
            self._watch_observation('sensor-alert', obs)
        )
        return True

    async def _watch_observation(self, f: str, obs):
        log.info("_watch_observation[%s]: started", f)
        try:
            async for response in obs.observation:
                log.info("_watch_observation[%s]: notification %s  payload (%d bytes): %s",
                         f, response.code, len(response.payload), response.payload.hex())
        except asyncio.CancelledError:
            obs.observation.cancel()
            log.info("_watch_observation[%s]: cancelled", f)
        except Exception as e:
            log.error("_watch_observation[%s]: error: %s", f, e)


class ThresholdsDialog(tk.Toplevel):
    def __init__(self, parent, key_filter: str, t_min, t_max, hysteresis: int, unit: str, on_apply):
        super().__init__(parent)
        self.title(f"Thresholds — {key_filter}")
        self.configure(bg='#1e1e2e')
        self.resizable(False, False)
        self.grab_set()

        self._on_apply = on_apply

        tk.Label(self, text="Threshold configuration", font=('Arial', 11, 'bold'),
                 fg='white', bg='#1e1e2e').pack(pady=(12, 4))
        tk.Label(self, text=f"Unit: {unit}",
                 font=('Arial', 9), fg='#aaa', bg='#1e1e2e').pack(pady=(0, 10))

        for label, attr, raw_val in (('t-min', '_entry_min', t_min), ('t-max', '_entry_max', t_max)):
            row = tk.Frame(self, bg='#1e1e2e', padx=16, pady=4)
            row.pack(fill=tk.X)
            tk.Label(row, text=f"{label} ({unit}):", font=('Arial', 11), fg='#aaccff',
                     bg='#1e1e2e', width=14, anchor='w').pack(side=tk.LEFT)
            entry = tk.Entry(row, font=('Arial', 11), bg='#2a2a3e', fg='white',
                             insertbackground='white', width=12)
            if raw_val is not None:
                entry.insert(0, str(raw_val))
            entry.pack(side=tk.LEFT, padx=8)
            setattr(self, attr, entry)

        row_hyst = tk.Frame(self, bg='#1e1e2e', padx=16, pady=4)
        row_hyst.pack(fill=tk.X)
        tk.Label(row_hyst, text="hysteresis (%):", font=('Arial', 11), fg='#aaccff',
                 bg='#1e1e2e', width=14, anchor='w').pack(side=tk.LEFT)
        self._entry_hysteresis = tk.Entry(row_hyst, font=('Arial', 11), bg='#2a2a3e', fg='white',
                                          insertbackground='white', width=12)
        self._entry_hysteresis.insert(0, str(hysteresis))
        self._entry_hysteresis.pack(side=tk.LEFT, padx=8)

        self._err_label = tk.Label(self, text='', font=('Arial', 9), fg='#ff6666', bg='#1e1e2e')
        self._err_label.pack()

        btn_row = tk.Frame(self, bg='#1e1e2e', pady=12)
        btn_row.pack()
        tk.Button(btn_row, text="Apply", bg='#90ee90', fg='#003020',
                  activebackground='#70cc70', activeforeground='#003020',
                  relief=tk.FLAT, padx=12, pady=4,
                  command=self._apply).pack(side=tk.LEFT, padx=6)
        tk.Button(btn_row, text="Cancel", bg='#ffaaaa', fg='#400000',
                  activebackground='#dd8888', activeforeground='#400000',
                  relief=tk.FLAT, padx=12, pady=4,
                  command=self.destroy).pack(side=tk.LEFT, padx=6)
        self.bind('<Return>', lambda _e: self._apply())

        self.update_idletasks()
        x = parent.winfo_x() + (parent.winfo_width() - self.winfo_width()) // 2
        y = parent.winfo_y() + (parent.winfo_height() - self.winfo_height()) // 2
        self.geometry(f"+{x}+{y}")

    def _apply(self):
        t_min_raw = t_max_raw = None
        try:
            s = self._entry_min.get().strip()
            if s:
                t_min_raw = float(s)
            s = self._entry_max.get().strip()
            if s:
                t_max_raw = float(s)
            hysteresis = int(self._entry_hysteresis.get().strip() or '5')
            if not (0 <= hysteresis <= 100):
                raise ValueError
        except ValueError:
            self._err_label.config(text="Invalid value — hysteresis must be 0–100.")
            return
        self._on_apply(t_min_raw, t_max_raw, hysteresis)
        self.destroy()


class MeasurementCard(tk.Frame):
    def __init__(self, parent, key_filter: str, m_type: str, initial_value: str, last_up: int):
        super().__init__(parent, relief=tk.RIDGE, borderwidth=2, bg="#1e1e2e")
        self.key_filter = key_filter
        self.last_up = last_up

        # Left: type label, value, buttons
        left = tk.Frame(self, bg='#1e1e2e', padx=8, pady=8)
        left.pack(side=tk.LEFT, fill=tk.BOTH)

        tk.Label(left, text=m_type.upper(), font=('Arial', 10, 'bold'),
                 fg='white', bg='#1e1e2e').pack()

        self.val_label = tk.Label(left, text=initial_value,
                                  font=('Arial', 18, 'bold'), fg='yellow', bg='#1e1e2e')
        self.val_label.pack(pady=6)

        btn_frame = tk.Frame(left, bg='#1e1e2e')
        btn_frame.pack()
        tk.Button(btn_frame, text="Refresh", bg='#888', fg='#003080',
                  activebackground='#999', activeforeground='#003080',
                  relief=tk.FLAT, padx=6, pady=2,
                  command=self._on_refresh).pack(side=tk.LEFT, padx=2)
        tk.Button(btn_frame, text="Stats", bg='#888', fg='#003080',
                  activebackground='#999', activeforeground='#003080',
                  relief=tk.FLAT, padx=6, pady=2,
                  command=self._on_stats).pack(side=tk.LEFT, padx=2)
        self._threshold_btn = tk.Button(btn_frame, text="Thresholds", bg='#888', fg='#003080',
                                        activebackground='#999', activeforeground='#003080',
                                        relief=tk.FLAT, padx=6, pady=2,
                                        command=self._on_thresholds)
        self._threshold_btn.pack(side=tk.LEFT, padx=2)
        tk.Button(btn_frame, text="Follow", bg='#888', fg='#003080',
                  activebackground='#999', activeforeground='#003080',
                  relief=tk.FLAT, padx=6, pady=2).pack(side=tk.LEFT, padx=2)

        # Right: stats panel (hidden until first fetch)
        self.stats_frame = tk.Frame(self, bg='#003080', padx=8, pady=6)
        self._stats_labels = {}
        for field in ('min', 'max', 'mean', 'median', 'σ', 'n'):
            row = tk.Frame(self.stats_frame, bg='#003080')
            row.pack(fill=tk.X, pady=1)
            tk.Label(row, text=f"{field}:", font=('Arial', 10), fg='#aaccff', bg='#003080',
                     width=6, anchor='w').pack(side=tk.LEFT)
            lbl = tk.Label(row, text='---', font=('Arial', 10, 'bold'), fg='white', bg='#003080',
                           anchor='w')
            lbl.pack(side=tk.LEFT)
            self._stats_labels[field] = lbl

        self._refresh_callback = None
        self._stats_callback = None
        self._thresholds_callback = None

    def set_refresh_callback(self, cb):
        self._refresh_callback = cb

    def set_stats_callback(self, cb):
        self._stats_callback = cb

    def set_thresholds_callback(self, cb):
        self._thresholds_callback = cb

    def set_thresholds_active(self, active: bool):
        if active:
            self._threshold_btn.config(bg='#003080', fg='white',
                                       activebackground='#0050b0', activeforeground='white')
        else:
            self._threshold_btn.config(bg='#888', fg='#003080',
                                       activebackground='#999', activeforeground='#003080')

    def _on_refresh(self):
        if self._refresh_callback:
            self._refresh_callback()

    def _on_stats(self):
        if self._stats_callback:
            self._stats_callback()

    def _on_thresholds(self):
        if self._thresholds_callback:
            self._thresholds_callback()

    def update_data(self, display_text: str, last_up: int):
        self.val_label.config(text=display_text)
        self.last_up = last_up

    def update_stats(self, stats: dict, precision: int, unit: str):
        factor = 10 ** precision

        def fmt(raw):
            return f"{raw / factor} {unit}" if raw is not None else '---'

        self._stats_labels['min'].config(text=fmt(stats.get('min')))
        self._stats_labels['max'].config(text=fmt(stats.get('max')))
        self._stats_labels['mean'].config(text=fmt(stats.get('mean')))
        self._stats_labels['median'].config(text=fmt(stats.get('median')))
        self._stats_labels['σ'].config(text=fmt(stats.get('stdev')))
        self._stats_labels['n'].config(text=str(stats.get('sample-count', '---')))

        if not self.stats_frame.winfo_ismapped():
            self.stats_frame.pack(side=tk.LEFT, fill=tk.Y)

    def check_timeout(self, current_time: int):
        if self.last_up > 0 and (current_time - self.last_up) > 300:
            self.val_label.config(text='---')


class CockpitDashboardApp:
    COLS = 3

    def __init__(self, device: RemoteDevice):
        self.device = device
        self.cards = {}
        self.queue = Queue()

        self.root = tk.Tk()
        self.root.title("Cockpit2 Dashboard")
        self.root.configure(bg='#13131f')
        self.root.geometry("900x600")

        self._setup_ui()

        # Asyncio loop in background thread
        self.loop = asyncio.new_event_loop()
        threading.Thread(target=self._run_loop, daemon=True).start()

        # Init model then first fetch
        self.root.after(100, self._schedule_init)
        # Process results queue
        self.root.after(200, self._process_queue)
        # Timeout check every 5s
        self.root.after(5000, self._check_timeouts)

    def _run_loop(self):
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    def _schedule_init(self):
        asyncio.run_coroutine_threadsafe(self._async_init(), self.loop)

    async def _async_init(self):
        try:
            await self.device.init_model()
            success = await self.device.bootstrap_db()
        except Exception as e:
            log.error("Init failed: %s", e)
            self.queue.put(('update', False))
            return
        log.info("Bootstrap %s", "succeeded" if success else "failed")
        self.queue.put(('update', success))

    def _refresh_card(self, f: str):
        asyncio.run_coroutine_threadsafe(self._async_fetch_measurement(f), self.loop)

    async def _async_fetch_measurement(self, f: str):
        success = await self.device.fetch_measurement(f)
        self.queue.put(('refresh', f, success))

    def _stats_card(self, f: str):
        asyncio.run_coroutine_threadsafe(self._async_fetch_statistics(f), self.loop)

    async def _async_fetch_statistics(self, f: str):
        success = await self.device.fetch_statistics(f)
        self.queue.put(('stats', f, success))

    def _thresholds_card(self, f: str):
        if not self.device.db:
            return
        module_name = self.device.yang_model_name.split('@')[0].replace(".sid", "")
        db_xpath = f"{module_name}:measurements/measurement"
        try:
            data = self.device.db[db_xpath + f]
            unit = data.get('unit', '')
            notif = data.get('notification-parameters', {})
            t_min = notif.get('t-min')
            t_max = notif.get('t-max')
            hysteresis = notif.get('hysteresis', 5)
        except KeyError:
            unit, t_min, t_max, hysteresis = '', None, None, 5

        ThresholdsDialog(
            self.root, f, t_min, t_max, hysteresis, unit,
            on_apply=lambda mn, mx, hyst: asyncio.run_coroutine_threadsafe(
                self._async_set_and_observe(f, mn, mx, hyst), self.loop
            )
        )

    async def _async_set_and_observe(self, f: str, t_min, t_max, hysteresis: int):
        success = await self.device.observe_threshold(f, t_min, t_max, hysteresis)
        if success:
            observed = await self.device.observe_sensor_alert(f)
            if observed:
                self.queue.put(('threshold_active', f, True))

    def _process_queue(self):
        while not self.queue.empty():
            msg = self.queue.get()
            if msg[0] == 'update' and msg[1]:
                self.update_ui()
            elif msg[0] == 'refresh' and msg[2]:
                self._update_card(msg[1])
            elif msg[0] == 'stats' and msg[2]:
                self._update_card_stats(msg[1])
            elif msg[0] == 'threshold_active':
                if msg[1] in self.cards:
                    self.cards[msg[1]].set_thresholds_active(msg[2])
        self.root.after(100, self._process_queue)

    def _update_card(self, f: str):
        if not self.device.db:
            return
        module_name = self.device.yang_model_name.split('@')[0].replace(".sid", "")
        db_xpath = f"{module_name}:measurements/measurement"
        measurement_path = db_xpath + f
        try:
            data = self.device.db[measurement_path]
            raw = data.get('value')
            precision = data.get('precision', 0)
            value = raw / 10**precision if raw is not None else '---'
            unit = data.get('unit', '')
            internal = data.get('internal', {})
            last_update = int(internal.get('last-update', 0))
            display_text = f"{value} {unit}"
            if f in self.cards:
                self.cards[f].update_data(display_text, last_update)
        except KeyError:
            pass

    def _update_card_stats(self, f: str):
        if not self.device.db:
            return
        module_name = self.device.yang_model_name.split('@')[0].replace(".sid", "")
        db_xpath = f"{module_name}:measurements/measurement"
        measurement_path = db_xpath + f
        try:
            data = self.device.db[measurement_path]
            precision = data.get('precision', 0)
            unit = data.get('unit', '')
            stats = data.get('statistics', {})
            if f in self.cards:
                self.cards[f].update_stats(stats, precision, unit)
        except KeyError:
            pass

    def _check_timeouts(self):
        current_time = int(time.time())
        for card in self.cards.values():
            card.check_timeout(current_time)
        self.root.after(5000, self._check_timeouts)

    def _setup_ui(self):
        # Header
        header = tk.Frame(self.root, bg='#2a2a3e', pady=8)
        header.pack(fill=tk.X)
        tk.Label(header, text="Cockpit2 Dashboard", font=('Arial', 14, 'bold'),
                 fg='white', bg='#2a2a3e').pack(side=tk.LEFT, padx=12)
        self.status_label = tk.Label(header, text="Connecting...", font=('Arial', 10),
                                      fg='#aaa', bg='#2a2a3e')
        self.status_label.pack(side=tk.RIGHT, padx=12)
        tk.Button(header, text="Refresh All", bg='#3a86ff', fg='white',
                  activebackground='#5a9fff', activeforeground='white',
                  relief=tk.FLAT, padx=8, pady=2,
                  command=self._manual_refresh).pack(side=tk.RIGHT, padx=6)

        # Scrollable canvas
        container = tk.Frame(self.root, bg='#13131f')
        container.pack(fill=tk.BOTH, expand=True)

        canvas = tk.Canvas(container, bg='#13131f', highlightthickness=0)
        scrollbar = ttk.Scrollbar(container, orient='vertical', command=canvas.yview)
        self.grid_frame = tk.Frame(canvas, bg='#13131f')

        self.grid_frame.bind('<Configure>',
            lambda e: canvas.configure(scrollregion=canvas.bbox('all')))

        canvas.create_window((0, 0), window=self.grid_frame, anchor='nw')
        canvas.configure(yscrollcommand=scrollbar.set)

        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self._grid_row = 0
        self._grid_col = 0

    def _manual_refresh(self):
        self.update_ui()

    def update_ui(self):
        if not self.device.db:
            self.status_label.config(text="No data")
            return

        module_name = self.device.yang_model_name.split('@')[0].replace(".sid", "")
        db_xpath = f"{module_name}:measurements/measurement"

        try:
            filters = self.device.db.get_keys(db_xpath)
            log.debug("update_ui: %d filter(s): %s", len(filters), filters)
        except Exception as e:
            log.error("update_ui get_keys failed: %s", e)
            self.status_label.config(text=f"Error: {e}")
            return

        for f in filters:
            measurement_path = db_xpath + f
            try:
                data = self.device.db[measurement_path]

                m_type = data.get('type', 'Unknown').split(':')[-1]
                raw = data.get('value')
                precision = data.get('precision', 0)
                value = raw / 10**precision if raw is not None else '---'
                unit = data.get('unit', '')
                internal = data.get('internal', {})
                last_update = int(internal.get('last-update', 0))
                display_text = f"{value} {unit}"

                if f in self.cards:
                    self.cards[f].update_data(display_text, last_update)
                else:
                    card = MeasurementCard(self.grid_frame, f, m_type, display_text, last_update)
                    card.set_refresh_callback(lambda key=f: self._refresh_card(key))
                    card.set_stats_callback(lambda key=f: self._stats_card(key))
                    card.set_thresholds_callback(lambda key=f: self._thresholds_card(key))
                    card.grid(row=self._grid_row, column=self._grid_col,
                              padx=8, pady=8, sticky='nsew')
                    self.cards[f] = card
                    self._grid_col += 1
                    if self._grid_col >= self.COLS:
                        self._grid_col = 0
                        self._grid_row += 1

            except KeyError:
                continue

        self.status_label.config(text=f"Updated {time.strftime('%H:%M:%S')}")

    def run(self):
        self.root.mainloop()
        self.loop.call_soon_threadsafe(self.loop.stop)


def main():
    parser = argparse.ArgumentParser(description="Cockpit2 GUI Dashboard")
    parser.add_argument("--host", type=str, default="[::1]", help="CoAP Server Host (default: [::1])")
    parser.add_argument("--port", type=int, default=None, help="CoAP Server Port")
    parser.add_argument("--model", type=str, default="coreconf-m2m@2026-03-16", help="YANG Model Name")
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose network logging")
    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
        logging.getLogger("coap").setLevel(logging.DEBUG)
        logging.getLogger("aiocoap").setLevel(logging.DEBUG)
    else:
        logging.getLogger().setLevel(logging.CRITICAL)
        logging.getLogger("coap").setLevel(logging.CRITICAL)
        logging.getLogger("aiocoap").setLevel(logging.CRITICAL)
        log.setLevel(logging.INFO)

    device = RemoteDevice(
        server_host=args.host,
        server_port=args.port,
        yang_model_name=args.model
    )

    app = CockpitDashboardApp(device)
    app.run()


if __name__ == "__main__":
    main()
