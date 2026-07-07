from __future__ import annotations

from backend.schemas.moments import InterestingMoment


def merge_overlapping_moments(moments: list[InterestingMoment], overlap_tolerance: float = 8.0) -> list[InterestingMoment]:
    if not moments:
        return []
    ordered = sorted(moments, key=lambda item: (item.start, -item.final_score))
    merged: list[InterestingMoment] = []
    for moment in ordered:
        if not merged or moment.start > merged[-1].end - overlap_tolerance:
            merged.append(moment)
            continue
        current = merged[-1]
        if moment.final_score > current.final_score:
            moment.start = min(current.start, moment.start)
            moment.end = max(current.end, moment.end)
            moment.duration = round(moment.end - moment.start, 2)
            merged[-1] = moment
        else:
            current.end = max(current.end, moment.end)
            current.duration = round(current.end - current.start, 2)
    return sorted(merged, key=lambda item: item.final_score, reverse=True)
