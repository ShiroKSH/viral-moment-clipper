from __future__ import annotations

from typing import Any

from backend.services.content_quality import quality_penalty


CATEGORICAL_FEATURES = ("moment_type",)
NUMERIC_FEATURES = (
    "duration",
    "word_count",
    "words_per_second",
    "semantic_interest_score",
    "hook_score",
    "clarity_score",
    "emotion_score",
    "novelty_score",
    "standalone_score",
    "retention_score",
    "speech_density_score",
    "audio_energy_score",
    "visual_energy_score",
    "speaker_count",
    "speaker_switches",
    "dialogue_score",
    "base_score",
    "quality_penalty",
    "starts_with_hook",
    "has_conflict",
    "has_story",
    "has_result",
    "is_ad_like",
    "is_generic_clip_text",
    "is_low_information",
)
FEATURE_NAMES = CATEGORICAL_FEATURES + NUMERIC_FEATURES


def _value(item: Any, name: str, default: Any = 0) -> Any:
    if isinstance(item, dict):
        return item.get(name, default)
    return getattr(item, name, default)


def extract_clip_features(clip: Any) -> dict[str, float | str | bool]:
    """Return stable, inference-safe features for a moment or clip candidate."""
    text = str(_value(clip, "text", "") or "")
    summary = str(_value(clip, "summary", "") or "")
    hook_text = str(_value(clip, "hook_text", "") or "")
    duration = float(_value(clip, "duration", 0) or 0)
    penalty, problems = quality_penalty(" ".join([text, summary, hook_text]))
    combined = " ".join([text, summary, hook_text]).lower()
    features: dict[str, float | str | bool] = {
        "moment_type": str(_value(clip, "moment_type", "unknown") or "unknown"),
        "duration": duration,
        "word_count": len(text.split()),
        "words_per_second": len(text.split()) / max(duration, 1),
        "semantic_interest_score": float(_value(clip, "semantic_interest_score", 0) or 0),
        "hook_score": float(_value(clip, "hook_score", 0) or 0),
        "clarity_score": float(_value(clip, "clarity_score", 0) or 0),
        "emotion_score": float(_value(clip, "emotion_score", 0) or 0),
        "novelty_score": float(_value(clip, "novelty_score", 0) or 0),
        "standalone_score": float(_value(clip, "standalone_score", 0) or 0),
        "retention_score": float(_value(clip, "retention_score", 0) or 0),
        "speech_density_score": float(_value(clip, "speech_density_score", 0) or 0),
        "audio_energy_score": float(_value(clip, "audio_energy_score", 0) or 0),
        "visual_energy_score": float(_value(clip, "visual_energy_score", 0) or 0),
        "speaker_count": float(_value(clip, "speaker_count", 0) or 0),
        "speaker_switches": float(_value(clip, "speaker_switches", 0) or 0),
        "dialogue_score": float(_value(clip, "dialogue_score", 0) or 0),
        "base_score": float(_value(clip, "base_score", 0) or 0),
        "quality_penalty": float(penalty),
        "starts_with_hook": bool(hook_text),
        "has_conflict": str(_value(clip, "moment_type", "")) == "controversial_take",
        "has_story": str(_value(clip, "moment_type", "")) == "personal_story",
        "has_result": any(term in combined for term in ("вывод", "результат", "итого", "result")),
        "is_ad_like": "ad or CTA language" in problems,
        "is_generic_clip_text": "generic clip-analysis text" in problems,
        "is_low_information": "low-information intro/outro" in problems,
    }
    return features


def feature_row(item: Any) -> dict[str, float | str]:
    features = extract_clip_features(item)
    return {name: features.get(name, 0) for name in FEATURE_NAMES}
