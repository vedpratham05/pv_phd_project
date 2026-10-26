from __future__ import annotations

import csv
import logging
import os
import uuid

from datetime import datetime
from pathlib import Path
from typing import Any
import requests
from dotenv import load_dotenv
from sqlalchemy.orm import Session

from ..models import AadhaarMaster, VerificationLog


# Load credentials from fastapi_backend/.env
ENV_FILE = Path(__file__).resolve().parents[2] / ".env"
load_dotenv(ENV_FILE)


# ============================================================
# LOGGING
# ============================================================

logger = logging.getLogger(__name__)


# ============================================================
# IN-MEMORY OTP FLOW STORE
# ============================================================
# NOTE:
# This dictionary is cleared whenever the backend restarts.
# For production, use a shared store such as Redis with a TTL.

AadhaarFlowStore: dict[str, dict[str, Any]] = {}


# ============================================================
# SANDBOX CONFIGURATION
# ============================================================

API_KEY: str | None = os.getenv("SANDBOX_API_KEY")
API_SECRET: str | None = os.getenv("SANDBOX_API_SECRET")

BASE_URL: str = os.getenv(
    "SANDBOX_BASE_URL",
    "https://api.sandbox.co.in",
).rstrip("/")

# Keep this aligned with the version enabled for your Sandbox API.
# Default matches the current configuration shown in your console.
SANDBOX_API_VERSION: str = os.getenv("SANDBOX_API_VERSION", "1.0").strip()
AADHAAR_FLOW_TTL_SECONDS: int = max(
    60,
    int(os.getenv("AADHAAR_FLOW_TTL_SECONDS", "600")),
)
DIGILOCKER_REDIRECT_URL: str = os.getenv(
    "DIGILOCKER_REDIRECT_URL",
    "https://developer.sandbox.co.in/",
).strip()


# ============================================================
# CREDENTIAL FILE
# ============================================================

def _default_csv_path() -> Path:
    """
    Find the Sandbox credentials CSV file.

    Environment variable takes priority, followed by the
    project's live and test credential files.
    """

    env_path = os.getenv("SANDBOX_CREDENTIALS_FILE")

    if env_path:
        return Path(env_path).expanduser()

    local_live = Path("sbox_live_key.csv")

    if local_live.exists():
        return local_live

    parent_live = (
        Path(__file__).resolve().parents[3]
        / "sbox_live_key.csv"
    )

    if parent_live.exists():
        return parent_live

    return Path("sbox_test_key.csv")


def _load_credentials_from_csv(
    csv_path: Path,
) -> tuple[str | None, str | None]:
    """
    Read API credentials from a CSV file.

    Expected column names:
        API Key
        API Secret
    """

    try:
        with csv_path.open(
            newline="",
            encoding="utf-8-sig",
        ) as handle:

            reader = csv.DictReader(handle)
            row = next(reader, None)

            if not row:
                return None, None

            api_key = row.get("API Key")
            api_secret = row.get("API Secret")

            return (
                api_key.strip() if api_key else None,
                api_secret.strip() if api_secret else None,
            )

    except (OSError, csv.Error, UnicodeError) as exc:
        logger.warning(
            "Could not read Sandbox credentials CSV: %s",
            type(exc).__name__,
        )

        return None, None


# ============================================================
# CONFIGURATION VALIDATION
# ============================================================

def validate_configuration() -> bool:
    """
    Validate API credentials and select the appropriate
    Sandbox environment.

    Explicit SANDBOX_BASE_URL takes priority.
    """

    global API_KEY, API_SECRET, BASE_URL

    if not API_KEY or not API_SECRET:
        csv_key, csv_secret = _load_credentials_from_csv(
            _default_csv_path()
        )

        API_KEY = API_KEY or csv_key
        API_SECRET = API_SECRET or csv_secret

    if not API_KEY or not API_SECRET:
        logger.error(
            "Sandbox credentials are missing. Configure "
            "SANDBOX_API_KEY and SANDBOX_API_SECRET."
        )

        return False

    # Infer the environment only when BASE_URL was not
    # explicitly provided.
    if not os.getenv("SANDBOX_BASE_URL"):

        if API_KEY.startswith("key_test_"):
            BASE_URL = "https://test-api.sandbox.co.in"

        elif API_KEY.startswith("key_live_"):
            BASE_URL = "https://api.sandbox.co.in"

    BASE_URL = BASE_URL.rstrip("/")

    return True


# ============================================================
# RESPONSE HELPERS
# ============================================================

def _response_message(
    result: dict[str, Any],
) -> str:
    """
    Extract a readable message from common API response
    structures without assuming one fixed nesting level.
    """

    data = result.get("data")

    if isinstance(data, dict):
        for key in (
            "message",
            "error",
            "description",
        ):
            value = data.get(key)

            if value:
                return str(value)

    for key in (
        "message",
        "error",
        "description",
        "error_description",
    ):
        value = result.get(key)

        if value:
            return str(value)

    errors = result.get("errors")

    if errors:
        return str(errors)

    return "The Sandbox provider did not return a readable message."


def _provider_code(
    result: dict[str, Any],
) -> Any:
    """
    Extract the provider status code without assuming
    that it is always an integer.
    """

    return (
        result.get("code")
        or result.get("status_code")
        or result.get("status")
    )


def _is_provider_success(
    http_status: int,
    result: dict[str, Any],
) -> bool:
    """
    Detect a successful HTTP/API response.

    HTTP 2xx is necessary but not sufficient. An explicit
    provider error must never be treated as success.

    The exact provider response should be checked against
    the current Sandbox API documentation.
    """

    if not 200 <= http_status < 300:
        return False

    if result.get("error") or result.get("errors"):
        return False

    code = _provider_code(result)

    if code is not None:
        code_text = str(code).strip().lower()

        if code_text in {
            "400",
            "401",
            "403",
            "404",
            "422",
            "429",
            "500",
            "502",
            "503",
            "504",
            "error",
            "failed",
            "failure",
        }:
            return False

    return True


# ============================================================
# AUTHENTICATION
# ============================================================

def get_jwt_token() -> str | None:
    """
    Authenticate with Sandbox and obtain an access token.

    Never log the API key, API secret, or returned token.
    """

    if not validate_configuration():
        return None

    url = f"{BASE_URL}/authenticate"

    headers = {
        "x-api-key": API_KEY,
        "x-api-secret": API_SECRET,
        "x-api-version": SANDBOX_API_VERSION,
    }

    try:
        response = requests.post(
            url,
            headers=headers,
            timeout=30,
        )

        try:
            payload = response.json()

        except ValueError:
            logger.error(
                "Sandbox authentication returned non-JSON "
                "content. HTTP status: %s",
                response.status_code,
            )

            return None

        if not response.ok:
            logger.error(
                "Sandbox authentication failed. "
                "HTTP status: %s; provider message: %s",
                response.status_code,
                _response_message(payload),
            )

            return None

        data = payload.get("data", {})

        if not isinstance(data, dict):
            logger.error(
                "Unexpected Sandbox authentication response structure."
            )

            return None

        token = (
            data.get("access_token")
            or payload.get("access_token")
        )

        if not token:
            logger.error(
                "Sandbox authentication response did not contain "
                "an access token."
            )

            return None

        return str(token)

    except requests.RequestException as exc:
        logger.error(
            "Sandbox authentication request failed: %s",
            type(exc).__name__,
        )

        return None


def _digilocker_request(
    flow: dict[str, Any],
    method: str,
    path: str,
) -> dict[str, Any]:
    """Call a DigiLocker endpoint using the token stored for this flow."""

    response = requests.request(
        method,
        f"{BASE_URL}{path}",
        headers={
            "Authorization": flow["token"],
            "x-api-key": API_KEY,
            "x-api-version": SANDBOX_API_VERSION,
        },
        timeout=60,
    )
    try:
        result = response.json()
    except ValueError as exc:
        raise ValueError(
            "DigiLocker returned an invalid response. Please try again."
        ) from exc

    if not response.ok or not _is_provider_success(response.status_code, result):
        raise ValueError(
            f"DigiLocker verification request failed: {_response_message(result)}"
        )

    result["http_status"] = response.status_code
    return result


# ============================================================
# MASK AADHAAR NUMBER
# ============================================================

def mask_aadhaar(
    aadhaar_number: str,
) -> str:
    """
    Return a masked Aadhaar representation.

    Example:
        123456789012 -> XXXXXXXX9012
    """

    digits = "".join(
        character
        for character in str(aadhaar_number)
        if character.isdigit()
    )

    if len(digits) != 12:
        raise ValueError(
            "Aadhaar number must contain exactly 12 digits."
        )

    return f"XXXXXXXX{digits[-4:]}"


# ============================================================
# START OTP FLOW
# ============================================================

def start_aadhaar_otp(
    aadhaar_number: str,
) -> tuple[str, str, str, str]:
    """
    Start a DigiLocker consent session and create a local flow ID.

    The old Aadhaar OKYC OTP endpoints were discontinued by UIDAI/Sandbox.
    DigiLocker owns the OTP and consent UI, so this function returns the
    authorization URL instead of asking this application to collect an OTP.
    """

    digits = "".join(
        character
        for character in str(aadhaar_number)
        if character.isdigit()
    )

    if len(digits) != 12:
        raise ValueError(
            "Aadhaar number must contain exactly 12 digits."
        )

    if not validate_configuration():
        raise ValueError(
            "Sandbox configuration is incomplete. "
            "Check your API credentials and environment."
        )

    token = get_jwt_token()

    if not token:
        raise ValueError(
            "Could not authenticate with Sandbox. "
            "Check the API credentials and Sandbox environment."
        )

    url = f"{BASE_URL}/kyc/digilocker/sessions/init"
    headers = {
        "Authorization": token,
        "x-api-key": API_KEY,
        "x-api-version": SANDBOX_API_VERSION,
        "Content-Type": "application/json",
    }
    payload = {
        "@entity": "in.co.sandbox.kyc.digilocker.session.request",
        "flow": "signin",
        "redirect_url": DIGILOCKER_REDIRECT_URL,
        "doc_types": ["aadhaar"],
        "purpose": "Visitor Identity Verification",
        "requestor_name": "College Visitor Verification",
        "options": {
            "verification_method": ["aadhaar"],
            "pinless": True,
            "force_login": True,
        },
    }

    try:
        response = requests.post(url, headers=headers, json=payload, timeout=60)
        result = response.json()
    except (requests.RequestException, ValueError) as exc:
        logger.error("DigiLocker session request failed: %s", type(exc).__name__)
        raise ValueError(
            "Could not start DigiLocker verification. Please try again."
        ) from exc

    if not _is_provider_success(response.status_code, result):
        logger.error(
            "DigiLocker session request unsuccessful. HTTP status=%s; message=%s",
            response.status_code,
            _response_message(result),
        )
        raise ValueError(
            f"DigiLocker verification could not start: {_response_message(result)}"
        )

    data = result.get("data")
    if not isinstance(data, dict):
        raise ValueError("DigiLocker returned an invalid session response.")

    authorization_url = data.get("authorization_url")
    session_id = data.get("session_id")
    if not authorization_url or not session_id:
        raise ValueError("DigiLocker did not return a verification link.")

    flow_id = str(uuid.uuid4())

    AadhaarFlowStore[flow_id] = {
        "token": token,
        "session_id": str(session_id),
        "aadhaar_number": digits,
        "created_at": datetime.utcnow(),
    }

    return (
        flow_id,
        str(session_id),
        "Open DigiLocker, complete Aadhaar OTP consent, then click Verify DigiLocker.",
        str(authorization_url),
    )


# ============================================================
# VERIFY OTP AND SAVE AADHAAR RECORD
# ============================================================

def verify_aadhaar_otp_and_upsert(
    db: Session,
    flow_id: str,
    otp: str = "",
) -> tuple[AadhaarMaster, dict[str, Any]]:
    """
    Verify the OTP with Sandbox and insert/update the Aadhaar
    record in the database.

    The record is saved only after a recognized successful
    provider response and a valid identity payload.
    """

    flow = AadhaarFlowStore.get(flow_id)

    if not flow:
        raise ValueError(
            "Invalid or expired flow_id. Request a fresh OTP."
        )

    # Reject expired flows before contacting the provider. The provider can
    # expire its reference earlier, so provider-expired flows are also
    # consumed below and must be replaced with a new OTP request.
    created_at = flow.get("created_at")

    if isinstance(created_at, datetime):
        elapsed = (
            datetime.utcnow() - created_at
        ).total_seconds()

        if elapsed > AADHAAR_FLOW_TTL_SECONDS:
            AadhaarFlowStore.pop(flow_id, None)

            raise ValueError(
                "The OTP verification session has expired. "
                "Please request a fresh OTP."
            )

    status_result = _digilocker_request(
        flow,
        "GET",
        f"/kyc/digilocker/sessions/{flow['session_id']}/status",
    )
    status_data = status_result.get("data", {})
    status = status_data.get("status") if isinstance(status_data, dict) else None

    if status != "succeeded":
        if status in {"failed", "expired"}:
            AadhaarFlowStore.pop(flow_id, None)
        raise ValueError(
            "DigiLocker consent is not complete. Open the DigiLocker link, "
            "finish Aadhaar OTP verification and consent, then try again."
        )

    result = _digilocker_request(
        flow,
        "GET",
        f"/kyc/digilocker/sessions/{flow['session_id']}/user/profile",
    )

    if not isinstance(result, dict):
        raise ValueError(
            "The Aadhaar provider returned an invalid response."
        )

    data = result.get("data", {})

    if not isinstance(data, dict):
        data = {}

    provider_message = _response_message(result)
    message_lower = provider_message.strip().lower()

    http_status = result.get("http_status", 200)

    if http_status is None:
        # Some callers or test doubles may not provide this field.
        # In that case, rely on the provider response structure.
        http_status = 200

    if not 200 <= int(http_status) < 300:
        raise ValueError(
            f"Aadhaar verification service returned HTTP "
            f"{http_status}: {provider_message}"
        )

    # Explicit provider errors must not be treated as success.
    if result.get("error") or result.get("errors"):
        raise ValueError(
            f"Aadhaar verification failed: {provider_message}"
        )

    provider_code = _provider_code(result)

    if provider_code is not None:
        code_text = str(provider_code).strip().lower()

        if code_text not in {
            "200",
            "success",
            "ok",
        }:
            raise ValueError(
                f"Aadhaar verification failed: {provider_message}"
            )

    full_name = (
        data.get("name")
        or data.get("full_name")
    )

    if not full_name:
        raise ValueError(
            "The provider reported success but did not return "
            "the expected identity details. Check the provider "
            "response structure before retrying."
        )

    # Obtain the masked Aadhaar using the number stored in the
    # original OTP flow, not an untrusted request field.
    masked = mask_aadhaar(
        flow["aadhaar_number"]
    )

    existing = (
        db.query(AadhaarMaster)
        .filter(
            AadhaarMaster.masked_aadhaar == masked
        )
        .first()
    )

    full_address = (
        data.get("full_address")
        or data.get("address")
        or ""
    )

    date_of_birth = data.get("date_of_birth") or ""
    if isinstance(date_of_birth, (int, float)):
        date_of_birth = datetime.fromtimestamp(
            date_of_birth / 1000,
        ).strftime("%Y-%m-%d")

    transaction_id = (
        result.get("transaction_id")
        or data.get("transaction_id")
        or str(uuid.uuid4())
    )

    now = datetime.utcnow()

    if existing:
        existing.full_name = full_name

        existing.date_of_birth = (
            date_of_birth
            or existing.date_of_birth
        )

        existing.gender = (
            data.get("gender")
            or existing.gender
        )

        existing.address = (
            full_address
            or existing.address
        )

        existing.aadhaar_photo = (
            data.get("photo")
            or existing.aadhaar_photo
        )

        existing.transaction_id = transaction_id

        existing.year_of_birth = (
            data.get("year_of_birth")
            or existing.year_of_birth
        )

        existing.care_of = (
            data.get("care_of")
            or existing.care_of
        )

        existing.mobile_hash = (
            data.get("mobile_hash")
            or existing.mobile_hash
        )

        existing.email_hash = (
            data.get("email_hash")
            or existing.email_hash
        )

        existing.share_code = (
            data.get("share_code")
            or existing.share_code
        )

        existing.verification_timestamp = now

        aadhaar = existing

    else:
        aadhaar = AadhaarMaster(
            masked_aadhaar=masked,
            full_name=full_name,
            date_of_birth=date_of_birth,
            gender=data.get("gender") or "",
            address=full_address,
            aadhaar_photo=data.get("photo") or "",
            transaction_id=transaction_id,
            year_of_birth=data.get("year_of_birth") or "",
            care_of=data.get("care_of") or "",
            mobile_hash=data.get("mobile_hash") or "",
            email_hash=data.get("email_hash") or "",
            share_code=data.get("share_code") or "",
            verification_timestamp=now,
        )

        db.add(aadhaar)

    db.add(
        VerificationLog(
            event_type="aadhaar_verify",
            status="success",
            message="Aadhaar OTP verification successful.",
            transaction_id=transaction_id,
        )
    )

    try:
        db.commit()
        db.refresh(aadhaar)

    except Exception:
        db.rollback()

        logger.exception(
            "Database error while saving Aadhaar verification."
        )

        raise ValueError(
            "Aadhaar verification succeeded, but the database "
            "could not save the record. Check the database logs."
        )

    # Consume the flow only after successful database persistence.
    AadhaarFlowStore.pop(flow_id, None)

    return aadhaar, result