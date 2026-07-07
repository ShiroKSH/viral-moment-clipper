from __future__ import annotations

import re
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9._-]+")


def resolve_project_path(value: str | Path) -> Path:
    path = Path(value)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path.resolve()


def slugify(value: str, fallback: str = "project") -> str:
    cleaned = SAFE_NAME_RE.sub("-", value.strip()).strip(".-").lower()
    return cleaned[:80] or fallback


def ensure_runtime_dirs(config) -> None:
    for value in (config.paths.output_dir, config.paths.temp_dir, config.paths.models_dir):
        resolve_project_path(value).mkdir(parents=True, exist_ok=True)


def project_output_dir(config, project_name: str, project_id: str, custom_output_dir: str | None = None) -> Path:
    base = resolve_project_path(custom_output_dir or config.paths.output_dir)
    folder = base / f"{slugify(project_name)}-{project_id[:8]}"
    for child in ("clips", "subtitles", "metadata", "source"):
        (folder / child).mkdir(parents=True, exist_ok=True)
    return folder


def safe_upload_name(filename: str) -> str:
    name = Path(filename).name
    stem = slugify(Path(name).stem, "video")
    suffix = Path(name).suffix.lower()
    return f"{stem}{suffix}"
