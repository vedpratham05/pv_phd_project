from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

import requests
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import text

try:
    from twilio.rest import Client as TwilioClient
except ImportError:
    TwilioClient = None

from ..config import settings
from ..database import get_visitor_db, get_college_db, college_engine, visitor_engine
from ..models import (
    AadhaarMaster, 
    FaceEmbedding, 
    QrPass, 
    VerificationLog, 
    VisitSession, 
    VisitorMaster, 
    SecurityAlert,
    AdminUser,
    CameraTrackingLog,
    FacultyMaster
)
from ..schemas import (
    AdminLoginRequest,
    AadhaarOtpStartRequest,
    AadhaarOtpStartResponse,
    AadhaarOtpVerifyRequest,
    AadhaarOtpVerifyResponse,
    AadhaarSummary,
    FaceRegistrationRequest,
    FaceRegistrationResponse,
    VisitorFormRequest,
    VisitorFormResponse,
)
from ..services.face_service import (
    cosine_similarity,
    create_face_embedding,
    detect_single_face,
    decode_base64_image,
    liveness_passed,
    normalize_data_url,
)
from ..services.visitor_service import create_visit_session_with_qr, get_or_create_visitor

router = APIRouter(prefix="/workflow", tags=["workflow"])

SURVEILLANCE_DASHBOARD_CACHE = []

# =====================================================================
# EDGE_BRIDGE.PY AUTO-LAUNCH — tied to this router's startup/shutdown
# =====================================================================
# When the main app does `app.include_router(router)`, any startup/shutdown
# handlers registered here are merged into the app itself, so edge_bridge.py
# starts automatically whenever the FastAPI backend starts, and is cleanly
# terminated when it shuts down. No changes to main.py are needed.
#
# Override the resolved path with the EDGE_BRIDGE_PATH env var if your
# project layout doesn't match the assumed one below.
_edge_bridge_process: subprocess.Popen | None = None


def _resolve_edge_bridge_path() -> Path | None:
    env_override = os.environ.get("EDGE_BRIDGE_PATH")
    if env_override:
        candidate = Path(env_override).resolve()
        return candidate if candidate.exists() else None

    here = Path(__file__).resolve()
    # Assumes this file lives at <project_root>/backend/routers/workflow.py
    # and edge_bridge.py lives at <project_root>/edge_bridge.py. Adjust the
    # candidates below (or set EDGE_BRIDGE_PATH) if your layout differs.
    candidates = [
        here.parent.parent.parent / "edge_bridge.py",  # project_root/edge_bridge.py
        here.parent.parent / "edge_bridge.py",
        here.parent / "edge_bridge.py",
        # Confirmed absolute path for this project, as a last-resort fallback
        # in case the relative-path assumptions above don't match how the
        # backend is actually being launched (e.g. run from a different cwd,
        # packaged differently, etc.).
        Path("/Users/prathamved/Downloads/pranali_mam_phd_pj/edge_bridge.py"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


@router.on_event("startup")
def _ensure_admin_users_schema() -> None:
    """The college DB file picked by the path-search may be one that never
    had the admin_users table (it lived only in the stale copy next to the
    code). Create it if missing and seed the default admin account so the
    dashboard login always works."""
    with college_engine.begin() as conn:
        conn.execute(text(
            "CREATE TABLE IF NOT EXISTS admin_users ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "username VARCHAR(100) UNIQUE NOT NULL, "
            "password_hash VARCHAR(255) NOT NULL, "
            "role VARCHAR(50) DEFAULT 'admin')"
        ))
        # Default admin credentials: username "admin", password "admin123".
        # Insert if missing, and repair any previously mis-seeded password
        # (an earlier version briefly seeded "password123").
        existing = conn.execute(
            text("SELECT password_hash FROM admin_users WHERE username = :u"),
            {"u": "admin"}
        ).fetchone()
        if existing is None:
            conn.execute(
                text("INSERT INTO admin_users (username, password_hash, role) "
                     "VALUES (:u, :p, :r)"),
                {"u": "admin", "p": "admin123", "r": "admin"}
            )
            print("[*] Seeded default admin account -> username: admin | password: admin123")
        elif existing[0] == "password123":
            conn.execute(
                text("UPDATE admin_users SET password_hash = :p WHERE username = :u"),
                {"p": "admin123", "u": "admin"}
            )
            print("[*] Corrected admin password to the default: admin123")
    print("[*] Admin users schema ensured (admin_users).")


@router.on_event("startup")
def _ensure_faculty_verification_schema() -> None:
    """Lightweight in-place migration so faculty verification works on the
    existing college_system.db without a manual schema step. Mirrors the
    visitor-side structures: faculty get Aadhaar-link columns on
    faculty_master plus their own face-embedding table."""
    with college_engine.begin() as conn:
        # If this is a fresh college_system.db (e.g. after the database path
        # changed), faculty_master won't exist yet — create it first so the
        # ALTER TABLE below never hits "no such table".
        conn.execute(text(
            "CREATE TABLE IF NOT EXISTS faculty_master ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "employee_id VARCHAR(50) UNIQUE NOT NULL, "
            "name VARCHAR(255) NOT NULL, "
            "department VARCHAR(255) NOT NULL, "
            "phone_number VARCHAR(20) NOT NULL, "
            "room_number VARCHAR(50) NOT NULL, "
            "assigned_floor INTEGER NOT NULL)"
        ))
        conn.execute(text(
            "CREATE TABLE IF NOT EXISTS faculty_face_embeddings ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "faculty_id INTEGER NOT NULL, "
            "face_embedding TEXT NOT NULL, "
            "face_image TEXT NOT NULL, "
            "is_liveness_passed BOOLEAN DEFAULT 1, "
            "aadhaar_match_score FLOAT DEFAULT 0.0, "
            "captured_at DATETIME, "
            "FOREIGN KEY (faculty_id) REFERENCES faculty_master (id))"
        ))
        # SQLite has no "ADD COLUMN IF NOT EXISTS" — probe and add each one.
        existing_cols = {
            row[1] for row in conn.execute(text("PRAGMA table_info(faculty_master)")).fetchall()
        }
        for col_name, col_def in [
            ("masked_aadhaar", "VARCHAR(12)"),
            ("is_verified", "BOOLEAN DEFAULT 0"),
            ("aadhaar_verified_at", "DATETIME"),
        ]:
            if col_name not in existing_cols:
                conn.execute(text(f"ALTER TABLE faculty_master ADD COLUMN {col_name} {col_def}"))
    print("[*] Faculty verification schema ensured (faculty_face_embeddings + aadhaar columns).")


@router.on_event("startup")
def _ensure_faculty_registration_schema() -> None:
    """New table in college.db that stores the full faculty registration
    record (same identity fields as the visitor Aadhaar registry): admin
    registers faculty here from the dashboard, and a matching row is kept
    in faculty_master so all existing floor/host logic keeps working."""
    with college_engine.begin() as conn:
        conn.execute(text(
            "CREATE TABLE IF NOT EXISTS faculty_registration ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "employee_id VARCHAR(50) UNIQUE NOT NULL, "
            "name VARCHAR(255) NOT NULL, "
            "department VARCHAR(255) NOT NULL, "
            "phone_number VARCHAR(20) NOT NULL, "
            "room_number VARCHAR(50) NOT NULL, "
            "assigned_floor INTEGER NOT NULL, "
            "email VARCHAR(255), "
            "designation VARCHAR(255), "
            "masked_aadhaar VARCHAR(12), "
            "full_name VARCHAR(255), "
            "date_of_birth VARCHAR(20), "
            "gender VARCHAR(10), "
            "address TEXT, "
            "aadhaar_photo TEXT, "
            "is_aadhaar_verified BOOLEAN DEFAULT 0, "
            "registered_at DATETIME)"
        ))
    print("[*] Faculty registration table ensured in college.db (faculty_registration).")


@router.on_event("startup")
def _ensure_faculty_identity_college_schema() -> None:
    """Faculty Aadhaar records and verification logs live in college.db,
    fully separated from the visitor database. Creates mirror tables
    aadhaar_master + verification_logs inside college_system.db (with
    visitor_id NULLABLE, fixing the NOT NULL IntegrityError that crashed
    faculty OTP verification)."""
    with college_engine.begin() as conn:
        conn.execute(text(
            "CREATE TABLE IF NOT EXISTS aadhaar_master ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "masked_aadhaar VARCHAR(12) UNIQUE NOT NULL, "
            "full_name VARCHAR(255) NOT NULL, "
            "date_of_birth VARCHAR(50) NOT NULL, "
            "gender VARCHAR(20) NOT NULL, "
            "address TEXT NOT NULL, "
            "transaction_id VARCHAR(100) UNIQUE NOT NULL, "
            "aadhaar_photo TEXT, "
            "year_of_birth VARCHAR(10), "
            "care_of VARCHAR(255), "
            "mobile_hash VARCHAR(255), "
            "email_hash VARCHAR(255), "
            "share_code VARCHAR(10), "
            "verification_timestamp DATETIME)"
        ))
        conn.execute(text(
            "CREATE TABLE IF NOT EXISTS verification_logs ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "event_type VARCHAR(100) NOT NULL, "
            "status VARCHAR(50) NOT NULL, "
            "message TEXT NOT NULL, "
            "transaction_id VARCHAR(100), "
            "visitor_id VARCHAR(50), "
            "created_at DATETIME, "
            "timestamp DATETIME)"
        ))
    print("[*] Faculty identity schema ensured in college.db (aadhaar_master + verification_logs).")


@router.on_event("startup")
def _ensure_security_dispatch_schema() -> None:
    """Adds the 'Admin sends alert to Security' tracking columns to
    security_alerts so the flow's escalation chain (Admin Alert -> Send
    Alert to Security -> Detain Visitor -> Blocked) is enforced in order."""
    with visitor_engine.begin() as conn:
        # Fresh visitor.db safety: create the table if it doesn't exist yet
        # (SQLAlchemy's create_all may not have run before this handler).
        conn.execute(text(
            "CREATE TABLE IF NOT EXISTS security_alerts ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "session_id INTEGER NOT NULL, "
            "alert_priority VARCHAR(20) NOT NULL, "
            "alert_type VARCHAR(100) NOT NULL, "
            "current_floor INTEGER, "
            "message TEXT NOT NULL, "
            "is_resolved BOOLEAN DEFAULT 0, "
            "security_dispatched BOOLEAN DEFAULT 0, "
            "dispatched_at DATETIME, "
            "timestamp DATETIME)"
        ))
        existing_cols = {
            row[1] for row in conn.execute(text("PRAGMA table_info(security_alerts)")).fetchall()
        }
        for col_name, col_def in [
            ("security_dispatched", "BOOLEAN DEFAULT 0"),
            ("dispatched_at", "DATETIME"),
        ]:
            if col_name not in existing_cols:
                conn.execute(text(f"ALTER TABLE security_alerts ADD COLUMN {col_name} {col_def}"))
    print("[*] Security dispatch schema ensured (security_alerts.security_dispatched).")


@router.on_event("startup")
def _ensure_visitor_core_schema() -> None:
    """Fresh visitor_system.db safety net: create the core visitor tables
    used by raw-SQL queries (face_embeddings is read by the live Re-ID
    tracking loop on every camera frame) so the app never crashes with
    'no such table' even on a brand-new database file."""
    with visitor_engine.begin() as conn:
        conn.execute(text(
            "CREATE TABLE IF NOT EXISTS face_embeddings ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "visitor_id INTEGER NOT NULL, "
            "face_embedding TEXT NOT NULL, "
            "face_image TEXT NOT NULL, "
            "is_liveness_passed BOOLEAN DEFAULT 1, "
            "aadhaar_match_score FLOAT DEFAULT 0.0, "
            "captured_at DATETIME)"
        ))
        conn.execute(text(
            "CREATE TABLE IF NOT EXISTS verification_logs ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "event_type VARCHAR(100) NOT NULL, "
            "status VARCHAR(50) NOT NULL, "
            "message TEXT, "
            "transaction_id VARCHAR(100), "
            "visitor_id VARCHAR(100), "
            "created_at DATETIME, "
            "timestamp DATETIME)"
        ))
        # Per-visit grace period (the "Grace Time for Visitor to return" box in
        # the flow) is configurable from the visitor form. Older visit_sessions
        # rows predate this column — add it in place if missing so the
        # wrong-floor timer can read each session's own grace window.
        session_cols = {
            row[1] for row in conn.execute(text("PRAGMA table_info(visit_sessions)")).fetchall()
        }
        if session_cols and "grace_period_seconds" not in session_cols:
            conn.execute(text(
                "ALTER TABLE visit_sessions ADD COLUMN grace_period_seconds INTEGER NOT NULL DEFAULT 60"
            ))
    print("[*] Visitor core schema ensured (face_embeddings, verification_logs).")


# =====================================================================
# CAMERA REGISTRY — dynamic multi-camera nodes (entrance / floor / room)
# =====================================================================
# Cameras are logical nodes, each mapping to a floor and (optionally) a
# faculty room, plus an admin-assigned MJPEG stream URL. The capture bridge
# (edge_bridge.py) reads this registry and spawns one worker per camera that
# has a stream_url. Room cameras are auto-created when a faculty is added or
# edits their room/floor.
# No hardcoded entrance IP — the phone's DHCP address changes. The entrance
# camera is seeded with no stream and auto-filled by WiFi discovery on startup
# (_auto_discover_cameras_on_startup) or the admin 'Auto-Detect' button.
DEFAULT_ENTRANCE_STREAM = None


@router.on_event("startup")
def _ensure_camera_nodes_schema() -> None:
    """Creates the camera_nodes registry in the visitor DB (same DB as
    camera_tracking_logs) and seeds the two fixed floor cameras: the
    entrance on Floor 0 and a First-Floor camera on Floor 1."""
    with visitor_engine.begin() as conn:
        conn.execute(text(
            "CREATE TABLE IF NOT EXISTS camera_nodes ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "camera_id VARCHAR(100) UNIQUE NOT NULL, "
            "label VARCHAR(255) NOT NULL, "
            "floor INTEGER NOT NULL, "
            "room_number VARCHAR(50), "
            "stream_url TEXT, "
            "is_active BOOLEAN DEFAULT 1)"
        ))
        # Seed the fixed floor cameras (insert-if-missing; never clobber an
        # admin-assigned stream_url on restart).
        for camera_id, label, floor, stream in [
            ("CAM_FLOOR_0", "Entrance — Floor 0", 0, DEFAULT_ENTRANCE_STREAM),
            ("CAM_FLOOR_1", "First Floor — Floor 1", 1, None),
        ]:
            exists = conn.execute(
                text("SELECT 1 FROM camera_nodes WHERE camera_id = :cid"),
                {"cid": camera_id}
            ).fetchone()
            if not exists:
                conn.execute(
                    text("INSERT INTO camera_nodes (camera_id, label, floor, room_number, stream_url, is_active) "
                         "VALUES (:cid, :lbl, :fl, NULL, :st, 1)"),
                    {"cid": camera_id, "lbl": label, "fl": floor, "st": stream}
                )
    print("[*] Camera registry ensured (camera_nodes: CAM_FLOOR_0, CAM_FLOOR_1).")


# How often the backend re-checks every camera's phone and re-discovers if it
# dropped off the WiFi (Android sleeps the radio / DHCP hands out a new IP).
CAMERA_REHEAL_SECONDS = 20


def _heal_cameras_once() -> None:
    """Clear any camera whose phone is no longer reachable (stale/changed IP)
    and auto-assign live IP-Webcam phones to streamless cameras. Idempotent and
    safe to call on a timer — this is what keeps cameras online automatically
    when the phone's IP changes, with no manual re-entry and no restart."""
    try:
        with visitor_engine.begin() as conn:
            rows = conn.execute(text(
                "SELECT camera_id, stream_url FROM camera_nodes "
                "WHERE stream_url IS NOT NULL AND stream_url != ''"
            )).fetchall()
        for camera_id, url in rows:
            if not _stream_host_reachable(url):
                print(f"[!] [CAMERA] {camera_id} stream {url} unreachable — clearing for auto-detect.")
                with visitor_engine.begin() as conn:
                    conn.execute(
                        text("UPDATE camera_nodes SET stream_url = NULL WHERE camera_id = :c"),
                        {"c": camera_id},
                    )
        _auto_assign_streams()
    except Exception as e:
        print(f"[!] [CAMERA] auto-heal failed: {e}")


@router.on_event("startup")
def _auto_discover_cameras_on_startup() -> None:
    """Runs the camera auto-heal on boot AND then every CAMERA_REHEAL_SECONDS in
    a background daemon thread, so a phone that changes IP or drops off WiFi is
    re-found automatically. This is what stops the endless
    'host ... timed out / host is down' bridge spam without editing any IP."""
    def _loop() -> None:
        while True:
            _heal_cameras_once()
            time.sleep(CAMERA_REHEAL_SECONDS)

    threading.Thread(target=_loop, daemon=True).start()


@router.on_event("startup")
def _ensure_camera_tracking_schema() -> None:
    """Creates the camera_tracking_logs table in the visitor DB if it doesn't
    exist. This table is written to by the live Re-ID stream on every
    detection, so it must exist for surveillance to function."""
    with visitor_engine.begin() as conn:
        conn.execute(text(
            "CREATE TABLE IF NOT EXISTS camera_tracking_logs ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "session_id INTEGER NOT NULL, "
            "camera_id VARCHAR(100) NOT NULL, "
            "detected_floor INTEGER NOT NULL, "
            "tracking_confidence FLOAT, "
            "timestamp DATETIME, "
            "FOREIGN KEY (session_id) REFERENCES visit_sessions (id), "
            "FOREIGN KEY (camera_id) REFERENCES camera_nodes (camera_id))"
        ))
    print("[*] Camera tracking log schema ensured (camera_tracking_logs).")


def _sync_faculty_cameras(floor: int, room_number: str | None, faculty_name: str | None) -> None:
    """Ensures a floor camera exists for the faculty's floor and upserts a
    dedicated room camera (CAM_ROOM_<room>) for the faculty's room. Called
    whenever a faculty is registered or edits their floor/room so the camera
    registry always has a node covering them."""
    with visitor_engine.begin() as conn:
        # Ensure a floor camera exists for this floor.
        floor_cam = f"CAM_FLOOR_{floor}"
        if not conn.execute(text("SELECT 1 FROM camera_nodes WHERE camera_id = :c"), {"c": floor_cam}).fetchone():
            conn.execute(
                text("INSERT INTO camera_nodes (camera_id, label, floor, room_number, stream_url, is_active) "
                     "VALUES (:c, :l, :f, NULL, NULL, 1)"),
                {"c": floor_cam, "l": f"Floor {floor}", "f": floor}
            )

        if not room_number:
            return

        room_cam = f"CAM_ROOM_{str(room_number).strip().replace(' ', '_')}"
        label = f"Room {room_number}" + (f" — {faculty_name}" if faculty_name else "")
        existing = conn.execute(
            text("SELECT camera_id FROM camera_nodes WHERE camera_id = :c"), {"c": room_cam}
        ).fetchone()
        if existing:
            # Keep floor/label current, but leave any assigned stream_url intact.
            conn.execute(
                text("UPDATE camera_nodes SET label = :l, floor = :f, room_number = :r WHERE camera_id = :c"),
                {"l": label, "f": floor, "r": str(room_number), "c": room_cam}
            )
        else:
            conn.execute(
                text("INSERT INTO camera_nodes (camera_id, label, floor, room_number, stream_url, is_active) "
                     "VALUES (:c, :l, :f, :r, NULL, 1)"),
                {"c": room_cam, "l": label, "f": floor, "r": str(room_number)}
            )

    # A new floor/room camera may have just been created with no stream — try to
    # grab a live phone's IP off the WiFi automatically (background; non-blocking).
    _auto_assign_streams_bg()


def _resolve_camera_node(camera_id: str) -> dict | None:
    """Look up a camera node by camera_id -> {label, floor, room_number}. Used
    by stream-reid to know each detection's floor/room for presence tracking."""
    with visitor_engine.begin() as conn:
        row = conn.execute(
            text("SELECT camera_id, label, floor, room_number, stream_url FROM camera_nodes WHERE camera_id = :c"),
            {"c": camera_id}
        ).fetchone()
    if not row:
        return None
    return {"camera_id": row[0], "label": row[1], "floor": row[2], "room_number": row[3], "stream_url": row[4]}


@router.on_event("startup")
def _start_edge_bridge() -> None:
    global _edge_bridge_process

    # Guard against double-launch if this module gets imported more than
    # once in the same process (e.g. certain test setups).
    if _edge_bridge_process is not None and _edge_bridge_process.poll() is None:
        return

    edge_bridge_path = _resolve_edge_bridge_path()
    if edge_bridge_path is None:
        print("[!] edge_bridge.py not found — skipping auto-launch. "
              "Set the EDGE_BRIDGE_PATH env var to its location if this "
              "path assumption is wrong.")
        return

    print(f"[*] Auto-launching edge_bridge.py from {edge_bridge_path} ...")
    _edge_bridge_process = subprocess.Popen(
        [sys.executable, str(edge_bridge_path)],
        cwd=str(edge_bridge_path.parent),
    )


@router.on_event("shutdown")
def _stop_edge_bridge() -> None:
    global _edge_bridge_process
    if _edge_bridge_process is None:
        return
    if _edge_bridge_process.poll() is None:
        print("[*] Shutting down edge_bridge.py subprocess...")
        _edge_bridge_process.terminate()
        try:
            _edge_bridge_process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            _edge_bridge_process.kill()
    _edge_bridge_process = None


class CameraStreamPayload(BaseModel):
    camera_id: str
    current_floor: int
    frame_image_base64: str


# =====================================================================
# WRONG-FLOOR GRACE PERIOD / ESCALATION STATE
# =====================================================================
# Matches the workflow: on a wrong-floor detection, first just message the
# visitor and start a grace timer. Only escalate (call the faculty host +
# raise a HIGH SecurityAlert) if they're still on the wrong floor once the
# grace period elapses. This is in-memory (per active_session.id), which is
# fine for a single-process dev/demo deployment; it resets on restart.
WRONG_FLOOR_GRACE_SECONDS = 60

# session_id -> datetime of first wrong-floor detection in the current streak
_WRONG_FLOOR_FIRST_SEEN: dict[int, datetime] = {}
# session_id -> True once escalation (faculty call + HIGH alert) has fired,
# so we don't re-notify on every single subsequent frame while they're still
# on the wrong floor.
_WRONG_FLOOR_ESCALATED: set[int] = set()

# employee_id -> (floor, room_number, last_seen_datetime). Lightweight faculty
# location tracking from faculty face matches, used only to enrich alerts
# ("your host is currently on Floor X"). Not persisted; resets on restart.
_FACULTY_LOCATION: dict[str, tuple] = {}

# (session_id, camera_id) -> datetime of the last CameraTrackingLog insert, so
# we throttle presence writes to ~one row every few seconds per camera instead
# of one per video frame.
_LAST_TRACKING_LOG: dict[tuple, datetime] = {}
TRACKING_LOG_MIN_INTERVAL_SECONDS = 3


# =====================================================================
# TWILIO WHATSAPP ALERT DELIVERY
# =====================================================================
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID", "")
def _format_whatsapp_number(raw_number: str) -> str:
    number = (raw_number or "").strip()
    if not number.startswith("+"):
        default_cc = getattr(settings, "default_country_code", "+91")
        number = f"{default_cc}{number}"
    return f"whatsapp:{number}"

TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN", "")
TWILIO_WHATSAPP_FROM = os.getenv("TWILIO_WHATSAPP_FROM", "")

# SMS delivery (per the project flow: wrong-direction alerts go to the
# visitor's mobile number as a plain text SMS). This must be a normal
# SMS-capable Twilio phone number in E.164 format (e.g. "+12025550123"),
# NOT a whatsapp: sender. Fill it in from your Twilio Console -> Phone Numbers.
TWILIO_SMS_FROM = os.getenv("TWILIO_SMS_FROM", "")

# NOTE: In Twilio's WhatsApp *sandbox* (the default for new accounts), the
# destination number must have first sent the sandbox's "join <code>" message
# to that sandbox number, or Twilio will reject the send. For faculty numbers
# that haven't opted in, this will fail — that's expected until you're on an
# approved WhatsApp Business sender, or each faculty member joins the sandbox.
def _format_whatsapp_number(raw_number: str) -> str:
    number = (raw_number or "").strip()
    if not number.startswith("+"):
        default_cc = getattr(settings, "default_country_code", "+91")
        number = f"{default_cc}{number}"
    return f"whatsapp:{number}"


def _format_sms_number(raw_number: str) -> str:
    """Normalizes a raw mobile number to E.164 for SMS (adds the default
    country code if the number was stored without one)."""
    number = (raw_number or "").strip()
    if not number:
        return ""
    if not number.startswith("+"):
        default_cc = getattr(settings, "default_country_code", "+91")
        number = f"{default_cc}{number}"
    return number


def send_sms_alert(to_phone_number: str, message: str) -> bool:
    """Sends a plain-text SMS via Twilio to the visitor's mobile number.
    Never raises — returns True/False so a delivery hiccup can't break the
    surveillance/alerting flow. Used for the flow's wrong-direction notices."""
    if TwilioClient is None:
        print("[!] 'twilio' package not installed — run `pip install twilio`. Skipping SMS send.")
        return False

    if not all([TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_SMS_FROM]) or \
       TWILIO_ACCOUNT_SID.startswith("ACxxxx") or "X" in TWILIO_SMS_FROM:
        print("[!] Twilio SMS credentials are still placeholders — fill in TWILIO_ACCOUNT_SID / "
              "TWILIO_AUTH_TOKEN / TWILIO_SMS_FROM near the top of workflow.py. Skipping SMS send.")
        return False

    to_number = _format_sms_number(to_phone_number)
    if not to_number:
        return False

    try:
        client = TwilioClient(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
        client.messages.create(
            from_=TWILIO_SMS_FROM,
            to=to_number,
            body=message,
        )
        return True
    except Exception as exc:
        print(f"[!] Failed to send SMS alert via Twilio: {exc}")
        return False


def send_whatsapp_alert(to_phone_number: str, message: str) -> bool:
    """Sends a WhatsApp message via Twilio. Never raises — returns True/False
    so a notification hiccup can't break the surveillance/alerting flow."""
    if TwilioClient is None:
        print("[!] 'twilio' package not installed — run `pip install twilio`. Skipping WhatsApp send.")
        return False

    if not all([TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_WHATSAPP_FROM]) or \
       TWILIO_ACCOUNT_SID.startswith("ACxxxx"):
        print("[!] Twilio credentials are still placeholders — fill in TWILIO_ACCOUNT_SID / "
              "TWILIO_AUTH_TOKEN / TWILIO_WHATSAPP_FROM near the top of workflow.py. "
              "Skipping WhatsApp send.")
        return False

    try:
        client = TwilioClient(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
        client.messages.create(
            from_=TWILIO_WHATSAPP_FROM if TWILIO_WHATSAPP_FROM.startswith("whatsapp:") else f"whatsapp:{TWILIO_WHATSAPP_FROM}",
            to=_format_whatsapp_number(to_phone_number),
            body=message,
        )
        return True
    except Exception as exc:
        print(f"[!] Failed to send WhatsApp alert via Twilio: {exc}")
        return False


def notify_visitor_and_faculty(
    visitor_name: str,
    visitor_phone: str | None,
    visitor_message: str,
    faculty_name: str | None,
    faculty_phone: str | None,
    faculty_message: str,
) -> dict:
    """Per the project flow, BOTH parties get alerted on every notification
    event — the visitor on their registered mobile number and the faculty
    host on their faculty_master phone number. Never raises; returns a
    delivery summary so callers can log it."""
    visitor_sent = False
    faculty_sent = False

    if visitor_phone:
        visitor_sent = send_sms_alert(visitor_phone, visitor_message)
        print(f"\n📨 [VISITOR SMS] {visitor_name} ({visitor_phone}) "
              f"{'✅ SMS delivered' if visitor_sent else '⚠️ SMS not delivered'}: {visitor_message}\n")
    else:
        print(f"\n⚠️ [VISITOR SMS] No mobile number on record for {visitor_name} — "
              f"message logged only: {visitor_message}\n")

    if faculty_phone:
        faculty_sent = send_sms_alert(faculty_phone, faculty_message)
        print(f"\n📲 [FACULTY SMS] {faculty_name} ({faculty_phone}) "
              f"{'✅ SMS delivered' if faculty_sent else '⚠️ SMS not delivered'}: {faculty_message}\n")
    else:
        print(f"\n⚠️ [FACULTY SMS] No phone number on record for faculty host — "
              f"message logged only: {faculty_message}\n")

    return {"visitor_sent": visitor_sent, "faculty_sent": faculty_sent}


# =====================================================================
# SECURE ADMINISTRATIVE ACCESS CONTROL LAYER
# =====================================================================

@router.post("/admin/login")
def admin_login(payload: AdminLoginRequest, db_college: Session = Depends(get_college_db)):
    """Validates security officer login credentials using the dedicated college database layer."""
    admin = db_college.query(AdminUser).filter(AdminUser.username == payload.username).first()
    if not admin or admin.password_hash != payload.password:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, 
            detail="Invalid Security Guard ID or Secret Password."
        )
    return {"status": "success", "role": admin.role}


@router.get("/logs/surveillance")
def get_surveillance_dashboard_logs():
    return SURVEILLANCE_DASHBOARD_CACHE[::-1][:25]


# =====================================================================
# CAMERA REGISTRY ENDPOINTS
# =====================================================================

class CameraStreamAssignRequest(BaseModel):
    stream_url: str


def _normalize_stream_url(raw: str) -> str:
    """Mirror of the admin UI's IP normalization: accept a bare IP, host:port,
    or full URL and coerce it to a full MJPEG endpoint (http://<host>:8080/video)."""
    url = (raw or "").strip()
    if not url:
        return ""
    if not url.startswith("http://") and not url.startswith("https://"):
        url = "http://" + url
    # If no explicit port and no path, assume the IP Webcam defaults.
    tail = url.split("://", 1)[1]
    if ":" not in tail.split("/", 1)[0]:
        # no port — add :8080 to the host portion
        host = tail.split("/", 1)[0]
        rest = tail[len(host):]
        url = url.split("://", 1)[0] + "://" + host + ":8080" + rest
    if not url.rstrip("/").endswith("/video"):
        url = url.rstrip("/") + "/video"
    return url


# --- Automatic IP-Webcam discovery on the local WiFi -----------------------
# The phone running the "IP Webcam" app serves MJPEG on port 8080 at /video.
# Its IP changes every time DHCP re-leases (e.g. 192.168.29.224 -> .223), which
# is exactly the "host is down" error the bridge was spamming. Instead of
# hardcoding the IP we scan the server's own /24 subnet for any phone answering
# on 8080 and hand back its stream URL — so a newly added camera can grab the
# phone's current IP automatically.
IPWEBCAM_PORT = 8080


def _local_subnet_prefix() -> str | None:
    """Best-effort: find this machine's LAN IPv4 and return its /24 prefix,
    e.g. '192.168.29'. Uses a UDP 'connect' (no packets are actually sent) to
    learn which interface routes to the internet."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0.5)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        parts = ip.split(".")
        if len(parts) == 4 and not ip.startswith("127."):
            return ".".join(parts[:3])
    except Exception:
        pass
    return None


def _probe_ipwebcam(ip: str) -> str | None:
    """Return the MJPEG URL if host `ip` is a real IP-Webcam phone, else None.

    We MUST NOT return a URL on a mere open port — routers, printers and other
    devices also listen on 8080 (the router at x.x.x.1 accepted the connection
    and then read-timed-out the bridge). So the only positive signal is a real
    MJPEG response: /video must answer with a multipart/x-mixed-replace (or
    image) content-type. If that fails we fall back to the landing page's
    'IP Webcam' fingerprint. Anything ambiguous → None."""
    try:
        with socket.create_connection((ip, IPWEBCAM_PORT), timeout=0.35):
            pass
    except Exception:
        return None
    stream = f"http://{ip}:{IPWEBCAM_PORT}/video"
    # Primary, definitive check: does /video serve an MJPEG stream? stream=True
    # returns headers without downloading the body, so this is cheap.
    try:
        r = requests.get(stream, stream=True, timeout=1.5)
        ctype = (r.headers.get("Content-Type") or "").lower()
        r.close()
        if "multipart" in ctype or "mixed-replace" in ctype or ctype.startswith("image/"):
            return stream
    except Exception:
        pass
    # Secondary check: the IP-Webcam landing page names itself.
    try:
        r = requests.get(f"http://{ip}:{IPWEBCAM_PORT}/", timeout=1.2)
        body = (r.text or "")[:4000].lower()
        if "ip webcam" in body:
            return stream
    except Exception:
        pass
    # Open port but no camera evidence — do NOT assign it.
    return None


def _stream_host_reachable(stream_url: str) -> bool:
    """Quick TCP check that the phone behind a stream URL is still on the WiFi.
    Used to detect a stale IP (phone got a new DHCP lease) so we can clear it."""
    try:
        host = stream_url.split("://", 1)[1].split("/", 1)[0]
        h, _, p = host.partition(":")
        port = int(p) if p else IPWEBCAM_PORT
        with socket.create_connection((h, port), timeout=0.5):
            return True
    except Exception:
        return False


def _discover_ipwebcam_streams(prefix: str | None = None) -> list[str]:
    """Scan every host on the LAN /24 concurrently and return the stream URLs of
    all IP-Webcam phones found."""
    prefix = prefix or _local_subnet_prefix()
    if not prefix:
        return []
    hosts = [f"{prefix}.{i}" for i in range(1, 255)]
    found: list[str] = []
    with ThreadPoolExecutor(max_workers=64) as pool:
        for url in pool.map(_probe_ipwebcam, hosts):
            if url:
                found.append(url)
    return found


def _auto_assign_streams() -> list[dict]:
    """Discover phones on the WiFi and assign each newly-found stream to a
    camera node that has no stream yet (floors/entrance first). Returns the
    list of assignments made. Safe to call repeatedly — it never reassigns a
    stream that's already in use by another node."""
    streams = _discover_ipwebcam_streams()
    if not streams:
        return []
    assigned: list[dict] = []
    with visitor_engine.begin() as conn:
        used = {
            r[0] for r in conn.execute(text(
                "SELECT stream_url FROM camera_nodes WHERE stream_url IS NOT NULL AND stream_url != ''"
            )).fetchall()
        }
        available = [s for s in streams if s not in used]
        empties = conn.execute(text(
            "SELECT camera_id FROM camera_nodes WHERE stream_url IS NULL OR stream_url = '' "
            "ORDER BY floor, camera_id"
        )).fetchall()
        for row, stream in zip(empties, available):
            camera_id = row[0]
            conn.execute(
                text("UPDATE camera_nodes SET stream_url = :s, is_active = 1 WHERE camera_id = :c"),
                {"s": stream, "c": camera_id},
            )
            assigned.append({"camera_id": camera_id, "stream_url": stream})
    for a in assigned:
        print(f"[*] [CAMERA] Auto-assigned phone {a['stream_url']} -> {a['camera_id']}")
    return assigned


def _auto_assign_streams_bg() -> None:
    """Run auto-assign in a daemon thread so a subnet scan never blocks a
    request or app startup."""
    threading.Thread(target=lambda: _auto_assign_streams(), daemon=True).start()


@router.get("/cameras/discover")
def discover_cameras():
    """Scan the WiFi /24 for IP-Webcam phones and return their stream URLs
    (without assigning). Drives the admin 'Auto-Detect' button preview."""
    prefix = _local_subnet_prefix()
    streams = _discover_ipwebcam_streams(prefix)
    return {"subnet": f"{prefix}.0/24" if prefix else None, "found": streams}


@router.post("/cameras/auto-assign")
def auto_assign_cameras():
    """Scan the WiFi and auto-assign discovered phone streams to camera nodes
    that don't have one — so you never have to type an IP by hand."""
    assigned = _auto_assign_streams()
    return {"status": "success", "assigned": assigned, "assigned_count": len(assigned)}


@router.get("/cameras")
def list_cameras():
    """Camera registry for the admin dashboard feeds AND the edge_bridge
    capture workers. Returns every node with its floor/room/stream."""
    with visitor_engine.begin() as conn:
        rows = conn.execute(text(
            "SELECT camera_id, label, floor, room_number, stream_url, is_active "
            "FROM camera_nodes ORDER BY floor, camera_id"
        )).fetchall()
    return [
        {
            "camera_id": r[0],
            "label": r[1],
            "floor": r[2],
            "room_number": r[3],
            "stream_url": r[4],
            "is_active": bool(r[5]),
        }
        for r in rows
    ]


@router.post("/cameras/{camera_id}/stream")
def assign_camera_stream(camera_id: str, payload: CameraStreamAssignRequest):
    """Assign/replace the MJPEG stream URL for a camera node. edge_bridge.py
    polls the registry and starts a capture worker for it within ~15s."""
    stream_url = _normalize_stream_url(payload.stream_url)
    if not stream_url:
        raise HTTPException(status_code=400, detail="A camera stream IP or URL is required.")
    with visitor_engine.begin() as conn:
        found = conn.execute(
            text("SELECT 1 FROM camera_nodes WHERE camera_id = :c"), {"c": camera_id}
        ).fetchone()
        if not found:
            raise HTTPException(status_code=404, detail=f"Camera node {camera_id} not found.")
        conn.execute(
            text("UPDATE camera_nodes SET stream_url = :s, is_active = 1 WHERE camera_id = :c"),
            {"s": stream_url, "c": camera_id}
        )
    print(f"[*] [CAMERA] Stream assigned to {camera_id}: {stream_url}")
    return {"status": "success", "camera_id": camera_id, "stream_url": stream_url}


@router.get("/admin/security-alerts")
def list_security_alerts(db_visitor: Session = Depends(get_visitor_db)):
    """Feeds the 'Admin Alert' panel: open, unresolved floor-violation alerts,
    newest first, with enough visitor/session context to act on (detain)."""
    rows = db_visitor.execute(text(
        "SELECT sa.id, sa.session_id, sa.alert_priority, sa.alert_type, "
        "sa.current_floor, sa.message, sa.is_resolved, sa.timestamp, "
        "vs.employee_to_meet, vs.department, vm.name, vm.visitor_id, "
        "sa.security_dispatched "
        "FROM security_alerts sa "
        "JOIN visit_sessions vs ON vs.id = sa.session_id "
        "JOIN visitor_master vm ON vm.id = vs.visitor_id "
        "WHERE sa.is_resolved = 0 "
        "ORDER BY sa.id DESC"
    )).fetchall()

    return [
        {
            "alert_id": r[0],
            "session_id": r[1],
            "alert_priority": r[2],
            "alert_type": r[3],
            "current_floor": r[4],
            "message": r[5],
            "is_resolved": bool(r[6]),
            "timestamp": r[7],
            "employee_to_meet": r[8],
            "department": r[9],
            "visitor_name": r[10],
            "visitor_ref": r[11],
            "security_dispatched": bool(r[12]),
        }
        for r in rows
    ]


@router.post("/admin/security-alerts/{alert_id}/dispatch-security")
def dispatch_security(alert_id: int, db_visitor: Session = Depends(get_visitor_db)):
    """'SEND ALERT TO SECURITY' step of the flow: the admin reviews the
    Admin Alert and forwards it to the on-ground security team. This must
    happen BEFORE the detain step — the detain endpoint rejects alerts
    that haven't been dispatched to security yet."""
    row = db_visitor.execute(
        text("SELECT sa.id, sa.session_id, sa.current_floor, sa.security_dispatched, "
             "vm.name, vm.visitor_id "
             "FROM security_alerts sa "
             "JOIN visit_sessions vs ON vs.id = sa.session_id "
             "JOIN visitor_master vm ON vm.id = vs.visitor_id "
             "WHERE sa.id = :aid"),
        {"aid": alert_id}
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Security alert not found.")
    if row[3]:
        return {"status": "already_dispatched", "msg": "Security team already alerted for this incident."}

    db_visitor.execute(
        text("UPDATE security_alerts SET security_dispatched = 1, dispatched_at = :t WHERE id = :aid"),
        {"t": datetime.utcnow(), "aid": alert_id}
    )
    db_visitor.execute(
        text("INSERT INTO verification_logs (event_type, status, message, transaction_id, visitor_id, created_at, timestamp) "
             "VALUES (:ev, :st, :msg, :tx, :v_id, :t1, :t2)"),
        {
            "ev": "security_dispatch",
            "st": "dispatched",
            "msg": f"Admin forwarded alert #{alert_id} to security team. "
                   f"Visitor {row[4]} still on Floor {row[2]}.",
            "tx": str(uuid.uuid4()),
            "v_id": row[5],
            "t1": datetime.utcnow(),
            "t2": datetime.utcnow()
        }
    )
    db_visitor.commit()

    print(f"\n🚨 [SEND ALERT TO SECURITY] Admin dispatched alert #{alert_id} to the security "
          f"team: visitor {row[4]} is on Floor {row[2]}. Security will detain the visitor.\n")

    return {
        "status": "success",
        "msg": f"Alert forwarded to security. Security team dispatched to Floor {row[2]}.",
        "alert_id": alert_id,
    }


@router.post("/admin/security-alerts/{alert_id}/detain")
def detain_visitor(alert_id: int, db_visitor: Session = Depends(get_visitor_db)):
    """Final escalation step: security detains the visitor and admin blocks
    them. Resolves the triggering alert and flips the session to 'blocked'
    so surveillance/dashboard code can distinguish it from a normal active
    or completed visit."""
    alert = db_visitor.get(SecurityAlert, alert_id)
    if not alert:
        raise HTTPException(status_code=404, detail="Security alert not found.")

    # Enforce the flow's ordering: the admin must SEND THE ALERT TO SECURITY
    # first, and only then can security detain and the admin block.
    dispatched_row = db_visitor.execute(
        text("SELECT security_dispatched FROM security_alerts WHERE id = :aid"),
        {"aid": alert_id}
    ).fetchone()
    if not dispatched_row or not dispatched_row[0]:
        raise HTTPException(
            status_code=409,
            detail="Alert has not been sent to security yet. Dispatch security first."
        )

    session_row = db_visitor.execute(
        text("SELECT id, visitor_id FROM visit_sessions WHERE id = :sid"),
        {"sid": alert.session_id}
    ).fetchone()
    if not session_row:
        raise HTTPException(status_code=404, detail="Associated visit session not found.")

    alert.is_resolved = True

    db_visitor.execute(
        text("UPDATE visit_sessions SET status = 'blocked', exit_time = :t WHERE id = :idx"),
        {"t": datetime.utcnow(), "idx": session_row[0]}
    )

    # Clear any grace-period tracking state for this session — it's over now.
    _WRONG_FLOOR_FIRST_SEEN.pop(session_row[0], None)
    _WRONG_FLOOR_ESCALATED.discard(session_row[0])

    visitor_row = db_visitor.execute(
        text("SELECT visitor_id FROM visitor_master WHERE id = :vid"),
        {"vid": session_row[1]}
    ).fetchone()

    db_visitor.execute(
        text("INSERT INTO verification_logs (event_type, status, message, transaction_id, visitor_id, created_at, timestamp) "
             "VALUES (:ev, :st, :msg, :tx, :v_id, :t1, :t2)"),
        {
            "ev": "visitor_detained",
            "st": "blocked",
            "msg": f"Visitor detained by security and blocked by admin (alert #{alert_id}).",
            "tx": str(uuid.uuid4()),
            "v_id": visitor_row[0] if visitor_row else None,
            "t1": datetime.utcnow(),
            "t2": datetime.utcnow()
        }
    )
    db_visitor.commit()

    print(f"\n🚔 [SECURITY DISPATCH] Visitor detained on-site. "
          f"Session #{session_row[0]} marked BLOCKED by admin action on alert #{alert_id}.\n")

    return {"status": "success", "msg": "Visitor detained and blocked.", "session_id": session_row[0]}

@router.get("/faculty/list")
def get_faculty_list(db_college: Session = Depends(get_college_db)):
    """Fetches faculty details for visitor form dropdowns."""
    faculty = db_college.query(FacultyMaster).all()
    return [{"name": f.name, "department": f.department, "floor": f.assigned_floor} for f in faculty]


# =====================================================================
# ADMIN: FACULTY REGISTRATION (new faculty_registration table, college.db)
# =====================================================================

class FacultyRegistrationRequest(BaseModel):
    employee_id: str
    name: str
    department: str
    phone_number: str
    room_number: str
    assigned_floor: int
    email: str | None = None
    designation: str | None = None
    aadhaar_number: str | None = None
    full_name: str | None = None
    date_of_birth: str | None = None
    gender: str | None = None
    address: str | None = None
    aadhaar_photo: str | None = None


@router.post("/admin/faculty/register")
def admin_register_faculty(
    payload: FacultyRegistrationRequest,
    db_college: Session = Depends(get_college_db),
):
    """Admin-side faculty onboarding. Writes the full identity record
    (Aadhaar fields included, mirroring the visitor registry) into the
    new faculty_registration table AND keeps faculty_master in sync so
    visitor-form dropdowns, floor authorization, and WhatsApp host alerts
    all work immediately for the new faculty member."""
    employee_id = payload.employee_id.strip()
    phone = payload.phone_number.strip()

    if not employee_id or not payload.name.strip() or not phone:
        raise HTTPException(status_code=400, detail="Employee ID, name, and phone number are required.")

    duplicate = db_college.execute(
        text("SELECT id FROM faculty_registration WHERE employee_id = :eid"),
        {"eid": employee_id}
    ).fetchone()
    if duplicate:
        raise HTTPException(status_code=409, detail=f"Faculty with Employee ID {employee_id} is already registered.")

    masked_aadhaar = None
    if payload.aadhaar_number:
        from ..services.aadhaar_service import mask_aadhaar
        try:
            masked_aadhaar = mask_aadhaar(payload.aadhaar_number)
        except Exception:
            digits = "".join(ch for ch in payload.aadhaar_number if ch.isdigit())
            if len(digits) != 12:
                raise HTTPException(status_code=400, detail="Aadhaar number must be 12 digits.")
            masked_aadhaar = "XXXX-XXXX-" + digits[-4:]

    db_college.execute(
        text("INSERT INTO faculty_registration (employee_id, name, department, phone_number, "
             "room_number, assigned_floor, email, designation, masked_aadhaar, full_name, "
             "date_of_birth, gender, address, aadhaar_photo, is_aadhaar_verified, registered_at) "
             "VALUES (:eid, :name, :dept, :phone, :room, :floor, :email, :desig, :maadhaar, "
             ":fullname, :dob, :gender, :addr, :photo, :verified, :ts)"),
        {
            "eid": employee_id,
            "name": payload.name.strip(),
            "dept": payload.department.strip(),
            "phone": phone,
            "room": payload.room_number.strip(),
            "floor": payload.assigned_floor,
            "email": payload.email,
            "desig": payload.designation,
            "maadhaar": masked_aadhaar,
            "fullname": payload.full_name,
            "dob": payload.date_of_birth,
            "gender": payload.gender,
            "addr": payload.address,
            "photo": payload.aadhaar_photo,
            "verified": False,
            "ts": datetime.utcnow(),
        }
    )

    # Keep faculty_master in sync so the rest of the system (visitor form
    # dropdown, floor checks, host WhatsApp alerts) sees the new faculty.
    existing_master = db_college.query(FacultyMaster).filter(
        FacultyMaster.employee_id == employee_id
    ).first()
    if existing_master:
        existing_master.name = payload.name.strip()
        existing_master.department = payload.department.strip()
        existing_master.phone_number = phone
        existing_master.room_number = payload.room_number.strip()
        existing_master.assigned_floor = payload.assigned_floor
    else:
        new_master = FacultyMaster(
            employee_id=employee_id,
            name=payload.name.strip(),
            department=payload.department.strip(),
            phone_number=phone,
            room_number=payload.room_number.strip(),
            assigned_floor=payload.assigned_floor
        )
        db_college.add(new_master)
    
    if masked_aadhaar:
        db_college.execute(
            text("UPDATE faculty_master SET masked_aadhaar = :m WHERE employee_id = :eid"),
            {"m": masked_aadhaar, "eid": employee_id}
        )
    db_college.commit()

    # Auto-provision cameras for this faculty: a floor camera for their floor
    # and a dedicated room camera (per the flow's "camera in the faculty room").
    _sync_faculty_cameras(payload.assigned_floor, payload.room_number.strip(), payload.name.strip())

    print(f"[*] [FACULTY REGISTERED] {payload.name} ({employee_id}) — Floor {payload.assigned_floor}, "
          f"Room {payload.room_number}, Phone {phone}.")

    return {
        "status": "success",
        "msg": f"Faculty {payload.name} registered successfully. "
               f"They can now complete Aadhaar + face verification at the Faculty Verification Desk.",
        "employee_id": employee_id,
    }


@router.get("/admin/faculty/registered")
def admin_list_registered_faculty(db_college: Session = Depends(get_college_db)):
    """Feeds the admin dashboard's registered-faculty table."""
    rows = db_college.execute(text(
        "SELECT fr.employee_id, fr.name, fr.department, fr.phone_number, fr.room_number, "
        "fr.assigned_floor, fr.masked_aadhaar, fr.registered_at, "
        "COALESCE(fm.is_verified, 0) "
        "FROM faculty_registration fr "
        "LEFT JOIN faculty_master fm ON fm.employee_id = fr.employee_id "
        "ORDER BY fr.id DESC"
    )).fetchall()

    return [
        {
            "employee_id": r[0],
            "name": r[1],
            "department": r[2],
            "phone_number": r[3],
            "room_number": r[4],
            "assigned_floor": r[5],
            "masked_aadhaar": r[6] or "Not linked",
            "registered_at": r[7],
            "is_verified": bool(r[8]),
        }
        for r in rows
    ]


class FacultyUpdateDetailsRequest(BaseModel):
    employee_id: str
    department: str | None = None
    room_number: str | None = None
    assigned_floor: int | None = None
    phone_number: str | None = None


@router.post("/faculty/update-details")
def faculty_update_details(payload: FacultyUpdateDetailsRequest, db_college: Session = Depends(get_college_db)):
    """Faculty self-service: a verified faculty edits their own floor / room /
    department / phone. Updates BOTH faculty_master and faculty_registration
    (kept in sync) and re-syncs the room/floor camera nodes so tracking and
    host SMS immediately use the new location."""
    faculty = db_college.query(FacultyMaster).filter(
        FacultyMaster.employee_id == payload.employee_id.strip()
    ).first()
    if not faculty:
        raise HTTPException(status_code=404, detail="No faculty record found for this Employee ID.")

    # Apply only the fields that were provided (partial update).
    if payload.department is not None and payload.department.strip():
        faculty.department = payload.department.strip()
    if payload.room_number is not None and payload.room_number.strip():
        faculty.room_number = payload.room_number.strip()
    if payload.assigned_floor is not None:
        faculty.assigned_floor = int(payload.assigned_floor)
    if payload.phone_number is not None and payload.phone_number.strip():
        faculty.phone_number = payload.phone_number.strip()

    # Keep the full registration record in sync.
    db_college.execute(
        text("UPDATE faculty_registration SET department = :d, room_number = :r, "
             "assigned_floor = :f, phone_number = :p WHERE employee_id = :eid"),
        {
            "d": faculty.department,
            "r": faculty.room_number,
            "f": faculty.assigned_floor,
            "p": faculty.phone_number,
            "eid": faculty.employee_id,
        }
    )
    db_college.commit()

    # Re-provision cameras for the (possibly new) floor + room.
    _sync_faculty_cameras(faculty.assigned_floor, faculty.room_number, faculty.name)

    print(f"[*] [FACULTY UPDATED] {faculty.name} ({faculty.employee_id}) → "
          f"Floor {faculty.assigned_floor}, Room {faculty.room_number}, "
          f"Dept {faculty.department}, Phone {faculty.phone_number}.")

    return {
        "status": "success",
        "msg": "Your details were updated. Visitor routing, tracking and SMS now use the new floor/room.",
        "faculty": {
            "employee_id": faculty.employee_id,
            "name": faculty.name,
            "department": faculty.department,
            "room_number": faculty.room_number,
            "assigned_floor": faculty.assigned_floor,
            "phone_number": faculty.phone_number,
        },
    }


# =====================================================================
# FACULTY IDENTITY VERIFICATION (mirrors the visitor Aadhaar + face flow)
# =====================================================================
# Same pipeline as visitors: Aadhaar OTP verification first, then face
# enrollment (3-angle liveness) on first verification, or a single live
# face scan on subsequent check-ins. Faculty embeddings live in the
# college database (faculty_face_embeddings), fully separate from
# visitor embeddings.

class FacultyAadhaarStartRequest(BaseModel):
    employee_id: str
    aadhaar_number: str


class FacultyAadhaarVerifyRequest(BaseModel):
    employee_id: str
    flow_id: str
    otp: str


class FacultyFaceRequest(BaseModel):
    employee_id: str
    front_image_base64: str
    left_image_base64: str | None = None
    right_image_base64: str | None = None
    blink_done: bool = False
    turn_left_done: bool = False
    turn_right_done: bool = False
    is_revisit: bool = False


def _get_faculty_or_404(db_college: Session, employee_id: str) -> FacultyMaster:
    faculty = db_college.query(FacultyMaster).filter(
        FacultyMaster.employee_id == employee_id.strip()
    ).first()
    if not faculty:
        raise HTTPException(
            status_code=404,
            detail="No faculty record found for this Employee ID. Contact the college admin."
        )
    return faculty


@router.post("/faculty/aadhaar/start")
def faculty_aadhaar_start(payload: FacultyAadhaarStartRequest, db_college: Session = Depends(get_college_db)):
    """Step 1 of faculty verification: validate the employee ID, then either
    short-circuit to the face-scan step (already verified faculty = revisit
    mode, exactly like returning visitors) or trigger an Aadhaar OTP."""
    from ..services.aadhaar_service import mask_aadhaar, start_aadhaar_otp

    faculty = _get_faculty_or_404(db_college, payload.employee_id)
    masked = mask_aadhaar(payload.aadhaar_number)

    already_verified = db_college.execute(
        text("SELECT is_verified, masked_aadhaar FROM faculty_master WHERE id = :fid"),
        {"fid": faculty.id}
    ).fetchone()

    if already_verified and already_verified[0]:
        if already_verified[1] and already_verified[1] != masked:
            raise HTTPException(
                status_code=400,
                detail="This Aadhaar number does not match the one registered for this faculty member."
            )
        return {
            "pre_verified": True,
            "message": "Faculty already Aadhaar-verified. Switching to Face Scan Authentication mode.",
            "faculty": {
                "employee_id": faculty.employee_id,
                "name": faculty.name,
                "department": faculty.department,
                "room_number": faculty.room_number,
                "assigned_floor": faculty.assigned_floor,
            },
        }

    try:
        flow_id, session_id, message, authorization_url = start_aadhaar_otp(payload.aadhaar_number)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {
        "pre_verified": False,
        "flow_id": flow_id,
        "reference_id": session_id,
        "authorization_url": authorization_url,
        "message": message,
    }


@router.post("/faculty/aadhaar/verify")
def faculty_aadhaar_verify(
    payload: FacultyAadhaarVerifyRequest,
    db_college: Session = Depends(get_college_db),
):
    """Step 2: verify the OTP against the Aadhaar provider. IMPORTANT:
    faculty Aadhaar records are stored in college.db's own aadhaar_master
    table (NOT the visitor database) — the college session is passed to
    the service so the upsert and its internal verification log both land
    in college_system.db, where visitor_id is nullable."""
    from ..services.aadhaar_service import verify_aadhaar_otp_and_upsert
    import time as _time

    faculty = _get_faculty_or_404(db_college, payload.employee_id)

    # "Source Unavailable" is a transient upstream error from the Sandbox
    # Aadhaar API (UIDAI source momentarily unreachable). Retry a couple of
    # times with a short delay before giving up, and return an actionable
    # message if it still fails.
    aadhaar = None
    last_error = None
    for attempt in range(3):
        try:
            aadhaar, _raw = verify_aadhaar_otp_and_upsert(db_college, payload.flow_id, payload.otp)
            break
        except ValueError as exc:
            last_error = str(exc)
            if "source unavailable" in last_error.lower() and attempt < 2:
                print(f"[!] Aadhaar provider returned 'Source Unavailable' "
                      f"(attempt {attempt + 1}/3) — retrying in 2s...")
                _time.sleep(2)
                continue
            break

    if aadhaar is None:
        if last_error and "source unavailable" in last_error.lower():
            raise HTTPException(
                status_code=503,
                detail="Aadhaar verification service (UIDAI source) is temporarily unavailable. "
                       "This is an upstream provider issue, not a problem with your OTP. "
                       "Please click 'Verify Faculty & Send OTP' again to get a fresh OTP and retry."
            )
        raise HTTPException(status_code=400, detail=last_error or "OTP verification failed.")

    db_college.execute(
        text("UPDATE faculty_master SET masked_aadhaar = :m, is_verified = 1, "
             "aadhaar_verified_at = :t WHERE id = :fid"),
        {"m": aadhaar.masked_aadhaar, "t": datetime.utcnow(), "fid": faculty.id}
    )
    # Sync the full identity record into faculty_registration as well.
    db_college.execute(
        text("UPDATE faculty_registration SET masked_aadhaar = :m, full_name = :fn, "
             "date_of_birth = :dob, gender = :g, address = :addr, aadhaar_photo = :photo, "
             "is_aadhaar_verified = 1 WHERE employee_id = :eid"),
        {
            "m": aadhaar.masked_aadhaar,
            "fn": aadhaar.full_name,
            "dob": aadhaar.date_of_birth,
            "g": aadhaar.gender,
            "addr": aadhaar.address,
            "photo": aadhaar.aadhaar_photo,
            "eid": faculty.employee_id,
        }
    )
    db_college.execute(
        text("INSERT INTO verification_logs (event_type, status, message, transaction_id, visitor_id, created_at, timestamp) "
             "VALUES (:ev, :st, :msg, :tx, :v_id, :t1, :t2)"),
        {
            "ev": "faculty_aadhaar_verification",
            "st": "success",
            "msg": f"Faculty {faculty.name} ({faculty.employee_id}) Aadhaar-verified.",
            "tx": aadhaar.transaction_id,
            "v_id": faculty.employee_id,
            "t1": datetime.utcnow(),
            "t2": datetime.utcnow()
        }
    )
    db_college.commit()

    return {
        "status": "success",
        "message": "Faculty Aadhaar verified. Proceed to face registration.",
        "faculty": {
            "employee_id": faculty.employee_id,
            "name": faculty.name,
            "full_name": aadhaar.full_name,
            "department": faculty.department,
            "date_of_birth": aadhaar.date_of_birth,
            "gender": aadhaar.gender,
            "aadhaar_photo": aadhaar.aadhaar_photo,
            "masked_aadhaar": aadhaar.masked_aadhaar,
        },
    }


@router.post("/faculty/face/register")
def faculty_face_register(
    payload: FacultyFaceRequest,
    db_college: Session = Depends(get_college_db),
):
    """Step 3: exactly like the visitor face step. First verification =
    3-angle liveness enrollment into faculty_face_embeddings. Revisit =
    single live scan matched against stored faculty embeddings."""
    faculty = _get_faculty_or_404(db_college, payload.employee_id)

    verified_row = db_college.execute(
        text("SELECT is_verified FROM faculty_master WHERE id = :fid"),
        {"fid": faculty.id}
    ).fetchone()
    if not verified_row or not verified_row[0]:
        raise HTTPException(
            status_code=400,
            detail="Complete Aadhaar OTP verification before face registration."
        )

    front_img = decode_base64_image(payload.front_image_base64)
    if not detect_single_face(front_img):
        raise HTTPException(status_code=400, detail="Face detection failed. Face must be visible and clear.")

    if not payload.is_revisit:
        if not liveness_passed(payload.blink_done, payload.turn_left_done, payload.turn_right_done):
            raise HTTPException(status_code=400, detail="Multi-angle liveness verification failed.")
    else:
        if not payload.blink_done:
            raise HTTPException(status_code=400, detail="Liveness check missing for authentication frame.")

    live_embedding = create_face_embedding(payload.front_image_base64)
    MATCH_THRESHOLD = getattr(settings, "face_match_threshold", 0.88)

    if payload.is_revisit:
        stored_rows = db_college.execute(
            text("SELECT face_embedding FROM faculty_face_embeddings WHERE faculty_id = :fid"),
            {"fid": faculty.id}
        ).fetchall()
        if not stored_rows:
            raise HTTPException(
                status_code=404,
                detail="No enrolled face profile found for this faculty member. Register your face first."
            )

        highest_score = 0.0
        for stored in stored_rows:
            stored_vector = stored[0]
            if isinstance(stored_vector, str):
                stored_vector = json.loads(stored_vector)
            score = cosine_similarity(live_embedding, stored_vector)
            highest_score = max(highest_score, score)

        if highest_score < MATCH_THRESHOLD:
            raise HTTPException(
                status_code=401,
                detail=f"Face authentication rejected. Match confidence {round(highest_score, 4)} "
                       f"is below the required threshold."
            )

        db_college.execute(
            text("INSERT INTO verification_logs (event_type, status, message, transaction_id, visitor_id, created_at, timestamp) "
                 "VALUES (:ev, :st, :msg, :tx, :v_id, :t1, :t2)"),
            {
                "ev": "faculty_face_authentication",
                "st": "success",
                "msg": f"Faculty access granted. Vector match confidence: {round(highest_score, 4)}",
                "tx": str(uuid.uuid4()),
                "v_id": faculty.employee_id,
                "t1": datetime.utcnow(),
                "t2": datetime.utcnow()
            }
        )
        db_college.commit()

        return {
            "status": "Faculty Identity Verified. Live face authentication successful.",
            "employee_id": faculty.employee_id,
            "name": faculty.name,
            "department": faculty.department,
            "assigned_floor": faculty.assigned_floor,
            "face_match_score": highest_score,
            "is_revisit": True,
        }

    # New enrollment
    db_college.execute(
        text("INSERT INTO faculty_face_embeddings (faculty_id, face_embedding, face_image, captured_at, is_liveness_passed, aadhaar_match_score) "
             "VALUES (:fid, :emb, :img, :t, :live, :score)"),
        {
            "fid": faculty.id,
            "emb": json.dumps(live_embedding),
            "img": normalize_data_url(payload.front_image_base64),
            "t": datetime.utcnow(),
            "live": True,
            "score": 1.0
        }
    )
    db_college.commit()

    # Faculty logs belong in college.db, never the visitor database.
    db_college.execute(
        text("INSERT INTO verification_logs (event_type, status, message, transaction_id, visitor_id, created_at, timestamp) "
             "VALUES (:ev, :st, :msg, :tx, :v_id, :t1, :t2)"),
        {
            "ev": "faculty_face_registration",
            "st": "success",
            "msg": f"Faculty {faculty.name} face profile enrolled.",
            "tx": str(uuid.uuid4()),
            "v_id": faculty.employee_id,
            "t1": datetime.utcnow(),
            "t2": datetime.utcnow()
        }
    )
    db_college.commit()

    return {
        "status": "Faculty Face Profile Registered Successfully. Verification complete.",
        "employee_id": faculty.employee_id,
        "name": faculty.name,
        "department": faculty.department,
        "assigned_floor": faculty.assigned_floor,
        "face_match_score": 1.0,
        "is_revisit": False,
    }


@router.get("/faculty/{employee_id}/visitors")
def get_faculty_visitors(employee_id: str, db_visitor: Session = Depends(get_visitor_db), db_college: Session = Depends(get_college_db)):
    """For the faculty 'My Visitors' dashboard: lists their current/recent
    visitors with live presence details (arrival, wait time, exit, location)."""
    faculty = db_college.query(FacultyMaster).filter(FacultyMaster.employee_id == employee_id).first()
    if not faculty:
        raise HTTPException(status_code=404, detail="Faculty member not found.")

    two_hours_ago = datetime.utcnow() - timedelta(hours=2)
    sessions = db_visitor.query(VisitSession).filter(
        VisitSession.employee_to_meet == faculty.name,
        (VisitSession.status.in_(["active", "blocked"])) | (VisitSession.exit_time > two_hours_ago)
    ).order_by(VisitSession.id.desc()).all()

    results = []
    for session in sessions:
        logs = db_visitor.query(CameraTrackingLog).filter(CameraTrackingLog.session_id == session.id).order_by(CameraTrackingLog.timestamp.asc()).all()
        faculty_floor_logs = [log for log in logs if log.detected_floor == faculty.assigned_floor]

        arrival = faculty_floor_logs[0].timestamp if faculty_floor_logs else None
        last_seen = logs[-1].timestamp if logs else None
        last_seen_faculty_floor = faculty_floor_logs[-1].timestamp if faculty_floor_logs else None

        exited = session.status != 'active' or (last_seen and (datetime.utcnow() - last_seen).total_seconds() > 60)
        end_time = session.exit_time if session.exit_time else (last_seen_faculty_floor if exited and last_seen_faculty_floor else datetime.utcnow())
        wait_minutes = round((end_time - arrival).total_seconds() / 60, 1) if arrival else 0

        latest_log = logs[-1] if logs else None
        current_camera = _resolve_camera_node(latest_log.camera_id) if latest_log else None
        # "In the faculty room" when the visitor's current camera is that
        # faculty's dedicated room camera (matched by room_number, not string
        # suffix, so it's robust to spaces/renames).
        in_room = bool(
            current_camera
            and faculty.room_number
            and current_camera.get("room_number")
            and str(current_camera["room_number"]) == str(faculty.room_number)
        )

        results.append({
            "visitor_name": session.visitor.name, "visitor_id": session.visitor.visitor_id, "purpose_of_visit": session.purpose_of_visit,
            "status": session.status, "arrival": arrival, "wait_minutes": wait_minutes, "exited": exited, "exit_time": session.exit_time,
            "in_room": in_room, "current_camera_id": current_camera['camera_id'] if current_camera else None,
            "current_camera_label": current_camera['label'] if current_camera else "Not seen",
            "current_floor": current_camera['floor'] if current_camera else None,
            "stream_url": current_camera['stream_url'] if current_camera else None,
        })
    return results

# =====================================================================
# VISITOR SYSTEM REGISTRATION & IDENTITY VERIFICATION
# =====================================================================

@router.post("/aadhaar/start", response_model=AadhaarOtpStartResponse)
def aadhaar_start(
    payload: AadhaarOtpStartRequest,
    response: Response,
    db_visitor: Session = Depends(get_visitor_db),
    db_college: Session = Depends(get_college_db),
):
    from ..services.aadhaar_service import mask_aadhaar, start_aadhaar_otp
    masked = mask_aadhaar(payload.aadhaar_number)
    existing_aadhaar = db_visitor.query(AadhaarMaster).filter(AadhaarMaster.masked_aadhaar == masked).first()

    # Older E-KYC/faculty flows stored the shared Aadhaar record in the
    # college database. Import that verified identity into the visitor store
    # once so returning visitors do not need DigiLocker again and can use the
    # visitor face-registration foreign key safely.
    if not existing_aadhaar:
        legacy_aadhaar = db_college.query(AadhaarMaster).filter(
            AadhaarMaster.masked_aadhaar == masked
        ).first()
        if legacy_aadhaar:
            existing_aadhaar = AadhaarMaster(
                masked_aadhaar=legacy_aadhaar.masked_aadhaar,
                full_name=legacy_aadhaar.full_name,
                date_of_birth=legacy_aadhaar.date_of_birth,
                gender=legacy_aadhaar.gender,
                address=legacy_aadhaar.address,
                transaction_id=legacy_aadhaar.transaction_id,
                aadhaar_photo=legacy_aadhaar.aadhaar_photo,
                year_of_birth=legacy_aadhaar.year_of_birth,
                care_of=legacy_aadhaar.care_of,
                mobile_hash=legacy_aadhaar.mobile_hash,
                email_hash=legacy_aadhaar.email_hash,
                share_code=legacy_aadhaar.share_code,
                verification_timestamp=legacy_aadhaar.verification_timestamp,
            )
            db_visitor.add(existing_aadhaar)
            db_visitor.commit()
            db_visitor.refresh(existing_aadhaar)

    if existing_aadhaar:
        summary = AadhaarSummary(
            aadhaar_id=existing_aadhaar.id,
            masked_aadhaar=existing_aadhaar.masked_aadhaar,
            full_name=existing_aadhaar.full_name,
            date_of_birth=existing_aadhaar.date_of_birth,
            gender=existing_aadhaar.gender,
            address=existing_aadhaar.address,
            transaction_id=existing_aadhaar.transaction_id,
            aadhaar_photo=existing_aadhaar.aadhaar_photo,
            year_of_birth=existing_aadhaar.year_of_birth,
            care_of=existing_aadhaar.care_of,
            mobile_hash=existing_aadhaar.mobile_hash,
            email_hash=existing_aadhaar.email_hash,
            share_code=existing_aadhaar.share_code,
            verification_timestamp=existing_aadhaar.verification_timestamp,
        )
        return AadhaarOtpStartResponse(
            message="Existing Aadhaar record found. Switching to Revisit Face Scan Authentication mode.",
            pre_verified=True,
            aadhaar=summary,
        )

    try:
        flow_id, session_id, message, authorization_url = start_aadhaar_otp(payload.aadhaar_number)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return AadhaarOtpStartResponse(
        flow_id=flow_id,
        reference_id=session_id,
        authorization_url=authorization_url,
        message=message,
    )


@router.post("/aadhaar/verify", response_model=AadhaarOtpVerifyResponse)
def aadhaar_verify(payload: AadhaarOtpVerifyRequest, db_visitor: Session = Depends(get_visitor_db)):
    from ..services.aadhaar_service import verify_aadhaar_otp_and_upsert
    import time as _time

    # Same transient-error retry as the faculty flow: "Source Unavailable"
    # is an upstream Sandbox/UIDAI hiccup, not a bad OTP.
    aadhaar = None
    raw = None
    last_error = None
    for attempt in range(3):
        try:
            aadhaar, raw = verify_aadhaar_otp_and_upsert(db_visitor, payload.flow_id, payload.otp)
            break
        except ValueError as exc:
            last_error = str(exc)
            if "source unavailable" in last_error.lower() and attempt < 2:
                print(f"[!] Aadhaar provider returned 'Source Unavailable' "
                      f"(attempt {attempt + 1}/3) — retrying in 2s...")
                _time.sleep(2)
                continue
            break

    if aadhaar is None:
        if last_error and "source unavailable" in last_error.lower():
            raise HTTPException(
                status_code=503,
                detail="Aadhaar verification service (UIDAI source) is temporarily unavailable. "
                       "This is an upstream provider issue, not a problem with your OTP. "
                       "Please request a fresh OTP and retry."
            )
        raise HTTPException(status_code=400, detail=last_error or "OTP verification failed.")

    summary = AadhaarSummary(
        aadhaar_id=aadhaar.id,
        masked_aadhaar=aadhaar.masked_aadhaar,
        full_name=aadhaar.full_name,
        date_of_birth=aadhaar.date_of_birth,
        gender=aadhaar.gender,
        address=aadhaar.address,
        transaction_id=aadhaar.transaction_id,
        aadhaar_photo=aadhaar.aadhaar_photo,
        year_of_birth=aadhaar.year_of_birth,
        care_of=aadhaar.care_of,
        mobile_hash=aadhaar.mobile_hash,
        email_hash=aadhaar.email_hash,
        share_code=aadhaar.share_code,
        verification_timestamp=aadhaar.verification_timestamp,
    )
    return AadhaarOtpVerifyResponse(aadhaar=summary, raw_response=raw)


@router.post("/face/register", response_model=FaceRegistrationResponse)
def face_register(payload: FaceRegistrationRequest, db_visitor: Session = Depends(get_visitor_db)):
    aadhaar_model = db_visitor.get(AadhaarMaster, payload.aadhaar_id)
    if not aadhaar_model:
        raise HTTPException(status_code=404, detail="Aadhaar record not found for the given ID.")

    front_img = decode_base64_image(payload.front_image_base64)
    if not detect_single_face(front_img):
        raise HTTPException(status_code=400, detail="Face detection failed. Face must be visible and clear.")

    if not payload.is_revisit:
        if not liveness_passed(payload.blink_done, payload.turn_left_done, payload.turn_right_done):
            raise HTTPException(status_code=400, detail="Multi-angle liveness verification failed.")
    else:
        if not payload.blink_done:
            raise HTTPException(status_code=400, detail="Liveness check missing for authentication frame.")

    live_embedding = create_face_embedding(payload.front_image_base64)
    
    # Strictly fetch columns to avoid looking up unmapped metadata models parameters
    all_stored_embeddings = db_visitor.execute(text("SELECT id, visitor_id, face_embedding FROM face_embeddings")).fetchall()
    matched_visitor = None
    highest_score = 0.0
    MATCH_THRESHOLD = getattr(settings, "face_match_threshold", 0.88)

    for stored in all_stored_embeddings:
        stored_vector = stored[2]
        if isinstance(stored_vector, str):
            stored_vector = json.loads(stored_vector)

        score = cosine_similarity(live_embedding, stored_vector)
        if score > highest_score:
            highest_score = score
            if score >= MATCH_THRESHOLD:
                # Aligned query execution matching exact schema info parameters
                matched_visitor = db_visitor.execute(
                    text("SELECT id, visitor_id, name, dob, gender, address, mobile_number, email FROM visitor_master WHERE id = :v_id"), 
                    {"v_id": stored[1]}
                ).fetchone()

    if payload.is_revisit:
        if not matched_visitor:
            matched_visitor = db_visitor.execute(
                text("SELECT id, visitor_id, name, dob, gender, address, mobile_number, email FROM visitor_master WHERE aadhaar_id = :a_id"), 
                {"a_id": aadhaar_model.id}
            ).fetchone()

        if not matched_visitor:
            raise HTTPException(status_code=404, detail="Verification rejected. No profile matching this face found.")

        status_text = "Revisit Verified. Live face verification successful."
        
        # Safe transaction log save using text parameters matching exact columns layout mapping
        db_visitor.execute(
            text("INSERT INTO verification_logs (event_type, status, message, transaction_id, visitor_id, created_at, timestamp) "
                 "VALUES (:ev, :st, :msg, :tx, :v_id, :t1, :t2)"),
            {
                "ev": "revisit_face_authentication",
                "st": "success",
                "msg": f"Access Granted. Vector match confidence: {round(highest_score, 4)}",
                "tx": aadhaar_model.transaction_id,
                "v_id": matched_visitor[1],
                "t1": datetime.utcnow(),
                "t2": datetime.utcnow()
            }
        )
        db_visitor.commit()

        profile_data = {
            "name": matched_visitor[2],
            "date_of_birth": matched_visitor[3],
            "gender": matched_visitor[4],
            "mobile_number": matched_visitor[6] or "",
            "email": matched_visitor[7] or "",
        }

        return FaceRegistrationResponse(
            visitor_id=matched_visitor[1],
            face_match_score=highest_score,
            liveness_passed=True,
            status=status_text,
            is_revisit=True,
            auto_filled_profile=profile_data
        )

    status_text = "New Unique Face Profile Registered Successfully"
    visitor = get_or_create_visitor(
        db_visitor,
        aadhaar_id=aadhaar_model.id,
        name=aadhaar_model.full_name,
        dob=aadhaar_model.date_of_birth,
        gender=aadhaar_model.gender,
        address=aadhaar_model.address,
    )

    # Insert into face_embeddings using table columns schema info configuration maps
    db_visitor.execute(
        text("INSERT INTO face_embeddings (visitor_id, face_embedding, face_image, captured_at, is_liveness_passed, aadhaar_match_score) "
             "VALUES (:v_id, :emb, :img, :t, :live, :score)"),
        {
            "v_id": visitor.id,
            "emb": json.dumps(live_embedding),
            "img": normalize_data_url(payload.front_image_base64),
            "t": datetime.utcnow(),
            "live": True,
            "score": highest_score
        }
    )

    db_visitor.execute(
        text("INSERT INTO verification_logs (event_type, status, message, transaction_id, visitor_id, created_at, timestamp) "
             "VALUES (:ev, :st, :msg, :tx, :v_id, :t1, :t2)"),
        {
            "ev": "face_registration",
            "st": "success",
            "msg": status_text,
            "tx": aadhaar_model.transaction_id,
            "v_id": visitor.visitor_id,
            "t1": datetime.utcnow(),
            "t2": datetime.utcnow()
        }
    )
    db_visitor.commit()

    return FaceRegistrationResponse(
        visitor_id=visitor.visitor_id,
        face_match_score=highest_score,
        liveness_passed=True,
        status=status_text,
        is_revisit=False
    )


@router.post("/visitor/form", response_model=VisitorFormResponse)
def submit_visitor_form(
    payload: VisitorFormRequest,
    db_visitor: Session = Depends(get_visitor_db),
    db_college: Session = Depends(get_college_db),
):
    # Safe text query lookup mapping properties matching table info schema parameters
    row = db_visitor.execute(
        text("SELECT id FROM visitor_master WHERE visitor_id = :v_id"), 
        {"v_id": payload.visitor_id}
    ).fetchone()
    
    if not row:
        raise HTTPException(status_code=404, detail="Visitor profile record not found.")

    db_visitor.execute(
        text("UPDATE visitor_master SET mobile_number = :m, email = :e WHERE id = :idx"),
        {"m": payload.mobile_number, "e": payload.email, "idx": row[0]}
    )

    visitor_model = db_visitor.query(VisitorMaster).filter(VisitorMaster.id == row[0]).first()

    # Auto-close any stale active sessions for this visitor before starting a
    # new one, so surveillance matching never has more than one active
    # session (and therefore one target floor) to reconcile against.
    db_visitor.execute(
        text("UPDATE visit_sessions SET status = 'completed', exit_time = :t "
             "WHERE visitor_id = :v_id AND status = 'active'"),
        {"t": datetime.utcnow(), "v_id": visitor_model.id}
    )

    session, qr_pass = create_visit_session_with_qr(
        db=db_visitor,
        visitor=visitor_model,
        purpose_of_visit=payload.purpose_of_visit,
        department=payload.department,
        employee_to_meet=payload.employee_to_meet,
        expected_duration=payload.expected_duration,
        vehicle_number=payload.vehicle_number,
        grace_period_seconds=max(1, int(payload.grace_period_minutes)) * 60,
    )
    
    db_visitor.execute(
        text("INSERT INTO verification_logs (event_type, status, message, transaction_id, visitor_id, created_at, timestamp) "
             "VALUES (:ev, :st, :msg, :tx, :v_id, :t1, :t2)"),
        {
            "ev": "visit_session_create",
            "st": "success",
            "msg": "Visitor form submitted and pass generated.",
            "tx": str(uuid.uuid4()),
            "v_id": visitor_model.visitor_id,
            "t1": datetime.utcnow(),
            "t2": datetime.utcnow()
        }
    )
    db_visitor.commit()

    # NORMAL MESSAGE STAGE (per the project flow): as soon as the visitor
    # pass is generated, BOTH the visitor and the faculty host receive a
    # WhatsApp alert — the visitor gets their pass confirmation with the
    # target floor, and the faculty is informed that their visitor has
    # entered and is on the way.
    faculty_host = db_college.query(FacultyMaster).filter(
        FacultyMaster.name == payload.employee_to_meet
    ).first()
    target_floor = faculty_host.assigned_floor if faculty_host else session.assigned_floor

    notify_visitor_and_faculty(
        visitor_name=visitor_model.name,
        visitor_phone=payload.mobile_number or visitor_model.mobile_number,
        visitor_message=(
            f"✅ Visitor Pass Generated. Session: {session.session_id}. "
            f"You are meeting {payload.employee_to_meet} ({payload.department}) "
            f"on Floor {target_floor}"
            + (f", Room {faculty_host.room_number}" if faculty_host else "")
            + ". Please proceed directly to that floor. You are under campus camera tracking."
        ),
        faculty_name=faculty_host.name if faculty_host else payload.employee_to_meet,
        faculty_phone=faculty_host.phone_number if faculty_host else None,
        faculty_message=(
            f"🛂 Visitor Arrival: {visitor_model.name} has checked in at the entrance to meet "
            f"you. Purpose: {payload.purpose_of_visit}. Expected duration: "
            f"{payload.expected_duration}. They are being directed to Floor {target_floor}."
        ),
    )

    return VisitorFormResponse(
        session_id=session.session_id,
        pass_id=qr_pass.pass_id,
        qr_image_base64=qr_pass.qr_image_base64,
    )


@router.post("/session/close")
def close_visitor_session(session_id: str, db_visitor: Session = Depends(get_visitor_db)):
    row = db_visitor.execute(
        text("SELECT id FROM visit_sessions WHERE session_id = :sid"), 
        {"sid": session_id}
    ).fetchone()
    
    if not row:
        raise HTTPException(status_code=404, detail="Active check-in entry session not found.")

    # Realigned exit_time matching exact PRAGMA table_info definitions parameters
    db_visitor.execute(
        text("UPDATE visit_sessions SET status = 'completed', exit_time = :t WHERE id = :idx"),
        {"t": datetime.utcnow(), "idx": row[0]}
    )
    
    open_alerts = db_visitor.query(SecurityAlert).filter(
        SecurityAlert.session_id == row[0], 
        SecurityAlert.is_resolved == False
    ).all()
    for alert in open_alerts:
        alert.is_resolved = True

    db_visitor.commit()
    return {"status": "success", "msg": "Tracking loops closed. Session archived."}


# =====================================================================
# SURVEILLANCE TELEMETRY & CROSS-DATABASE ROUTING BREACH ENGINE
# =====================================================================

@router.post("/tracking/stream-reid")
def tracking_stream_reid(
    payload: CameraStreamPayload, 
    db_visitor: Session = Depends(get_visitor_db),
    db_college: Session = Depends(get_college_db)
):
    try:
        live_embedding = create_face_embedding(payload.frame_image_base64)
    except Exception:
        return {"identified": False, "msg": "No human profile extracted from surveillance frame"}

    # --- Faculty Location Tracking ---
    # In parallel to visitor matching, check if the face belongs to a faculty member.
    all_faculty_embeddings = db_college.execute(text("SELECT fm.employee_id, fm.name, ffe.face_embedding, fm.assigned_floor, fm.room_number FROM faculty_face_embeddings ffe JOIN faculty_master fm ON fm.id = ffe.faculty_id")).fetchall()
    FACULTY_MATCH_THRESHOLD = 0.88
    for fac_emb in all_faculty_embeddings:
        stored_vector = json.loads(fac_emb[2])
        score = cosine_similarity(live_embedding, stored_vector)
        if score >= FACULTY_MATCH_THRESHOLD:
            camera_node = _resolve_camera_node(payload.camera_id)
            if camera_node:
                _FACULTY_LOCATION[fac_emb[0]] = (
                    camera_node['floor'],
                    camera_node['room_number'],
                    datetime.utcnow()
                )
                print(f"[*] [FACULTY TRACKING] {fac_emb[1]} detected on Floor {camera_node['floor']}")
            break # Assume first match is correct


    all_stored = db_visitor.execute(text("SELECT visitor_id, face_embedding FROM face_embeddings")).fetchall()
    matched_visitor = None
    highest_score = 0.0
    MATCH_THRESHOLD = 0.88

    for stored in all_stored:
        stored_vector = stored[1]
        if isinstance(stored_vector, str):
            stored_vector = json.loads(stored_vector)

        score = cosine_similarity(live_embedding, stored_vector)
        if score > highest_score:
            highest_score = score
            if score >= MATCH_THRESHOLD:
                matched_visitor = db_visitor.query(VisitorMaster).filter(VisitorMaster.id == stored[0]).first()

    camera_node = _resolve_camera_node(payload.camera_id)
    authoritative_floor = camera_node['floor'] if camera_node else payload.current_floor

    if matched_visitor:
        active_session = db_visitor.query(VisitSession).filter(VisitSession.visitor_id == matched_visitor.id, VisitSession.status == "active").order_by(VisitSession.id.desc()).first()
        if active_session:
            log_key = (active_session.id, payload.camera_id)
            last_log_time = _LAST_TRACKING_LOG.get(log_key)
            if not last_log_time or (datetime.utcnow() - last_log_time).total_seconds() > TRACKING_LOG_MIN_INTERVAL_SECONDS:
                db_visitor.add(CameraTrackingLog(session_id=active_session.id, camera_id=payload.camera_id, detected_floor=authoritative_floor, tracking_confidence=highest_score))
                db_visitor.commit()
                _LAST_TRACKING_LOG[log_key] = datetime.utcnow()

    if not matched_visitor:
        return {"identified": False, "score": highest_score}

    # Multiple "active" sessions can pile up for the same visitor if a prior
    # session is never explicitly closed via /workflow/session/close. Without
    # an explicit ordering, .first() can return a stale, older session
    # instead of the one the visitor is actually on right now. Always take
    # the most recently created active session.
    active_session = db_visitor.query(VisitSession).filter(
        VisitSession.visitor_id == matched_visitor.id,
        VisitSession.status == "active"
    ).order_by(VisitSession.id.desc()).first()

    # If the visitor's most recent session was already blocked (detained by
    # security), don't treat them as "identified, no active session" —
    # surface it distinctly so the dashboard/edge device can react.
    if active_session is None:
        blocked_session = db_visitor.query(VisitSession).filter(
            VisitSession.visitor_id == matched_visitor.id,
            VisitSession.status == "blocked"
        ).order_by(VisitSession.id.desc()).first()
        if blocked_session:
            SURVEILLANCE_DASHBOARD_CACHE.append({
                "id": str(uuid.uuid4()),
                "name": matched_visitor.name,
                "visitor_id": matched_visitor.visitor_id,
                "camera_id": payload.camera_id,
                "current_floor": authoritative_floor,
                "target_floor": None,
                "confidence": float(highest_score),
                "alert_flag": True,
                "alert_message": "🚫 BLOCKED VISITOR DETECTED ON PREMISES.",
                "timestamp": datetime.utcnow().isoformat()
            })
            return {
                "identified": True,
                "visitor_id": matched_visitor.visitor_id,
                "name": matched_visitor.name,
                "current_floor": authoritative_floor,
                "target_floor": None,
                "floor_unauthorized_alert": True,
                "alert_details": "🚫 BLOCKED VISITOR DETECTED ON PREMISES."
            }

    alert_flag = False
    alert_message = "Authorized Clearance Area Path ✓"
    allowed_floor = None

    if active_session:
        faculty_host = db_college.query(FacultyMaster).filter(
            FacultyMaster.name == active_session.employee_to_meet
        ).first()

        allowed_floor = faculty_host.assigned_floor if faculty_host else active_session.assigned_floor
        session_key = active_session.id
        # Each visit carries its own "Grace Time for Visitor to return" window
        # (set on the visitor form). Fall back to the module default for older
        # sessions created before this column existed.
        grace_seconds = getattr(active_session, "grace_period_seconds", None) or WRONG_FLOOR_GRACE_SECONDS

        if authoritative_floor != allowed_floor:
            alert_flag = True
            now = datetime.utcnow()
            first_seen = _WRONG_FLOOR_FIRST_SEEN.get(session_key)

            if first_seen is None:
                # message stage. Per the flow, BOTH the visitor and the
                # faculty host receive a WhatsApp alert here — the visitor is
                # told to correct course, the faculty gets a heads-up. Grace
                # timer starts; no SecurityAlert yet.
                _WRONG_FLOOR_FIRST_SEEN[session_key] = now
                room_txt = f"Room {faculty_host.room_number}" if faculty_host and faculty_host.room_number else "the meeting room"
                alert_message = (
                    f"⚠️ Wrong Direction: You are on Floor {authoritative_floor}, "
                    f"expected on Floor {allowed_floor} ({room_txt}). Please head to the correct floor."
                )

                # If we've recently tracked the faculty host on a different floor
                # than their assigned one, tell the visitor where the host is now.
                faculty_location_msg = ""
                if faculty_host and faculty_host.employee_id in _FACULTY_LOCATION:
                    fac_floor, fac_room, _ = _FACULTY_LOCATION[faculty_host.employee_id]
                    if fac_floor != faculty_host.assigned_floor:
                        faculty_location_msg = f" Note: your host is currently on Floor {fac_floor}."

                notify_visitor_and_faculty(
                    visitor_name=matched_visitor.name,
                    visitor_phone=matched_visitor.mobile_number,
                    visitor_message=(
                        f"Wrong direction. You are on Floor {authoritative_floor}, "
                        f"but you must go to Floor {allowed_floor} ({room_txt}) to meet "
                        f"{active_session.employee_to_meet}. Please return within "
                        f"{grace_seconds} seconds.{faculty_location_msg}"
                    ),
                    faculty_name=faculty_host.name if faculty_host else active_session.employee_to_meet,
                    faculty_phone=faculty_host.phone_number if faculty_host else None,
                    faculty_message=(
                        f"ℹ️ Visitor Update: Your visitor {matched_visitor.name} was detected on "
                        f"Floor {authoritative_floor} instead of your floor "
                        f"(Floor {allowed_floor}, {room_txt}). They have been messaged to redirect. "
                        f"A grace period is now running."
                    ),
                )

            else:
                elapsed = (now - first_seen).total_seconds()

                if elapsed < grace_seconds:
                    # Still within the grace window — keep it low-key.
                    remaining = int(grace_seconds - elapsed)
                    alert_message = (
                        f"⏳ Still on Floor {authoritative_floor}, expected Floor {allowed_floor}. "
                        f"{remaining}s remaining to return before security is alerted."
                    )

                elif session_key not in _WRONG_FLOOR_ESCALATED:
                    # Grace period expired and they're still on the wrong floor:
                    # escalate — call the faculty host and raise a HIGH alert.
                    _WRONG_FLOOR_ESCALATED.add(session_key)
                    alert_message = (
                        f"🚨 WRONG FLOOR INTRUSION: Expected Floor {allowed_floor}, "
                        f"found on Floor {authoritative_floor} after grace period expired."
                    )

                    # DB-level dedupe: only raise ONE open alert per session. The
                    # in-memory guard above resets whenever the server reloads
                    # (uvicorn --reload on every code save), which otherwise
                    # spawns a fresh alert row on every camera frame. If an
                    # unresolved floor-violation alert already exists for this
                    # session, don't create another or re-notify.
                    existing_alert = db_visitor.query(SecurityAlert).filter(
                        SecurityAlert.session_id == active_session.id,
                        SecurityAlert.alert_type == "floor_violation",
                        SecurityAlert.is_resolved == False,
                    ).first()

                    if existing_alert is None:
                        # Escalation: BOTH parties are alerted again — the
                        # visitor gets a final urgent warning, the faculty host
                        # is asked to call the visitor (per the flow: "Message to
                        # person for calling to visitor") before security dispatch.
                        notify_visitor_and_faculty(
                            visitor_name=matched_visitor.name,
                            visitor_phone=matched_visitor.mobile_number,
                            visitor_message=(
                                f"🚨 FINAL SECURITY WARNING: You are still on Floor "
                                f"{authoritative_floor} after the grace period. Report to Floor "
                                f"{allowed_floor} (Room {faculty_host.room_number if faculty_host else 'N/A'}) immediately. Security has been alerted and "
                                f"{active_session.employee_to_meet} has been asked to contact you."
                            ),
                            faculty_name=faculty_host.name if faculty_host else active_session.employee_to_meet,
                            faculty_phone=faculty_host.phone_number if faculty_host else None,
                            faculty_message=(
                                f"🚨 Security Notice: Your expected visitor [{matched_visitor.name}] "
                                f"has breached area permissions and was detected on Floor "
                                f"{authoritative_floor} (expected Floor {allowed_floor}) after the "
                                f"grace period expired. Please call the visitor now. Security has "
                                f"been alerted."
                            ),
                        )

                        db_visitor.add(SecurityAlert(
                            session_id=active_session.id,
                            alert_priority="HIGH",
                            alert_type="floor_violation",
                            current_floor=authoritative_floor,
                            message=alert_message
                        ))
                        db_visitor.commit()
                else:
                    # Already escalated for this streak — keep flagging on the
                    # dashboard but don't re-notify faculty or duplicate alerts.
                    alert_message = (
                        f"🚨 Still on Floor {authoritative_floor} (expected Floor {allowed_floor}). "
                        f"Security has already been alerted."
                    )
        else:
            # Visitor is on (or has returned to) the correct floor — clear any
            # in-progress grace/escalation tracking for this session.
            _WRONG_FLOOR_FIRST_SEEN.pop(session_key, None)
            _WRONG_FLOOR_ESCALATED.discard(session_key)

    # Session context for the admin "Matched Visitor Record" panel. These come
    # from the active visit session (None if the visitor has no active session,
    # e.g. was just identified without checking in).
    department = active_session.department if active_session else None
    employee_to_meet = active_session.employee_to_meet if active_session else None
    purpose_of_visit = active_session.purpose_of_visit if active_session else None

    SURVEILLANCE_DASHBOARD_CACHE.append({
        "id": str(uuid.uuid4()),
        "name": matched_visitor.name,
        "visitor_id": matched_visitor.visitor_id,
        "camera_id": payload.camera_id,
        "current_floor": authoritative_floor,
        "target_floor": allowed_floor,
        "department": active_session.department if active_session else None,
        "employee_to_meet": active_session.employee_to_meet if active_session else None,
        "purpose_of_visit": active_session.purpose_of_visit if active_session else None,
        "confidence": float(highest_score),
        "alert_flag": alert_flag,
        "alert_message": alert_message,
        "timestamp": datetime.utcnow().isoformat()
    })

    return {
        "identified": True,
        "visitor_id": matched_visitor.visitor_id,
        "name": matched_visitor.name,
        "current_floor": authoritative_floor,
        "floor_unauthorized_alert": alert_flag,
        "alert_details": alert_message,
        "target_floor": allowed_floor,
        "department": active_session.department if active_session else None,
        "employee_to_meet": active_session.employee_to_meet if active_session else None,
        "purpose_of_visit": active_session.purpose_of_visit if active_session else None,
    }
