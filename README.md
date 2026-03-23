# ESP32-CAM Photo Capture System

Click **Capture Photo** in the browser → camera takes a JPEG → image appears on the page in near real-time.

-------------------------------------------------------------------------------------------------------------------------------------------------

## Architecture


Browser  ──SSE──►  FastAPI server  ◄──long-poll──  ESP32-CAM
   │                    │                               │
   └──POST /capture──►  │ ──{"cmd":"capture"}──────►   │
                        │  ◄──POST /upload (raw JPEG)── │
                        │                               │
                   saves to uploads/
                   broadcasts SSE events


- **Browser → Server**: `POST /api/capture` triggers a capture command.
- **Server → Camera**: long-poll (`GET /api/command`) holds the connection open; responds instantly when a command is available.
- **Camera → Server**: `POST /api/upload` with raw `image/jpeg` body, streamed to disk.
- **Server → Browser**: SSE (`GET /api/events`) pushes status, request-state, and new-image events.

-------------------------------------------------------------------------------------------------------------------------------------------------

## Project structure

.
├── firmware/               Arduino / PlatformIO firmware
│   ├── src/main.cpp
│   ├── include/
│   │   ├── config.h            Tunables (resolution, timeouts, retries)
│   │   └── secrets.h.example   Copy → secrets.h, add credentials
│   └── platformio.ini
├── server/                 Python server
│   ├── app/
│   │   ├── main.py             FastAPI entry point
│   │   ├── state.py            Shared state, command channel, SSE broadcaster
│   │   └── routes/camera.py    All API endpoints
│   ├── requirements.txt
│   └── .env.example
├── web/                    Browser UI (served as static files)
│   ├── index.html
│   ├── style.css
│   └── app.js
└── uploads/                Saved JPEGs (git-ignored)

-------------------------------------------------------------------------------------------------------------------------------------------------

## Server setup & run

**Requirements**: Python 3.10+

```bash
# 1. Create and activate a virtual environment
python -m venv .venv
# Windows:
.venv\Scripts\activate
# Linux / macOS:
source .venv/bin/activate

# 2. Install dependencies
pip install -r server/requirements.txt

# 3. (Optional) copy and edit the env file
cp server/.env.example server/.env
# Edit server/.env if you need non-default ports or paths

# 4. Run — from the PROJECT ROOT
uvicorn server.app.main:app --host 0.0.0.0 --port 8000 --reload
```

Open **http://localhost:8000** (or your LAN IP) in a browser.

-------------------------------------------------------------------------------------------------------------------------------------------------

## ESP32-CAM flash & setup

**Requirements**: [PlatformIO](https://platformio.org/) (VS Code extension or CLI)


bash
# 1. Copy and edit secrets

cp firmware/include/secrets.h.example firmware/include/secrets.h

# Edit firmware/include/secrets.h:
   WIFI_SSID     — your network name
   WIFI_PASSWORD — your network password
   SERVER_HOST   — LAN IP of the machine running the server (NOT localhost)
   SERVER_PORT   — default 8000

# 2. Wire GPIO0 to GND on the ESP32-CAM (enables flash mode)

# 3. Upload

cd firmware
pio run --target upload --upload-port COM3   # adjust port

# 4. Disconnect GPIO0 from GND, press Reset
# Monitor serial output:
pio device monitor --baud 115200


> **No PlatformIO?**  Open `firmware/` as an Arduino IDE sketch. Install the
> `esp32` board package (Espressif). Select board **AI Thinker ESP32-CAM**,
> flash mode **DIO**, partition scheme **Huge APP**.

-------------------------------------------------------------------------------------------------------------------------------------------------

## Speed tuning

| 		Setting			| 		Where		| 				Effect 					|
|---------------------------------------|-------------------------------|-----------------------------------------------------------------------|
| `CAM_RESOLUTION` 			| `config.h` 			| Biggest single factor. `QVGA` is fastest; `UXGA` is slowest. 		|
| `CAM_JPEG_QUALITY` 			| `config.h` 			| Lower value = larger file = slower upload. 10–15 is a good balance. 	|
| `LONG_POLL_TIMEOUT_S` 		| `config.h` + `server/.env`	| How long the camera waits for a command. 25 s works well. 		|
| `WiFi.setSleep(false)`		| `main.cpp`			| Already set. Removing it adds ~20 ms latency per packet. 		|
| `fb_count = 2` + `CAMERA_GRAB_LATEST` | `main.cpp` 			| Ensures fresh frames; dropping to 1 saves ~60 KB PSRAM but may stall. |
| Server CPU / network 			|   		  —      	| Running server on the same LAN as the camera eliminates WAN RTT. 	|

Typical end-to-end latency on a good LAN (VGA, quality 12):
- Long-poll wakeup: ~0 ms (command delivered immediately)
- Capture: ~200–350 ms
- Upload (~30–60 KB): ~80–200 ms
- SSE push to browser: ~5 ms
- **Total**: ~300–600 ms from click to image visible
