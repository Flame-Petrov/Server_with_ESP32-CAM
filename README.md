# ESP32-CAM Photo Capture System

Capture a photo from a browser UI, have the ESP32-CAM take the shot, upload the JPEG to a FastAPI server, and push the result back to the page in near real-time.

## Overview

This project is split into three parts:

- `firmware/`: ESP32-CAM firmware built with PlatformIO / Arduino
- `server/`: FastAPI backend that coordinates commands, uploads, and SSE events
- `web/`: static browser UI served by the backend

## Architecture

```text
Browser -- POST /api/capture --> FastAPI server <-- GET /api/command (long-poll) -- ESP32-CAM
Browser <-- GET /api/events (SSE) -- FastAPI server <-- POST /api/upload (image/jpeg) -- ESP32-CAM

FastAPI server:
- queues capture commands
- saves uploaded JPEGs to uploads/
- broadcasts status and new-image events to the browser
```

## Repository Layout

```text
.
|-- firmware/
|   |-- include/
|   |   |-- config.h
|   |   `-- secrets.h.example
|   |-- src/
|   |   `-- main.cpp
|   `-- platformio.ini
|-- server/
|   |-- app/
|   |   |-- main.py
|   |   |-- state.py
|   |   `-- routes/
|   |       `-- camera.py
|   |-- .env.example
|   `-- requirements.txt
|-- web/
|   |-- app.js
|   |-- index.html
|   `-- style.css
`-- uploads/
```

## Requirements

- Python 3.10+
- ESP32-CAM (AI Thinker ESP32-CAM target)
- USB-to-serial adapter for flashing / serial monitoring
- PlatformIO CLI or the PlatformIO VS Code extension

## Quick Start

### 1. Run the server

Create and activate a virtual environment from the project root:

```bash
python -m venv .venv
```

Windows PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
```

Linux / macOS:

```bash
source .venv/bin/activate
```

Install dependencies:

```bash
python -m pip install -r server/requirements.txt
```

Copy `server/.env.example` to `server/.env` and adjust values if needed. The defaults are fine for local development.

Run the backend from the project root:

```bash
uvicorn server.app.main:app --host 0.0.0.0 --port 8000 --reload
```

Then open `http://localhost:8000` in your browser.

### 2. Configure the firmware

Create `firmware/include/secrets.h` from `firmware/include/secrets.h.example`, then set:

- `WIFI_SSID`
- `WIFI_PASSWORD`
- `SERVER_HOST`
- `SERVER_PORT`

`SERVER_HOST` must be the LAN IP address of the machine running the FastAPI server. Do not use `localhost` or `127.0.0.1`.

### 3. Flash the ESP32-CAM

Put the board into flash mode by wiring `GPIO0` to `GND`.

From `firmware/`:

```bash
pio run --target upload --upload-port COM3
```

Or from the project root:

```bash
python -m platformio run -d firmware --target upload --upload-port COM3
```

Replace `COM3` with the correct serial port on your machine.

After upload:

1. Disconnect `GPIO0` from `GND`
2. Press reset on the board
3. Open a serial monitor

```bash
pio device monitor --port COM3 --baud 115200
```

If `pio` is not on your `PATH`, install PlatformIO CLI:

```bash
python -m pip install -U platformio
```

Or use:

```bash
python -m platformio device monitor --port COM3 --baud 115200
```

### 4. Use the app

Once the server is running and the ESP32-CAM has connected to Wi-Fi:

1. Open the web UI
2. Click **Capture Photo**
3. Wait for the new image event to arrive
4. The JPEG will be saved in `uploads/` and shown in the browser

## Arduino IDE Fallback

If you do not want to use PlatformIO, open `firmware/` in Arduino IDE and use:

- Board: `AI Thinker ESP32-CAM`
- Flash mode: `DIO`
- Partition scheme: `Huge APP`

## Performance Tuning

| Setting | Location | Effect |
| --- | --- | --- |
| `CAM_RESOLUTION` | `firmware/include/config.h` | Biggest single latency / file-size factor. Lower resolutions are faster. |
| `CAM_JPEG_QUALITY` | `firmware/include/config.h` | Lower value means higher quality and larger files, which usually uploads slower. |
| `LONG_POLL_TIMEOUT_S` | `firmware/include/config.h` | Must stay aligned with the server timeout for clean command delivery. |
| `LONG_POLL_TIMEOUT` | `server/.env` | Server-side long-poll timeout; keep it matched to the firmware value. |
| `WiFi.setSleep(false)` | `firmware/src/main.cpp` | Reduces packet wake latency on the ESP32. |
| `fb_count = 2` and `CAMERA_GRAB_LATEST` | `firmware/src/main.cpp` | Helps keep frames fresh at the cost of more PSRAM. |

Typical end-to-end latency on a good LAN is in the low hundreds of milliseconds, depending mostly on capture resolution, JPEG size, and Wi-Fi quality.

## Troubleshooting

### `pio` is not recognized

Install the CLI and run PlatformIO through Python if needed:

```bash
python -m pip install -U platformio
python -m platformio run -d firmware --target upload --upload-port COM3
```

### Serial monitor cannot open the COM port

Only one process can own a serial port at a time. Close Arduino IDE, other serial monitors, or any previous `pio device monitor` process before opening the port again.

### COM port disappears or changes

Unplug and reconnect the USB-to-serial adapter, then re-check the available port. Some adapters re-enumerate after reset or upload.

### Camera does not connect to the server

Check these first:

- `SERVER_HOST` points to your machine's LAN IP
- the ESP32-CAM and the server are on the same network
- the backend is listening on the expected port
- firewall rules are not blocking inbound connections to the server
