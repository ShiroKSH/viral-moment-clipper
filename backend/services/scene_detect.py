from __future__ import annotations

from pathlib import Path
import re

from backend.core.errors import AppError
from backend.core.ffmpeg import run_command


SHOWINFO_TIME_RE = re.compile(r"pts_time:([0-9]+(?:\.[0-9]+)?)")


def _parse_scene_times(stderr: str, duration: float) -> list[float]:
    cuts: list[float] = []
    for match in SHOWINFO_TIME_RE.finditer(stderr):
        timestamp = round(float(match.group(1)), 2)
        if timestamp <= 0.08 or timestamp >= duration - 0.4:
            continue
        if cuts and timestamp - cuts[-1] < 0.25:
            continue
        cuts.append(timestamp)
    return cuts


def _scene_command(
    ffmpeg_path: str,
    video_path: Path,
    start: float,
    duration: float,
    threshold: float,
    hwaccel: str | None,
) -> list[str]:
    argv = [ffmpeg_path, "-hide_banner", "-nostdin", "-loglevel", "info"]
    if hwaccel:
        argv.extend(["-hwaccel", hwaccel])
    argv.extend(
        [
            "-ss",
            f"{start:.3f}",
            "-t",
            f"{duration:.3f}",
            "-i",
            str(video_path),
            "-an",
            "-sn",
            "-vf",
            f"setpts=PTS-STARTPTS,select=gt(scene\\,{threshold:.3f}),showinfo",
            "-fps_mode",
            "vfr",
            "-f",
            "null",
            "-",
        ]
    )
    return argv


def detect_scene_cuts(
    video_path: Path,
    *,
    ffmpeg_path: str,
    start: float,
    duration: float,
    threshold: float = 0.10,
    hwaccel: str | None = "cuda",
) -> list[float]:
    if duration <= 1 or not video_path.exists():
        return []
    threshold = max(0.03, min(0.80, threshold))
    attempts = [hwaccel, None] if hwaccel else [None]
    for active_hwaccel in attempts:
        command = _scene_command(
            ffmpeg_path,
            video_path,
            start,
            duration,
            threshold,
            active_hwaccel,
        )
        try:
            completed = run_command(command, timeout=max(30, int(duration * 2 + 20)))
        except AppError:
            continue
        return _parse_scene_times(completed.stderr, duration)
    return []
