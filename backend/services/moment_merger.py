from __future__ import annotations

from backend.schemas.moments import InterestingMoment


def _overlap_ratio(left: InterestingMoment, right: InterestingMoment) -> float:
    overlap = max(0.0, min(left.end, right.end) - max(left.start, right.start))
    return overlap / max(0.001, min(left.duration, right.duration))


def merge_overlapping_moments(moments: list[InterestingMoment], overlap_tolerance: float = 0.55) -> list[InterestingMoment]:
    if not moments:
        return []
    ordered = sorted(moments, key=lambda item: item.final_score, reverse=True)
    selected: list[InterestingMoment] = []
    for moment in ordered:
        if any(_overlap_ratio(moment, existing) >= overlap_tolerance for existing in selected):
            continue
        selected.append(moment)
    return selected
