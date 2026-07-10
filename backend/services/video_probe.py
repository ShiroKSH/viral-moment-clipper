from __future__ import annotations

import json
from fractions import Fraction
from pathlib import Path

from backend.core.config import Settings
from backend.core.ffmpeg import ffprobe_json
from backend.schemas.video import VideoMetadata


def _fps(value: str | None) -> float:
    if not value or value == "0/0":
        return 0
    try:
        return float(Fraction(value))
    except (ValueError, ZeroDivisionError):
        return 0


def _duration(value: object) -> float:
    try:
        return max(0.0, float(value or 0))
    except (TypeError, ValueError):
        return 0.0


def _primary_video_stream(streams: list[dict]) -> dict:
    return next(
        (
            stream
            for stream in streams
            if stream.get("codec_type") == "video" and not stream.get("disposition", {}).get("attached_pic")
        ),
        {},
    )


def playable_duration(raw: dict) -> float:
    streams = raw.get("streams", [])
    video = _primary_video_stream(streams)
    audio = next((stream for stream in streams if stream.get("codec_type") == "audio"), {})
    return _duration(video.get("duration")) or _duration(raw.get("format", {}).get("duration")) or _duration(audio.get("duration"))


def probe_video(path: Path, config: Settings) -> VideoMetadata:
    raw = ffprobe_json(config.paths.ffprobe_path, path)
    streams = raw.get("streams", [])
    video = _primary_video_stream(streams)
    audio = next((stream for stream in streams if stream.get("codec_type") == "audio"), {})
    return VideoMetadata(
        duration=playable_duration(raw),
        width=int(video.get("width") or 0),
        height=int(video.get("height") or 0),
        fps=_fps(video.get("avg_frame_rate") or video.get("r_frame_rate")),
        video_codec=video.get("codec_name") or "",
        audio_codec=audio.get("codec_name") or "",
        raw=raw,
    )


def metadata_json(metadata: VideoMetadata) -> str:
    return json.dumps(metadata.model_dump(), ensure_ascii=False)
