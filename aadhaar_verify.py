import csv
import json
import os

import requests

# -------------------------------------------------------------
# CONFIGURATION
# Replace these strings with keys from your console dashboard
# -------------------------------------------------------------
CSV_CREDENTIALS_FILE = os.getenv(
    "SANDBOX_CREDENTIALS_FILE",
    "sbox_live_key.csv" if os.path.exists("sbox_live_key.csv") else "sbox_test_key.csv",
)
API_KEY = os.getenv("SANDBOX_API_KEY")
API_SECRET = os.getenv("SANDBOX_API_SECRET")
BASE_URL = os.getenv("SANDBOX_BASE_URL", "https://api.sandbox.co.in")


def is_valid_aadhaar_number(aadhaar_number):
    return len(aadhaar_number) == 12 and aadhaar_number.isdigit()


def is_valid_otp(otp):
    return len(otp) == 6 and otp.isdigit()


def load_credentials_from_csv(csv_path):
    try:
        with open(csv_path, newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            row = next(reader, None)
            if not row:
                return None, None
            return row.get("API Key"), row.get("API Secret")
    except FileNotFoundError:
        return None, None
    except Exception:
        return None, None


def validate_configuration():
    global API_KEY, API_SECRET, BASE_URL

    if not API_KEY or not API_SECRET:
        csv_api_key, csv_api_secret = load_credentials_from_csv(CSV_CREDENTIALS_FILE)
        API_KEY = API_KEY or csv_api_key
        API_SECRET = API_SECRET or csv_api_secret

    if not API_KEY or not API_SECRET or not BASE_URL:
        print("❌ Missing configuration: set SANDBOX_API_KEY, SANDBOX_API_SECRET, and SANDBOX_BASE_URL.")
        print(f"   Or place API Key/API Secret in {CSV_CREDENTIALS_FILE}.")
        return False

    print(f"[Config] Using credentials from: {CSV_CREDENTIALS_FILE}")
    print(f"[Config] Using base URL: {BASE_URL}")

    if not os.getenv("SANDBOX_BASE_URL"):
        if API_KEY.startswith("key_test_"):
            BASE_URL = "https://test-api.sandbox.co.in"
        elif API_KEY.startswith("key_live_"):
            BASE_URL = "https://api.sandbox.co.in"

    return True


def get_jwt_token():
    """Generates a temporary JWT access token using credentials."""
    url = f"{BASE_URL}/authenticate"
    headers = {
        "x-api-key": API_KEY,
        "x-api-secret": API_SECRET,
        "x-api-version": "1.0",
    }
    try:
        response = requests.post(url, headers=headers)
        response_json = response.json()
        return response_json.get("data", {}).get("access_token")
    except Exception as e:
        print(f"❌ Failed authentication handshake: {e}")
        return None


def trigger_aadhaar_otp(token, aadhaar_number):
    """
    Step 1: Triggers an official UIDAI OTP code message
    directly to the citizen's linked phone number.
    """
    url = f"{BASE_URL}/kyc/aadhaar/okyc/otp"
    headers = {
        "Authorization": token,
        "x-api-key": API_KEY,
        "x-api-version": "1.0",
        "Content-Type": "application/json",
    }
    payload = {
        "@entity": "in.co.sandbox.kyc.aadhaar.okyc.otp.request",
        "aadhaar_number": aadhaar_number,
        "consent": "y",
        "reason": "For KYC",
    }

    print("\n[System] Connecting to verification servers...")
    response = requests.post(url, headers=headers, json=payload)
    try:
        res_data = response.json()
    except Exception:
        res_data = {"message": response.text}

    if response.status_code == 200 and "data" in res_data:
        data = res_data["data"]
        reference_id = (
            data.get("reference_id")
            or data.get("referenceId")
            or data.get("referenceID")
            or res_data.get("reference_id")
            or res_data.get("referenceId")
        )
        if reference_id is not None:
            return reference_id

        message = str(data.get("message", "") or res_data.get("message", ""))
        if "try after 45 seconds" in message.lower():
            print("⏳ OTP was generated, but the provider asked to try after 45 seconds.")
            print("   Run the script again later; it will not wait or retry automatically.")
            return None

        print("❌ OTP response did not include a reference id.")
        print(f"   Details: {res_data}")
        return None

    if response.status_code == 403:
        print("❌ Access denied by the API provider.")
        print("   This usually means the key is valid but not enabled for this Aadhaar OTP/eKYC product or endpoint.")
        print("   Check the console to ensure this specific product is enabled for the current key.")
        print(f"   Details: {res_data}")
        return None

    if response.status_code == 503:
        print("❌ Source unavailable from the provider.")
        print("   The API endpoint or upstream Aadhaar source is temporarily down.")
        print(f"   Details: {res_data}")
        return None

    print(f"❌ Error dispatching message: {res_data}")
    return None


def verify_aadhaar_otp(token, reference_id, otp):
    """
    Step 2: Validates the incoming code to unlock official
    e-KYC profile fields (Name, Photo, Address).
    """
    url = f"{BASE_URL}/kyc/aadhaar/okyc/otp/verify"
    headers = {
        "Authorization": token,
        "x-api-key": API_KEY,
        "x-api-version": "1.0",
        "Content-Type": "application/json",
    }
    payload = {
        "@entity": "in.co.sandbox.kyc.aadhaar.okyc.request",
        "reference_id": str(reference_id),
        "otp": str(otp),
    }

    print("[System] Validating cryptographic signature details...")
    response = requests.post(url, headers=headers, json=payload)
    try:
        result = response.json()
    except Exception:
        result = {"message": response.text}

    if response.status_code == 400:
        print("❌ Invalid request body sent to verify endpoint.")
        print(f"   Details: {result}")

    return result
