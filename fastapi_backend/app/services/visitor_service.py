from __future__ import annotations
import os
import uuid
from datetime import datetime
from sqlalchemy import text
from sqlalchemy.orm import Session
from twilio.rest import Client

from ..models import QrPass, VisitSession, VisitorMaster
from ..database import SessionLocalCollege
from .qr_service import generate_qr_base64

# Twilio Credentials
TWILIO_SID = os.getenv("TWILIO_ACCOUNT_SID", "")
TWILIO_TOKEN = os.getenv("TWILIO_AUTH_TOKEN", "")
TWILIO_WHATSAPP_NUMBER = os.getenv("TWILIO_WHATSAPP_FROM", "")

def send_notification_to_faculty(phone: str, message: str):
    """Sends simple text-based WhatsApp notification."""
    try:
        clean_phone = str(phone).replace('+', '').strip()
        if len(clean_phone) == 10: clean_phone = f"91{clean_phone}"
        formatted_phone = f"+{clean_phone}"

        client = Client(TWILIO_SID, TWILIO_TOKEN)
        client.messages.create(
            from_=TWILIO_WHATSAPP_NUMBER,
            body=message,
            to=f'whatsapp:{formatted_phone}'
        )
        print(f"[*] Notification sent to {formatted_phone}")
    except Exception as e:
        print(f"[*] Twilio Error: {e}")

def get_or_create_visitor(db: Session, aadhaar_id: int, name: str, dob: str, gender: str, address: str, phone: str = None, email: str = None) -> VisitorMaster:
    """Returns an existing visitor or creates a new one."""
    existing = db.query(VisitorMaster).filter(VisitorMaster.aadhaar_id == aadhaar_id).first()
    if existing: return existing
    
    count = db.execute(text("SELECT COUNT(id) FROM visitor_master")).scalar() or 0
    v_id = f"VIS-{datetime.utcnow().year}-{count + 1:06d}"
    
    visitor = VisitorMaster(
        visitor_id=v_id, aadhaar_id=aadhaar_id, name=name, 
        dob=dob, gender=gender, address=address,
        mobile_number=phone, email=email
    )
    db.add(visitor); db.commit(); db.refresh(visitor)
    return visitor

def create_visit_session_with_qr(
    db: Session, visitor: VisitorMaster, purpose_of_visit: str, department: str,
    employee_to_meet: str, expected_duration: str, vehicle_number: str,
    grace_period_seconds: int = 60
) -> tuple[VisitSession, QrPass]:

    with SessionLocalCollege() as db_college:
        faculty = db_college.execute(
            text("SELECT phone_number, assigned_floor FROM faculty_master WHERE name = :name"),
            {"name": employee_to_meet}
        ).fetchone()

    session = VisitSession(
        session_id=str(uuid.uuid4()),
        visitor_id=visitor.id,
        purpose_of_visit=purpose_of_visit,
        department=department,
        employee_to_meet=employee_to_meet,
        expected_duration_minutes=int(expected_duration) if str(expected_duration).isdigit() else 30,
        assigned_floor=faculty[1] if faculty else 0,
        grace_period_seconds=grace_period_seconds,
        vehicle_number=vehicle_number,
        status="active"
    )
    db.add(session); db.flush()
    
    if faculty:
        msg = (
            f"🔔 *New Visitor Alert*\n"
            f"👤 *Name:* {visitor.name}\n"
            f"📞 *Mobile:* {visitor.mobile_number or 'N/A'}\n"
            f"📧 *Email:* {visitor.email or 'N/A'}\n"
            f"🎯 *Purpose:* {purpose_of_visit}\n"
            f"🏢 *Floor:* {faculty[1]}"
        )
        send_notification_to_faculty(phone=str(faculty[0]), message=msg)

    payload = f"visitor_id={visitor.visitor_id};session_id={session.session_id};name={visitor.name}"
    qr_pass = QrPass(
        pass_id=str(uuid.uuid4()),
        visitor_id=visitor.id,
        visit_session_id=session.id, 
        qr_payload=payload,
        qr_image_base64=generate_qr_base64(payload)
    )
    
    db.add(qr_pass); db.commit()
    db.refresh(session); db.refresh(qr_pass)
    return session, qr_pass