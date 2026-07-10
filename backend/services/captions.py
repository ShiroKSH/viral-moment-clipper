from __future__ import annotations

import re
from pathlib import Path

from backend.schemas.clips import ClipCandidate
from backend.services.content_quality import repair_mojibake


BASE_HASHTAGS = ["#shorts", "#tiktok", "#reels"]


def _keywords(text: str) -> list[str]:
    words = [word.strip(".,!?;:()[]\"'").lower() for word in repair_mojibake(text).split()]
    return [word for word in words if len(word) > 5][:5]


def build_caption_text(clip: ClipCandidate) -> str:
    title = repair_mojibake(clip.suggested_title or clip.hook_text or "Interesting moment")
    description = repair_mojibake(clip.suggested_caption or clip.summary)
    tags = BASE_HASHTAGS + [f"#{re.sub(r'[^A-Za-zА-Яа-я0-9_]', '', word)}" for word in _keywords(clip.text)]
    tags = [tag for tag in tags if len(tag) > 1]
    return f"TITLE:\n{title}\n\nDESCRIPTION:\n{description}\n\nHASHTAGS:\n{' '.join(dict.fromkeys(tags))}\n"


def write_caption_file(clip: ClipCandidate, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(build_caption_text(clip), encoding="utf-8")
    return path
