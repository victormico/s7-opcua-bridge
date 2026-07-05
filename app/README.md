# S7 → OPC UA Gateway — Arduino App Lab app

An Arduino App Lab app for the **UNO Q** that turns a Siemens S7 PLC into an
**OPC UA server**, configured entirely from a web dashboard served by the board,
with live health shown on the on-board LED via the microcontroller.

It showcases the UNO Q's dual-brain design:

- **Linux (MPU), Python** — the S7 ⇄ OPC UA bridge (`python-snap7` + `asyncua`)
  and the dashboard back-end.
- **Microcontroller (MCU), sketch** — a status indicator driven over the
  Router Bridge (`Bridge.call("set_status", plc_ok, opcua_ok, alarm)`).
- **`arduino:web_ui` Brick** — serves the dashboard in `assets/` and carries the
  Socket.IO messages between the browser and Python.

No PLC required: an **embedded S7 simulator** runs on the board (toggle it from
the dashboard) so the whole pipeline is demoable stand-alone.

## What runs where

```
app/
├── app.yaml            # manifest: declares the arduino:web_ui Brick
├── config.json         # gateway config (defaults to the embedded simulator)
├── python/
│   ├── main.py         # App Lab entry: gateway thread + WebUI handlers + status push
│   ├── web_adapter.py  # discover / save-config / status over Socket.IO
│   └── requirements.txt
├── sketch/
│   ├── sketch.ino      # LED_BUILTIN status indicator (Bridge RPC target)
│   └── sketch.yaml     # fqbn: arduino:zephyr:unoq
└── assets/             # dashboard (index.html, app.js, styles.css)
```

The gateway logic itself is the shared `services/gateway` package at the repo
root — `python/main.py` runs it in a background thread. Because of that, **the
whole repository must be on the board**, and the app is started from its `app/`
subfolder.

## Status on the LED matrix

The sketch drives the UNO Q's built-in **13×8 LED matrix** (via
`Arduino_LED_Matrix` + `ArduinoGraphics`), mirrored on `LED_BUILTIN`:

| Board state                              | LED matrix                       |
| ---------------------------------------- | -------------------------------- |
| Gateway healthy (PLC + OPC UA up)        | 🙂 smiley face                   |
| Alarm active (`alarm_active` tag set)    | scrolling text `ALARM: TEMP HIGH`|
| PLC disconnected (OPC UA still serving)  | scrolling text `PLC OFFLINE`     |
| OPC UA server not running yet            | blank                            |

With the embedded simulator, temperature is a sine wave that periodically
crosses the 27 °C alarm threshold, so the matrix alternates between the smiley
and the scrolling alarm — a live demo of the alarm propagating PLC → OPC UA →
microcontroller.

## Deploy and run

### Option A — Import as a ZIP (App Lab GUI, recommended)

An App Lab `.zip` must be a **single self-contained app** (`app.yaml` at the zip
root). This app normally borrows the shared `services/` package from the repo,
so a zip is produced by a build script that vendors those modules into
`python/services/`:

```bash
python scripts/build_applab_zip.py
# -> dist/s7-opcua-gateway-applab.zip
```

Then in App Lab use **Import from ZIP** and pick that file. Do **not** zip the
whole repository — App Lab expects one app, and a raw `app/` zip would be
missing the gateway code.

### Option B — CLI with the full repo checkout

The app also runs straight from a full repo checkout (it finds `services/` at
the repo root). The board is reachable as `arduino@gaudi`:

```bash
# Copy the whole repo to the board (services/ must come along)
scp -r . arduino@gaudi:~/ArduinoApps/s7-opcua-bridge

# Start / inspect / stop the app (started from the app/ subfolder)
arduino-app-cli app start ~/ArduinoApps/s7-opcua-bridge/app
arduino-app-cli app logs  ~/ArduinoApps/s7-opcua-bridge/app
arduino-app-cli app stop  ~/ArduinoApps/s7-opcua-bridge/app
```

Python dependencies in `python/requirements.txt` are installed automatically on
first run.

## Try it

1. Open the app's web UI. The **simulator auto-starts**, so status should show
   **PLC Connected** / **OPC UA Running** and the on-board LED goes solid.
2. Click **Discover** → the four demo tags appear. Rename any, then **Save
   config** → the OPC UA node tree reloads live.
3. Point an OPC UA client (e.g. UaExpert) at
   `opc.tcp://<uno-q-ip>:4840/arduino/gateway` and watch the live values.
4. Toggle the **Simulator off** → nodes go **Bad** and the LED slow-blinks; turn
   it back on → nodes recover to **Good**.

To use a **real PLC** instead, turn the simulator off, set the PLC IP/port in the
dashboard, and Save.
