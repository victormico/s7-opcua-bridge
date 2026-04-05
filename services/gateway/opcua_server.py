"""Asynchronous OPC UA server for the gateway service."""

from __future__ import annotations

import logging
from typing import Any

from asyncua import Node, Server, ua
from asyncua.ua import DataValue, StatusCode, Variant, VariantType

from .tag_config import TAG_CONFIG

logger = logging.getLogger("opcua_server")

NAMESPACE_URI = "Arduino_Industrial_Gateway"

_TYPE_TO_VARIANT: dict[str, VariantType] = {
    "float": VariantType.Float,
    "uint32": VariantType.UInt32,
    "bool": VariantType.Boolean,
}

_DISPLAY_NAMES: dict[str, str] = {
    "temperature": "Temperature",
    "piece_counter": "Piece_Counter",
    "machine_running": "Machine_Running",
    "alarm_active": "Alarm_Active",
}

NODE_DEFINITIONS: dict[str, tuple[str, VariantType]] = {
    tag_name: (
        _DISPLAY_NAMES.get(tag_name, tag_name),
        _TYPE_TO_VARIANT[str(config["data_type"])],
    )
    for tag_name, config in TAG_CONFIG.items()
}

_DEFAULT_VALUES: dict[VariantType, object] = {
    VariantType.Float: 0.0,
    VariantType.UInt32: 0,
    VariantType.Boolean: False,
}

BAD_STATUS_CODE = ua.UInt32(ua.StatusCodes.BadNoData)

__all__ = ["BAD_STATUS_CODE", "NAMESPACE_URI", "NODE_DEFINITIONS", "OPCUAGateway"]


class OPCUAGateway:
    def __init__(self, endpoint: str = "opc.tcp://0.0.0.0:4840/arduino/gateway"):
        self.endpoint = endpoint
        self._server = Server()
        self._ns_idx: int = 0
        self._nodes: dict[str, Node] = {}

    async def init(self) -> None:
        await self._server.init()
        self._server.set_endpoint(self.endpoint)
        self._ns_idx = await self._server.register_namespace(NAMESPACE_URI)
        logger.info(
            "Namespace '%s' registered with index %d.",
            NAMESPACE_URI,
            self._ns_idx,
        )
        await self._create_object_tree()

    async def _create_object_tree(self) -> None:
        objects_node = self._server.get_objects_node()
        industrial_unit = await objects_node.add_object(self._ns_idx, "Industrial_Unit")
        logger.info("Node 'Industrial_Unit' created.")
        plc_node = await industrial_unit.add_object(self._ns_idx, "S7_PLC_1")
        logger.info("Node 'S7_PLC_1' created.")

        for data_key, (node_name, variant_type) in NODE_DEFINITIONS.items():
            initial_value = _DEFAULT_VALUES.get(variant_type, 0)
            var_node = await plc_node.add_variable(
                self._ns_idx,
                node_name,
                ua.Variant(initial_value, variant_type),
            )
            await var_node.set_writable()
            self._nodes[data_key] = var_node
            logger.info("OPC UA variable '%s' created.", node_name)

    async def __aenter__(self) -> "OPCUAGateway":
        await self.init()
        await self._server.start()
        logger.info("OPC UA server started at %s", self.endpoint)
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        await self._server.stop()
        logger.info("OPC UA server stopped.")

    async def update_nodes(self, data: dict[str, Any]) -> None:
        for data_key, node in self._nodes.items():
            value = data.get(data_key)
            now = ua.DateTime.utcnow()

            if value is None:
                dv = DataValue(
                    StatusCode_=StatusCode(BAD_STATUS_CODE),
                    SourceTimestamp=now,
                )
            else:
                _, variant_type = NODE_DEFINITIONS[data_key]
                dv = DataValue(
                    Value=Variant(value, variant_type),
                    StatusCode_=StatusCode(ua.UInt32(ua.StatusCodes.Good)),
                    SourceTimestamp=now,
                )

            await node.write_value(dv)

        logger.debug("OPC UA nodes updated: %s", data)
