"""Shared runtime state for the gateway.

Both front-ends — the aiohttp REST API (``gateway_api``, used by the Docker
stack) and the Arduino App Lab WebUI adapter (``app/python/web_adapter.py``) —
read and mutate the *same* state through this module, so the gateway core does
not need to know which one is driving it.
"""

from __future__ import annotations

import asyncio

GATEWAY_STATUS: dict[str, object] = {
    "plc_connected": False,
    "opcua_running": False,
    "last_error": None,
}

_CONFIG_RELOAD_EVENT: asyncio.Event | None = None
_CONFIG_RELOAD_LOOP: asyncio.AbstractEventLoop | None = None

__all__ = [
    "GATEWAY_STATUS",
    "get_status",
    "set_config_reload_event",
    "trigger_config_reload",
    "update_status",
]


def update_status(**values: object) -> None:
    GATEWAY_STATUS.update(values)


def get_status() -> dict[str, object]:
    """Return a copy of the current status, safe to hand to a serializer."""
    return dict(GATEWAY_STATUS)


def set_config_reload_event(
    event: asyncio.Event | None,
    loop: asyncio.AbstractEventLoop | None = None,
) -> None:
    """Register the reload event and, optionally, the loop that owns it.

    ``loop`` is only needed when the event will be fired from a *different*
    thread than the one running the gateway (the App Lab case). The Docker path
    fires it from within the gateway loop, so it can leave ``loop`` unset.
    """
    global _CONFIG_RELOAD_EVENT, _CONFIG_RELOAD_LOOP
    _CONFIG_RELOAD_EVENT = event
    _CONFIG_RELOAD_LOOP = loop


def trigger_config_reload() -> None:
    """Fire the reload event, whether called from the gateway loop or another thread."""
    event = _CONFIG_RELOAD_EVENT
    if event is None:
        return

    loop = _CONFIG_RELOAD_LOOP
    if loop is not None and loop.is_running():
        loop.call_soon_threadsafe(event.set)
    else:
        event.set()
