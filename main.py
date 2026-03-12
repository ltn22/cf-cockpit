import asyncio
import aiocoap
from pycoreconf import CORECONFModel
import cbor2 as cbor
import logging
import json

logging.basicConfig(level=logging.INFO)
logging.getLogger("coap").setLevel(logging.INFO)

class RemoteDevice:
    def __init__(self):
        self.model = None
        self.db = None

    async def bootstrap_db(self, server_host: str, server_port: int, yang_model_name: str):
        print(f"Initializing PyCoreConf Model with {yang_model_name}...")
        
        sid_file = yang_model_name if yang_model_name.endswith('.sid') else f"{yang_model_name}.sid"
        self.model = CORECONFModel(sid_file)
        
        # Get module base name to construct xpath (removes @<date> and .sid extension)
        module_name = yang_model_name.split('@')[0].replace(".sid", "")
        
        # bootstrap 
        measurements_sid = self.model.sids[f"/{module_name}:measurements/measurement"]
            
        print("Creating CoAP request...")
        protocol = await aiocoap.Context.create_client_context()
        
        port_str = f":{server_port}" if server_port else ""
        uri = f"coap://{server_host}{port_str}/c?d=0"
        
        request = aiocoap.Message(
            code=aiocoap.FETCH, 
            uri=uri,
            payload=cbor.dumps(measurements_sid)
        )
        request.opt.content_format = 142
        request.opt.accept = 142

        try:
            response = await asyncio.wait_for(protocol.request(request).response, timeout=5.0)
        except asyncio.TimeoutError:
            logging.error("Timeout: The CoAP request timed out after 5 seconds.")
            return
        except Exception as e:
            logging.error(f"Failed to fetch resource: {e}")
            return

        try:
            self.db = self.model.loadDB(response.payload)
        except Exception as e:
            logging.error(f"PyCoreConf Exception loading DB: {e}", exc_info=True)

import argparse

async def main():
    parser = argparse.ArgumentParser(description="Fetch PyCoreConf Database over CoAP")
    parser.add_argument("--host", type=str, default="[::1]", help="CoAP Server Host (default: [::1])")
    parser.add_argument("--port", type=int, default=None, help="CoAP Server Port (default: default CoAP port)")
    parser.add_argument("--model", type=str, default="coreconf-m2m@2026-03-08", help="YANG Model Name (default: coreconf-m2m@2026-03-08)")
    
    args = parser.parse_args()

    device = RemoteDevice()
    await device.bootstrap_db(
        server_host=args.host,
        server_port=args.port,
        yang_model_name=args.model
    )

if __name__ == "__main__":
    asyncio.run(main())
