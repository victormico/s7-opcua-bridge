"""
Main entry point for the S7-to-OPC UA Bridge.

Integrates S7Collector and OPCUAGateway in an async loop that:
  1. Connects to the S7 PLC (or simulator).
  2. Starts the OPC UA server.
  3. Reads PLC values every 500 ms.
  4. Updates the OPC UA nodes with the latest values.

Usage:
    python main.py [--host HOST] [--port PORT] [--opcua-port OPCUA_PORT]

When run without arguments it connects to the local simulator
(127.0.0.1:1102) and exposes the OPC UA server on port 4840.
"""

import argparse
import asyncio
import logging
import signal

from opcua_server import OPCUAGateway
from s7_collector import S7Collector, connect_with_retry

# Global logging configuration
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("main")

# PLC read interval (500 ms)
READ_INTERVAL = 0.5


async def bridge_loop(
    collector: S7Collector,
    gateway: OPCUAGateway,
    interval: float = READ_INTERVAL,
) -> None:
    """
    Main bridge loop.

    Reads data from the PLC and updates the OPC UA nodes on every iteration.

    Args:
        collector: S7Collector instance (connected or reconnecting).
        gateway:   OPCUAGateway instance that has already been started.
        interval:  Seconds between each read cycle (default 0.5 s).
    """
    logger.info("Bridge loop started (interval=%.1f s).", interval)

    while True:
        # Reconnect to the PLC if the connection has been lost
        if not collector._connected:
            logger.warning("PLC disconnected. Attempting to reconnect...")
            await connect_with_retry(collector, delay=5.0)

        # Read data from the PLC
        await collector.read_db1()

        # Update OPC UA nodes (Bad Status is set automatically when value is None)
        await gateway.update_nodes(collector.data)

        # Wait until the next read cycle
        await asyncio.sleep(interval)


async def main(
    plc_host: str = "127.0.0.1",
    plc_port: int = 1102,
    plc_rack: int = 0,
    plc_slot: int = 1,
    opcua_port: int = 4840,
) -> None:
    """
    Main coroutine for the S7 <-> OPC UA bridge.

    Args:
        plc_host:   IP address of the S7 PLC (or simulator).
        plc_port:   TCP port of the S7 PLC.
        plc_rack:   Rack number of the S7 PLC.
        plc_slot:   Slot number of the S7 PLC.
        opcua_port: TCP port for the OPC UA server.
    """
    opcua_endpoint = f"opc.tcp://0.0.0.0:{opcua_port}/arduino/gateway"

    # Create the S7 collector
    collector = S7Collector(
        host=plc_host, rack=plc_rack, slot=plc_slot, port=plc_port
    )

    # Connect to the PLC in the background (does not block the OPC UA server)
    await collector.connect()

    # Start the OPC UA server and run the bridge loop
    async with OPCUAGateway(endpoint=opcua_endpoint) as gateway:
        logger.info(
            "Bridge started. PLC=%s:%d | OPC UA endpoint=%s",
            plc_host,
            plc_port,
            opcua_endpoint,
        )

        # Register signal handlers for a clean shutdown
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


# ------------------------------------------------------------------
# Command-line argument parsing
# ------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="S7-to-OPC UA Industrial Gateway"
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="IP address of the S7 PLC (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=1102,
        help="TCP port of the S7 PLC (default: 1102)",
    )
    parser.add_argument(
        "--rack",
        type=int,
        default=0,
        help="Rack number of the S7 PLC (default: 0)",
    )
    parser.add_argument(
        "--slot",
        type=int,
        default=1,
        help="Slot number of the S7 PLC (default: 1)",
    )
    parser.add_argument(
        "--opcua-port",
        type=int,
        default=4840,
        help="TCP port for the OPC UA server (default: 4840)",
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
