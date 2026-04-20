from __future__ import annotations

import asyncio
import json
import logging
import os

from aiohttp import web

from ..s7_simulator.tag_config import TAG_CONFIG as SIMULATOR_TAG_CONFIG
from .config import get_config_path, get_variable_mappings, load_gateway_config

logger = logging.getLogger("gateway_api")

routes = web.RouteTableDef()
GATEWAY_STATUS: dict[str, object] = {
    "plc_connected": False,
    "opcua_running": False,
    "last_error": None,
}
_CONFIG_RELOAD_EVENT: asyncio.Event | None = None


def set_config_reload_event(event: asyncio.Event | None) -> None:
    global _CONFIG_RELOAD_EVENT
    _CONFIG_RELOAD_EVENT = event


def update_status(**values: object) -> None:
    GATEWAY_STATUS.update(values)


@web.middleware
async def cors_middleware(request: web.Request, handler):
    if request.method == "OPTIONS":
        response = web.Response(status=204)
    else:
        response = await handler(request)

    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET,POST,OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return response

# Discover S7 variables (DB1 only, for now)
@routes.post("/discover")
async def discover(request):
    params = await request.json()
    host = params.get("host")
    rack = int(params.get("rack", 0))
    slot = int(params.get("slot", 1))
    port = int(params.get("port", 102))
    db_number = int(params.get("db_number", 1))

    if not host:
        return web.json_response({"error": "host is required"}, status=400)

    configured = get_variable_mappings(load_gateway_config())
    variables = []
    for name, cfg in SIMULATOR_TAG_CONFIG.items():
        variables.append(
            {
                "name": name,
                "db_number": db_number,
                "layout": cfg,
                "configured": configured.get(name),
            }
        )

    return web.json_response(
        {
            "plc": {"host": host, "rack": rack, "slot": slot, "port": port, "db_number": db_number},
            "variables": variables,
        }
    )

# Save config
@routes.post("/save-config")
async def save_config(request):
    config = await request.json()
    path = get_config_path()
    path.write_text(json.dumps(config, indent=2), encoding="utf-8")
    if _CONFIG_RELOAD_EVENT is not None:
        _CONFIG_RELOAD_EVENT.set()
    return web.json_response({"status": "ok", "path": str(path)})

# Status endpoint
@routes.get("/status")
async def status(request):
    return web.json_response(GATEWAY_STATUS)

app = web.Application()
app.middlewares.append(cors_middleware)
app.add_routes(routes)

async def start_api() -> web.AppRunner:
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(
        runner,
        host="0.0.0.0",
        port=int(os.getenv("GATEWAY_API_PORT", "8080")),
    )
    await site.start()
    return runner


async def stop_api(runner: web.AppRunner | None) -> None:
    if runner is not None:
        await runner.cleanup()
