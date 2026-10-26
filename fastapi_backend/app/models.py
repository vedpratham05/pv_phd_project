from __future__ import annotations
from datetime import datetime
from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from .database import Base

class AdminUser(Base):
    __tablename__ = "admin_users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(100), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    role = Column(String(50), default="security")

class FacultyMaster(Base):
    __tablename__ = "faculty_master"
    id = Column(Integer, primary_key=True, index=True)
    employee_id = Column(String(50), unique=True, nullable=False, index=True)
    name = Column(String(255), nullable=False)
    department = Column(String(255), nullable=False)
    phone_number = Column(String(20), nullable=False)
    room_number = Column(String(50), nullable=False)
    assigned_floor = Column(Integer, nullable=False)
    # Faculty verification (mirrors visitor Aadhaar flow). These columns are
    # auto-added by the startup migration in routers/workflow.py.
    masked_aadhaar = Column(String(12), nullable=True)
    is_verified = Column(Boolean, default=False)
    aadhaar_verified_at = Column(DateTime, nullable=True)

    face_embeddings = relationship("FacultyFaceEmbedding", back_populates="faculty")


class FacultyRegistration(Base):
    """Full faculty onboarding record in college.db — mirrors the identity
    fields kept for visitors (Aadhaar details included). Auto-created by
    the startup migration in routers/workflow.py."""
    __tablename__ = "faculty_registration"
    id = Column(Integer, primary_key=True, index=True)
    employee_id = Column(String(50), unique=True, nullable=False, index=True)
    name = Column(String(255), nullable=False)
    department = Column(String(255), nullable=False)
    phone_number = Column(String(20), nullable=False)
    room_number = Column(String(50), nullable=False)
    assigned_floor = Column(Integer, nullable=False)
    email = Column(String(255), nullable=True)
    designation = Column(String(255), nullable=True)
    masked_aadhaar = Column(String(12), nullable=True)
    full_name = Column(String(255), nullable=True)
    date_of_birth = Column(String(20), nullable=True)
    gender = Column(String(10), nullable=True)
    address = Column(Text, nullable=True)
    aadhaar_photo = Column(Text, nullable=True)
    is_aadhaar_verified = Column(Boolean, default=False)
    registered_at = Column(DateTime, default=datetime.utcnow)


class FacultyFaceEmbedding(Base):
    __tablename__ = "faculty_face_embeddings"
    id = Column(Integer, primary_key=True, index=True)
    faculty_id = Column(Integer, ForeignKey("faculty_master.id"), nullable=False)
    face_embedding = Column(Text, nullable=False)
    face_image = Column(Text, nullable=False)
    is_liveness_passed = Column(Boolean, default=True)
    aadhaar_match_score = Column(Float, default=0.0)
    captured_at = Column(DateTime, default=datetime.utcnow)
    faculty = relationship("FacultyMaster", back_populates="face_embeddings")

class AadhaarMaster(Base):
    __tablename__ = "aadhaar_master"
    id = Column(Integer, primary_key=True, index=True)
    masked_aadhaar = Column(String(12), unique=True, nullable=False, index=True)
    full_name = Column(String(255), nullable=False)
    date_of_birth = Column(String(50), nullable=False)
    gender = Column(String(20), nullable=False)
    address = Column(Text, nullable=False)
    transaction_id = Column(String(100), unique=True, nullable=False)
    aadhaar_photo = Column(Text, nullable=True)
    year_of_birth = Column(String(10), nullable=True)
    care_of = Column(String(255), nullable=True)
    mobile_hash = Column(String(255), nullable=True)
    email_hash = Column(String(255), nullable=True)
    share_code = Column(String(10), nullable=True)
    verification_timestamp = Column(DateTime, default=datetime.utcnow)
    visitor_profile = relationship("VisitorMaster", uselist=False, back_populates="aadhaar_ref")

class VisitorMaster(Base):
    __tablename__ = "visitor_master"
    id = Column(Integer, primary_key=True, index=True)
    visitor_id = Column(String(50), unique=True, nullable=False, index=True)
    aadhaar_id = Column(Integer, ForeignKey("aadhaar_master.id"), unique=True, nullable=False)
    name = Column(String(255), nullable=False)
    dob = Column(String(50), nullable=False)
    gender = Column(String(20), nullable=False)
    address = Column(Text, nullable=False)
    mobile_number = Column(String(20), nullable=True)
    email = Column(String(255), nullable=True)
    # created_at HATA DIYA GAYA HAI (DB schema match karne ke liye)

    aadhaar_ref = relationship("AadhaarMaster", back_populates="visitor_profile")
    face_embeddings = relationship("FaceEmbedding", back_populates="visitor")
    sessions = relationship("VisitSession", back_populates="visitor")

class FaceEmbedding(Base):
    __tablename__ = "face_embeddings"
    id = Column(Integer, primary_key=True, index=True)
    visitor_id = Column(Integer, ForeignKey("visitor_master.id"), nullable=False)
    face_embedding = Column(Text, nullable=False)
    face_image = Column(Text, nullable=False)
    is_liveness_passed = Column(Boolean, default=True)
    aadhaar_match_score = Column(Float, nullable=False)
    captured_at = Column(DateTime, default=datetime.utcnow)
    visitor = relationship("VisitorMaster", back_populates="face_embeddings")

class VisitSession(Base):
    __tablename__ = "visit_sessions"
    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(String(50), unique=True, nullable=False, index=True)
    visitor_id = Column(Integer, ForeignKey("visitor_master.id"), nullable=False)
    purpose_of_visit = Column(String(255), nullable=False)
    department = Column(String(255), nullable=False)
    employee_to_meet = Column(String(255), nullable=False)
    expected_duration_minutes = Column(Integer, nullable=False)
    vehicle_number = Column(String(50), nullable=True)
    assigned_floor = Column(Integer, nullable=False, default=0)
    grace_period_seconds = Column(Integer, nullable=False, default=60)
    status = Column(String(50), default="active")
    entry_time = Column(DateTime, default=datetime.utcnow)
    exit_time = Column(DateTime, nullable=True)

    visitor = relationship("VisitorMaster", back_populates="sessions")
    qr_pass = relationship("QrPass", uselist=False, back_populates="session")
    tracking_logs = relationship("CameraTrackingLog", back_populates="session")
    alerts = relationship("SecurityAlert", back_populates="session")

class QrPass(Base):
    __tablename__ = "qr_passes"
    
    id = Column(Integer, primary_key=True, index=True)
    pass_id = Column(String(50), unique=True, nullable=False)
    
    # DB schema ke mutabik column names:
    visitor_id = Column(Integer, ForeignKey("visitor_master.id"), nullable=False)
    visit_session_id = Column(Integer, ForeignKey("visit_sessions.id"), nullable=False) # Purana naam
    qr_payload = Column(Text, nullable=False) # Purana naam
    qr_image_base64 = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow) # Purana naam

    # Relationship ko map karein (taaki code break na ho)
    session = relationship("VisitSession", back_populates="qr_pass", foreign_keys=[visit_session_id])
    
class CameraTrackingLog(Base):
    __tablename__ = "camera_tracking_logs"
    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(Integer, ForeignKey("visit_sessions.id"), nullable=False)
    camera_id = Column(String(100), nullable=False)
    detected_floor = Column(Integer, nullable=False)
    tracking_confidence = Column(Float, nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow)
    session = relationship("VisitSession", back_populates="tracking_logs")

class SecurityAlert(Base):
    __tablename__ = "security_alerts"
    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(Integer, ForeignKey("visit_sessions.id"), nullable=False)
    alert_priority = Column(String(20), default="HIGH")
    alert_type = Column(String(100), nullable=False)
    current_floor = Column(Integer, nullable=False)
    message = Column(Text, nullable=False)
    is_resolved = Column(Boolean, default=False)
    # "Send Alert to Security" step tracking — auto-added by the startup
    # migration in routers/workflow.py.
    security_dispatched = Column(Boolean, default=False)
    dispatched_at = Column(DateTime, nullable=True)
    timestamp = Column(DateTime, default=datetime.utcnow)
    session = relationship("VisitSession", back_populates="alerts")

class VerificationLog(Base):
    __tablename__ = "verification_logs"
    id = Column(Integer, primary_key=True, index=True)
    event_type = Column(String(100), nullable=False)
    status = Column(String(50), nullable=False)
    message = Column(Text, nullable=False)
    transaction_id = Column(String(100), nullable=True)
    visitor_id = Column(String(50), nullable=True)
    timestamp = Column(DateTime, default=datetime.utcnow) 
    # created_at HATA DIYA GAYA HAI
