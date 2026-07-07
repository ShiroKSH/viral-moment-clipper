from __future__ import annotations


def estimate_visual_energy(start: float, end: float) -> float:
    return min(100, 50 + ((start + end) % 9) * 2.5)
