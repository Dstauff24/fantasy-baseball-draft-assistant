import importlib
import traceback
from pathlib import Path
from types import SimpleNamespace
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.live_draft_routes import router as live_draft_router

app = FastAPI(title="Fantasy Baseball Draft Assistant API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_origin_regex=r"^https://.*\.(lovableproject\.com|lovable\.app)$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(live_draft_router)

@app.get("/health")
def health():
    return {"ok": True}