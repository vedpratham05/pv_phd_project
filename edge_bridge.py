import cv2
import base64
import requests
import time
import threading
import numpy as np

# Central backend endpoints.
API_URL = "http://127.0.0.1:8000/workflow/tracking/stream-reid"
CAMERAS_URL = "http://127.0.0.1:8000/workflow/cameras"

# No hardcoded camera IP. The phone's IP changes on every DHCP lease, so a
# fixed URL just spams "host is down". The backend registry (auto-populated by
# WiFi discovery) is the single source of truth; the bridge waits for it and
# stays idle until a real stream_url is assigned.
AUTOMATED_STREAM_URL = None

# camera_id -> live config dict {"floor": int, "stream_url": str|None, "label": str}.
# The worker thread reads its stream_url/floor from this shared dict on every
# reconnect, so when the admin assigns/changes a stream in the registry the
# running worker picks it up within a few seconds — no restart needed.
WORKERS: dict[str, dict] = {}
_WORKERS_LOCK = threading.Lock()

# How often to poll the registry for new/updated cameras.
REGISTRY_POLL_SECONDS = 15


def camera_connection_worker(camera_id: str):
    """One capture loop per camera node. Streams MJPEG from the camera's
    assigned URL, extracts frames, and POSTs them to the Re-ID endpoint tagged
    with this camera's id + floor."""
    print(f"[*] Starting background loop for node: {camera_id}")

    # Pre-processing tools
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))

    # Only log a disconnect once per outage, not every 3s, so a phone that's
    # temporarily off/roaming doesn't flood the console. The backend auto-heal
    # loop clears a dead stream_url within ~20s and re-finds the phone, at which
    # point this worker reconnects silently.
    last_error_key = None

    while True:
        config = WORKERS.get(camera_id, {})
        stream_url = config.get("stream_url")
        floor = config.get("floor", 0)

        # No stream assigned yet — wait for the registry to assign an IP.
        if not stream_url:
            time.sleep(3)
            continue

        try:
            stream = requests.get(stream_url, stream=True, timeout=10)
            bytes_buffer = bytes()
            if last_error_key is not None:
                print(f"[+] {camera_id}: reconnected to {stream_url}.")
                last_error_key = None

            for chunk in stream.iter_content(chunk_size=1024):
                # If the admin reassigned this camera's stream, break and
                # reconnect to the new URL.
                if WORKERS.get(camera_id, {}).get("stream_url") != stream_url:
                    print(f"[*] {camera_id}: stream URL changed — reconnecting.")
                    break

                bytes_buffer += chunk
                a = bytes_buffer.find(b'\xff\xd8')          # SOI (frame start)
                # The end-of-image marker (FFD9) must be searched for AFTER the
                # start marker. Searching from index 0 lets a stray FFD9 sit
                # *before* the next FFD8 and yield an empty/negative slice —
                # cv2.imdecode then raises "!buf.empty()", which escapes to the
                # outer try and tears down the whole stream every few frames.
                b = bytes_buffer.find(b'\xff\xd9', a + 2) if a != -1 else -1
                if a == -1 and len(bytes_buffer) > 1_048_576:
                    bytes_buffer = bytes_buffer[-2:]  # no frame start — avoid unbounded growth

                if a != -1 and b != -1:
                    jpg_bytes = bytes_buffer[a:b + 2]
                    bytes_buffer = bytes_buffer[b + 2:]

                    if not jpg_bytes:
                        continue

                    # cv2.imdecode RAISES cv2.error on an empty/corrupt buffer
                    # (it does not return None), so guard it. A single bad frame
                    # is skipped instead of killing the connection.
                    try:
                        frame = cv2.imdecode(np.frombuffer(jpg_bytes, dtype=np.uint8), cv2.IMREAD_COLOR)
                    except cv2.error:
                        continue
                    if frame is None:
                        continue

                    # --- AI OPTIMIZATION LAYER ---
                    # 1. Flip (phone often mirrors the preview)
                    frame = cv2.flip(frame, 1)

                    # 2. Image sharpening for face detection (CLAHE on L channel)
                    lab = cv2.cvtColor(frame, cv2.COLOR_BGR2LAB)
                    l, a_chan, b_chan = cv2.split(lab)
                    l2 = clahe.apply(l)
                    lab = cv2.merge((l2, a_chan, b_chan))
                    frame = cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)

                    # 3. Quality compression for fast API network transfer
                    encode_param = [int(cv2.IMWRITE_JPEG_QUALITY), 85]
                    _, img_buffer = cv2.imencode('.jpg', frame, encode_param)
                    base64_payload = base64.b64encode(img_buffer).decode('utf-8')
                    # -----------------------------

                    try:
                        response = requests.post(
                            API_URL,
                            json={
                                "camera_id": camera_id,
                                "current_floor": floor,
                                "frame_image_base64": base64_payload,
                            },
                            timeout=2,
                        )
                        if response.status_code == 200:
                            data = response.json()
                            if data.get("identified"):
                                flag = " 🚨 WRONG FLOOR" if data.get("floor_unauthorized_alert") else ""
                                print(f"✅ [{camera_id}] Visitor: {data.get('name')} | Floor {floor}{flag}")
                    except Exception:
                        pass  # network jitter

        except Exception as e:
            # Log a given outage only once (dedupe by URL + error type) instead
            # of every 3s. The backend clears the dead stream within ~20s and
            # re-discovers the phone's new IP automatically.
            error_key = (stream_url, type(e).__name__)
            if error_key != last_error_key:
                print(f"[!] {camera_id} stream lost ({stream_url}): {type(e).__name__}. "
                      f"Waiting for backend auto-detect to re-assign the phone…")
                last_error_key = error_key
            time.sleep(3)


def _ensure_worker(camera_id: str, floor: int, stream_url, label: str):
    """Create the worker thread for a camera if it doesn't exist yet, and keep
    its live config (stream_url/floor) up to date."""
    with _WORKERS_LOCK:
        existing = WORKERS.get(camera_id)
        if existing is None:
            WORKERS[camera_id] = {"floor": floor, "stream_url": stream_url, "label": label}
            thread = threading.Thread(target=camera_connection_worker, args=(camera_id,), daemon=True)
            WORKERS[camera_id]["thread"] = thread
            thread.start()
            print(f"[+] Registered camera node {camera_id} ({label}) — Floor {floor}, stream={stream_url}")
        else:
            # Update in place so the running worker picks up changes.
            existing["floor"] = floor
            existing["label"] = label
            if existing.get("stream_url") != stream_url:
                print(f"[*] Updating {camera_id} stream -> {stream_url}")
                existing["stream_url"] = stream_url


def registry_poller():
    """Polls the backend camera registry and (re)configures a worker per active
    camera that has a stream assigned."""
    seeded_fallback = False
    while True:
        try:
            resp = requests.get(CAMERAS_URL, timeout=5)
            resp.raise_for_status()
            cameras = resp.json()
            for cam in cameras:
                if not cam.get("is_active"):
                    continue
                _ensure_worker(
                    camera_id=cam["camera_id"],
                    floor=int(cam.get("floor", 0)),
                    stream_url=cam.get("stream_url"),
                    label=cam.get("label", cam["camera_id"]),
                )
            seeded_fallback = True  # registry reachable at least once
        except Exception as e:
            # Registry unreachable — seed the entrance camera once so capture
            # still works before the backend is fully up.
            if not seeded_fallback and "CAM_FLOOR_0" not in WORKERS:
                print(f"[!] Camera registry unreachable ({e}). Seeding entrance fallback.")
                _ensure_worker("CAM_FLOOR_0", 0, AUTOMATED_STREAM_URL, "Entrance — Floor 0")
        time.sleep(REGISTRY_POLL_SECONDS)


if __name__ == "__main__":
    print("=" * 65)
    print("🚀 MULTI-CAMERA SURVEILLANCE BRIDGE — registry-driven")
    print("=" * 65)
    poller = threading.Thread(target=registry_poller, daemon=True)
    poller.start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n[!] Stopped.")
