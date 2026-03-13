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
        xpath = f"/{db_xpath}{f}"

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
            self.db[db_xpath + f] = data
            self.db[db_xpath + f] = {'internal': {'last-update': int(time.time())}}
        except Exception as e:
            log.error("fetch_measurement failed: %s", e)
            return False

        return True


class MeasurementCard(tk.Frame):
    def __init__(self, parent, key_filter: str, m_type: str, initial_value: str, last_up: int):
        super().__init__(parent, relief=tk.RIDGE, borderwidth=2, padx=8, pady=8, bg="#1e1e2e")
        self.key_filter = key_filter
        self.last_up = last_up

        tk.Label(self, text=m_type.upper(), font=('Arial', 10, 'bold'),
                 fg='white', bg='#1e1e2e').pack()

        self.val_label = tk.Label(self, text=initial_value,
                                  font=('Arial', 18, 'bold'), fg='yellow', bg='#1e1e2e')
        self.val_label.pack(pady=6)

        btn_frame = tk.Frame(self, bg='#1e1e2e')
        btn_frame.pack()
        tk.Button(btn_frame, text="Refresh", bg='#888', fg='#003080',
                  activebackground='#999', activeforeground='#003080',
                  relief=tk.FLAT, padx=6, pady=2,
                  command=self._on_refresh).pack(side=tk.LEFT, padx=2)
        tk.Button(btn_frame, text="Stats", bg='#888', fg='#003080',
                  activebackground='#999', activeforeground='#003080',
                  relief=tk.FLAT, padx=6, pady=2).pack(side=tk.LEFT, padx=2)
        tk.Button(btn_frame, text="Follow", bg='#888', fg='#003080',
                  activebackground='#999', activeforeground='#003080',
                  relief=tk.FLAT, padx=6, pady=2).pack(side=tk.LEFT, padx=2)

        self._refresh_callback = None

    def set_refresh_callback(self, cb):
        self._refresh_callback = cb

    def _on_refresh(self):
        if self._refresh_callback:
            self._refresh_callback()

    def update_data(self, display_text: str, last_up: int):
        self.val_label.config(text=display_text)
        self.last_up = last_up

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
        await self.device.init_model()
        success = await self.device.bootstrap_db()
        log.info("Bootstrap %s", "succeeded" if success else "failed")
        self.queue.put(('update', success))

    def _refresh_card(self, f: str):
        asyncio.run_coroutine_threadsafe(self._async_fetch_measurement(f), self.loop)

    async def _async_fetch_measurement(self, f: str):
        success = await self.device.fetch_measurement(f)
        self.queue.put(('refresh', f, success))

    def _process_queue(self):
        while not self.queue.empty():
            msg = self.queue.get()
            if msg[0] == 'update' and msg[1]:
                self.update_ui()
            elif msg[0] == 'refresh' and msg[2]:
                self.update_ui()
        self.root.after(100, self._process_queue)

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
    parser.add_argument("--model", type=str, default="coreconf-m2m@2026-03-08", help="YANG Model Name")
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
