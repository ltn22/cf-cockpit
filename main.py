import asyncio
import aiocoap
from pycoreconf import CORECONFModel
import cbor2
import logging
import json

logging.basicConfig(level=logging.INFO)
logging.getLogger("coap").setLevel(logging.INFO)

async def main():
    print("Initializing PyCoreConf Model...")
    model = CORECONFModel("coreconf-m2m@2026-03-08.sid")
    db = model.loadDB()
    
    # Get the SID using _resolve_path()
    measurement_xpath = "/coreconf-m2m:measurements/measurement"

    try:
        sid, key = db._resolve_path(measurement_xpath)
    except Exception as e:
        print(f"Error resolving path: {e}")
        return

    if not sid:
        print(f"Could not find SID for {measurement_xpath}")
        return
        
    print("Creating CoAP context...")
    protocol = await aiocoap.Context.create_client_context()

    print("Constructing FETCH request for coap://xlapak.touta.in/c?d=0")
    # Using FETCH method. The payload is a CBOR-encoded array containing the SID.
    payload = cbor2.dumps([sid])
    
    request = aiocoap.Message(
        code=aiocoap.FETCH, 
        uri='coap://xlapak.touta.in/c?d=0',
        payload=payload
    )
    request.opt.content_format = 142
    request.opt.accept = 142

    try:
        print("Sending request with 5s timeout...")
        response = await asyncio.wait_for(protocol.request(request).response, timeout=5.0)
    except asyncio.TimeoutError:
        print("Timeout: The CoAP request timed out after 5 seconds.")
        return
    except Exception as e:
        print(f"Failed to fetch resource: {e}")
        return

    print("Response Code:", response.code)
    try:
        print("Response Payload Hex:", response.payload.hex())
    except Exception as e:
        print("Error getting payload hex:", e)

    try:
        cbor_data = cbor2.loads(response.payload)
        print("Raw CBOR data:", cbor_data)
    except Exception as e:
        print("Could not decode raw CBOR:", e)

    print("\n--- Parsing PyCoreConf Database ---")
    try:
        db = model.loadDB(response.payload)
        print("JSON Dump from pycoreconf DB:")
        print(json.dumps(db, indent=2))

    except Exception as e:
        print("\nPyCoreConf Exception loading DB:")
        print(e)
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())
