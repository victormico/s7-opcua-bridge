# s7-opcua-bridge
Industrial S7-to-OPCUA Edge Gateway

## Overview

An open-source edge gateway that reads data from Siemens S7 PLCs and exposes
it through an OPC UA server.  The system is designed to run on a Debian-based
Linux distribution (e.g. on an Arduino UNO R4 WiFi or similar SBC).

## Architecture

| Layer | Technology |
|-------|-----------|
| Language | Python 3.10+ |
| S7 protocol | [python-snap7](https://github.com/gijzelaerr/python-snap7) |
| OPC UA protocol | [asyncua](https://github.com/FreeOpcUa/opcua-asyncio) |
| Concurrency | `asyncio` (non-blocking I/O) |

## Project structure

```
s7-opcua-bridge/
├── plc_simulator.py   # Mock Snap7 server – simulates a real S7 PLC
├── s7_collector.py    # S7Collector – async client that reads DB1
├── opcua_server.py    # OPCUAGateway – async OPC UA server
├── main.py            # Main async loop (bridge entry point)
├── requirements.txt   # Python dependencies
└── tests/
    └── test_bridge.py # Unit and integration tests
```

## OPC UA node tree

```
Objects/
└── Industrial_Unit/
    └── S7_PLC_1/
        ├── Temperature    (Float,  DB1 bytes 0-3)
        └── Piece_Counter  (UInt32, DB1 bytes 4-7)
```

Namespace URI: `Arduino_Industrial_Gateway`

## Quick start

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Start the PLC simulator (terminal 1)

```bash
python plc_simulator.py
```

### 3. Start the bridge (terminal 2)

```bash
python main.py
```

The bridge connects to `127.0.0.1:102` by default and exposes the OPC UA
server at `opc.tcp://0.0.0.0:4840/arduino/gateway`.

### 4. Connect to a real PLC

```bash
python main.py --host 192.168.0.10 --port 102 --rack 0 --slot 1
```

### All command-line options

```
usage: main.py [-h] [--host HOST] [--port PORT] [--rack RACK] [--slot SLOT]
               [--opcua-port OPCUA_PORT]

S7-to-OPC UA Industrial Gateway

options:
  --host HOST           IP address of the S7 PLC (default: 127.0.0.1)
  --port PORT           TCP port of the S7 PLC (default: 102)
  --rack RACK           Rack number of the S7 PLC (default: 0)
  --slot SLOT           Slot number of the S7 PLC (default: 1)
  --opcua-port OPCUA_PORT
                        TCP port for the OPC UA server (default: 4840)
```

## Running the tests

```bash
python -m pytest tests/ -v
```

## Error handling

If the PLC loses its connection, the OPC UA server continues running and
marks the affected nodes with a **Bad StatusCode** (`BadNoData`).
Once the PLC reconnects, reads resume automatically and the nodes return
to **Good** status.
