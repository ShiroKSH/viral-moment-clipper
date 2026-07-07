from __future__ import annotations

from backend.core.utils import clamp


WEIGHTS = {
    "semantic_interest_score": 0.18,
    "hook_score": 0.18,
    "clarity_score": 0.12,
    "emotion_score": 0.10,
    "novelty_score": 0.10,
    "standalone_score": 0.12,
    "retention_score": 0.12,
    "speech_density_score": 0.04,
    "audio_energy_score": 0.02,
    "visual_energy_score": 0.02,
}


def calculate_base_score(scores: dict[str, float]) -> float:
    total = sum(clamp(scores.get(key, 0), 0, 100) * weight for key, weight in WEIGHTS.items())
    return round(clamp(total, 0, 100), 2)


def combine_personal_score(base_score: float, learned_model_score: float, personal_weight: float = 0.35) -> float:
    personal_weight = clamp(personal_weight, 0, 1)
    return round(clamp(base_score * (1 - personal_weight) + learned_model_score * personal_weight, 0, 100), 2)
