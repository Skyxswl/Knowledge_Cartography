import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware

# Initialize database tables BEFORE importing routers that use models.
from backend.database import init_db
init_db()

from backend.api import nodes as nodes_router
from backend.api import experiment as experiment_router
from backend.api import sessions as sessions_router
from backend.api import turns as turns_router

app = FastAPI(title="ZoomMind Knowledge Graph API")


def _cors_origins() -> list[str]:
    configured = os.getenv("ZOOMMIND_CORS_ORIGINS", "")
    origins = [origin.strip() for origin in configured.split(",") if origin.strip()]
    if origins:
        return origins
    return [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


app.include_router(sessions_router.router)
app.include_router(turns_router.router)
app.include_router(nodes_router.router)
app.include_router(experiment_router.router)


FRONTEND_DIST = Path(__file__).resolve().parents[1] / "frontend" / "dist"


@app.get("/{full_path:path}", include_in_schema=False)
def serve_frontend(full_path: str):
    if full_path.startswith("api/"):
        raise HTTPException(status_code=404, detail="Not Found")
    if not FRONTEND_DIST.exists():
        return {"detail": "Frontend build not found"}

    requested_path = (FRONTEND_DIST / full_path).resolve()
    if FRONTEND_DIST in requested_path.parents and requested_path.is_file():
        return FileResponse(requested_path)
    return FileResponse(FRONTEND_DIST / "index.html")
