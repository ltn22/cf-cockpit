#!/usr/bin/env python3
"""Cockpit CLI — interface ligne de commande pour le monitoring de capteurs."""

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
    def __init__(self, host: str, port: int | None, yang_model_name: str):
        self.host = host
        self.port = port
        self.yang_model_name = yang_model_name
        self.model = None
        self.ds = None
        self.protocol = None
        self.filters = []  # liste ordonnée des filtres de capteurs
        self._follow_tasks = {}  # idx -> asyncio.Task


    def _module_name(self) -> str:
        import os
        base = os.path.basename(self.yang_model_name)
        return base.split('@')[0].replace('.sid', '')

    def _uri(self, path: str) -> str:
        port_str = f":{self.port}" if self.port else ""
        return f"coap://{self.host}{port_str}/{path}"

    def _coap_request(self, uri: str, payload: bytes) -> aiocoap.Message:
        req = aiocoap.Message(code=aiocoap.FETCH, uri=uri, payload=payload)
        req.opt.content_format = 142
        req.opt.accept = 142
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

        req = self._coap_request(self._uri("c?d=0"), cbor.dumps(sid))
        resp = await asyncio.wait_for(self.protocol.request(req).response, timeout=5.0)
 
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

        req = self._coap_request(self._uri("c"), cbor.dumps(instance_id))
        resp = await asyncio.wait_for(self.protocol.request(req).response, timeout=5.0)
        decoded = json.loads(self.model.toJSON(resp.payload))
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

        req = self._coap_request(self._uri("c"), cbor.dumps(instance_id))
        resp = await asyncio.wait_for(self.protocol.request(req).response, timeout=5.0)
        data = json.loads(self.model.toJSON(resp.payload))
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

    async def cmd_follow(self, idx: int, step_ms: int = 5000, max_samples: int = 1):
        if not self._check_idx(idx):
            return

        f = self.filters[idx - 1]
        module_name = self._module_name()
        db_xpath = f"{module_name}:transducers/transducer"

        # 1. iPATCH — activate history notification on the sensor
        xpath_hist = f"/{db_xpath}{f}/notification-parameters/history"
        target_sid, key_values = self.ds._resolve_path(xpath_hist)
        ipatch_key = [target_sid] + key_values

        qualified_payload = {db_xpath + '/notification-parameters/history': {
            'active': True, 'step': step_ms, 'max-samples': max_samples,
            'encoding': 'delta',
        }}
        ipatch_payload = cbor.dumps({tuple(ipatch_key): cbor.loads(
            self.model.toCORECONF(json.dumps(qualified_payload))
        )})

        patch_req = aiocoap.Message(
            code=aiocoap.numbers.codes.Code(7),  # iPATCH
            uri=self._uri("c"),
            payload=ipatch_payload,
        )
        patch_req.opt.content_format = 142

        resp = await asyncio.wait_for(self.protocol.request(patch_req).response, timeout=5.0)
        if not resp.code.is_successful():
            print(f"  Erreur iPATCH: {resp.code}")
            return

        # 2. FETCH+Observe on /s for history/time-series
        xpath_ts = f"/{module_name}:history/time-series{f}"
        target_sid_ts, key_values_ts = self.ds._resolve_path(xpath_ts)
        instance_id = [target_sid_ts] + key_values_ts

        obs_req = aiocoap.Message(code=aiocoap.FETCH, uri=self._uri("s"),
                                  payload=cbor.dumps(instance_id))
        obs_req.opt.content_format = 142
        obs_req.opt.accept = 142
        obs_req.opt.observe = 0

        obs = self.protocol.request(obs_req)
        first = await asyncio.wait_for(obs.response, timeout=5.0)
        if not first.code.is_successful():
            print(f"  Erreur Observe: {first.code}")
            obs.observation.cancel()
            return

        data = self.ds[db_xpath + f]
        m_type = data.get('type', '?').split(':')[-1]
        precision = data.get('precision', 0)
        unit = data.get('unit', '')
        factor = 10 ** precision

        print(f"  [{idx}] Observation {m_type} démarrée")

        def _print_values(payload):
            new_ds = self.model.create_datastore(payload)
            xpath_values = f"/{module_name}:history/time-series{f}/values"
            values = new_ds[xpath_values]
            ts = time.strftime('%H:%M:%S')
            if isinstance(values, list):
                for v in values:
                    print(f"  [{idx}] {m_type}: {v / factor} {unit}  ({ts})")
            elif values is not None:
                print(f"  [{idx}] {m_type}: {values / factor} {unit}  ({ts})")

        _print_values(first.payload)

        try:
            async for resp in obs.observation:
                _print_values(resp.payload)
        except (KeyboardInterrupt, asyncio.CancelledError):
            pass
        finally:
            obs.observation.cancel()
            print("  Observation arrêtée.")

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
        print("Commandes: list, refresh N, stat N, follow N, quit  (ou: l, r N, s N, f N, q)")

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

            elif cmd in ('follow', 'f'):
                if len(parts) < 2:
                    print("  Usage: follow N")
                    continue
                try:
                    n = int(parts[1])
                    if n in self._follow_tasks and not self._follow_tasks[n].done():
                        print(f"  Capteur {n} déjà observé.")
                    else:
                        self._follow_tasks[n] = asyncio.ensure_future(self.cmd_follow(n))
                        print(f"  Observation capteur {n} lancée en arrière-plan.")
                except ValueError:
                    print(f"  Argument invalide: {parts[1]}")
                except Exception as e:
                    print(f"  Erreur: {e}")

            elif cmd in ('unfollow', 'uf'):
                if len(parts) < 2:
                    print("  Usage: unfollow N")
                    continue
                try:
                    n = int(parts[1])
                    task = self._follow_tasks.pop(n, None)
                    if task and not task.done():
                        task.cancel()
                        print(f"  Observation capteur {n} arrêtée.")
                    else:
                        print(f"  Capteur {n} non observé.")
                except ValueError:
                    print(f"  Argument invalide: {parts[1]}")

            elif cmd == 'help':
                print("  list / l              — lister les capteurs")
                print("  refresh N / r N       — lire la valeur du capteur N")
                print("  stat N / s N          — statistiques du capteur N")
                print("  follow N / f N        — observer le capteur N en arriere-plan")
                print("  unfollow N / uf N     — arreter l'observation du capteur N")
                print("  quit / q              — quitter")

            else:
                print(f"  Commande inconnue: '{line}'. Tapez 'help' pour l'aide.")


def main():
    parser = argparse.ArgumentParser(description="Cockpit CLI — monitoring de capteurs IoT")
    parser.add_argument("--host",  default="[::1]",                  help="Hôte CoAP (défaut: [::1])")
    parser.add_argument("--port",  type=int, default=None,           help="Port CoAP")
    parser.add_argument("--model", default="coreconf-m2m@2026-03-29", help="Nom du modèle YANG")
    parser.add_argument("-v", "--verbose", action="store_true",      help="Logs détaillés")
    args = parser.parse_args()

    if not args.verbose:
        logging.disable(logging.CRITICAL)

    cli = CockpitCLI(args.host, args.port, args.model)
    asyncio.run(cli.run())


if __name__ == "__main__":
    main()
