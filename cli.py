#!/usr/bin/env python3
"""Cockpit CLI — command-line interface for sensor monitoring."""

__version__ = "1.6.0"

import asyncio
import argparse
import json
import logging
import re
import time
import sys
from pathlib import Path

import aiocoap

import cbor2 as cbor
from pycoreconf import CORECONFModel


# Two modules are needed: coreconf-m2m carries the structure (containers,
# lists, leaves) and atmos the transducer-type identities. CORECONFModel
# merges several SID files into a single SID table.
DEFAULT_SID_FILES = ["coreconf-m2m@2026-09-01", "atmos@2026-08-24"]

# default-unit / default-precision / default-category are YANG extensions, and
# SID files carry no extension data — so they are read straight from the YANG
# module the SID file designates. Each identity body is a flat list of
# statements (no nested braces), which keeps the parsing to one regex.
_IDENTITY_RE = re.compile(r"identity\s+([\w.-]+)\s*\{([^}]*)\}", re.S)
_DEFAULT_EXT_RE = re.compile(r"ccm2m:(default-unit|default-precision|default-category)\s+\"([^\"]*)\"")


def _no_data(precision: int | None) -> str:
    if not precision:  # unknown precision, or no decimals at all
        return '---'
    return f"---.{'-' * precision}"


class SidCatalog:
    """
    The loaded SID files, indexed by the SID ranges they own.

    A device answers identityref leaves with bare SID numbers. Going from such
    a number back to the module that assigned it — and from there to the YANG
    file holding the default-unit/default-precision extensions — is what this
    class is for. No product module name is hardcoded anywhere: a station built
    on another module works as soon as its .sid and .yang are supplied.
    """

    def __init__(self, sid_files: list[str]):
        self.modules = []  # one record per SID file, in load order
        for path in sid_files:
            meta = json.loads(Path(path).read_text())
            meta = meta.get("ietf-sid-file:sid-file", meta)
            self.modules.append({
                "path": Path(path),
                "name": meta.get("module-name", ""),
                "revision": meta.get("module-revision", ""),
                # entry-point and size are JSON strings, not numbers.
                "ranges": [(int(r["entry-point"]), int(r["entry-point"]) + int(r["size"]))
                           for r in meta.get("assignment-range", [])],
                "dependencies": {d["module-name"]: d["module-revision"]
                                 for d in meta.get("dependency-revision", [])},
            })
        self._defaults = {}  # module name -> {identity: {...}}, parsed on demand

    def module_of(self, sid: int | None) -> dict | None:
        """The module whose assignment-range covers *sid*."""
        if sid is None:
            return None
        for mod in self.modules:
            if any(low <= sid < high for low, high in mod["ranges"]):
                return mod
        return None

    @staticmethod
    def yang_path(mod: dict) -> Path:
        """The YANG module a SID file designates, sitting alongside it."""
        return mod["path"].parent / f"{mod['name']}@{mod['revision']}.yang"

    def describe(self):
        """Show which SID file owns which range, and the YANG module behind it."""
        print("\n  Loaded models")
        for mod in self.modules:
            ranges = ", ".join(f"{low}..{high - 1}" for low, high in mod["ranges"]) or "—"
            yang = self.yang_path(mod)
            state = yang.name if yang.exists() else f"{yang.name} (missing)"
            print(f"    {mod['path'].name:<30} SID {ranges:<22} → {state}")
            if not yang.exists():
                print(f"      Warning: default units and precisions for "
                      f"{mod['name']} unavailable — only the device's overrides apply.")

    def check_dependencies(self):
        """Warn when the loaded SID files disagree on a module revision."""
        loaded = {mod["name"]: mod["revision"] for mod in self.modules}
        for mod in self.modules:
            for name, revision in mod["dependencies"].items():
                if name in loaded and loaded[name] != revision:
                    print(f"  Warning: {mod['path'].name} depends on "
                          f"{name}@{revision}, but {name}@{loaded[name]} is loaded.")

    def resolve_identity(self, sid: int | None, identity: str) -> tuple[dict | None, dict]:
        """
        Walk a SID number back to its module and the defaults it declares.

        Returns (module record, {unit, precision, category}) — the module is
        None when no loaded SID file claims that number.
        """
        mod = self.module_of(sid)
        if mod is None:
            return None, {}
        return mod, self._module_defaults(mod).get(identity.split(':')[-1], {})

    def _module_defaults(self, mod: dict) -> dict:
        cached = self._defaults.get(mod["name"])
        if cached is not None:
            return cached

        yang = self.yang_path(mod)
        defaults = {}
        if not yang.exists():
            # Without the module the extensions are simply out of reach; the
            # overrides the device does send still apply, so carry on.
            # describe() is what reports the missing file to the user.
            pass
        else:
            for name, body in _IDENTITY_RE.findall(yang.read_text()):
                ext = dict(_DEFAULT_EXT_RE.findall(body))
                precision = ext.get("default-precision")
                defaults[name] = {
                    "unit": ext.get("default-unit"),
                    "precision": int(precision) if precision is not None else None,
                    "category": ext.get("default-category"),
                }
        self._defaults[mod["name"]] = defaults
        return defaults


class CockpitCLI:
    def __init__(self, host: str, port: int | None, sid_files: list[str], timeout: float = 10.0):
        self.host = host
        self.port = port
        self.sid_files = sid_files
        self.timeout = timeout
        self.model = None
        self.catalog = None
        self.module = None            # structure module, i.e. the XPath prefix
        self.ds = None
        self.protocol = None
        self.filters = []  # ordered list of sensor filters
        self.reference_epoch = 0      # bootstrap/reference-epoch
        self.minimal_step = 1         # bootstrap/minimal-step, in seconds
        self._follow_tasks = {}  # idx -> asyncio.Task

    def _structure_module(self) -> str:
        """The module defining the data tree, as opposed to the identity modules."""
        for mod in self.catalog.modules:
            if f"/{mod['name']}:bootstrap" in self.model.sids:
                return mod["name"]
        raise RuntimeError("no loaded module defines the bootstrap container")

    def _remote(self) -> str:
        port_str = f":{self.port}" if self.port else ""
        return f"{self.host}{port_str}"

    def _coap_request(self, path: str, payload: bytes) -> aiocoap.Message:
        req = aiocoap.Message(transport_tuning=aiocoap.Unreliable, code=aiocoap.FETCH, payload=payload)
        req.opt.uri_path = (path,)
        req.opt.content_format = 141
        req.opt.accept = 142
        req.unresolved_remote = self._remote()
        return req

    async def _fetch(self, instance_id) -> bytes:
        """FETCH one instance identifier and return the raw CORECONF payload.

        A FETCH always answers with the whole sub-tree below the requested
        node; there is no way to ask for less.
        """
        req = self._coap_request("c", cbor.dumps(instance_id))
        resp = await asyncio.wait_for(self.protocol.request(req).response, timeout=self.timeout)
        if not resp.code.is_successful():
            raise RuntimeError(f"FETCH {instance_id}: {resp.code}")
        return resp.payload

    async def init(self):
        paths = [f if f.endswith('.sid') else f"{f}.sid" for f in self.sid_files]
        self.catalog = SidCatalog(paths)
        self.catalog.check_dependencies()
        self.model = CORECONFModel(paths)
        self.module = self._structure_module()
        self.protocol = await aiocoap.Context.create_client_context()

    async def bootstrap(self) -> list:
        """
        Read the device's bootstrap container in one round trip.

        The whole sub-tree comes back: the scalar leaves (reference-epoch,
        uptime, minimal-step) together with the inventory entries. The
        inventory is also the discovery list — it enumerates every transducer
        the device knows, so the transducers list itself need not be walked.
        """
        self.catalog.describe()

        payload = await self._fetch(self.model.sids[f"/{self.module}:bootstrap"])
        self.ds = self.model.create_datastore(payload)

        self.reference_epoch = self._leaf(f"/{self.module}:bootstrap/reference-epoch", 0)
        self.minimal_step = self._leaf(f"/{self.module}:bootstrap/minimal-step", 1) or 1
        uptime = self._leaf(f"/{self.module}:bootstrap/uptime", None)

        epoch_date = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(self.reference_epoch))
        print(f"\n  {self.module}:bootstrap")
        print(f"    reference-epoch  {self.reference_epoch}  ({epoch_date})"
              "   ← origin of every timestamp in the model")
        print(f"    uptime           {uptime} s")
        print(f"    minimal-step     {self.minimal_step} s"
              "   ← floor for history/step")

        self.filters = self._hydrate_inventory()
        return self.filters

    def _leaf(self, xpath: str, default):
        try:
            value = self.ds[xpath]
        except Exception:
            return default
        return default if value is None else value

    def _hydrate_inventory(self) -> list:
        """
        Resolve unit and precision for every inventory entry, once.

        bootstrap/inventory carries unit-override / precision-override only
        where the device departs from the default declared on its
        transducer-type identity — in practice the station sends none at all.
        Writing the identity defaults in here, locally, turns every later read
        into a plain lookup instead of a fallback scattered over each call site.

        The hydrated container never leaves the client: bootstrap is
        config false, and sending it back would present defaults as overrides.
        """
        inv = f"/{self.module}:bootstrap/inventory"
        filters = []
        unresolved = []

        print(f"\n  {self.module}:bootstrap/inventory — SID → module → YANG defaults resolution")
        print(f"  {'SID':>9}  {'Identity':<34} {'Module':<14} {'Unit':<8} {'Prec.':>6}  Category")
        print("  " + "─" * 92)

        for f in self.ds.predicates(inv) or []:
            entry = self.ds[inv + f]
            identity = entry.get('type', '')
            # Address entries by their module-qualified identity: the short
            # form predicates() returns cannot be encoded back into a SID.
            qualified = f"[type='{identity}']"
            filters.append(qualified)

            sid = self.model.sids.get(identity)
            mod, defaults = self.catalog.resolve_identity(sid, identity)

            patch = {}
            if 'unit-override' not in entry and defaults.get('unit') is not None:
                patch['unit-override'] = defaults['unit']
            if 'precision-override' not in entry and defaults.get('precision') is not None:
                patch['precision-override'] = defaults['precision']
            if patch:
                self.ds[inv + qualified] = patch

            # A starred value came from the device as an override; a bare one
            # is the default the identity declares in its YANG module.
            hydrated = self.ds[inv + qualified]
            unit = hydrated.get('unit-override')
            precision = hydrated.get('precision-override')
            unit_str = '—' if unit is None else unit + ('' if 'unit-override' in patch else '*')
            prec_str = '—' if precision is None else f"{precision}" + ('' if 'precision-override' in patch else '*')
            print(f"  {sid if sid is not None else '?':>9}  {identity:<34} "
                  f"{(mod['name'] if mod else '?'):<14} {unit_str:<8} {prec_str:>6}  "
                  f"{defaults.get('category') or '—'}")

            # A raw integer means nothing without a precision to scale it by:
            # no override, no default, no value. Better a blank than a number
            # silently read at 10^0.
            if precision is None:
                unresolved.append((sid, identity))

        print("  " + "─" * 92)
        print("  * override sent by the device; without a star, default value read from the "
              "YANG module.")
        print("    The inventory completed this way stays local: bootstrap is config false and "
              "is never sent back.")

        for sid, identity in unresolved:
            print(f"  Warning: SID {sid} ({identity}) — no precision-override and no "
                  f"default-precision; values ignored.")

        return filters

    def _sensor(self, idx: int) -> tuple[str, str, str, int | None]:
        """
        (filter, short type, unit, precision) for sensor idx (1-based).

        A precision of None means the inventory resolved none — neither an
        override nor an identity default — so the raw values cannot be scaled.
        """
        f = self.filters[idx - 1]
        entry = self.ds[f"/{self.module}:bootstrap/inventory{f}"]
        return (f,
                entry.get('type', '?').split(':')[-1],
                entry.get('unit-override', ''),
                entry.get('precision-override'))

    def _scaled(self, raw, unit: str, precision: int | None) -> str:
        """Raw integer rendered at its precision, or a blank when unusable."""
        if raw is None or precision is None:
            return _no_data(precision)
        return f"{raw / 10 ** precision} {unit}".rstrip()

    def _local_time(self, timestamp) -> str:
        """Format a device timestamp, which is relative to reference-epoch."""
        if timestamp is None:
            return time.strftime('%H:%M:%S')
        return time.strftime('%H:%M:%S', time.localtime(self.reference_epoch + timestamp))

    def _check_idx(self, idx: int) -> bool:
        if idx < 1 or idx > len(self.filters):
            print(f"  Error: sensor {idx} does not exist (1–{len(self.filters)})")
            return False
        return True

    # ------------------------------------------------------------------ #
    # Commands                                                              #
    # ------------------------------------------------------------------ #

    def cmd_list(self):
        print()
        print(f"  {'#':>3}  {'Type':<28} {'Unit':<8} {'Prec.':>5}  Filter")
        print("  " + "─" * 78)
        for i in range(1, len(self.filters) + 1):
            try:
                f, m_type, unit, precision = self._sensor(i)
            except Exception:
                f, m_type, unit, precision = self.filters[i - 1], '?', '', None
            prec_str = '—' if precision is None else f"{precision}"
            print(f"  {i:>3}  {m_type:<28} {unit or '—':<8} {prec_str:>5}  {f}")
        print()

    async def cmd_refresh(self, idx: int):
        if not self._check_idx(idx):
            return

        f, m_type, unit, precision = self._sensor(idx)
        db_xpath = f"{self.module}:transducers/transducer"
        xpath = f"/{db_xpath}{f}/quantity/value"

        # Only the "value" leaf is fetched: timestamp and timestamp-source
        # are not needed for a plain refresh, and statistics are a sibling
        # fetched by cmd_stat.
        target_sid, key_values = self.ds._resolve_path(xpath)
        payload = await self._fetch([target_sid] + key_values)
        decoded = self.model.toJSON(payload, return_pydict=True)
        raw = next(iter(decoded.values()), None)
        if isinstance(raw, str):
            raw = int(raw)

        self.ds[db_xpath + f] = {"quantity": {"value": raw}}

        ts = self._local_time(None)
        print(f"  [{idx}] {m_type}: {self._scaled(raw, unit, precision)}  ({ts})")
        if precision is None:
            print(f"       unknown precision — raw {raw}, not converted.")

    async def cmd_stat(self, idx: int):
        if not self._check_idx(idx):
            return

        f, m_type, unit, precision = self._sensor(idx)
        db_xpath = f"{self.module}:transducers/transducer"
        xpath = f"/{db_xpath}{f}/statistics"

        target_sid, key_values = self.ds._resolve_path(xpath)
        payload = await self._fetch([target_sid] + key_values)
        data = self.model.toJSON(payload, return_pydict=True)
        stats = next(iter(data.values()), {}) or {}

        self.ds[db_xpath + f] = {'statistics': stats}

        def fmt(raw):
            return self._scaled(raw, unit, precision)

        print(f"\n  [{idx}] Statistics — {m_type}:")
        if precision is None:
            print("    unknown precision — values not converted.")
        print(f"    min:     {fmt(stats.get('min'))}")
        print(f"    max:     {fmt(stats.get('max'))}")
        print(f"    mean:    {fmt(stats.get('mean'))}")
        print(f"    median:  {fmt(stats.get('median'))}")
        print(f"    σ:       {fmt(stats.get('stdev'))}")
        print(f"    n:       {stats.get('sample-count', '---')}")
        print()

    async def cmd_stop(self, idx: int):
        """Stop the observation: cancel locally, aiocoap sends RST on the next notification."""
        task = self._follow_tasks.pop(idx, None)
        if task is None or task.done():
            print(f"  Sensor {idx} not observed.")
            return
        task.cancel()
        print(f"  [{idx}] Observation stopped.")

    async def cmd_follow(self, idx: int, step: int | None = None, max_samples: int = 3):
        if not self._check_idx(idx):
            return

        log = logging.getLogger(f"follow[{idx}]")
        obs = None

        # history/step is in seconds and must be at least bootstrap/minimal-step:
        # the device refreshes no faster than that, and a shorter step only
        # re-reads values it has not recomputed.
        requested = self.minimal_step if step is None else step
        step = max(requested, self.minimal_step)
        if step != requested:
            print(f"  [{idx}] step {requested} s < minimal-step, raised to {step} s.")

        try:
            f, m_type, unit, precision = self._sensor(idx)
            db_xpath = f"{self.module}:transducers/transducer"

            # 1. iPATCH — activate history notification on the sensor
            xpath_hist = f"/{db_xpath}{f}/notification-parameters/history"
            target_sid, key_values = self.ds._resolve_path(xpath_hist)
            ipatch_key = [target_sid] + key_values

            qualified_payload = {db_xpath + '/notification-parameters/history': {
                'step': step, 'max-samples': max_samples,
                'encoding': 'delta',
            }}
            ipatch_payload = cbor.dumps({tuple(ipatch_key): cbor.loads(
                self.model.toCORECONF(json.dumps(qualified_payload))
            )})

            patch_req = aiocoap.Message(
                transport_tuning=aiocoap.Unreliable,
                code=aiocoap.numbers.codes.Code(7),  # iPATCH
                payload=ipatch_payload,
            )
            patch_req.opt.uri_path = ('c',)
            patch_req.opt.content_format = 142
            patch_req.unresolved_remote = self._remote()

            resp = await asyncio.wait_for(self.protocol.request(patch_req).response, timeout=self.timeout)
            if not resp.code.is_successful():
                print(f"  iPATCH error: {resp.code}")
                return

            # 2. FETCH+Observe on /s for the time-series' "values" leaf-list
            # directly: the subscription is already transducer-specific, so
            # the "type" field carried by the full time-series entry would
            # only repeat what the client already knows.
            xpath_ts = f"/{self.module}:history/time-series{f}/values"
            log.debug("resolving xpath_ts: %s", xpath_ts)
            target_sid_ts, key_values_ts = self.ds._resolve_path(xpath_ts)
            instance_id = [target_sid_ts] + key_values_ts

            obs_req = aiocoap.Message(transport_tuning=aiocoap.Unreliable, code=aiocoap.FETCH,
                                      payload=cbor.dumps(instance_id))
            obs_req.opt.uri_path = ('s',)
            obs_req.opt.content_format = 141
            obs_req.opt.accept = 142
            obs_req.opt.observe = 0
            obs_req.unresolved_remote = self._remote()

            obs = self.protocol.request(obs_req, handle_blockwise=False)
            first = await asyncio.wait_for(obs.response, timeout=self.timeout)
            if not first.code.is_successful():
                print(f"  Observe error: {first.code}")
                return

            print(f"  [{idx}] {m_type} observation started (step {step} s, {max_samples} samples)")
            if precision is None:
                print(f"  [{idx}] unknown precision — received values will not be converted.")

            encoding = 'delta'  # matches the iPATCH payload above

            def _print_values(payload):
                log.debug("notification received: %d bytes payload=%s", len(payload), payload.hex())
                # Strip CoAP framing bytes (Observe + Content-Format options + 0xFF marker)
                # that may precede the actual CBOR payload in some aiocoap versions.
                ff = payload.find(b'\xff')
                if ff >= 0:
                    payload = payload[ff + 1:]
                try:
                    new_ds = self.model.create_datastore(payload)
                    values = new_ds[xpath_ts]
                    if not values:
                        return
                    log.debug("raw values: %r", values)
                    if encoding == 'delta' and isinstance(values, list):
                        decoded, acc = [], 0
                        for v in values:
                            acc += v
                            decoded.append(acc)
                        values = decoded
                    ts = time.strftime('%H:%M:%S')
                    if isinstance(values, list):
                        for v in values:
                            print(f"  [{idx}] {m_type}: {self._scaled(v, unit, precision)}  ({ts})")
                    elif values is not None:
                        print(f"  [{idx}] {m_type}: {self._scaled(values, unit, precision)}  ({ts})")
                except Exception as e:
                    log.debug("decode error:", exc_info=True)
                    print(f"  [{idx}] notification decode error: {e}")

            log.debug("first observe response: code=%s, %d bytes", first.code, len(first.payload))
            _print_values(first.payload)  # empty first response is silently skipped

            async for resp in obs.observation:
                log.debug("observe notification: code=%s, %d bytes", resp.code, len(resp.payload))
                _print_values(resp.payload)

        except asyncio.CancelledError:
            pass
        except Exception as e:
            log.debug("cmd_follow error:", exc_info=True)
            print(f"  [{idx}] error: {e}")
        finally:
            if obs is not None:
                # obs.observation.cancel() sets cancelled=True, but the internal
                # generator (_run) only sees the flag on the next notification.
                # _stop_interest() forces it immediately: the next notification
                # will arrive with no handler registered and aiocoap will send
                # RST automatically.
                if obs.observation is not None:
                    try:
                        obs.observation.cancel()
                    except Exception:
                        pass
                try:
                    obs._stop_interest()
                except Exception:
                    pass
            print(f"  [{idx}] Observation stopped.")

    # ------------------------------------------------------------------ #
    # REPL                                                                 #
    # ------------------------------------------------------------------ #

    async def run(self):
        host_display = f"{self.host}:{self.port}" if self.port else self.host
        print(f"\nCockpit CLI — connecting to coap://{host_display} …")

        try:
            await self.init()
            await self.bootstrap()
        except Exception as e:
            print(f"Connection error: {e}")
            return

        print(f"Connected. {len(self.filters)} sensor(s) discovered, "
              f"minimal step {self.minimal_step} s.")
        self.cmd_list()
        print("Commands: list, refresh N, stat N, follow N [step] [n], stop N, quit"
              "  (or: l, r N, s N, f N, q)")

        loop = asyncio.get_event_loop()
        while True:
            try:
                line = await loop.run_in_executor(None, lambda: input("\ncockpit> ").strip())
            except (EOFError, KeyboardInterrupt):
                print("\nGoodbye.")
                break

            if not line:
                continue

            parts = line.split()
            cmd = parts[0].lower()

            if cmd in ('quit', 'exit', 'q'):
                print("Goodbye.")
                break

            elif cmd in ('list', 'ls', 'l'):
                self.cmd_list()

            elif cmd in ('refresh', 'r'):
                if len(parts) < 2:
                    print("  Usage: refresh N")
                    continue
                try:
                    await self.cmd_refresh(int(parts[1]))
                except ValueError:
                    print(f"  Invalid number: {parts[1]}")
                except Exception as e:
                    print(f"  Error: {e}")

            elif cmd in ('stat', 'stats', 's'):
                if len(parts) < 2:
                    print("  Usage: stat N")
                    continue
                try:
                    await self.cmd_stat(int(parts[1]))
                except ValueError:
                    print(f"  Invalid number: {parts[1]}")
                except Exception as e:
                    print(f"  Error: {e}")

            elif cmd == 'stop':
                if len(parts) < 2:
                    print("  Usage: stop N")
                    continue
                try:
                    await self.cmd_stop(int(parts[1]))
                except ValueError:
                    print(f"  Invalid argument: {parts[1]}")

            elif cmd in ('follow', 'f'):
                if len(parts) < 2:
                    print("  Usage: follow N [step_s] [max_samples]")
                    continue
                try:
                    n = int(parts[1])
                    step = int(parts[2]) if len(parts) > 2 else None
                    samples = int(parts[3]) if len(parts) > 3 else 3
                    if n in self._follow_tasks and not self._follow_tasks[n].done():
                        print(f"  Sensor {n} already observed.")
                    else:
                        task = asyncio.ensure_future(self.cmd_follow(n, step, samples))
                        def _on_done(t, _idx=n):
                            if not t.cancelled() and t.exception():
                                print(f"  [{_idx}] task error: {t.exception()!r}")
                        task.add_done_callback(_on_done)
                        self._follow_tasks[n] = task
                except ValueError:
                    print(f"  Invalid argument: {' '.join(parts[1:])}")
                except Exception as e:
                    print(f"  Error: {e}")

            elif cmd in ('unfollow', 'uf'):
                if len(parts) < 2:
                    print("  Usage: unfollow N")
                    continue
                try:
                    await self.cmd_stop(int(parts[1]))
                except ValueError:
                    print(f"  Invalid argument: {parts[1]}")

            elif cmd == 'help':
                print("  list / l              — list sensors")
                print("  refresh N / r N       — read the value of sensor N")
                print("  stat N                — statistics for sensor N")
                print("  follow N [step] [n]   — observe sensor N in the background")
                print("                          step in seconds (default: minimal-step)")
                print("  stop N / uf N         — stop the observation (sends RST)")
                print("  quit / q              — quit")

            else:
                print(f"  Unknown command: '{line}'. Type 'help' for help.")


def main():
    parser = argparse.ArgumentParser(description="Cockpit CLI — IoT sensor monitoring")
    parser.add_argument("--host",  default="[::1]",                  help="CoAP host (default: [::1])")
    parser.add_argument("--port",  type=int, default=None,           help="CoAP port")
    parser.add_argument("--model", nargs="+", default=DEFAULT_SID_FILES,
                        help="YANG/SID models to load (structure then identities)")
    parser.add_argument("--timeout", type=float, default=10.0,          help="CoAP timeout in seconds (default: 10)")
    parser.add_argument("-v", "--verbose", action="store_true",         help="Verbose logs")
    args = parser.parse_args()

    if args.verbose:
        logging.basicConfig(level=logging.DEBUG, format="%(levelname)s %(name)s: %(message)s")
    else:
        logging.disable(logging.CRITICAL)

    import aiocoap.meta
    print(f"cli v{__version__}  aiocoap v{aiocoap.meta.version}")

    cli = CockpitCLI(args.host, args.port, args.model, timeout=args.timeout)
    asyncio.run(cli.run())


if __name__ == "__main__":
    main()
