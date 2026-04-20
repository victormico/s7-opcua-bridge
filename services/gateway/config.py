"""Runtime configuration helpers for the gateway service."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

CONFIG_PATH = Path(__file__).with_name("config.json")


def get_config_path() -> Path:
    return Path(os.getenv("GATEWAY_CONFIG", str(CONFIG_PATH)))


def load_gateway_config(config_path: str | Path | None = None) -> dict[str, Any]:
    path = Path(config_path) if config_path is not None else get_config_path()
    if not path.exists():
        return {}

    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def get_plc_settings(config: dict[str, Any]) -> dict[str, Any]:
    plc_config = config.get("plc", {})
    if not isinstance(plc_config, dict):
        return {}
    return plc_config


def get_variable_mappings(config: dict[str, Any]) -> dict[str, dict[str, int | str]]:
    variables = config.get("variables", [])
    if not isinstance(variables, list):
        return {}

    mappings: dict[str, dict[str, int | str]] = {}
    for variable in variables:
        if not isinstance(variable, dict):
            continue
        name = variable.get("name")
        if not isinstance(name, str) or not name:
            continue

        enabled = variable.get("enabled", True)
        if not enabled:
            continue

        mappings[name] = {
            key: value
            for key, value in variable.items()
            if key not in {"name", "enabled"} and isinstance(value, (int, str))
        }
    return mappings


def build_node_definitions(
    variable_mappings: dict[str, dict[str, int | str]]
) -> dict[str, tuple[str, object]]:
    from asyncua.ua import VariantType

    type_map: dict[str, VariantType] = {
        "float": VariantType.Float,
        "uint32": VariantType.UInt32,
        "bool": VariantType.Boolean,
    }

    node_definitions: dict[str, tuple[str, object]] = {}
    for tag_name, mapping in variable_mappings.items():
        data_type = str(mapping.get("data_type", ""))
        if data_type not in type_map:
            continue
        display_name = str(mapping.get("display_name", tag_name)).replace("_", " ").title().replace(" ", "_")
        node_definitions[tag_name] = (display_name, type_map[data_type])

    return node_definitions