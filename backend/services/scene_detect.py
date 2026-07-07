from __future__ import annotations


def estimate_scene_changes(duration: float) -> int:
    return max(0, int(duration // 12))
