"""Main entry point for the container-ready S7-to-OPC UA gateway service."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import signal
from pathlib import Path


from .opcua_server import OPCUAGateway
from .gateway_api import set_config_reload_event, start_api, stop_api, update_status
from .config import get_config_path, get_plc_settings, get_variable_mappings, load_gateway_config
from .s7_collector import S7Collector, connect_with_retry

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("main")

READ_INTERVAL = 0.5

__all__ = ["READ_INTERVAL", "bridge_loop", "main", "_parse_args"]


def _default_plc_host() -> str:
    return os.getenv("PLC_IP", "127.0.0.1")


def _default_int(name: str, fallback: int) -> int:
    try:
        return int(os.getenv(name, str(fallback)))
    except ValueError:
        return fallback


def _load_config() -> dict[str, object]:
    try:
        return load_gateway_config(get_config_path())
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Ignoring invalid config file %s: %s", get_config_path(), exc)
        return {}


async def bridge_loop(
    collector: S7Collector,
    gateway: OPCUAGateway,
    interval: float = READ_INTERVAL,
    reload_event: asyncio.Event | None = None,
) -> None:
    collector._running = True
    logger.info("Bridge loop started (interval=%.1f s).", interval)

    while True:
        if reload_event is not None and reload_event.is_set():
            raise RuntimeError("Config reload requested")

        if not collector._connected:
            logger.warning("PLC disconnected. Attempting to reconnect...")
            await connect_with_retry(collector, delay=5.0)
            update_status(plc_connected=collector._connected)

        await collector.read_db1()
        await gateway.update_nodes(collector.data)
        update_status(
            plc_connected=collector._connected,
            opcua_running=True,
            last_error=None,
        )
        await asyncio.sleep(interval)


async def main(
    plc_host: str | None = None,
    plc_port: int | None = None,
    plc_rack: int | None = None,
    plc_slot: int | None = None,
    opcua_port: int | None = None,
) -> None:
    config = _load_config()
    plc_config = get_plc_settings(config)
    variable_mappings = get_variable_mappings(config)

    plc_host = plc_host or os.getenv("PLC_IP") or str(plc_config.get("host", _default_plc_host()))
    plc_port = (
        plc_port
        if plc_port is not None
        else _default_int("PLC_PORT", int(plc_config.get("port", 1102)))
    )
    plc_rack = (
        plc_rack
        if plc_rack is not None
        else _default_int("PLC_RACK", int(plc_config.get("rack", 0)))
    )
    plc_slot = (
        plc_slot
        if plc_slot is not None
        else _default_int("PLC_SLOT", int(plc_config.get("slot", 1)))
    )
    opcua_port = (
        opcua_port
        if opcua_port is not None
        else _default_int("OPCUA_PORT", int(config.get("opcua_port", 4840)))
    )

    opcua_endpoint = f"opc.tcp://0.0.0.0:{opcua_port}/arduino/gateway"
    loop = asyncio.get_running_loop()
    api_runner = await start_api()
    current_collector: S7Collector | None = None

    def _shutdown(sig: signal.Signals) -> None:
        logger.info("Signal %s received. Stopping bridge...", sig.name)
        if current_collector is not None:
            current_collector.stop()
        for task in asyncio.all_tasks(loop):
            task.cancel()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _shutdown, sig)

    try:
        while True:
            config_reload_event = asyncio.Event()
            set_config_reload_event(config_reload_event)

            config = _load_config()
            plc_config = get_plc_settings(config)
            variable_mappings = get_variable_mappings(config)

            current_collector = S7Collector(
                host=plc_host or os.getenv("PLC_IP") or str(plc_config.get("host", _default_plc_host())),
                rack=plc_rack if plc_rack is not None else _default_int("PLC_RACK", int(plc_config.get("rack", 0))),
                slot=plc_slot if plc_slot is not None else _default_int("PLC_SLOT", int(plc_config.get("slot", 1))),
                port=plc_port if plc_port is not None else _default_int("PLC_PORT", int(plc_config.get("port", 1102))),
                variable_mappings=variable_mappings,
            )

            await current_collector.connect()
            update_status(plc_connected=current_collector._connected, opcua_running=False, last_error=None)

            try:
                async with OPCUAGateway(endpoint=opcua_endpoint, variable_mappings=variable_mappings) as gateway:
                    logger.info(
                        "Bridge started. PLC=%s:%d | OPC UA endpoint=%s",
                        current_collector.host,
                        current_collector.port,
                        opcua_endpoint,
                    )
                    await bridge_loop(
                        current_collector,
                        gateway,
                        interval=READ_INTERVAL,
                        reload_event=config_reload_event,
                    )
            except RuntimeError as exc:
                if str(exc) != "Config reload requested":
                    raise
                logger.info("Gateway config changed. Reloading OPC UA nodes...")
                continue
            finally:
                await current_collector.disconnect()
                update_status(plc_connected=False, opcua_running=False, last_error=None)
    except asyncio.CancelledError:
        logger.info("Bridge stopped cleanly.")
    finally:
        set_config_reload_event(None)
        await stop_api(api_runner)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="S7-to-OPC UA Industrial Gateway")
    parser.add_argument(
        "--host",
        default=_default_plc_host(),
        help="IP address of the S7 PLC (default: 127.0.0.1 or PLC_IP)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=_default_int("PLC_PORT", 1102),
        help="TCP port of the S7 PLC (default: 1102 or PLC_PORT)",
    )
    parser.add_argument(
        "--rack",
        type=int,
        default=_default_int("PLC_RACK", 0),
        help="Rack number of the S7 PLC (default: 0 or PLC_RACK)",
    )
    parser.add_argument(
        "--slot",
        type=int,
        default=_default_int("PLC_SLOT", 1),
        help="Slot number of the S7 PLC (default: 1 or PLC_SLOT)",
    )
    parser.add_argument(
        "--opcua-port",
        type=int,
        default=_default_int("OPCUA_PORT", 4840),
        help="TCP port for the OPC UA server (default: 4840 or OPCUA_PORT)",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    asyncio.run(
        main(
            plc_host=args.host,
            plc_port=args.port,
            plc_rack=args.rack,
            plc_slot=args.slot,
            opcua_port=args.opcua_port,
        )
    )
