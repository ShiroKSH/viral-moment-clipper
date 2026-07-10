from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from backend.core.utils import write_json


CLIP_ID_RE = re.compile(r"clip_[A-Za-z0-9_-]+")


@dataclass
class ArchiveResult:
    archive_dir: Path | None = None
    moved_files: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _artifact_paths(output_dir: Path, clip_ids: list[str]) -> tuple[list[Path], list[str]]:
    paths = [
        output_dir / "source" / "analysis_report.json",
        output_dir / "source" / "candidate_selection.json",
    ]
    warnings: list[str] = []
    for clip_id in clip_ids:
        if not CLIP_ID_RE.fullmatch(clip_id):
            warnings.append(f"Skipped unsafe clip id: {clip_id!r}")
            continue
        paths.extend((output_dir / "clips").glob(f"{clip_id}_score_*.mp4"))
        paths.extend(
            [
                output_dir / "subtitles" / f"{clip_id}.srt",
                output_dir / "subtitles" / f"{clip_id}.ass",
                output_dir / "subtitles" / f"{clip_id}_speech.wav",
                output_dir / "subtitles" / f"{clip_id}_speech_transcript.json",
                output_dir / "metadata" / f"{clip_id}.json",
                output_dir / "metadata" / f"{clip_id}_edit_plan.json",
                output_dir / "metadata" / f"{clip_id}_render_integrity.json",
                output_dir / "metadata" / f"{clip_id}_caption.txt",
            ]
        )
    return sorted({path for path in paths if path.is_file()}), warnings


def archive_analysis_artifacts(output_dir: Path, clip_ids: list[str]) -> ArchiveResult:
    """Move the previous analysis generation aside without touching source media."""
    root = output_dir.resolve()
    sources, warnings = _artifact_paths(root, clip_ids)
    result = ArchiveResult(warnings=warnings)
    if not sources:
        return result

    generation = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S_%fZ")
    archive_dir = root / "archive" / generation
    result.archive_dir = archive_dir

    for source in sources:
        resolved = source.resolve()
        if root not in resolved.parents:
            result.warnings.append(f"Skipped artifact outside project output: {source}")
            continue
        relative = source.relative_to(root)
        destination = archive_dir / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            source.replace(destination)
            result.moved_files.append(relative.as_posix())
        except OSError as exc:
            result.warnings.append(f"Could not archive {relative.as_posix()}: {exc}")

    write_json(
        archive_dir / "manifest.json",
        {
            "archived_at": datetime.now(timezone.utc).isoformat(),
            "clip_ids": clip_ids,
            "moved_files": result.moved_files,
            "warnings": result.warnings,
        },
    )
    return result
