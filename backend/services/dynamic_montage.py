from __future__ import annotations


PROFILE_LIMITS = {
    "clean": {"zooms_per_10": 1, "interrupt_sec": 7.0},
    "balanced": {"zooms_per_10": 2, "interrupt_sec": 4.5},
    "aggressive": {"zooms_per_10": 4, "interrupt_sec": 3.5},
    "podcast": {"zooms_per_10": 1, "interrupt_sec": 8.0},
    "gaming": {"zooms_per_10": 4, "interrupt_sec": 3.5},
    "banger": {"zooms_per_10": 3, "interrupt_sec": 3.2},
    "story": {"zooms_per_10": 2, "interrupt_sec": 5.5},
    "meme": {"zooms_per_10": 4, "interrupt_sec": 2.8},
}


def profile_limits(profile: str) -> dict:
    return PROFILE_LIMITS.get(profile, PROFILE_LIMITS["balanced"])
