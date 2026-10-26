from __future__ import annotations

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
import datetime

# 1. Absolute Path matching your exact college_system.db location
COLLEGE_DATABASE_URL = "sqlite:////Users/prathamved/Downloads/pranali_mam_phd_pj/fastapi_backend/college_system.db"

engine = create_engine(
    COLLEGE_DATABASE_URL,
    connect_args={"check_same_thread": False}
)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)

def seed_administrative_credentials():
    db = SessionLocal()
    print("[*] Connecting to college_system.db to seed administrative controls...")
    
    try:
        # Create table if it doesn't exist natively
        db.execute(text("""
            CREATE TABLE IF NOT EXISTS admin_users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username VARCHAR(255) NOT NULL UNIQUE,
                password_hash VARCHAR(255) NOT NULL,
                role VARCHAR(50) NOT NULL
            );
        """))
        db.commit()

        # Check if the admin user already exists
        existing_admin = db.execute(
            text("SELECT id FROM admin_users WHERE username = :u"), 
            {"u": "admin"}
        ).fetchone()

        if not existing_admin:
            # Insert default credentials matching your login interface requirements
            db.execute(
                text("INSERT INTO admin_users (username, password_hash, role) VALUES (:u, :p, :r)"),
                {"u": "admin", "p": "password123", "r": "security_officer"}
            )
            db.commit()
            print("[SUCCESS] Admin account created successfully!")
            print(" -> Username: admin")
            print(" -> Password: password123")
        else:
            print("[INFO] Admin user already exists in the database table.")

        # Optional: Add a default faculty member for floor violation checking routines
        db.execute(text("""
            CREATE TABLE IF NOT EXISTS faculty_master (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name VARCHAR(255) NOT NULL,
                assigned_floor INTEGER NOT NULL,
                phone_number VARCHAR(20)
            );
        """))
        db.commit()

    except Exception as e:
        print(f"[ERROR] Seeding execution failed: {e}")
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    seed_administrative_credentials()