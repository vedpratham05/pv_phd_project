from __future__ import annotations

import json
import os
import uuid
from typing import Any
import requests

from flask import Flask, jsonify, render_template, request

from datetime import datetime, timezone

import requests
from flask import Flask, jsonify, render_template, request


app = Flask(__name__, static_folder="static", template_folder="templates")
app.config["JSON_SORT_KEYS"] = False
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0

FLOW_STORE: dict[str, dict[str, Any]] = {}
FLOW_TTL_SECONDS = max(
    60,
    int(os.getenv("AADHAAR_FLOW_TTL_SECONDS", "600")),
)

# Target endpoint mapping to look up background processing components from the FastAPI engine
FASTAPI_BACKEND_URL = "http://127.0.0.1:8000/workflow"


def parse_profile_response(result: dict[str, Any], phone_number: str = "") -> dict[str, Any]:
    """
    Parses profile dictionary items dynamically, handling structural variations 
    between raw Sandbox Provider layouts and internal FastAPI models cleanly.
    """
    data = result.get("data", {}) if isinstance(result, dict) else {}
    
    # Adaptive check: If the dict is coming downstream from our local FastAPI database cache
    if "aadhaar" in result:
        data = result["aadhaar"]
        
    address_data = data.get("address", "")
    full_address = address_data if isinstance(address_data, str) else data.get("full_address", "")

    return {
        "reference_id": data.get("reference_id", data.get("transaction_id", "")),
        "status": data.get("status", "VALID"),
        "message": data.get("message", "Aadhaar profile loaded successfully."),
        "name": data.get("name", data.get("full_name", "")),
        "gender": data.get("gender", ""),
        "date_of_birth": data.get("date_of_birth", ""),
        "year_of_birth": data.get("year_of_birth", ""),
        "care_of": data.get("care_of", ""),
        "full_address": full_address,
        "mobile_hash": data.get("mobile_hash", ""),
        "aadhaar_photo": data.get("photo", data.get("aadhaar_photo", "")),
        "share_code": data.get("share_code", ""),
        "email_hash": data.get("email_hash", ""),
        "phone_number": phone_number or "Not returned by API",
        "address": full_address
    }


@app.get("/")
def index():
    """Explicitly uses Flask template loaders to prevent text streaming glitches inside browsers."""
    return render_template("index.html")


@app.post("/api/start")
def api_start():
    """Start Aadhaar OTP flow through FastAPI only (single source of truth)."""
    payload = request.get_json(silent=True) or {}
    aadhaar_number = str(payload.get("aadhaar_number", "")).strip()
    phone_number = str(payload.get("phone_number", "")).strip()

    if len(aadhaar_number) != 12 or not aadhaar_number.isdigit():
        return jsonify({"ok": False, "error": "Enter a valid 12-digit Aadhaar number."}), 400

    try:
        backend_response = requests.post(
            f"{FASTAPI_BACKEND_URL}/aadhaar/start",
            json={"aadhaar_number": aadhaar_number},
            timeout=30,
        )
    except requests.RequestException as exc:
        app.logger.error("FastAPI Aadhaar start request failed: %s", type(exc).__name__)
        return jsonify({"ok": False, "error": "Aadhaar verification service is unavailable. Please try again."}), 503

    try:
        backend_data = backend_response.json()
    except ValueError:
        backend_data = {}

    if not backend_response.ok:
        detail = backend_data.get("detail") or backend_data.get("message") or "Could not request OTP."
        return jsonify({"ok": False, "error": str(detail)}), backend_response.status_code

    if backend_data.get("pre_verified"):
        return jsonify({
            "ok": True,
            "pre_verified": True,
            "message": backend_data.get("message", "Existing Aadhaar record found. Continue with face authentication."),
            "aadhaar": backend_data.get("aadhaar"),
        })

    # This ID belongs to FastAPI's AadhaarFlowStore. Flask must not create a
    # separate Sandbox flow for the same OTP.
    flow_id = backend_data.get("flow_id")
    if not flow_id:
        return jsonify({"ok": False, "error": "The verification service did not return a flow ID. Please try again."}), 502

    FLOW_STORE[flow_id] = {
        "phone_number": phone_number,
        "created_at": datetime.now(timezone.utc).timestamp(),
    }
    return jsonify({
        "ok": True,
        "flow_id": flow_id,
        "message": backend_data.get("message", "OTP request processed."),
        "reference_id": backend_data.get("reference_id"),
        "authorization_url": backend_data.get("authorization_url"),
        "phone_number": phone_number,
    })


@app.post("/api/verify")
def api_verify():
    """Verify the OTP exactly once through the FastAPI flow that started it."""
    payload = request.get_json(silent=True) or {}
    flow_id = str(payload.get("flow_id", "")).strip()
    otp = str(payload.get("otp", "")).strip()

    if not flow_id or flow_id not in FLOW_STORE:
        return jsonify({"ok": False, "error": "This verification session is missing or expired. Request a new OTP."}), 400
    if len(otp) != 6 or not otp.isdigit():
        return jsonify({"ok": False, "error": "Enter a valid 6-digit OTP."}), 400

    flow = FLOW_STORE[flow_id]
    elapsed = datetime.now(timezone.utc).timestamp() - flow["created_at"]
    if elapsed > FLOW_TTL_SECONDS:
        FLOW_STORE.pop(flow_id, None)
        return jsonify({"ok": False, "error": "Your 10-minute verification session has expired. Request a new OTP."}), 400

    try:
        # Critical fix: do not verify directly with Sandbox and then submit the
        # same OTP to FastAPI a second time.
        sync_response = requests.post(
            f"{FASTAPI_BACKEND_URL}/aadhaar/verify",
            json={"flow_id": flow_id, "otp": otp},
            timeout=35,
        )
    except requests.RequestException as exc:
        app.logger.error("FastAPI Aadhaar verify request failed: %s", type(exc).__name__)
        return jsonify({"ok": False, "error": "Aadhaar verification service is temporarily unavailable. Please try again."}), 503

    try:
        result = sync_response.json()
    except ValueError:
        result = {}

    if not sync_response.ok:
        detail = result.get("detail") or result.get("message") or "Aadhaar verification failed."
        if sync_response.status_code != 503:
            FLOW_STORE.pop(flow_id, None)
        return jsonify({"ok": False, "error": str(detail)}), sync_response.status_code

    profile = parse_profile_response(result, flow.get("phone_number", ""))
    FLOW_STORE.pop(flow_id, None)
    return jsonify({"ok": True, "profile": profile, "raw": result})


# ---------------------------------------------------------------------
# ADMIN SECURITY OFFICE LOGIN PROXY PASSTHROUGH ROUTE
# ---------------------------------------------------------------------
@app.post("/workflow/admin/login")
def app_admin_login_proxy():
    try:
        payload = request.get_json(silent=True) or {}
        fastapi_login_route = f"{FASTAPI_BACKEND_URL}/admin/login"
        backend_response = requests.post(fastapi_login_route, json=payload, timeout=5)
        return jsonify(backend_response.json()), backend_response.status_code
    except Exception as e:
        return jsonify({"ok": False, "detail": f"College backend database offline: {e}"}), 502


@app.get("/health")
def health():
    return jsonify({"ok": True})


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)