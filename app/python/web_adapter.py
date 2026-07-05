"""WebUI message handlers for the App Lab gateway.

This is the App Lab equivalent of ``services/gateway/gateway_api.py``: it exposes
the same three operations the dashboard needs — discover, save-config, status —
but over the ``arduino:web_ui`` Brick's Socket.IO channel instead of an aiohttp
REST API. It deliberately reuses the exact same gateway helpers and shared
state so the two front-ends stay behaviourally identical.

The browser (``assets/app.js``) speaks these messages:

    -> discover           {host, rack, slot, port, db_number}
    <- discover_result    {plc, variables}
    -> save_config        {plc, opcua_port, variables}
    <- save_result        {ok, path|error}
    -> get_initial_state  (none)
    <- initial_state      {config, status}
    -> get_status         (none)
    <- status_update      {plc_connected, opcua_running, last_error, simulator_running}
    -> sim_start | sim_stop
    <- status_update      (broadcast)
"""

from __future__ import annotations

import json
import logging

from services.gateway.config import (
    get_config_path,
    get_variable_mappings,
    load_gateway_config,
)
from services.gateway.status import get_status, trigger_config_reload
from services.s7_simulator.tag_config import TAG_CONFIG as SIMULATOR_TAG_CONFIG

logger = logging.getLogger("web_adapter")


def status_payload(sim) -> dict:
    """Current gateway health plus the embedded-simulator state."""
    payload = get_status()
    payload["simulator_running"] = sim.running
    return payload


def register(ui, sim) -> None:
    """Wire the dashboard messages to gateway operations.

    ``ui`` is the WebUI Brick instance, ``sim`` the SimulatorController from
    main.py. Handlers receive ``(client, data)`` from the web_ui Brick.
    """

    def on_discover(client, data):
        logger.info("discover request from %s: %s", client, data)
        data = data or {}
        host = data.get("host")
        if not host:
            ui.send_message("discover_result", {"error": "host is required"}, client)
            return

        configured = get_variable_mappings(load_gateway_config())
        variables = [
            {
                "name": name,
                "db_number": int(data.get("db_number", 1)),
                "layout": cfg,
                "configured": configured.get(name),
            }
            for name, cfg in SIMULATOR_TAG_CONFIG.items()
        ]
        logger.info("discover -> returning %d variables", len(variables))
        ui.send_message(
            "discover_result",
            {
                "plc": {
                    "host": host,
                    "rack": int(data.get("rack", 0)),
                    "slot": int(data.get("slot", 1)),
                    "port": int(data.get("port", 102)),
                    "db_number": int(data.get("db_number", 1)),
                },
                "variables": variables,
            },
            client,
        )

    def on_save_config(client, data):
        try:
            path = get_config_path()
            path.write_text(json.dumps(data, indent=2), encoding="utf-8")
            # The gateway loop runs on another thread; trigger_config_reload
            # hops back to it safely (call_soon_threadsafe) so the OPC UA node
            # tree rebuilds with the new mapping.
            trigger_config_reload()
            ui.send_message("save_result", {"ok": True, "path": str(path)}, client)
        except OSError as exc:
            logger.exception("Failed to save config")
            ui.send_message("save_result", {"ok": False, "error": str(exc)}, client)

    def on_get_initial_state(client, data):
        config = load_gateway_config()
        logger.info(
            "initial_state request from %s: %d configured variables",
            client,
            len(config.get("variables", [])),
        )
        ui.send_message(
            "initial_state",
            {"config": config, "status": status_payload(sim)},
            client,
        )

    def on_get_status(client, data):
        ui.send_message("status_update", status_payload(sim), client)

    def on_sim_start(client, data):
        sim.start()
        ui.send_message("status_update", status_payload(sim))

    def on_sim_stop(client, data):
        sim.stop()
        ui.send_message("status_update", status_payload(sim))

    ui.on_message("discover", on_discover)
    ui.on_message("save_config", on_save_config)
    ui.on_message("get_initial_state", on_get_initial_state)
    ui.on_message("get_status", on_get_status)
    ui.on_message("sim_start", on_sim_start)
    ui.on_message("sim_stop", on_sim_stop)
    logger.info("WebUI message handlers registered (discover/save_config/status/sim)")
