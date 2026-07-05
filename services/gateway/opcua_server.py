"""Asynchronous OPC UA server for the gateway service."""

from __future__ import annotations

import inspect
import logging
from typing import Any

from asyncua import Node, Server, ua
from asyncua.ua import DataValue, StatusCode, Variant, VariantType

from .config import build_node_definitions, get_variable_mappings, load_gateway_config

logger = logging.getLogger("opcua_server")

NAMESPACE_URI = "Arduino_Industrial_Gateway"

_DEFAULT_CONFIG = load_gateway_config()
_DEFAULT_VARIABLE_MAPPINGS = get_variable_mappings(_DEFAULT_CONFIG)

NODE_DEFINITIONS: dict[str, tuple[str, VariantType]] = build_node_definitions(
    _DEFAULT_VARIABLE_MAPPINGS
)

_DEFAULT_VALUES: dict[VariantType, object] = {
    VariantType.Float: 0.0,
    VariantType.UInt32: 0,
    VariantType.Boolean: False,
}

BAD_STATUS_CODE = ua.UInt32(ua.StatusCodes.BadNoData)

# asyncua renamed the DataValue status-code kwarg across versions
# (``StatusCode_`` in some, ``StatusCode`` in others — e.g. the UNO Q's newer
# build). Detect it once so update_nodes works regardless of installed version.
_STATUS_KW = (
    "StatusCode_"
    if "StatusCode_" in inspect.signature(DataValue.__init__).parameters
    else "StatusCode"
)

__all__ = ["BAD_STATUS_CODE", "NAMESPACE_URI", "NODE_DEFINITIONS", "OPCUAGateway"]


class OPCUAGateway:
    def __init__(
        self,
        endpoint: str = "opc.tcp://0.0.0.0:4840/arduino/gateway",
        variable_mappings: dict[str, dict[str, int | str]] | None = None,
    ):
        self.endpoint = endpoint
        self._server = Server()
        self._ns_idx: int = 0
        self._nodes: dict[str, Node] = {}
        self.variable_mappings = variable_mappings or _DEFAULT_VARIABLE_MAPPINGS
        self.node_definitions = build_node_definitions(self.variable_mappings)

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

        for data_key, (node_name, variant_type) in self.node_definitions.items():
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
                    SourceTimestamp=now,
                    **{_STATUS_KW: StatusCode(BAD_STATUS_CODE)},
                )
            else:
                _, variant_type = self.node_definitions[data_key]
                dv = DataValue(
                    Value=Variant(value, variant_type),
                    SourceTimestamp=now,
                    **{_STATUS_KW: StatusCode(ua.UInt32(ua.StatusCodes.Good))},
                )

            await node.write_value(dv)

        logger.debug("OPC UA nodes updated: %s", data)
