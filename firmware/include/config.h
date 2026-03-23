#pragma once

// ── Camera settings ──────────────────────────────────────────────────────────
// Resolution options (ascending size/latency):
//   FRAMESIZE_QVGA (320x240), FRAMESIZE_CIF (352x288),
//   FRAMESIZE_VGA  (640x480), FRAMESIZE_SVGA (800x600),
//   FRAMESIZE_XGA  (1024x768), FRAMESIZE_UXGA (1600x1200)
#define CAM_RESOLUTION   FRAMESIZE_HD

// JPEG quality: 0–63 (lower value = higher quality / larger file)
#define CAM_JPEG_QUALITY 10

// ── Network timeouts ─────────────────────────────────────────────────────────
#define WIFI_TIMEOUT_MS        15000   // Max wait for WiFi association (ms)
#define LONG_POLL_TIMEOUT_S    25      // Seconds the server holds the long-poll
#define HTTP_CONNECT_TIMEOUT_MS 8000   // TCP connect timeout (ms)
#define UPLOAD_TIMEOUT_MS      20000   // Max time for a single upload attempt (ms)

// ── Upload settings ───────────────────────────────────────────────────────────
#define MAX_UPLOAD_RETRIES  3
#define RETRY_DELAY_MS      1500

// ── Serial baud ───────────────────────────────────────────────────────────────
#define SERIAL_BAUD 115200
