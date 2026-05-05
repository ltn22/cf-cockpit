#!/usr/bin/env python3
"""
Minimal CoAP Observe prototype — reproduces the FETCH+Observe option-parsing bug.

Usage
-----
  uv run python observe_proto.py --server
  uv run python observe_proto.py --mode get        # GET+Observe
  uv run python observe_proto.py --mode fetch      # FETCH+Observe (shows the bug)

With standard aiocoap, FETCH+Observe produces opt.observe=None on the client
side (CoAP option bytes land in resp.payload instead of being parsed).
The ltn22 fork works around this; the standard release does not.
"""
import argparse
import asyncio

import aiocoap
import aiocoap.resource as resource
from aiocoap import Message
from aiocoap.meta import version as aiocoap_version


# ── Server ────────────────────────────────────────────────────────────────────

class CounterResource(resource.ObservableResource):
    """Simple counter, notifies observers every few seconds."""

    def __init__(self):
        super().__init__()
        self._counter = 0

    def _response(self, request=None):
        body = ""
        if request is not None and request.payload:
            body = f"  fetch-body={request.payload.hex()}"
        return Message(payload=f"counter={self._counter}{body}".encode())

    async def render_get(self, request):
        return self._response()

    async def render_fetch(self, request):
        return self._response(request)


async def run_server(interval: float):
    root = resource.Site()
    counter = CounterResource()
    root.add_resource(["counter"], counter)

    ctx = await aiocoap.Context.create_server_context(root, bind=("::1", 5683))
    print(f"[server] aiocoap {aiocoap_version}")
    print(f"[server] coap://[::1]:5683/counter  (GET+Observe  and  FETCH+Observe)")
    print(f"[server] tick every {interval}s\n")

    while True:
        await asyncio.sleep(interval)
        counter._counter += 1
        counter.updated_state()          # re-calls render_get or render_fetch per observer
        print(f"[server] tick → counter={counter._counter}")


# ── Client ────────────────────────────────────────────────────────────────────

async def run_client(mode: str, max_notifications: int):
    ctx = await aiocoap.Context.create_client_context()
    print(f"[client] aiocoap {aiocoap_version}  mode={mode}\n")

    if mode == "get":
        req = Message(code=aiocoap.GET)
    else:
        req = Message(
            code=aiocoap.FETCH,
            payload=b"\x82\x01\x02",   # CBOR [1, 2] — arbitrary body to prove FETCH
        )
        req.opt.content_format = 0     # text/plain (simplified — use 141 for yang-ids)

    req.opt.uri_path        = ("counter",)
    req.opt.observe         = 0
    req.unresolved_remote   = "[::1]:5683"

    obs   = ctx.request(req)
    first = await obs.response
    print(f"[client] first response:")
    print(f"         code        = {first.code}")
    print(f"         opt.observe = {first.opt.observe}   ← None with standard aiocoap (bug)")
    print(f"         payload     = {first.payload!r}")
    print()

    count = 0
    try:
        async for resp in obs.observation:
            count += 1
            print(f"[client] notification #{count}:")
            print(f"         opt.observe = {resp.opt.observe}")
            print(f"         payload     = {resp.payload!r}")
            print()
            if count >= max_notifications:
                break
    except Exception as e:
        print(f"[client] observation ended: {type(e).__name__}: {e}")
    finally:
        obs.observation.cancel()
        await ctx.shutdown()
        print(f"[client] done  ({count} notification(s) received)")


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--server",   action="store_true", help="Run as server")
    p.add_argument("--mode",     choices=["get", "fetch"], default="fetch",
                   help="Client mode (default: fetch)")
    p.add_argument("--interval", type=float, default=3.0,
                   help="Server tick interval in seconds (default: 3)")
    p.add_argument("--max",      type=int,   default=5,
                   help="Max notifications to receive before stopping (default: 5)")
    args = p.parse_args()

    if args.server:
        asyncio.run(run_server(args.interval))
    else:
        asyncio.run(run_client(args.mode, args.max))


if __name__ == "__main__":
    main()
