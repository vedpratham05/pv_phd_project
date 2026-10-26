from datetime import datetime
from pydantic import BaseModel, Field

class AdminLoginRequest(BaseModel):
    username: str
    password: str

class AadhaarOtpStartRequest(BaseModel):
    aadhaar_number: str = Field(min_length=12, max_length=12)

class AadhaarSummary(BaseModel):
    aadhaar_id: int
    masked_aadhaar: str
    full_name: str
    date_of_birth: str
    gender: str
    address: str
    transaction_id: str
    aadhaar_photo: str | None = None
    year_of_birth: str | None = None
    care_of: str | None = None
    mobile_hash: str | None = None
    email_hash: str | None = None
    share_code: str | None = None
    verification_timestamp: datetime

class AadhaarOtpStartResponse(BaseModel):
    flow_id: str | None = None
    reference_id: str | None = None
    authorization_url: str | None = None
    message: str
    pre_verified: bool = False
    aadhaar: AadhaarSummary | None = None

class AadhaarOtpVerifyRequest(BaseModel):
    flow_id: str
    otp: str = Field(min_length=6, max_length=6)

class AadhaarOtpVerifyResponse(BaseModel):
    aadhaar: AadhaarSummary
    raw_response: dict

class FaceRegistrationRequest(BaseModel):
    aadhaar_id: int
    front_image_base64: str
    left_image_base64: str | None = None
    right_image_base64: str | None = None
    blink_done: bool = False
    turn_left_done: bool = False
    turn_right_done: bool = False
    is_revisit: bool = False

class FaceRegistrationResponse(BaseModel):
    visitor_id: str
    face_match_score: float
    liveness_passed: bool
    status: str
    is_revisit: bool = False
    auto_filled_profile: dict | None = None

class VisitorFormRequest(BaseModel):
    visitor_id: str
    mobile_number: str = ""
    email: str = ""
    purpose_of_visit: str
    department: str
    employee_to_meet: str
    expected_duration: str
    vehicle_number: str = ""
    grace_period_minutes: int = 10

class VisitorFormResponse(BaseModel):
    session_id: str
    pass_id: str
    qr_image_base64: str