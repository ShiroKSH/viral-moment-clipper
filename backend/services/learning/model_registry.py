from __future__ import annotations

from backend.services.learning.personal_ranker import ranker_summary


def active_model_summary() -> dict:
    return ranker_summary()
