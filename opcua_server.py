"""
Asynchronous OPC UA server.

Defines the 'Arduino_Industrial_Gateway' namespace and builds the
object tree:

    Objects/
    └── Industrial_Unit/
        └── S7_PLC_1/
            ├── Temperature    (Float)
            └── Piece_Counter  (UInt32)

When PLC data is unavailable (value is None), nodes are written with
a Bad StatusCode to signal that the PLC connection has been lost.
"""

import logging
from typing import Any

from asyncua import Node, Server, ua
from asyncua.ua import DataValue, StatusCode, Variant, VariantType

# Module logger
logger = logging.getLogger("opcua_server")

# OPC UA namespace URI for this gateway
NAMESPACE_URI = "Arduino_Industrial_Gateway"

# Mapping: data dictionary key -> (OPC UA node name, VariantType)
NODE_DEFINITIONS: dict[str, tuple[str, VariantType]] = {
    "temperature": ("Temperature", VariantType.Float),
    "piece_counter": ("Piece_Counter", VariantType.UInt32),
}

# Default initial values used when creating variable nodes
# (asyncua does not allow None as an initial value for numeric types)
_DEFAULT_VALUES: dict[VariantType, object] = {
    VariantType.Float: 0.0,
    VariantType.UInt32: 0,
}


# OPC UA status code used when data is unavailable (connection lost)
BAD_STATUS_CODE = ua.StatusCodes.BadNoData


class OPCUAGateway:
    """
    OPC UA server that exposes S7 PLC data.

    Creates and maintains the OPC UA object tree and provides the
    ``update_nodes`` method to refresh node values from the
    S7Collector data dictionary.
    """

    def __init__(self, endpoint: str = "opc.tcp://0.0.0.0:4840/arduino/gateway"):
        """
        Initialise the OPC UA server.

        Args:
            endpoint: OPC UA endpoint URL.
        """
        self.endpoint = endpoint
        self._server = Server()

        # Namespace index (assigned during initialisation)
        self._ns_idx: int = 0

        # Node dictionary: data key -> OPC UA Node
        self._nodes: dict[str, Node] = {}

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def init(self) -> None:
        """Initialise the OPC UA server, register the namespace and create nodes."""
        await self._server.init()
        self._server.set_endpoint(self.endpoint)

        # Register the gateway namespace
        self._ns_idx = await self._server.register_namespace(NAMESPACE_URI)
        logger.info(
            "Namespace '%s' registered with index %d.",
            NAMESPACE_URI,
            self._ns_idx,
        )

        # Build the object tree
        await self._create_object_tree()

    async def _create_object_tree(self) -> None:
        """
        Create the OPC UA object tree:
        Objects -> Industrial_Unit -> S7_PLC_1 -> Variables
        """
        objects_node = self._server.get_objects_node()

        # Create Industrial_Unit
        industrial_unit = await objects_node.add_object(
            self._ns_idx, "Industrial_Unit"
        )
        logger.info("Node 'Industrial_Unit' created.")

        # Create S7_PLC_1 under Industrial_Unit
        plc_node = await industrial_unit.add_object(self._ns_idx, "S7_PLC_1")
        logger.info("Node 'S7_PLC_1' created.")

        # Create variable nodes and store them in the dictionary
        for data_key, (node_name, variant_type) in NODE_DEFINITIONS.items():
            initial_value = _DEFAULT_VALUES.get(variant_type, 0)
            var_node = await plc_node.add_variable(
                self._ns_idx,
                node_name,
                ua.Variant(initial_value, variant_type),
            )
            # Allow the server to write values to the node
            await var_node.set_writable()
            self._nodes[data_key] = var_node
            logger.info("OPC UA variable '%s' created.", node_name)

    async def __aenter__(self) -> "OPCUAGateway":
        """Support use as an async context manager."""
        await self.init()
        await self._server.start()
        logger.info("OPC UA server started at %s", self.endpoint)
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Stop the OPC UA server."""
        await self._server.stop()
        logger.info("OPC UA server stopped.")

    # ------------------------------------------------------------------
    # Node value updates
    # ------------------------------------------------------------------

    async def update_nodes(self, data: dict[str, Any]) -> None:
        """
        Update OPC UA nodes with values from the data dictionary.

        If a value is None the node is written with a Bad StatusCode to
        indicate that the PLC is unavailable.

        Args:
            data: Dictionary of PLC values (from S7Collector.data).
        """
        for data_key, node in self._nodes.items():
            value = data.get(data_key)

            if value is None:
                # Bad status: PLC is not responding or connection is lost
                dv = DataValue(
                    StatusCode_=StatusCode(BAD_STATUS_CODE)
                )
            else:
                # Good status: valid value
                _, variant_type = NODE_DEFINITIONS[data_key]
                dv = DataValue(
                    Value=Variant(value, variant_type),
                    StatusCode_=StatusCode(ua.StatusCodes.Good),
                )

            await node.write_value(dv)

        logger.debug("OPC UA nodes updated: %s", data)
