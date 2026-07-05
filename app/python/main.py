"""Arduino App Lab entry point for the S7 -> OPC UA gateway.

App Lab owns the main thread (via ``App.run``) and serves the dashboard through
the ``arduino:web_ui`` Brick. The gateway itself is the existing asyncio service
(``services.gateway.main.main``), run here in a background daemon thread. This
file is the glue:

  * background thread  -> runs the S7 <-> OPC UA bridge (asyncio)
  * WebUI handlers     -> discover / save-config / status / simulator toggle
  * status_loop (main) -> pushes health to the browser AND to the microcontroller
                          (Bridge.call "set_status"), keeping every Bridge/WebUI
                          call on the main thread

The whole repository is deployed to the board and this app is started from its
``app/`` subfolder, so we put the repo root on sys.path to import the shared
``services`` package rather than duplicating it.
"""

from __future__ import annotations

import logging
import sys
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent              # .../app/python
APP_DIR = HERE.parent                               # .../app
REPO_ROOT = APP_DIR.parent                          # repo root (dev / GUI-from-repo)
# Make `services` importable whether the app is self-contained (a vendored copy
# in python/services, e.g. an imported .zip) or running from the full repo
# checkout (services/ at the repo root). HERE also lets `import web_adapter`
# resolve. HERE is inserted last so the vendored copy wins when both exist.
for _p in (REPO_ROOT, HERE):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import os

# Keep the App Lab gateway config separate from the Docker default and make it
# writable on the board. Defaults (see app/config.json) point at the embedded
# simulator on 127.0.0.1:1102 so the app works with no PLC wired.
os.environ.setdefault("GATEWAY_CONFIG", str(APP_DIR / "config.json"))

import asyncio  # noqa: E402  (after sys.path/env setup)

from arduino.app_utils import App, Bridge  # noqa: E402  (App Lab runtime only)
from arduino.app_bricks.web_ui import WebUI  # noqa: E402

from services.gateway.main import main as gateway_main  # noqa: E402
from services.gateway.status import get_status, update_status  # noqa: E402
from services.s7_simulator.main import PLCSimulator  # noqa: E402

import web_adapter  # noqa: E402  (sibling module in app/python)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("applab_main")

STATUS_PUSH_INTERVAL = 1.0  # seconds
SIM_HOST = "127.0.0.1"
SIM_PORT = 1102

_stop_event = threading.Event()


class SimulatorController:
    """Start/stop the embedded S7 simulator so the app is demoable with no PLC."""

    def __init__(self, host: str = SIM_HOST, port: int = SIM_PORT) -> None:
        self._host = host
        self._port = port
        self._sim: PLCSimulator | None = None

    @property
    def running(self) -> bool:
        return self._sim is not None

    def start(self) -> None:
        if self._sim is None:
            logger.info("Starting embedded S7 simulator on %s:%d", self._host, self._port)
            self._sim = PLCSimulator(host=self._host, port=self._port)
            self._sim.start()

    def stop(self) -> None:
        if self._sim is not None:
            logger.info("Stopping embedded S7 simulator")
            self._sim.stop()
            self._sim = None


def _record_alarm(collector) -> None:
    """Per-cycle hook (gateway thread): publish the alarm flag into shared state.

    Only records state here; the Bridge call happens on the main thread in
    ``status_loop`` so all Bridge/WebUI traffic stays single-threaded.
    """
    update_status(alarm_active=bool(collector.data.get("alarm_active")))


def _run_gateway() -> None:
    try:
        asyncio.run(
            gateway_main(
                manage_signals=False,
                start_http_api=False,
                stop_event=_stop_event,
                on_cycle=_record_alarm,
            )
        )
    except Exception:  # keep the thread's failure visible in the app logs
        logger.exception("Gateway thread crashed")


def main() -> None:
    logger.info("=== S7 -> OPC UA Gateway App Lab app starting ===")
    ui = WebUI()
    sim = SimulatorController()
    web_adapter.register(ui, sim)

    if hasattr(ui, "on_connect"):
        ui.on_connect(lambda sid: logger.info("dashboard client connected: %s", sid))
    if hasattr(ui, "on_disconnect"):
        ui.on_disconnect(lambda sid: logger.info("dashboard client disconnected: %s", sid))

    gateway_thread = threading.Thread(target=_run_gateway, name="gateway", daemon=True)
    gateway_thread.start()

    # Auto-start the simulator for a zero-friction demo; the dashboard toggle
    # can stop it to show the OPC UA nodes go Bad, then recover.
    sim.start()
    logger.info("Gateway thread started, simulator auto-started, entering App.run()")

    def status_loop() -> None:
        time.sleep(STATUS_PUSH_INTERVAL)
        st = get_status()
        try:
            Bridge.call(
                "set_status",
                bool(st.get("plc_connected")),
                bool(st.get("opcua_running")),
                bool(st.get("alarm_active")),
            )
        except Exception:
            logger.exception("Bridge set_status failed")
        ui.send_message("status_update", web_adapter.status_payload(sim))

    try:
        App.run(user_loop=status_loop)
    finally:
        _stop_event.set()
        sim.stop()


if __name__ == "__main__":
    main()
