from fastapi import APIRouter

from backend.core.config import load_config
from backend.core.ffmpeg import command_available

router = APIRouter(prefix="/api", tags=["health"])


@router.get("/health")
def health() -> dict:
    config = load_config()
    return {
        "ok": True,
        "app": "viral-moment-clipper",
        "ffmpeg": command_available(config.paths.ffmpeg_path),
        "ffprobe": command_available(config.paths.ffprobe_path),
    }
