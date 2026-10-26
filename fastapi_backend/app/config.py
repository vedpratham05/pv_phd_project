import os


class Settings:
    app_name: str = "AI Smart Visitor Backend"
    database_url: str = os.getenv(
        "DATABASE_URL",
        "sqlite:///./visitor_system.db",
    )
    aadhaar_similarity_threshold: float = float(os.getenv("AADHAAR_SIMILARITY_THRESHOLD", "0.72"))
    face_match_threshold: float = float(os.getenv("FACE_MATCH_THRESHOLD", "0.70"))


settings = Settings()
