"""
S7 Client Reader (S7Collector).

Responsible for connecting to the S7 PLC (or simulator), reading
DB1 values asynchronously and storing them in a local dictionary
that the rest of the system can consume.

Values read:
  - temperature:    float (DB1 bytes 0-3)
  - piece_counter:  int   (DB1 bytes 4-7)
    - machine_running: bool (DB1 byte 8, bit 0)
    - alarm_active:    bool (DB1 byte 8, bit 1)
"""

import asyncio
import logging
import struct
from typing import Any

import snap7
from snap7.error import S7Error
from tag_config import TAG_CONFIG

# Module logger
logger = logging.getLogger("s7_collector")

# Data Block number to read
DB_NUMBER = 1

def get_bit(byte_data: int, bit_index: int) -> bool:
    """
    Extract one bit from a byte.

    Args:
        byte_data: Byte value (0..255).
        bit_index: Bit index (0..7), where 0 is LSB.

    Returns:
        True if the bit is 1, else False.
    """
    if not 0 <= bit_index <= 7:
        raise ValueError("bit_index must be in range 0..7")
    return bool((byte_data >> bit_index) & 0x01)


def _tag_size_bytes(config: dict[str, int | str]) -> int:
    """Return the number of bytes needed for a tag at its starting offset."""
    data_type = config["data_type"]
    if data_type == "float":
        return 4
    if data_type == "uint32":
        return 4
    if data_type == "bool":
        return 1
    raise ValueError(f"Unsupported data_type: {data_type}")


DB1_READ_SIZE = max(
    int(config["byte_offset"]) + _tag_size_bytes(config)
    for config in TAG_CONFIG.values()
)


class S7Collector:
    """
    Asynchronous S7 data collector.

    Manages the connection to the PLC, periodically reads DB1 and
    exposes the values in the `data` dictionary.  When a read fails
    or the connection is lost, values are set to ``None`` so the OPC UA
    server can mark the corresponding nodes as Bad Status.
    """

    def __init__(self, host: str, rack: int = 0, slot: int = 1, port: int = 102):
        """
        Initialise the collector.

        Args:
            host: IP address of the PLC or simulator.
            rack: PLC rack number (default 0).
            slot: PLC slot number (default 1).
            port: ISO TCP port the PLC listens on (default 102).
        """
        self.host = host
        self.rack = rack
        self.slot = slot
        self.port = port

        # Snap7 client (re-created on each reconnection attempt)
        self._client: snap7.client.Client | None = None

        # Latest values read from the PLC; None means the value is invalid
        self.data: dict[str, Any] = {key: None for key in TAG_CONFIG}

        # Controls whether the periodic read loop is active
        self._running = False

        # Tracks whether the client is connected to the PLC
        self._connected = False

    # ------------------------------------------------------------------
    # Connection management
    # ------------------------------------------------------------------

    async def connect(self) -> bool:
        """
        Attempt to connect to the PLC asynchronously.

        Returns:
            True if the connection was established, False otherwise.
        """
        try:
            # Snap7 operations are blocking; run them in a thread-pool executor
            await asyncio.get_event_loop().run_in_executor(None, self._do_connect)
            self._connected = True
            logger.info("Connected to PLC at %s:%d", self.host, self.port)
            return True
        except (S7Error, OSError, RuntimeError) as exc:
            self._connected = False
            logger.warning("Could not connect to PLC: %s", exc)
            return False

    def _do_connect(self) -> None:
        """Perform the synchronous Snap7 connection."""
        self._client = snap7.client.Client()
        self._client.connect(self.host, self.rack, self.slot, self.port)

    async def disconnect(self) -> None:
        """Close the connection to the PLC."""
        if self._client is not None:
            try:
                await asyncio.get_event_loop().run_in_executor(
                    None, self._client.disconnect
                )
            except (S7Error, OSError, RuntimeError) as exc:
                logger.debug("Error while disconnecting: %s", exc)
        self._connected = False
        self._client = None

    # ------------------------------------------------------------------
    # Data reading
    # ------------------------------------------------------------------

    async def read_db1(self) -> bool:
        """
        Read DB1 values from the PLC and update ``self.data``.

        Returns:
            True if the read succeeded, False on any error.
        """
        if not self._connected or self._client is None:
            self._mark_bad_quality()
            return False

        try:
            # Read bytes required by all configured tags.
            raw = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: self._client.db_read(  # type: ignore[union-attr]
                    DB_NUMBER,
                    0,
                    DB1_READ_SIZE,
                ),
            )

            for tag_name, config in TAG_CONFIG.items():
                byte_offset = int(config["byte_offset"])
                data_type = str(config["data_type"])

                if data_type == "float":
                    self.data[tag_name] = struct.unpack(
                        ">f", raw[byte_offset : byte_offset + 4]
                    )[0]
                elif data_type == "uint32":
                    self.data[tag_name] = struct.unpack(
                        ">I", raw[byte_offset : byte_offset + 4]
                    )[0]
                elif data_type == "bool":
                    bit_offset = int(config["bit_offset"])
                    self.data[tag_name] = get_bit(raw[byte_offset], bit_offset)
                else:
                    raise ValueError(f"Unsupported data_type: {data_type}")

            logger.debug(
                "Values read -> %s",
                self.data,
            )
            return True

        except (S7Error, OSError, RuntimeError, struct.error) as exc:
            logger.warning("Error reading DB1: %s", exc)
            self._connected = False
            self._mark_bad_quality()
            return False

    def _mark_bad_quality(self) -> None:
        """Set all values to None to signal an invalid / unavailable state."""
        for key in self.data:
            self.data[key] = None

    # ------------------------------------------------------------------
    # Periodic read loop
    # ------------------------------------------------------------------

    async def run(self, interval: float = 0.5) -> None:
        """
        Start the periodic PLC read loop.

        Reconnects automatically whenever the connection is lost.

        Args:
            interval: Time in seconds between each read (default 0.5 s).
        """
        self._running = True
        logger.info("Starting periodic PLC read every %.1f s.", interval)

        while self._running:
            # Reconnect if the connection has been lost
            if not self._connected:
                await connect_with_retry(self, delay=5.0)

            # Read data from the PLC
            await self.read_db1()

            # Wait until the next read cycle
            await asyncio.sleep(interval)

    def stop(self) -> None:
        """Stop the periodic read loop."""
        self._running = False


# ------------------------------------------------------------------
# Reconnection helper
# ------------------------------------------------------------------

async def connect_with_retry(collector: "S7Collector", delay: float = 5.0) -> None:
    """
    Repeatedly attempt to connect the collector to the PLC until successful.

    Args:
        collector: S7Collector instance to connect.
        delay:     Seconds to wait between attempts.
    """
    while not collector._connected and collector._running:
        logger.info("Attempting to connect to PLC %s...", collector.host)
        success = await collector.connect()
        if not success:
            logger.info("Retrying in %.1f s...", delay)
            await asyncio.sleep(delay)
