import asyncio
import aiocoap
from pycoreconf import CORECONFModel
import cbor2
import logging

logging.basicConfig(level=logging.DEBUG)
logging.getLogger("coap").setLevel(logging.DEBUG)

async def main():
    print("Creating CoAP context...")
    protocol = await aiocoap.Context.create_client_context()

    print("Constructing FETCH request for coap://xlapak.touta.in/c/measurement?depth=0")
    # Using FETCH method as requested. A FETCH request usually requires a payload.
    # We provide an empty CBOR array or map as payload to avoid hanging.
    empty_payload = cbor2.dumps([])
    request = aiocoap.Message(
        code=aiocoap.FETCH, 
        uri='coap://xlapak.touta.in/c/measurement?depth=0',
        payload=empty_payload
    )
    request.opt.content_format = 60000
    request.opt.accept = 60000

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

    print("\n--- Testing PyCoreConf Database Storage ---")
    try:
        # Initialize pycoreconf model - without sid file it might fail or act as pass-through
        model = CORECONFModel() 
        db = model.loadDB(response.payload)
        print("JSON Dump from pycoreconf DB:")
        print(db)

        print("\nPyCoreConf CBOR Hex:")
        print(db.to_cbor().hex())
    except Exception as e:
        print("\nPyCoreConf Exception:")
        print(e)
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())
