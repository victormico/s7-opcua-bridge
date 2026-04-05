"""Main entry point for the container-ready S7-to-OPC UA gateway service."""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import signal

from .opcua_server import OPCUAGateway
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


async def bridge_loop(
    collector: S7Collector,
    gateway: OPCUAGateway,
    interval: float = READ_INTERVAL,
) -> None:
    collector._running = True
    logger.info("Bridge loop started (interval=%.1f s).", interval)

    while True:
        if not collector._connected:
            logger.warning("PLC disconnected. Attempting to reconnect...")
            await connect_with_retry(collector, delay=5.0)

        await collector.read_db1()
        await gateway.update_nodes(collector.data)
        await asyncio.sleep(interval)


async def main(
    plc_host: str | None = None,
    plc_port: int | None = None,
    plc_rack: int | None = None,
    plc_slot: int | None = None,
    opcua_port: int | None = None,
) -> None:
    plc_host = plc_host or _default_plc_host()
    plc_port = plc_port if plc_port is not None else _default_int("PLC_PORT", 1102)
    plc_rack = plc_rack if plc_rack is not None else _default_int("PLC_RACK", 0)
    plc_slot = plc_slot if plc_slot is not None else _default_int("PLC_SLOT", 1)
    opcua_port = opcua_port if opcua_port is not None else _default_int("OPCUA_PORT", 4840)

    opcua_endpoint = f"opc.tcp://0.0.0.0:{opcua_port}/arduino/gateway"
    collector = S7Collector(host=plc_host, rack=plc_rack, slot=plc_slot, port=plc_port)

    await collector.connect()

    async with OPCUAGateway(endpoint=opcua_endpoint) as gateway:
        logger.info(
            "Bridge started. PLC=%s:%d | OPC UA endpoint=%s",
            plc_host,
            plc_port,
            opcua_endpoint,
        )

        loop = asyncio.get_running_loop()

        def _shutdown(sig: signal.Signals) -> None:
            logger.info("Signal %s received. Stopping bridge...", sig.name)
            collector.stop()
            for task in asyncio.all_tasks(loop):
                task.cancel()

        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, _shutdown, sig)

        try:
            await bridge_loop(collector, gateway, interval=READ_INTERVAL)
        except asyncio.CancelledError:
            logger.info("Bridge stopped cleanly.")
        finally:
            await collector.disconnect()


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
