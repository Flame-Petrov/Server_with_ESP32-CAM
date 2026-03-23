#include <Arduino.h>
#include <WiFi.h>
#include <HTTPClient.h>
#include <esp_camera.h>
#include <esp_timer.h>

#include "config.h"
#include "secrets.h"

// ── AI Thinker ESP32-CAM pin map ─────────────────────────────────────────────
#define PWDN_GPIO_NUM   32
#define RESET_GPIO_NUM  -1
#define XCLK_GPIO_NUM    0
#define SIOD_GPIO_NUM   26
#define SIOC_GPIO_NUM   27
#define Y9_GPIO_NUM     35
#define Y8_GPIO_NUM     34
#define Y7_GPIO_NUM     39
#define Y6_GPIO_NUM     36
#define Y5_GPIO_NUM     21
#define Y4_GPIO_NUM     19
#define Y3_GPIO_NUM     18
#define Y2_GPIO_NUM      5
#define VSYNC_GPIO_NUM  25
#define HREF_GPIO_NUM   23
#define PCLK_GPIO_NUM   22

// ── Pre-built URL strings (filled in setup) ──────────────────────────────────
static char s_cmdUrl[128];
static char s_uploadUrl[128];

static WiFiClient s_wifiClient;

// ── Helpers ──────────────────────────────────────────────────────────────────
static inline uint32_t ms_now() { return (uint32_t)(esp_timer_get_time() / 1000ULL); }

static void log_heap(const char *tag) {
    Serial.printf("[%s] Free heap: %u  PSRAM: %u\n",
                  tag,
                  (unsigned)esp_get_free_heap_size(),
                  (unsigned)esp_get_free_internal_heap_size());
}

// ── Camera init ───────────────────────────────────────────────────────────────
static bool initCamera() {
    camera_config_t cfg = {};
    cfg.ledc_channel  = LEDC_CHANNEL_0;
    cfg.ledc_timer    = LEDC_TIMER_0;
    cfg.pin_d0        = Y2_GPIO_NUM;
    cfg.pin_d1        = Y3_GPIO_NUM;
    cfg.pin_d2        = Y4_GPIO_NUM;
    cfg.pin_d3        = Y5_GPIO_NUM;
    cfg.pin_d4        = Y6_GPIO_NUM;
    cfg.pin_d5        = Y7_GPIO_NUM;
    cfg.pin_d6        = Y8_GPIO_NUM;
    cfg.pin_d7        = Y9_GPIO_NUM;
    cfg.pin_xclk      = XCLK_GPIO_NUM;
    cfg.pin_pclk      = PCLK_GPIO_NUM;
    cfg.pin_vsync     = VSYNC_GPIO_NUM;
    cfg.pin_href      = HREF_GPIO_NUM;
    cfg.pin_sscb_sda  = SIOD_GPIO_NUM;
    cfg.pin_sscb_scl  = SIOC_GPIO_NUM;
    cfg.pin_pwdn      = PWDN_GPIO_NUM;
    cfg.pin_reset     = RESET_GPIO_NUM;
    cfg.xclk_freq_hz  = 20000000;
    cfg.pixel_format  = PIXFORMAT_JPEG;
    cfg.frame_size    = CAM_RESOLUTION;
    cfg.jpeg_quality  = CAM_JPEG_QUALITY;
    cfg.fb_count      = 2;             // Double-buffer: grab_latest discards stale frames
    cfg.grab_mode     = CAMERA_GRAB_LATEST;
    cfg.fb_location   = CAMERA_FB_IN_PSRAM;

    esp_err_t err = esp_camera_init(&cfg);
    if (err != ESP_OK) {
        Serial.printf("[CAM] Init failed 0x%x\n", err);
        return false;
    }

    sensor_t *s = esp_camera_sensor_get();
    if (s) {
        // Sensible defaults; tune in config.h / secrets.h if needed
        s->set_whitebal(s, 1);
        s->set_awb_gain(s, 1);
        s->set_exposure_ctrl(s, 1);
        s->set_gain_ctrl(s, 1);
        s->set_lenc(s, 1);
        s->set_raw_gma(s, 1);
        s->set_dcw(s, 1);
        // OV3660 needs vflip + brightness boost
        if (s->id.PID == OV3660_PID) {
            s->set_vflip(s, 1);
            s->set_brightness(s, 1);
            s->set_saturation(s, -2);
        }
    }

    Serial.println("[CAM] Initialized OK");
    return true;
}

// ── WiFi ──────────────────────────────────────────────────────────────────────
static bool connectWiFi() {
    WiFi.mode(WIFI_STA);
    WiFi.setSleep(false);   // Disable power-save for minimum latency
    WiFi.setAutoReconnect(true);
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

    Serial.printf("[WIFI] Connecting to \"%s\"", WIFI_SSID);
    uint32_t t = millis();
    while (WiFi.status() != WL_CONNECTED) {
        if (millis() - t > WIFI_TIMEOUT_MS) {
            Serial.println("\n[WIFI] Timeout");
            return false;
        }
        delay(400);
        Serial.print('.');
    }
    Serial.printf("\n[WIFI] IP: %s  RSSI: %d dBm\n",
                  WiFi.localIP().toString().c_str(),
                  WiFi.RSSI());
    return true;
}

// ── Long-poll: block until server has a command or timeout ───────────────────
// Returns "capture" or "" on timeout/error.
static String doLongPoll() {
    HTTPClient http;
    http.begin(s_wifiClient, s_cmdUrl);
    http.setTimeout(LONG_POLL_TIMEOUT_S * 1000 + 6000);  // Slightly wider than server timeout

    uint32_t t0 = ms_now();
    int code = http.GET();
    uint32_t elapsed = ms_now() - t0;

    String result = "";
    if (code == 200) {
        // Body is JSON: {"cmd":"capture"} or {"cmd":"none"}
        String body = http.getString();
        Serial.printf("[POLL] %d  %u ms  body=%s\n", code, elapsed, body.c_str());
        if (body.indexOf("\"capture\"") >= 0) {
            result = "capture";
        }
    } else {
        Serial.printf("[POLL] HTTP %d  %u ms\n", code, elapsed);
        // Brief back-off on error to avoid hammering the server
        delay(2000);
    }

    http.end();
    return result;
}

// ── Upload a JPEG frame buffer ────────────────────────────────────────────────
static bool uploadJpeg(camera_fb_t *fb) {
    HTTPClient http;
    http.begin(s_wifiClient, s_uploadUrl);
    http.addHeader("Content-Type", "image/jpeg");
    http.setTimeout(UPLOAD_TIMEOUT_MS);

    uint32_t t0 = ms_now();
    Serial.printf("[UPLOAD] Sending %u bytes...\n", (unsigned)fb->len);

    // Pass the PSRAM buffer pointer directly — no intermediate copy
    int code = http.POST(fb->buf, fb->len);

    uint32_t elapsed = ms_now() - t0;
    if (code == 200 || code == 201) {
        Serial.printf("[UPLOAD] OK  %u ms\n", elapsed);
        http.end();
        return true;
    }
    Serial.printf("[UPLOAD] FAIL  HTTP %d  %u ms\n", code, elapsed);
    http.end();
    return false;
}

// ── Capture + upload with retry logic ────────────────────────────────────────
static void captureAndUpload() {
    uint32_t tTotal = ms_now();

    // Discard the buffered (potentially stale) frame, grab a fresh one
    {
        camera_fb_t *stale = esp_camera_fb_get();
        if (stale) esp_camera_fb_return(stale);
    }

    uint32_t tCap = ms_now();
    camera_fb_t *fb = esp_camera_fb_get();
    if (!fb) {
        Serial.println("[CAP] Failed to get frame buffer");
        return;
    }
    Serial.printf("[CAP] Frame: %u bytes  capture: %u ms\n",
                  (unsigned)fb->len, ms_now() - tCap);
    log_heap("CAP");

    bool ok = false;
    for (int attempt = 1; attempt <= MAX_UPLOAD_RETRIES && !ok; ++attempt) {
        if (attempt > 1) {
            Serial.printf("[UPLOAD] Retry %d/%d\n", attempt, MAX_UPLOAD_RETRIES);
            delay(RETRY_DELAY_MS);
        }
        ok = uploadJpeg(fb);
    }

    esp_camera_fb_return(fb);
    Serial.printf("[CAP] Total: %u ms  success=%s\n", ms_now() - tTotal, ok ? "yes" : "no");
}

// ── Setup ─────────────────────────────────────────────────────────────────────
void setup() {
    Serial.begin(SERIAL_BAUD);
    Serial.println("\n\n[BOOT] ESP32-CAM firmware starting");

    // Build URL strings once (avoids String allocations in the hot path)
    snprintf(s_cmdUrl,    sizeof(s_cmdUrl),
             "http://%s:%d/api/command?timeout=%d",
             SERVER_HOST, SERVER_PORT, LONG_POLL_TIMEOUT_S);
    snprintf(s_uploadUrl, sizeof(s_uploadUrl),
             "http://%s:%d/api/upload",
             SERVER_HOST, SERVER_PORT);

    Serial.printf("[BOOT] Command URL : %s\n", s_cmdUrl);
    Serial.printf("[BOOT] Upload  URL : %s\n", s_uploadUrl);

    if (!initCamera()) {
        Serial.println("[BOOT] Camera failed — restarting in 5 s");
        delay(5000);
        ESP.restart();
    }

    if (!connectWiFi()) {
        Serial.println("[BOOT] WiFi failed — restarting in 5 s");
        delay(5000);
        ESP.restart();
    }

    log_heap("BOOT");
    Serial.println("[BOOT] Ready — entering main loop");
}

// ── Loop ──────────────────────────────────────────────────────────────────────
void loop() {
    if (WiFi.status() != WL_CONNECTED) {
        Serial.println("[WIFI] Lost connection — waiting for reconnect...");
        delay(5000);
        return;
    }

    String cmd = doLongPoll();

    if (cmd == "capture") {
        captureAndUpload();
    }
    // Any other command values are silently ignored (future extensibility)
}
