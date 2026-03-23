"use strict";

// ── DOM refs ──────────────────────────────────────────────────────────────────
const $ = (id) => document.getElementById(id);

const sseIndicator  = $("sseIndicator");
const sseLabel      = $("sseLabel");
const cameraBadge   = $("cameraBadge");
const badgeText     = $("badgeText");
const lastSeenEl    = $("lastSeen");
const requestStateMetaEl = $("requestStateMeta");
const captureBtn    = $("captureBtn");
const btnLabel      = $("btnLabel");
const stateIcon     = $("stateIcon");
const stateText     = $("stateText");
const photoEmpty    = $("photoEmpty");
const photoFrame    = $("photoFrame");
const photoImg      = $("photoImg");
const photoMeta     = $("photoMeta");

// ── State ─────────────────────────────────────────────────────────────────────
let cameraOnline    = false;
let requestState    = "idle";   // "idle" | "capturing" | "uploading"
let sseConnected    = false;
let lastSeenDate    = null;
let tickTimer       = null;

// ── Relative time helper ──────────────────────────────────────────────────────
function relativeTime(isoStr) {
  if (!isoStr) return "—";
  const then = new Date(isoStr.replace("T", " ") + "Z");  // treat as UTC if no TZ
  const secs = Math.round((Date.now() - then.getTime()) / 1000);
  if (isNaN(secs)) return isoStr;
  if (secs <  5)  return "just now";
  if (secs < 60)  return `${secs}s ago`;
  if (secs < 3600) return `${Math.floor(secs / 60)}m ago`;
  return `${Math.floor(secs / 3600)}h ago`;
}

// ── Tick: refresh relative timestamps every second ────────────────────────────
function startTick() {
  if (tickTimer) return;
  tickTimer = setInterval(() => {
    if (lastSeenDate) {
      lastSeenEl.textContent = relativeTime(lastSeenDate);
    }
  }, 1000);
}

// ── Render: camera status ─────────────────────────────────────────────────────
function renderStatus({ online, last_seen }) {
  cameraOnline = online;
  lastSeenDate = last_seen ?? lastSeenDate;

  cameraBadge.className = "status-badge " + (online ? "online" : "offline");
  badgeText.textContent  = online ? "Online" : "Offline";
  lastSeenEl.textContent = lastSeenDate ? relativeTime(lastSeenDate) : "—";

  syncCaptureButton();
}

// ── Render: request state ─────────────────────────────────────────────────────
const STATE_LABELS = {
  idle:      "Idle",
  capturing: "Capturing…",
  uploading: "Uploading…",
};

function renderRequestState({ state }) {
  requestState = state;

  stateIcon.className  = "state-icon " + state;
  stateText.textContent = STATE_LABELS[state] ?? state;
  requestStateMetaEl.textContent = STATE_LABELS[state] ?? state;

  const busy = state !== "idle";
  captureBtn.classList.toggle("busy", busy);
  btnLabel.textContent = busy ? (STATE_LABELS[state] ?? "Working…") : "Capture Photo";

  syncCaptureButton();
}

// ── Enable / disable capture button ──────────────────────────────────────────
function syncCaptureButton() {
  captureBtn.disabled = !cameraOnline || requestState !== "idle";
}

// ── Render: new image ────────────────────────────────────────────────────────
function renderImage({ url, filename, size, timestamp }) {
  if (!url) return;

  photoFrame.style.display = "block";
  photoEmpty.style.display  = "none";

  photoImg.classList.add("loading");
  photoImg.classList.remove("arrived");

  const freshUrl = url + "?t=" + Date.now();  // bust browser cache
  photoImg.onload = () => {
    photoImg.classList.remove("loading");
    photoImg.classList.add("arrived");
  };
  photoImg.onerror = () => {
    photoImg.classList.remove("loading");
  };
  photoImg.src = freshUrl;

  // Build metadata label
  const parts = [];
  if (filename) parts.push(filename);
  if (size)     parts.push(formatBytes(size));
  if (timestamp) {
    const d = new Date(timestamp.replace("T", " "));
    if (!isNaN(d)) parts.push(d.toLocaleTimeString());
  }
  photoMeta.textContent = parts.join("  ·  ");
}

function formatBytes(n) {
  if (n == null) return "";
  if (n < 1024)        return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / (1024 * 1024)).toFixed(2)} MB`;
}

// ── SSE connection ────────────────────────────────────────────────────────────
let es        = null;
let reconnectDelay = 1000;

function connectSSE() {
  if (es) { es.close(); es = null; }

  sseIndicator.className = "sse-indicator";
  sseLabel.textContent   = "Connecting…";

  es = new EventSource("/api/events");

  es.addEventListener("init", (e) => {
    const data = JSON.parse(e.data);
    renderStatus(data);
    renderRequestState({ state: data.request_state ?? "idle" });
    setSseConnected(true);
    reconnectDelay = 1000;
  });

  es.addEventListener("status",        (e) => renderStatus(JSON.parse(e.data)));
  es.addEventListener("request_state", (e) => renderRequestState(JSON.parse(e.data)));
  es.addEventListener("image",         (e) => renderImage(JSON.parse(e.data)));

  es.onerror = () => {
    setSseConnected(false);
    es.close();
    es = null;
    sseLabel.textContent = `Reconnecting in ${(reconnectDelay / 1000).toFixed(0)}s…`;
    setTimeout(connectSSE, reconnectDelay);
    reconnectDelay = Math.min(reconnectDelay * 2, 30000);
  };
}

function setSseConnected(ok) {
  sseConnected = ok;
  sseIndicator.className = "sse-indicator " + (ok ? "connected" : "error");
  sseLabel.textContent   = ok ? "Live" : "Disconnected";
}

// ── Capture button handler ────────────────────────────────────────────────────
captureBtn.addEventListener("click", async () => {
  if (captureBtn.disabled) return;

  captureBtn.disabled = true;

  try {
    const res = await fetch("/api/capture", { method: "POST" });
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      showError(body.detail ?? `Error ${res.status}`);
      syncCaptureButton();
    }
    // Success: state transitions arrive via SSE
  } catch (err) {
    showError("Network error — is the server reachable?");
    syncCaptureButton();
  }
});

// ── Simple inline error toast ─────────────────────────────────────────────────
function showError(msg) {
  const toast = document.createElement("div");
  toast.className = "toast-error";
  toast.textContent = msg;
  Object.assign(toast.style, {
    position:    "fixed",
    bottom:      "1.5rem",
    left:        "50%",
    transform:   "translateX(-50%)",
    background:  "var(--red-dim)",
    color:       "var(--red)",
    border:      "1px solid var(--red)",
    padding:     ".65rem 1.2rem",
    borderRadius:"var(--radius-md)",
    fontSize:    ".85rem",
    fontWeight:  "500",
    zIndex:      "9999",
    whiteSpace:  "nowrap",
    boxShadow:   "0 4px 20px rgba(0,0,0,.5)",
  });
  document.body.appendChild(toast);
  setTimeout(() => toast.remove(), 4000);
}

// ── Boot ──────────────────────────────────────────────────────────────────────
startTick();
connectSSE();
