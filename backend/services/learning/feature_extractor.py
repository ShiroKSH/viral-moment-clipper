from __future__ import annotations

from typing import Any

from backend.schemas.learning import ClipFeatures
from backend.services.content_quality import quality_penalty


CATEGORICAL_FEATURES = ("moment_type",)
NUMERIC_FEATURES = tuple(name for name in ClipFeatures.model_fields if name not in CATEGORICAL_FEATURES)
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
    features = {name: _value(clip, name, 0) or 0 for name in NUMERIC_FEATURES}
    features.update({
        "moment_type": _value(clip, "moment_type", "unknown") or "unknown",
        "duration": duration,
        "word_count": len(text.split()),
        "words_per_second": len(text.split()) / max(duration, 1),
        "quality_penalty": float(penalty),
        "starts_with_hook": bool(hook_text),
        "has_conflict": str(_value(clip, "moment_type", "")) == "controversial_take",
        "has_story": str(_value(clip, "moment_type", "")) == "personal_story",
        "has_result": any(term in combined for term in ("вывод", "результат", "итого", "result")),
        "is_ad_like": "ad or CTA language" in problems,
        "is_generic_clip_text": "generic clip-analysis text" in problems,
        "is_low_information": "low-information intro/outro" in problems,
    })
    return ClipFeatures.model_validate(features).model_dump()


def feature_row(item: Any) -> dict[str, float | str]:
    features = extract_clip_features(item)
    return {name: str(features[name]) if name in CATEGORICAL_FEATURES else float(features[name]) for name in FEATURE_NAMES}
