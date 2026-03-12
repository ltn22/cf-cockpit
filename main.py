import asyncio
import aiocoap
from pycoreconf import CORECONFModel
import cbor2 as cbor
import logging
import json
import time
from datetime import datetime
import argparse
import re

from textual.app import App, ComposeResult
from textual.containers import Grid, Horizontal, Vertical
from textual.widgets import Header, Footer, Static, Button, Label

logging.basicConfig(level=logging.INFO)
logging.getLogger("coap").setLevel(logging.INFO)

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
        self.model = CORECONFModel(sid_file)
        self.protocol = await aiocoap.Context.create_client_context()

    async def fetch_db(self):
        module_name = self.yang_model_name.split('@')[0].replace(".sid", "")
        xpath = f"/{module_name}:measurements/measurement"
        
        if xpath not in self.model.sids:
            return False

        measurements_sid = self.model.sids[xpath]
        port_str = f":{self.server_port}" if self.server_port else ""
        uri = f"coap://{self.server_host}{port_str}/c?d=0"
        
        request = aiocoap.Message(
            code=aiocoap.FETCH, 
            uri=uri,
            payload=cbor.dumps(measurements_sid)
        )
        request.opt.content_format = 142
        request.opt.accept = 142

        try:
            response = await asyncio.wait_for(self.protocol.request(request).response, timeout=5.0)
            self.db = self.model.loadDB(response.payload)
        except Exception:
            return False
        
        db_xpath = f"{module_name}:measurements/measurement"

        try:
            filters = self.db.get_keys(db_xpath)
        except Exception:
            return False

        for f in filters:
            print (f)
            self.db[db_xpath + f] = {'internal': {'last-update': int(time.time())}}
        
        return True

class MeasurementCard(Static):
    """A widget to display a single measurement."""
    
    def __init__(self, key_filter: str, m_type: str, initial_value: str, last_up: int):
        super().__init__(classes="card")
        self.key_filter = key_filter
        self.safe_id = re.sub(r'[^a-zA-Z0-9_-]', '_', key_filter)
        self.m_type = m_type
        self.val_str = initial_value
        self.last_up = last_up

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label(self.m_type.upper(), classes="title")
            self.val_label = Label(self.val_str, id=f"val_{self.safe_id}", classes="value")
            yield self.val_label
            with Horizontal(classes="buttons"):
                yield Button("Refresh", id=f"refresh_{self.safe_id}", variant="primary")
                yield Button("Stats", id=f"stats_{self.safe_id}")
                yield Button("Follow", id=f"follow_{self.safe_id}")

    def update_data(self, display_text: str, last_up: int):
        self.val_str = display_text
        self.last_up = last_up
        self.val_label.update(display_text)

    def check_timeout(self, current_time: int):
        if self.last_up > 0 and (current_time - self.last_up) > 300:
            self.val_label.update("---")


class CockpitDashboardApp(App):
    TITLE = "Cockpit2 Dashboard"
    CSS = """
    Grid {
        grid-size: 3;
        grid-gutter: 1 2;
        padding: 1;
    }
    
    .card {
        height: 12;
        border: solid green;
        padding: 1;
    }
    
    .title {
        text-align: center;
        text-style: bold;
        width: 100%;
        margin-bottom: 1;
    }
    
    .value {
        text-align: center;
        content-align: center middle;
        text-style: bold;
        color: yellow;
        width: 100%;
        height: 3;
    }
    
    .buttons {
        align: center middle;
        height: 3;
        margin-top: 1;
    }
    
    Button {
        margin: 0 1;
    }
    """

    def __init__(self, device: RemoteDevice):
        super().__init__()
        self.device = device

    def compose(self) -> ComposeResult:
        yield Header()
        self.grid = Grid(id="measurement_grid")
        yield self.grid
        yield Footer()

    async def on_mount(self) -> None:
        await self.device.init_model()
        self.set_interval(5.0, self.check_timeouts)
        # Initial Fetch
        self.run_worker(self.fetch_and_update())

    async def fetch_and_update(self):
        success = await self.device.fetch_db()
        if success:
            self.update_ui()

    def update_ui(self):
        if not self.device.db:
            return
            
        module_name = self.device.yang_model_name.split('@')[0].replace(".sid", "")
        # The db key format sometimes drops the leading slash internally, handle accordingly
        db_xpath = f"{module_name}:measurements/measurement"
        
        try:
            filters = self.device.db.get_keys(db_xpath)
        except Exception:
            return

        for f in filters:
            measurement_path = db_xpath + f
            try:
                data = self.device.db[measurement_path]
                
                m_type = data.get('type', 'Unknown').split(':')[-1]
                value = data.get('value', '---')
                unit = data.get('unit', '')
                
                internal = data.get('internal', {})
                last_update = int(internal.get('last-update', 0))
                
                display_text = f"{value} {unit}"
                
                # Update if exist, otherwise create
                card_list = self.query(MeasurementCard)
                card = next((c for c in card_list if c.key_filter == f), None)
                
                if card:
                    card.update_data(display_text, last_update)
                else:
                    new_card = MeasurementCard(f, m_type, display_text, last_update)
                    self.grid.mount(new_card)
                    
            except KeyError:
                continue

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id
        if button_id and button_id.startswith("refresh_"):
            # Trigger a re-fetch of everything for simplicity
            self.run_worker(self.fetch_and_update())

    def check_timeouts(self):
        current_time = int(time.time())
        for card in self.query(MeasurementCard):
            card.check_timeout(current_time)


def main():
    parser = argparse.ArgumentParser(description="Cockpit2 GUI Dashboard")
    parser.add_argument("--host", type=str, default="[::1]", help="CoAP Server Host (default: [::1])")
    parser.add_argument("--port", type=int, default=None, help="CoAP Server Port")
    parser.add_argument("--model", type=str, default="coreconf-m2m@2026-03-08", help="YANG Model Name")
    args = parser.parse_args()

    # Turn off excessive logging for TUI
    logging.getLogger("coap").setLevel(logging.CRITICAL)
    logging.getLogger().setLevel(logging.CRITICAL)

    device = RemoteDevice(
        server_host=args.host,
        server_port=args.port,
        yang_model_name=args.model
    )
    
    app = CockpitDashboardApp(device)
    app.run()

if __name__ == "__main__":
    main()
