#!/usr/bin/env python3
"""Cockpit CLI — interface ligne de commande pour le monitoring de capteurs."""

__version__ = "1.5.0"

import asyncio
import argparse
import json
import logging
import time
import sys

import aiocoap

import cbor2 as cbor
from pycoreconf import CORECONFModel


def _no_data(precision: int) -> str:
    return '---' if precision == 0 else f"---.{'-' * precision}"


class CockpitCLI:
    def __init__(self, host: str, port: int | None, yang_model_name: str, timeout: float = 10.0):
        self.host = host
        self.port = port
        self.yang_model_name = yang_model_name
        self.timeout = timeout
        self.model = None
        self.ds = None
        self.protocol = None
        self.filters = []  # liste ordonnée des filtres de capteurs
        self._follow_tasks = {}  # idx -> asyncio.Task


    def _module_name(self) -> str:
        import os
        base = os.path.basename(self.yang_model_name)
        return base.split('@')[0].replace('.sid', '')

    def _remote(self) -> str:
        port_str = f":{self.port}" if self.port else ""
        return f"{self.host}{port_str}"

    def _coap_request(self, path: str, payload: bytes) -> aiocoap.Message:
        req = aiocoap.Message(transport_tuning=aiocoap.Unreliable, code=aiocoap.FETCH, payload=payload)
        if '?' in path:
            p, q = path.split('?', 1)
            req.opt.uri_path = (p,)
            req.opt.uri_query = tuple(q.split('&'))
        else:
            req.opt.uri_path = (path,)
        req.opt.content_format = 141
        req.opt.accept = 142
        req.unresolved_remote = self._remote()
        return req

    async def init(self):
        sid_file = (self.yang_model_name
                    if self.yang_model_name.endswith('.sid')
                    else f"{self.yang_model_name}.sid")
        self.model = CORECONFModel(sid_file)
        self.protocol = await aiocoap.Context.create_client_context()

    async def bootstrap(self) -> list:
        module_name = self._module_name()
        xpath = f"/{module_name}:transducers/transducer"
        sid = self.model.sids[xpath]

        req = self._coap_request("c?d=0", cbor.dumps(sid))
        resp = await asyncio.wait_for(self.protocol.request(req).response, timeout=self.timeout)
 
        self.ds = self.model.create_datastore(resp.payload)
        db_xpath = f"{module_name}:transducers/transducer"

        self.filters = self.ds.predicates(db_xpath)
        return self.filters

    def _sensor_info(self, idx: int) -> tuple[str, dict]:
        """Retourne (filter, data) pour le capteur numéro idx (base 1)."""
        f = self.filters[idx - 1]
        module_name = self._module_name()
        db_xpath = f"{module_name}:transducers/transducer"
        return f, self.ds[db_xpath + f]

    def _check_idx(self, idx: int) -> bool:
        if idx < 1 or idx > len(self.filters):
            print(f"  Erreur: capteur {idx} inexistant (1–{len(self.filters)})")
            return False
        return True

    # ------------------------------------------------------------------ #
    # Commandes                                                            #
    # ------------------------------------------------------------------ #

    def cmd_list(self):
        module_name = self._module_name()
        db_xpath = f"{module_name}:transducers/transducer"
        print()
        print(f"  {'#':>3}  {'Type':<28} {'Unité':<8} Filtre")
        print("  " + "─" * 65)
        for i, f in enumerate(self.filters, 1):
            try:
                data = self.ds[db_xpath + f]
                m_type = data.get('type', '?').split(':')[-1]
                unit = data.get('unit', '')
            except Exception:
                m_type, unit = '?', ''
            print(f"  {i:>3}  {m_type:<28} {unit:<8} {f}")
        print()

    async def cmd_refresh(self, idx: int):
        if not self._check_idx(idx):
            return

        f = self.filters[idx - 1]
        module_name = self._module_name()
        db_xpath = f"{module_name}:transducers/transducer"
        xpath = f"/{db_xpath}{f}/quantity/value"

        target_sid, key_values = self.ds._resolve_path(xpath)
        instance_id = [target_sid] + key_values

        req = self._coap_request("c", cbor.dumps(instance_id))
        resp = await asyncio.wait_for(self.protocol.request(req).response, timeout=self.timeout)
        decoded = self.model.toJSON(resp.payload, return_pydict=True)
        raw = next(iter(decoded.values()), None)
        if isinstance(raw, str):
            raw = int(raw)

        _t = time.time_ns()
        self.ds[db_xpath + f] = {
            "quantity": {
                "value": raw,
                "timestamp": _t // 1_000_000_000,
                "u-timestamp": (_t % 1_000_000_000) // 1_000,
            }
        }

        data = self.ds[db_xpath + f]
        m_type = data.get('type', '?').split(':')[-1]
        precision = data.get('precision', 0)
        unit = data.get('unit', '')
        value = raw / 10 ** precision if raw is not None else _no_data(precision)
        ts = time.strftime('%H:%M:%S')
        print(f"  [{idx}] {m_type}: {value} {unit}  ({ts})")

    async def cmd_stat(self, idx: int):
        if not self._check_idx(idx):
            return

        f = self.filters[idx - 1]
        module_name = self._module_name()
        db_xpath = f"{module_name}:transducers/transducer"
        xpath = f"/{db_xpath}{f}/quantity/statistics"

        target_sid, key_values = self.ds._resolve_path(xpath)
        instance_id = [target_sid] + key_values

        req = self._coap_request("c", cbor.dumps(instance_id))
        resp = await asyncio.wait_for(self.protocol.request(req).response, timeout=self.timeout)
        data = self.model.toJSON(resp.payload, return_pydict=True)
        stats = next(iter(data.values()), {})

        self.ds[db_xpath + f] = {'quantity': {'statistics': stats}}

        sensor_data = self.ds[db_xpath + f]
        m_type = sensor_data.get('type', '?').split(':')[-1]
        precision = sensor_data.get('precision', 0)
        unit = sensor_data.get('unit', '')
        factor = 10 ** precision

        def fmt(raw):
            return f"{raw / factor} {unit}" if raw is not None else _no_data(precision)

        print(f"\n  [{idx}] Statistiques — {m_type}:")
        print(f"    min:     {fmt(stats.get('min'))}")
        print(f"    max:     {fmt(stats.get('max'))}")
        print(f"    mean:    {fmt(stats.get('mean'))}")
        print(f"    median:  {fmt(stats.get('median'))}")
        print(f"    σ:       {fmt(stats.get('stdev'))}")
        print(f"    n:       {stats.get('sample-count', '---')}")
        print()

    async def cmd_stop(self, idx: int):
        """Arrête l'observation : annule localement, aiocoap envoie RST à la prochaine notification."""
        task = self._follow_tasks.pop(idx, None)
        if task is None or task.done():
            print(f"  Capteur {idx} non observé.")
            return
        task.cancel()
        print(f"  [{idx}] Observation arrêtée.")

    async def cmd_follow(self, idx: int, step_ms: int = 5000, max_samples: int = 3):
        if not self._check_idx(idx):
            return

        log = logging.getLogger(f"follow[{idx}]")
        obs = None

        try:
            f = self.filters[idx - 1]
            module_name = self._module_name()
            db_xpath = f"{module_name}:transducers/transducer"

            # 1. iPATCH — activate history notification on the sensor
            xpath_hist = f"/{db_xpath}{f}/notification-parameters/history"
            target_sid, key_values = self.ds._resolve_path(xpath_hist)
            ipatch_key = [target_sid] + key_values

            qualified_payload = {db_xpath + '/notification-parameters/history': {
                'step': step_ms, 'max-samples': max_samples,
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
                print(f"  Erreur iPATCH: {resp.code}")
                return

            # 2. FETCH+Observe on /s for history/time-series
            xpath_ts = f"/{module_name}:history/time-series{f}"
            log.debug("résolution xpath_ts: %s", xpath_ts)
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
                print(f"  Erreur Observe: {first.code}")
                return

            data = self.ds[db_xpath + f]
            m_type = data.get('type', '?').split(':')[-1]
            precision = data.get('precision', 0)
            unit = data.get('unit', '')
            factor = 10 ** precision

            print(f"  [{idx}] Observation {m_type} démarrée")

            encoding = 'delta'  # matches the iPATCH payload above

            def _print_values(payload):
                log.debug("notification reçue: %d octets payload=%s", len(payload), payload.hex())
                # Strip CoAP framing bytes (Observe + Content-Format options + 0xFF marker)
                # that may precede the actual CBOR payload in some aiocoap versions.
                ff = payload.find(b'\xff')
                if ff >= 0:
                    payload = payload[ff + 1:]
                try:
                    new_ds = self.model.create_datastore(payload)
                    xpath_values = f"/{module_name}:history/time-series{f}/values"
                    values = new_ds[xpath_values]
                    if not values:
                        return
                    log.debug("values brutes: %r", values)
                    if encoding == 'delta' and isinstance(values, list):
                        decoded, acc = [], 0
                        for v in values:
                            acc += v
                            decoded.append(acc)
                        values = decoded
                    ts = time.strftime('%H:%M:%S')
                    if isinstance(values, list):
                        for v in values:
                            print(f"  [{idx}] {m_type}: {v / factor} {unit}  ({ts})")
                    elif values is not None:
                        print(f"  [{idx}] {m_type}: {values / factor} {unit}  ({ts})")
                except Exception as e:
                    log.debug("erreur décodage:", exc_info=True)
                    print(f"  [{idx}] erreur décodage notification: {e}")

            log.debug("première réponse observe: code=%s, %d octets", first.code, len(first.payload))
            _print_values(first.payload)  # empty first response is silently skipped

            async for resp in obs.observation:
                log.debug("notification observe: code=%s, %d octets", resp.code, len(resp.payload))
                _print_values(resp.payload)

        except asyncio.CancelledError:
            pass
        except Exception as e:
            log.debug("erreur cmd_follow:", exc_info=True)
            print(f"  [{idx}] erreur: {e}")
        finally:
            if obs is not None:
                # obs.observation.cancel() marque cancelled=True mais le générateur
                # interne (_run) ne voit le flag qu'à la prochaine notification.
                # _stop_interest() le force immédiatement : la prochaine notification
                # arrivera sans handler enregistré et aiocoap enverra RST automatiquement.
                if obs.observation is not None:
                    try:
                        obs.observation.cancel()
                    except Exception:
                        pass
                try:
                    obs._stop_interest()
                except Exception:
                    pass
            print(f"  [{idx}] Observation arrêtée.")

    # ------------------------------------------------------------------ #
    # REPL                                                                 #
    # ------------------------------------------------------------------ #

    async def run(self):
        host_display = f"{self.host}:{self.port}" if self.port else self.host
        print(f"\nCockpit CLI — connexion à coap://{host_display} …")

        try:
            await self.init()
            await self.bootstrap()
        except Exception as e:
            print(f"Erreur de connexion: {e}")
            return

        print(f"Connecté. {len(self.filters)} capteur(s) découvert(s).")
        self.cmd_list()
        print("Commandes: list, refresh N, stat N, follow N, stop N, quit  (ou: l, r N, s N, f N, q)")

        loop = asyncio.get_event_loop()
        while True:
            try:
                line = await loop.run_in_executor(None, lambda: input("\ncockpit> ").strip())
            except (EOFError, KeyboardInterrupt):
                print("\nAu revoir.")
                break

            if not line:
                continue

            parts = line.split()
            cmd = parts[0].lower()

            if cmd in ('quit', 'exit', 'q'):
                print("Au revoir.")
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
                    print(f"  Numéro invalide: {parts[1]}")
                except Exception as e:
                    print(f"  Erreur: {e}")

            elif cmd in ('stat', 'stats', 's'):
                if len(parts) < 2:
                    print("  Usage: stat N")
                    continue
                try:
                    await self.cmd_stat(int(parts[1]))
                except ValueError:
                    print(f"  Numéro invalide: {parts[1]}")
                except Exception as e:
                    print(f"  Erreur: {e}")

            elif cmd == 'stop':
                if len(parts) < 2:
                    print("  Usage: stop N")
                    continue
                try:
                    await self.cmd_stop(int(parts[1]))
                except ValueError:
                    print(f"  Argument invalide: {parts[1]}")

            elif cmd in ('follow', 'f'):
                if len(parts) < 2:
                    print("  Usage: follow N")
                    continue
                try:
                    n = int(parts[1])
                    if n in self._follow_tasks and not self._follow_tasks[n].done():
                        print(f"  Capteur {n} déjà observé.")
                    else:
                        task = asyncio.ensure_future(self.cmd_follow(n))
                        def _on_done(t, _idx=n):
                            if not t.cancelled() and t.exception():
                                print(f"  [{_idx}] erreur tâche: {t.exception()!r}")
                        task.add_done_callback(_on_done)
                        self._follow_tasks[n] = task
                except ValueError:
                    print(f"  Argument invalide: {parts[1]}")
                except Exception as e:
                    print(f"  Erreur: {e}")

            elif cmd in ('unfollow', 'uf'):
                if len(parts) < 2:
                    print("  Usage: unfollow N")
                    continue
                try:
                    await self.cmd_stop(int(parts[1]))
                except ValueError:
                    print(f"  Argument invalide: {parts[1]}")

            elif cmd == 'help':
                print("  list / l              — lister les capteurs")
                print("  refresh N / r N       — lire la valeur du capteur N")
                print("  stat N                — statistiques du capteur N")
                print("  follow N / f N        — observer le capteur N en arriere-plan")
                print("  stop N / uf N         — arreter l'observation (envoie RST)")
                print("  quit / q              — quitter")

            else:
                print(f"  Commande inconnue: '{line}'. Tapez 'help' pour l'aide.")


def main():
    parser = argparse.ArgumentParser(description="Cockpit CLI — monitoring de capteurs IoT")
    parser.add_argument("--host",  default="[::1]",                  help="Hôte CoAP (défaut: [::1])")
    parser.add_argument("--port",  type=int, default=None,           help="Port CoAP")
    parser.add_argument("--model",   default="coreconf-m2m@2026-03-29", help="Nom du modèle YANG")
    parser.add_argument("--timeout", type=float, default=10.0,          help="Timeout CoAP en secondes (défaut: 10)")
    parser.add_argument("-v", "--verbose", action="store_true",         help="Logs détaillés")
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
