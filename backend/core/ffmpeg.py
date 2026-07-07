from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from backend.core.errors import AppError


def command_available(command: str) -> bool:
    return bool(shutil.which(command)) or Path(command).exists()


def run_command(argv: list[str], timeout: int | None = None) -> subprocess.CompletedProcess[str]:
    try:
        completed = subprocess.run(
            argv,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except FileNotFoundError as exc:
        raise AppError(f"{Path(argv[0]).name} not found") from exc
    except subprocess.TimeoutExpired as exc:
        raise AppError(f"{Path(argv[0]).name} timed out") from exc
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "command failed").strip()
        raise AppError(detail[-1200:])
    return completed


def ffprobe_json(ffprobe_path: str, video_path: Path) -> dict:
    argv = [
        ffprobe_path,
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        str(video_path),
    ]
    completed = run_command(argv, timeout=120)
    return json.loads(completed.stdout)
