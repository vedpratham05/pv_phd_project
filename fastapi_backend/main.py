import os
import sys

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.workflow import router as workflow_router
from app.config import settings
# Updated: Import the dual engines instead of the old single engine string
from app.database import Base, visitor_engine, college_engine

# Initialize database schemas across both independent isolation layers
Base.metadata.create_all(bind=visitor_engine)
Base.metadata.create_all(bind=college_engine)

app = FastAPI(title=settings.app_name, version="1.0.0")

# Configure CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    return {"ok": True}


# Register Application Routers
app.include_router(workflow_router)