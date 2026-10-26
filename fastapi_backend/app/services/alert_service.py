from __future__ import annotations
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
from ..models import VisitSession, SecurityAlert, VisitorMaster, AadhaarMaster

def evaluate_floor_clearance(db: Session, session: VisitSession, detected_floor: int, camera_id: str) -> dict:
    if session.assigned_floor == detected_floor:
        return {"status": "authorized", "alert_generated": False}

    existing_alert = db.query(SecurityAlert).filter(
        SecurityAlert.session_id == session.id,
        SecurityAlert.alert_type == "floor_violation",
        SecurityAlert.is_resolved == False
    ).first()

    if not existing_alert:
        new_warning = SecurityAlert(
            session_id=session.id,
            alert_priority="WARNING",
            alert_type="floor_violation",
            current_floor=detected_floor,
            message=f"Visitor stepped out on floor {detected_floor}. Dispatched automated re-routing paths."
        )
        db.add(new_warning)
        db.commit()
        return {"status": "warning_dispatched", "alert_generated": True}
    
    grace_limit = datetime.utcnow() - timedelta(minutes=3)
    if existing_alert.timestamp < grace_limit and existing_alert.alert_priority == "WARNING":
        existing_alert.alert_priority = "HIGH"
        existing_alert.message = f"CRITICAL SECURITY ESCALATION: Unauthorized Floor stay over grace duration limits."
        db.commit()
        return {"status": "security_dispatch_alert", "alert_generated": True}

    return {"status": "monitoring_escalation", "alert_generated": False}