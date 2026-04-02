"""
Siemens S7 PLC Simulator (Mock).

This script starts a Snap7 server that simulates a real S7 PLC.
It defines Data Block DB1 with 100 bytes and updates in real time:
  - Bytes 0-3:  Temperature (4-byte IEEE 754 float, big-endian)
  - Bytes 4-7:  Piece counter (4-byte unsigned integer, big-endian)
    - Byte 8 bit 0: Machine running (bool)
    - Byte 8 bit 1: Alarm active (bool)
"""

import asyncio
import math
import struct
import threading
import time
import logging

import snap7
from snap7.type import SrvArea

# Logging configuration
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("plc_simulator")

# Data Block size in bytes
DB_SIZE = 100

# Data Block identifier
DB_NUMBER = 1


class PLCSimulator:
    """
    Snap7-based S7 PLC simulator.

    Starts a Snap7 server, registers DB1 and continuously updates
    simulated values in a background thread.
    """

    def __init__(self, host: str = "0.0.0.0", port: int = 1102):
        """
        Initialise the simulator.

        Args:
            host: IP address the server will listen on.
            port: TCP port (default 1102, the S7 standard port).
        """
        self.host = host
        self.port = port

        # Snap7 server instance
        self._server = snap7.server.Server(log=False)

        # Shared memory for DB1 (100 bytes, initialised to zero)
        self._db_data = bytearray(DB_SIZE)

        # Controls whether the simulation loop is active
        self._running = False

        # Background thread that updates simulated values
        self._sim_thread: threading.Thread | None = None

        # Piece counter (incremented each simulation cycle)
        self._piece_counter: int = 0

    # ------------------------------------------------------------------
    # Lifecycle methods
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start the server and begin updating simulated values."""
        # Register DB1 as a DB memory area
        self._server.register_area(SrvArea.DB, DB_NUMBER, self._db_data)

        # Start the Snap7 server
        self._server.start_to(self.host, self.port)
        logger.info("Simulated PLC server listening on %s:%d", self.host, self.port)

        # Start the simulation background thread
        self._running = True
        self._sim_thread = threading.Thread(
            target=self._simulate_values, daemon=True, name="sim-values"
        )
        self._sim_thread.start()

    def stop(self) -> None:
        """Stop the simulation loop and the server."""
        self._running = False
        if self._sim_thread is not None:
            self._sim_thread.join(timeout=5)
        self._server.stop()
        logger.info("Simulated PLC server stopped.")

    # ------------------------------------------------------------------
    # Value simulation
    # ------------------------------------------------------------------

    def _simulate_values(self) -> None:
        """
        Simulation loop that updates DB1 values every second.

        - Bytes 0-3: Temperature (IEEE 754 float), oscillates between 18.0 and 28.0 °C.
        - Bytes 4-7: Piece counter (uint32), incremented by 1 each cycle.
        - Byte 8 bit 0: machine running (toggles every cycle).
        - Byte 8 bit 1: alarm active (True when temperature > 27.0 °C).
        """
        t = 0.0
        while self._running:
            # Temperature: sinusoidal wave between 18 and 28 degrees
            temperature = 23.0 + 5.0 * math.sin(t)

            # Pack the float into 4 bytes (big-endian, S7 format)
            temp_bytes = struct.pack(">f", temperature)
            for i, b in enumerate(temp_bytes):
                self._db_data[i] = b

            # Pack the piece counter as a big-endian uint32
            counter_bytes = struct.pack(">I", self._piece_counter % (2**32))
            for i, b in enumerate(counter_bytes):
                self._db_data[4 + i] = b

            # Digital states packed in byte 8
            machine_running = (self._piece_counter % 2) == 0
            alarm_active = temperature > 27.0

            digital_byte = 0
            if machine_running:
                digital_byte |= (1 << 0)
            if alarm_active:
                digital_byte |= (1 << 1)
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


# ------------------------------------------------------------------
# Entry point for running the simulator stand-alone
# ------------------------------------------------------------------

async def main() -> None:
    """Start the simulator and wait until Ctrl+C is pressed."""
    simulator = PLCSimulator()
    simulator.start()
    logger.info("Simulator running. Press Ctrl+C to stop.")
    try:
        while True:
            await asyncio.sleep(1)
    except asyncio.CancelledError:
        pass
    finally:
        simulator.stop()


if __name__ == "__main__":
    asyncio.run(main())
