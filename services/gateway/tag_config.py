"""Central tag configuration for the gateway service."""

TAG_CONFIG: dict[str, dict[str, int | str]] = {
    "temperature": {"byte_offset": 0, "data_type": "float"},
    "piece_counter": {"byte_offset": 4, "data_type": "uint32"},
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
