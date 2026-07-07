from __future__ import annotations

from backend.schemas.clips import ClipCandidate
from backend.services.content_quality import quality_penalty


def extract_clip_features(clip: ClipCandidate) -> dict[str, float | str | bool]:
    words = clip.text.split()
    penalty, problems = quality_penalty(" ".join([clip.text, clip.summary, clip.hook_text]))
    return {
        "moment_type": clip.moment_type,
        "duration": clip.duration,
        "word_count": len(words),
        "words_per_second": len(words) / max(clip.duration, 1),
        "starts_with_hook": bool(clip.hook_text),
        "has_conflict": clip.moment_type == "controversial_take",
        "has_story": clip.moment_type == "personal_story",
        "has_result": "вывод" in clip.text.lower() or "результат" in clip.text.lower(),
        "quality_penalty": penalty,
        "is_ad_like": "ad or CTA language" in problems,
        "is_generic_clip_text": "generic clip-analysis text" in problems,
        "is_low_information": "low-information intro/outro" in problems,
    }
