"""Tests for the Arduino App Lab WebUI adapter (app/python/web_adapter.py).

The adapter only depends on the shared ``services`` package (no App Lab
runtime), so it can be exercised off-board with a fake WebUI and simulator.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]
APP_PYTHON = REPO_ROOT / "app" / "python"
if str(APP_PYTHON) not in sys.path:
    sys.path.insert(0, str(APP_PYTHON))

import web_adapter  # noqa: E402
from services.gateway import status as gateway_status  # noqa: E402
from services.s7_simulator.tag_config import TAG_CONFIG as SIMULATOR_TAG_CONFIG  # noqa: E402


class FakeUI:
    def __init__(self) -> None:
        self.handlers: dict = {}
        self.sent: list = []

    def on_message(self, event, handler):
        self.handlers[event] = handler

    def send_message(self, event, payload=None, client=None):
        self.sent.append((event, payload, client))

    def emit(self, event, client=None, data=None):
        self.handlers[event](client, data)

    def last(self, event):
        for evt, payload, _client in reversed(self.sent):
            if evt == event:
                return payload
        return None


class FakeSim:
    def __init__(self) -> None:
        self._running = False

    @property
    def running(self) -> bool:
        return self._running

    def start(self) -> None:
        self._running = True

    def stop(self) -> None:
        self._running = False


class TestWebAdapter(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.config_path = Path(self.temp_dir.name) / "config.json"
        self.env_patch = patch.dict(
            os.environ, {"GATEWAY_CONFIG": str(self.config_path)}, clear=False
        )
        self.env_patch.start()
        gateway_status.update_status(plc_connected=False, opcua_running=False, last_error=None)
        gateway_status.set_config_reload_event(None)

        self.ui = FakeUI()
        self.sim = FakeSim()
        web_adapter.register(self.ui, self.sim)

    def tearDown(self) -> None:
        self.env_patch.stop()
        self.temp_dir.cleanup()

    def test_discover_returns_layout_and_configured(self) -> None:
        self.config_path.write_text(
            json.dumps(
                {
                    "variables": [
                        {
                            "name": "temperature",
                            "data_type": "float",
                            "byte_offset": 0,
                            "display_name": "Temperature",
                            "enabled": True,
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )

        self.ui.emit("discover", client="c1", data={"host": "127.0.0.1", "db_number": 1})

        result = self.ui.last("discover_result")
        self.assertEqual(result["plc"]["host"], "127.0.0.1")
        self.assertEqual(len(result["variables"]), len(SIMULATOR_TAG_CONFIG))
        temperature = next(v for v in result["variables"] if v["name"] == "temperature")
        self.assertEqual(temperature["layout"], SIMULATOR_TAG_CONFIG["temperature"])
        self.assertEqual(temperature["configured"]["display_name"], "Temperature")

    def test_discover_requires_host(self) -> None:
        self.ui.emit("discover", client="c1", data={})
        self.assertEqual(self.ui.last("discover_result"), {"error": "host is required"})

    def test_save_config_writes_file_and_triggers_reload(self) -> None:
        reload_event = asyncio.Event()
        gateway_status.set_config_reload_event(reload_event)
        config = {
            "plc": {"host": "127.0.0.1", "rack": 0, "slot": 1, "port": 1102},
            "opcua_port": 4840,
            "variables": [{"name": "temperature", "data_type": "float", "byte_offset": 0, "enabled": True}],
        }

        self.ui.emit("save_config", client="c1", data=config)

        result = self.ui.last("save_result")
        self.assertTrue(result["ok"])
        self.assertTrue(self.config_path.exists())
        self.assertEqual(json.loads(self.config_path.read_text(encoding="utf-8")), config)
        self.assertTrue(reload_event.is_set())
        gateway_status.set_config_reload_event(None)

    def test_status_includes_simulator_state(self) -> None:
        gateway_status.update_status(plc_connected=True, opcua_running=True)
        self.sim.start()

        self.ui.emit("get_status", client="c1")

        status = self.ui.last("status_update")
        self.assertTrue(status["plc_connected"])
        self.assertTrue(status["opcua_running"])
        self.assertTrue(status["simulator_running"])

    def test_sim_toggle_broadcasts_status(self) -> None:
        self.ui.emit("sim_start", client="c1")
        self.assertTrue(self.sim.running)
        self.assertTrue(self.ui.last("status_update")["simulator_running"])

        self.ui.emit("sim_stop", client="c1")
        self.assertFalse(self.sim.running)
        self.assertFalse(self.ui.last("status_update")["simulator_running"])


if __name__ == "__main__":
    unittest.main()
