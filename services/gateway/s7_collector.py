"""S7 client reader for the gateway service."""

from __future__ import annotations

import asyncio
import logging
import struct
from typing import Any

import snap7
from snap7.error import S7Error

from .config import get_variable_mappings, load_gateway_config

logger = logging.getLogger("s7_collector")

DB_NUMBER = 1
_DEFAULT_CONFIG = load_gateway_config()
DEFAULT_VARIABLE_MAPPINGS = get_variable_mappings(_DEFAULT_CONFIG)

__all__ = [
    "DB_NUMBER",
    "DB1_READ_SIZE",
    "DEFAULT_VARIABLE_MAPPINGS",
    "S7Collector",
    "connect_with_retry",
    "get_bit",
]


def get_bit(byte_data: int, bit_index: int) -> bool:
    if not 0 <= bit_index <= 7:
        raise ValueError("bit_index must be in range 0..7")
    return bool((byte_data >> bit_index) & 0x01)


def _tag_size_bytes(config: dict[str, int | str]) -> int:
    data_type = config["data_type"]
    if data_type in {"float", "uint32"}:
        return 4
    if data_type == "bool":
        return 1
    raise ValueError(f"Unsupported data_type: {data_type}")


DB1_READ_SIZE = max(
    int(config.get("byte_offset", 0)) + _tag_size_bytes(config)
    for config in DEFAULT_VARIABLE_MAPPINGS.values()
) if DEFAULT_VARIABLE_MAPPINGS else 0


class S7Collector:
    def __init__(
        self,
        host: str,
        rack: int = 0,
        slot: int = 1,
        port: int = 102,
        variable_mappings: dict[str, dict[str, int | str]] | None = None,
    ):
        self.host = host
        self.rack = rack
        self.slot = slot
        self.port = port
        self._client: snap7.client.Client | None = None
        self.variable_mappings = variable_mappings or DEFAULT_VARIABLE_MAPPINGS
        self.data: dict[str, Any] = {key: None for key in self.variable_mappings}
        self.read_size = max(
            int(config.get("byte_offset", 0)) + _tag_size_bytes(config)
            for config in self.variable_mappings.values()
        ) if self.variable_mappings else 0
        self._running = False
        self._connected = False

    async def connect(self) -> bool:
        try:
            await asyncio.get_running_loop().run_in_executor(None, self._do_connect)
            self._connected = True
            logger.info("Connected to PLC at %s:%d", self.host, self.port)
            return True
        except (S7Error, OSError, RuntimeError) as exc:
            self._connected = False
            logger.warning("Could not connect to PLC: %s", exc)
            return False

    def _do_connect(self) -> None:
        self._client = snap7.client.Client()
        self._client.connect(self.host, self.rack, self.slot, self.port)

    async def disconnect(self) -> None:
        if self._client is not None:
            try:
                await asyncio.get_running_loop().run_in_executor(
                    None, self._client.disconnect
                )
            except (S7Error, OSError, RuntimeError) as exc:
                logger.debug("Error while disconnecting: %s", exc)
        self._connected = False
        self._client = None

    async def read_db1(self) -> bool:
        if not self._connected or self._client is None:
            self._mark_bad_quality()
            return False

        try:
            raw = await asyncio.get_running_loop().run_in_executor(
                None,
                lambda: self._client.db_read(DB_NUMBER, 0, self.read_size),
            )

            for tag_name, config in self.variable_mappings.items():
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

            logger.debug("Values read -> %s", self.data)
            return True

        except (S7Error, OSError, RuntimeError, struct.error) as exc:
            logger.warning("Error reading DB1: %s", exc)
            self._connected = False
            self._mark_bad_quality()
            return False

    def _mark_bad_quality(self) -> None:
        for key in self.data:
            self.data[key] = None

    async def run(self, interval: float = 0.5) -> None:
        self._running = True
        logger.info("Starting periodic PLC read every %.1f s.", interval)

        while self._running:
            if not self._connected:
                await connect_with_retry(self, delay=5.0)

            await self.read_db1()
            await asyncio.sleep(interval)

    def stop(self) -> None:
        self._running = False


async def connect_with_retry(collector: "S7Collector", delay: float = 5.0) -> None:
    while not collector._connected and collector._running:
        logger.info("Attempting to connect to PLC %s...", collector.host)
        success = await collector.connect()
        if not success:
            logger.info("Retrying in %.1f s...", delay)
            await asyncio.sleep(delay)
