from __future__ import annotations

import asyncio
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from services.gateway import gateway_api
from services.gateway.config import (
    build_node_definitions,
    get_plc_settings,
    get_variable_mappings,
    load_gateway_config,
)
from services.s7_simulator.tag_config import TAG_CONFIG as SIMULATOR_TAG_CONFIG


class TestGatewayConfigHelpers(unittest.TestCase):
    def test_load_gateway_config_missing_returns_empty(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.json"
            self.assertEqual(load_gateway_config(config_path), {})

    def test_get_config_path_uses_environment_override(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            custom_path = Path(temp_dir) / "shared-config.json"
            with patch.dict(os.environ, {"GATEWAY_CONFIG": str(custom_path)}, clear=False):
                self.assertEqual(load_gateway_config(), {})
                self.assertEqual(custom_path, gateway_api.get_config_path())

    def test_get_plc_settings_and_variable_mappings(self) -> None:
        config = {
            "plc": {"host": "192.168.1.10", "rack": 0, "slot": 1, "port": 102},
            "variables": [
                {
                    "name": "temperature",
                    "data_type": "float",
                    "byte_offset": 0,
                    "display_name": "Temperature",
                    "enabled": True,
                },
                {
                    "name": "alarm_active",
                    "data_type": "bool",
                    "byte_offset": 8,
                    "bit_offset": 1,
                    "enabled": False,
                },
            ],
        }

        self.assertEqual(get_plc_settings(config), config["plc"])
        self.assertEqual(
            get_variable_mappings(config),
            {
                "temperature": {
                    "data_type": "float",
                    "byte_offset": 0,
                    "display_name": "Temperature",
                }
            },
        )

    def test_build_node_definitions_uses_display_names(self) -> None:
        variable_mappings: dict[str, dict[str, int | str]] = {
            "temperature": {
                "data_type": "float",
                "byte_offset": 0,
                "display_name": "Line Temperature",
            },
            "piece_counter": {
                "data_type": "uint32",
                "byte_offset": 4,
                "display_name": "Piece Counter",
            },
        }

        definitions = build_node_definitions(variable_mappings)

        self.assertEqual(definitions["temperature"][0], "Line_Temperature")
        self.assertEqual(definitions["piece_counter"][0], "Piece_Counter")


class TestGatewayAPI(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.config_path = Path(self.temp_dir.name) / "config.json"
        self.env_patch = patch.dict(
            os.environ,
            {"GATEWAY_CONFIG": str(self.config_path)},
            clear=False,
        )
        self.env_patch.start()
        gateway_api.update_status(
            plc_connected=False,
            opcua_running=False,
            last_error=None,
        )
        gateway_api.set_config_reload_event(None)

        app = web.Application(middlewares=[gateway_api.cors_middleware])
        app.add_routes(gateway_api.routes)
        self.client = TestClient(TestServer(app))
        await self.client.start_server()

    async def asyncTearDown(self) -> None:
        await self.client.close()
        self.env_patch.stop()
        self.temp_dir.cleanup()

    async def test_discover_returns_plc_metadata_and_layout(self) -> None:
        payload = {
            "plc": {
                "host": "192.168.1.10",
                "rack": 0,
                "slot": 1,
                "port": 102,
                "db_number": 1,
            },
            "variables": [
                {
                    "name": "temperature",
                    "data_type": "float",
                    "byte_offset": 0,
                    "display_name": "Temperature",
                    "enabled": True,
                }
            ],
        }
        self.config_path.write_text(json.dumps(payload), encoding="utf-8")

        response = await self.client.post(
            "/discover",
            json={"host": "192.168.1.10", "rack": 0, "slot": 1, "port": 102, "db_number": 1},
        )

        self.assertEqual(response.status, 200)
        body = await response.json()
        self.assertEqual(body["plc"]["host"], "192.168.1.10")
        self.assertEqual(len(body["variables"]), len(SIMULATOR_TAG_CONFIG))
        temperature = next(item for item in body["variables"] if item["name"] == "temperature")
        self.assertEqual(temperature["layout"], SIMULATOR_TAG_CONFIG["temperature"])
        self.assertEqual(temperature["configured"]["display_name"], "Temperature")

    async def test_save_config_writes_json_file(self) -> None:
        config = {
            "plc": {"host": "127.0.0.1", "rack": 0, "slot": 1, "port": 102},
            "opcua_port": 4840,
            "variables": [
                {"name": "temperature", "data_type": "float", "byte_offset": 0, "enabled": True}
            ],
        }

        reload_event = asyncio.Event()
        gateway_api.set_config_reload_event(reload_event)

        response = await self.client.post("/save-config", json=config)

        self.assertEqual(response.status, 200)
        self.assertTrue(self.config_path.exists())
        self.assertEqual(json.loads(self.config_path.read_text(encoding="utf-8")), config)
        self.assertTrue(reload_event.is_set())

        gateway_api.set_config_reload_event(None)

    async def test_status_endpoint_reflects_runtime_state(self) -> None:
        gateway_api.update_status(
            plc_connected=True,
            opcua_running=True,
            last_error=None,
        )

        response = await self.client.get("/status")

        self.assertEqual(response.status, 200)
        self.assertEqual(
            await response.json(),
            {
                "plc_connected": True,
                "opcua_running": True,
                "last_error": None,
            },
        )
