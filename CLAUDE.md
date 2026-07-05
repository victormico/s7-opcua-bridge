# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

An edge gateway that reads a Siemens S7 PLC's data block over the S7 protocol
and re-exposes it as an OPC UA server, with a browser dashboard for configuring
the tag mapping. Targets the Arduino UNO Q (ARM64) as the production edge device.

## Commands

```bash
# Full stack (simulator + gateway + dashboard) — the primary workflow
docker compose up --build

# Local dev: run each service as a module from the repo root (relative imports
# mean you cannot run the .py files directly)
python -m services.s7_simulator.main          # terminal 1: fake PLC on :1102
python -m services.gateway.main                # terminal 2: gateway
python -m services.gateway.main --host 192.168.0.10 --port 102 --rack 0 --slot 1

# Tests (unittest-based; run under pytest or plain unittest)
python -m pytest tests/ -v
python -m pytest tests/test_bridge.py::TestS7Collector::test_read_db1_parses_values_correctly -v
python -m unittest discover -s tests -p "test_*.py" -v   # if pytest isn't installed

# Arduino App Lab app (runs on the UNO Q, not locally — see app/README.md)
# Preferred: build a self-contained zip and Import from ZIP in App Lab.
python scripts/build_applab_zip.py            # -> dist/s7-opcua-gateway-applab.zip
# Or run from a full repo checkout on the board:
scp -r . arduino@gaudi:~/ArduinoApps/s7-opcua-bridge
arduino-app-cli app start ~/ArduinoApps/s7-opcua-bridge/app
```

Dependencies: `pip install -r requirements.txt` (or the per-service
`services/*/requirements.txt`). Requires a virtualenv with `python-snap7`,
`asyncua`, and `aiohttp`.

Ports: gateway OPC UA `4840`, gateway HTTP API `8080`, dashboard `3000` (Docker),
simulated/real PLC `1102` (this project uses the non-privileged `1102` instead of
the standard S7 port `102` so no `sudo` is needed).

## Architecture

Three independent services under `services/`, each with its own Dockerfile,
wired together by `docker-compose.yml`:

- **`s7_simulator/`** — a snap7 *server* that fakes a PLC. `main.py` runs a
  background thread updating a `bytearray` DB every second (sine-wave
  temperature, incrementing counter, boolean flags). Its byte layout lives in
  `tag_config.py`.
- **`gateway/`** — the core. Reads the PLC and serves OPC UA + an HTTP config API.
- **`dashboard/`** — static HTML/JS (served by nginx in Docker) that calls the
  gateway HTTP API to discover tags and persist the mapping.

### Gateway internals (`services/gateway/`)

- `main.py` — orchestrator. Resolves settings with a fixed precedence
  (**CLI arg → env var → config.json → hardcoded default**), then runs a
  **reload loop**: on each iteration it (re)creates the `S7Collector` and
  `OPCUAGateway` from the current config and runs `bridge_loop`. Saving config
  through the API sets an `asyncio.Event`; the loop detects it, raises
  `RuntimeError("Config reload requested")`, and rebuilds the OPC UA node tree
  so renamed/added tags take effect live. This sentinel-string RuntimeError is
  control flow, not an error — don't "fix" it by catching it away.
- `s7_collector.py` — the S7 client. snap7 is **blocking**, so every call
  (`connect`, `db_read`, `disconnect`) is wrapped in
  `run_in_executor`. `read_db1` does one bulk read of DB1 then slices/unpacks
  each tag by `byte_offset`/`data_type` (big-endian: `>f`, `>I`, and bit masking
  for booleans). On any read failure it sets `_connected = False` and marks all
  values `None`.
- `opcua_server.py` — async OPC UA server (`OPCUAGateway`, used as an async
  context manager). Builds the node tree `Objects/Industrial_Unit/S7_PLC_1/<tags>`.
  `update_nodes` writes `Good` status for real values and **`BadNoData` status
  for `None`** (this is how PLC disconnects surface to OPC UA clients — the
  server stays up, nodes go Bad, then recover).
- `gateway_api.py` — aiohttp API on `:8080` with permissive CORS for the
  dashboard: `POST /discover`, `POST /save-config` (writes config + fires the
  reload event), `GET /status`. Shared runtime state lives in module-level
  `GATEWAY_STATUS` and `_CONFIG_RELOAD_EVENT`.
- `config.py` — loads/parses `config.json`. `GATEWAY_CONFIG` env var overrides
  the path (in Docker it points at a persistent named volume,
  `/config/config.json`). `get_variable_mappings` skips disabled tags;
  `build_node_definitions` derives OPC UA display names.

### The config contract ties everything together

A single **variable-mappings** structure (`{tag_name: {byte_offset, data_type,
bit_offset?, display_name?, enabled?}}`, `data_type` ∈ `float`/`uint32`/`bool`)
flows from `config.json` through `config.py` into both the collector (drives how
bytes are parsed) and the OPC UA server (drives the node tree). To support a new
data type you must extend it in **three** places: `_tag_size_bytes` +
unpack logic in `s7_collector.py`, the `type_map` in `build_node_definitions`,
and `_DEFAULT_VALUES` in `opcua_server.py`. The simulator's `tag_config.py` is a
separate fixed layout that must stay byte-compatible with these mappings.

## Arduino App Lab app (`app/`)

A second deployment target: the same gateway packaged as a native Arduino App
Lab app for the UNO Q (contest deliverable). It **reuses** `services/gateway`
and `services/s7_simulator` rather than duplicating them, so both this and the
Docker stack stay in sync. Key pieces:

- `app/python/main.py` — App Lab entry. App Lab owns the main thread via
  `App.run(user_loop=…)`; the gateway runs in a **background daemon thread**
  (`asyncio.run(gateway_main(manage_signals=False, start_http_api=False,
  stop_event=…, on_cycle=…))`). It puts the repo root on `sys.path` to import
  `services`, so **the whole repo must be deployed**, and starts the app from
  `app/`. All `Bridge.call` / `ui.send_message` traffic is kept on the main
  thread (in `status_loop`); the gateway thread only writes shared state.
- `app/python/web_adapter.py` — the App Lab analogue of `gateway_api.py`:
  same discover/save-config/status operations, but over the `arduino:web_ui`
  Brick's Socket.IO channel (`ui.on_message`/`ui.send_message`) instead of REST.
- `app/sketch/sketch.ino` — MCU status LED, RPC target `set_status`.
- `app/assets/` — the dashboard, ported to the WebUI Socket.IO client.

This drove three small, additive changes to the shared core, all
default-off for the Docker path: `main()` gained `manage_signals` /
`start_http_api` / `stop_event` / `on_cycle` kwargs; `bridge_loop` and
`connect_with_retry` gained a `stop_event`; and the shared `GATEWAY_STATUS` /
reload-event state moved to `services/gateway/status.py` (re-exported from
`gateway_api.py`). The reload event is now fired via
`status.trigger_config_reload()`, which uses `call_soon_threadsafe` when the
firing thread differs from the gateway loop — essential for the App Lab case.

## Conventions

- All I/O is `asyncio`; wrap any blocking library call in `run_in_executor`
  rather than calling it directly in a coroutine.
- Services are Python packages run with `python -m services.<name>.main`; keep
  intra-package imports relative (`from .config import ...`).
