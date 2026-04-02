"""
Tests for the S7-to-OPC UA Bridge.

Covers the main components:
  - PLCSimulator: creation, simulated values and lifecycle.
  - S7Collector: DB1 reading, error handling and bad-quality state.
  - OPCUAGateway: initialisation, node tree structure and value updates.
  - Integration: reading from the simulator and exposing via OPC UA.
"""

import asyncio
import struct
import sys
import time
import unittest
from unittest.mock import MagicMock

# Add the repository root to the path so imports work in all environments
sys.path.insert(0, __import__("os").path.dirname(__import__("os").path.dirname(__file__)))

from plc_simulator import PLCSimulator, DB_NUMBER, DB_SIZE
from s7_collector import S7Collector


# ---------------------------------------------------------------------------
# PLC Simulator tests
# ---------------------------------------------------------------------------

class TestPLCSimulator(unittest.TestCase):
    """Unit tests for the S7 PLC simulator."""

    def setUp(self) -> None:
        # Use a high port so no root privileges are required
        self.simulator = PLCSimulator(host="127.0.0.1", port=10202)

    def tearDown(self) -> None:
        self.simulator.stop()

    def test_db_data_initial_size(self) -> None:
        """The initial DB1 buffer must be exactly DB_SIZE bytes."""
        self.assertEqual(len(self.simulator._db_data), DB_SIZE)

    def test_start_stop(self) -> None:
        """The simulator must start and stop without errors."""
        self.simulator.start()
        time.sleep(0.2)
        # Simulation thread should be alive
        self.assertTrue(self.simulator._sim_thread.is_alive())
        self.simulator.stop()
        # _running flag should be cleared
        self.assertFalse(self.simulator._running)

    def test_simulate_values_updates_db(self) -> None:
        """DB1 values must change after at least one simulation cycle."""
        self.simulator.start()
        # Wait for the thread to write at least one update
        time.sleep(1.5)
        temp = struct.unpack(">f", bytes(self.simulator._db_data[0:4]))[0]
        counter = struct.unpack(">I", bytes(self.simulator._db_data[4:8]))[0]

        # Temperature must be within the expected range (18..28 °C)
        self.assertGreaterEqual(temp, 17.9)
        self.assertLessEqual(temp, 28.1)

        # Counter must have been incremented at least once
        self.assertGreater(counter, 0)

    def test_piece_counter_increments(self) -> None:
        """The piece counter must increment on each simulation cycle."""
        self.simulator.start()
        time.sleep(2.5)
        self.assertGreaterEqual(self.simulator._piece_counter, 2)


# ---------------------------------------------------------------------------
# S7Collector tests
# ---------------------------------------------------------------------------

class TestS7Collector(unittest.TestCase):
    """Unit tests for the S7 data collector."""

    def setUp(self) -> None:
        self.collector = S7Collector(host="127.0.0.1", rack=0, slot=1, port=10299)

    def test_initial_data_is_none(self) -> None:
        """Initial values must be None before any read has occurred."""
        self.assertIsNone(self.collector.data["temperature"])
        self.assertIsNone(self.collector.data["piece_counter"])

    def test_mark_bad_quality(self) -> None:
        """_mark_bad_quality must set all values to None."""
        self.collector.data["temperature"] = 23.0
        self.collector.data["piece_counter"] = 5
        self.collector._mark_bad_quality()
        self.assertIsNone(self.collector.data["temperature"])
        self.assertIsNone(self.collector.data["piece_counter"])

    def test_connect_failure_marks_disconnected(self) -> None:
        """A failed connection attempt must leave _connected as False."""
        result = asyncio.get_event_loop().run_until_complete(self.collector.connect())
        self.assertFalse(result)
        self.assertFalse(self.collector._connected)

    def test_read_db1_without_connection_returns_false(self) -> None:
        """Reading without a connection must return False and mark bad quality."""
        result = asyncio.get_event_loop().run_until_complete(self.collector.read_db1())
        self.assertFalse(result)
        self.assertIsNone(self.collector.data["temperature"])

    def test_read_db1_parses_values_correctly(self) -> None:
        """Values read from the PLC must be unpacked correctly."""
        # Prepare a bytearray that simulates a PLC response
        temp_expected = 25.5
        counter_expected = 42
        raw = bytearray(8)
        raw[0:4] = struct.pack(">f", temp_expected)
        raw[4:8] = struct.pack(">I", counter_expected)

        # Mock the Snap7 client
        mock_client = MagicMock()
        mock_client.db_read.return_value = raw

        self.collector._client = mock_client
        self.collector._connected = True

        result = asyncio.get_event_loop().run_until_complete(self.collector.read_db1())

        self.assertTrue(result)
        self.assertAlmostEqual(self.collector.data["temperature"], temp_expected, places=4)
        self.assertEqual(self.collector.data["piece_counter"], counter_expected)

    def test_read_db1_marks_bad_quality_on_exception(self) -> None:
        """An exception during reading must mark all values as None."""
        from snap7.error import S7Error

        mock_client = MagicMock()
        mock_client.db_read.side_effect = S7Error("connection lost")

        self.collector._client = mock_client
        self.collector._connected = True

        result = asyncio.get_event_loop().run_until_complete(self.collector.read_db1())

        self.assertFalse(result)
        self.assertIsNone(self.collector.data["temperature"])
        self.assertFalse(self.collector._connected)

    def test_stop_sets_running_false(self) -> None:
        """stop() must set _running to False."""
        self.collector._running = True
        self.collector.stop()
        self.assertFalse(self.collector._running)


# ---------------------------------------------------------------------------
# Integration tests: Simulator + S7Collector
# ---------------------------------------------------------------------------

class TestSimulatorCollectorIntegration(unittest.TestCase):
    """
    Integration test that verifies the S7Collector can read real data
    from a locally running PLCSimulator.
    """

    def test_read_from_simulator(self) -> None:
        """The collector must be able to read real values from the simulator."""
        simulator = PLCSimulator(host="127.0.0.1", port=10203)
        simulator.start()
        # Wait for the simulator to write at least one update
        time.sleep(1.5)

        collector = S7Collector(host="127.0.0.1", rack=0, slot=1, port=10203)

        async def _run() -> None:
            connected = await collector.connect()
            self.assertTrue(connected, "Could not connect to the simulator")
            ok = await collector.read_db1()
            self.assertTrue(ok, "DB1 read failed")
            self.assertIsNotNone(collector.data["temperature"])
            self.assertIsNotNone(collector.data["piece_counter"])
            # Temperature must be within the expected range
            self.assertGreaterEqual(collector.data["temperature"], 17.9)
            self.assertLessEqual(collector.data["temperature"], 28.1)
            await collector.disconnect()

        asyncio.get_event_loop().run_until_complete(_run())
        simulator.stop()


# ---------------------------------------------------------------------------
# OPC UA server tests
# ---------------------------------------------------------------------------

class TestOPCUAGateway(unittest.IsolatedAsyncioTestCase):
    """Async tests for the OPC UA server."""

    async def asyncSetUp(self) -> None:
        from opcua_server import OPCUAGateway, NAMESPACE_URI, NODE_DEFINITIONS
        self.OPCUAGateway = OPCUAGateway
        self.NAMESPACE_URI = NAMESPACE_URI
        self.NODE_DEFINITIONS = NODE_DEFINITIONS

    async def test_init_and_namespace(self) -> None:
        """The OPC UA server must register the namespace correctly."""
        gw = self.OPCUAGateway(endpoint="opc.tcp://127.0.0.1:14840/test")
        async with gw:
            self.assertGreater(gw._ns_idx, 0)
            self.assertEqual(len(gw._nodes), len(self.NODE_DEFINITIONS))

    async def test_update_nodes_good_values(self) -> None:
        """Valid values must update nodes with a Good StatusCode."""
        from asyncua import ua

        gw = self.OPCUAGateway(endpoint="opc.tcp://127.0.0.1:14841/test")
        async with gw:
            data = {"temperature": 24.3, "piece_counter": 10}
            await gw.update_nodes(data)

            temp_node = gw._nodes["temperature"]
            dv = await temp_node.read_data_value()
            self.assertEqual(dv.StatusCode_.value, ua.StatusCodes.Good)
            self.assertAlmostEqual(dv.Value.Value, 24.3, places=3)

    async def test_update_nodes_bad_status_on_none(self) -> None:
        """A None value must result in a Bad StatusCode on the node."""
        from asyncua import ua

        gw = self.OPCUAGateway(endpoint="opc.tcp://127.0.0.1:14842/test")
        async with gw:
            data = {"temperature": None, "piece_counter": None}
            await gw.update_nodes(data)

            temp_node = gw._nodes["temperature"]
            # Pass raise_on_bad_status=False so we can inspect the status code
            dv = await temp_node.read_data_value(raise_on_bad_status=False)
            self.assertNotEqual(dv.StatusCode_.value, ua.StatusCodes.Good)


if __name__ == "__main__":
    unittest.main()
