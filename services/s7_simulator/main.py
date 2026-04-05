"""Container-ready Siemens S7 PLC simulator."""

from __future__ import annotations

import argparse
import asyncio
import logging
import math
import os
import struct
import threading
import time

import snap7
from snap7.type import SrvArea

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("plc_simulator")

DB_SIZE = 100
DB_NUMBER = 1

__all__ = ["DB_NUMBER", "DB_SIZE", "PLCSimulator", "main"]


class PLCSimulator:
    def __init__(self, host: str = "0.0.0.0", port: int = 1102):
        self.host = host
        self.port = port
        self._server = snap7.server.Server(log=False)
        self._db_data = bytearray(DB_SIZE)
        self._running = False
        self._sim_thread: threading.Thread | None = None
        self._piece_counter: int = 0

    def start(self) -> None:
        self._server.register_area(SrvArea.DB, DB_NUMBER, self._db_data)
        self._server.start_to(self.host, self.port)
        logger.info("Simulated PLC server listening on %s:%d", self.host, self.port)

        self._running = True
        self._sim_thread = threading.Thread(
            target=self._simulate_values, daemon=True, name="sim-values"
        )
        self._sim_thread.start()

    def stop(self) -> None:
        self._running = False
        if self._sim_thread is not None:
            self._sim_thread.join(timeout=5)
        self._server.stop()
        logger.info("Simulated PLC server stopped.")

    def _simulate_values(self) -> None:
        t = 0.0
        while self._running:
            temperature = 23.0 + 5.0 * math.sin(t)
            temp_bytes = struct.pack(">f", temperature)
            for index, byte_value in enumerate(temp_bytes):
                self._db_data[index] = byte_value

            counter_bytes = struct.pack(">I", self._piece_counter % (2**32))
            for index, byte_value in enumerate(counter_bytes):
                self._db_data[4 + index] = byte_value

            machine_running = (self._piece_counter % 2) == 0
            alarm_active = temperature > 27.0

            digital_byte = 0
            if machine_running:
                digital_byte |= 1 << 0
            if alarm_active:
                digital_byte |= 1 << 1
            self._db_data[8] = digital_byte

            logger.debug(
                "Simulated PLC -> Temperature: %.2f °C | Counter: %d | Running: %s | Alarm: %s",
                temperature,
                self._piece_counter,
                machine_running,
                alarm_active,
            )

            self._piece_counter += 1
            t += 0.1
            time.sleep(1.0)


def _default_host() -> str:
    return os.getenv("S7_SIM_HOST", "0.0.0.0")


def _default_port() -> int:
    try:
        return int(os.getenv("S7_SIM_PORT", "1102"))
    except ValueError:
        return 1102


async def main(host: str | None = None, port: int | None = None) -> None:
    simulator = PLCSimulator(host=host or _default_host(), port=port or _default_port())
    simulator.start()
    logger.info("Simulator running. Press Ctrl+C to stop.")
    try:
        while True:
            await asyncio.sleep(1)
    except asyncio.CancelledError:
        pass
    finally:
        simulator.stop()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Siemens S7 PLC Simulator")
    parser.add_argument(
        "--host",
        default=_default_host(),
        help="Bind host (default: 0.0.0.0 or S7_SIM_HOST)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=_default_port(),
        help="Bind port (default: 1102 or S7_SIM_PORT)",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    asyncio.run(main(host=args.host, port=args.port))
