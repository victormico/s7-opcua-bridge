"""
Central tag configuration for S7 <-> OPC UA mapping.

Kept outside runtime components (simulator, collector, OPC UA server)
to mimic real deployments where tag maps come from engineering config.
"""

# Tag configuration inside DB1.
# For boolean tags, use byte_offset + bit_offset (0..7).
TAG_CONFIG: dict[str, dict[str, int | str]] = {
    "temperature": {
        "byte_offset": 0,
        "data_type": "float",
    },
    "piece_counter": {
        "byte_offset": 4,
        "data_type": "uint32",
    },
    "machine_running": {
        "byte_offset": 8,
        "bit_offset": 0,
        "data_type": "bool",
    },
    "alarm_active": {
        "byte_offset": 8,
        "bit_offset": 1,
        "data_type": "bool",
    },
}
