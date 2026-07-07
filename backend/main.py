from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.api import routes_clips, routes_feedback, routes_health, routes_jobs, routes_projects, routes_settings
from backend.core.config import load_config
from backend.core.paths import ensure_runtime_dirs
from backend.db.database import init_db


def create_app() -> FastAPI:
    config = load_config()
    ensure_runtime_dirs(config)
    init_db()

    app = FastAPI(title="Viral Moment Clipper", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(routes_health.router)
    app.include_router(routes_settings.router)
    app.include_router(routes_projects.router)
    app.include_router(routes_jobs.router)
    app.include_router(routes_clips.router)
    app.include_router(routes_feedback.router)
    return app


app = create_app()
