from __future__ import annotations


def estimate_audio_energy(start: float, end: float) -> float:
    duration = max(1, end - start)
    return min(100, 45 + (duration % 11) * 3)
