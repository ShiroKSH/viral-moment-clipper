from __future__ import annotations

import json
from urllib.parse import urlparse

import httpx

from backend.core.config import Settings
from backend.schemas.moments import InterestingMoment, SentenceSegment


def analyze_with_local_llm(sentences: list[SentenceSegment], config: Settings) -> list[InterestingMoment]:
    if not config.local_llm.enabled:
        return []
    parsed = urlparse(config.local_llm.base_url)
    if parsed.scheme not in {"http", "https"}:
        return []
    sample = "\n".join(f"{s.start:.1f}-{s.end:.1f}: {s.text}" for s in sentences[:20])
    payload = {
        "model": config.local_llm.model,
        "stream": False,
        "prompt": (
            "Return strict JSON array of potentially interesting short-video moments. "
            "Fields: start,end,summary,moment_type,hook_text,reason. Transcript:\n" + sample
        ),
    }
    try:
        response = httpx.post(f"{config.local_llm.base_url.rstrip('/')}/api/generate", json=payload, timeout=config.local_llm.timeout_sec)
        response.raise_for_status()
        text = response.json().get("response", "[]")
        raw = json.loads(text)
    except Exception:
        return []
    moments: list[InterestingMoment] = []
    for index, item in enumerate(raw if isinstance(raw, list) else [], start=1):
        try:
            start = float(item.get("start", 0))
            end = float(item.get("end", start + config.clips.preferred_duration_sec))
            moments.append(
                InterestingMoment(
                    id=f"llm_moment_{index:03}",
                    start=start,
                    end=end,
                    duration=end - start,
                    text="",
                    summary=str(item.get("summary", "")),
                    moment_type=str(item.get("moment_type", "insight")),
                    hook_text=str(item.get("hook_text", "")),
                    reason=str(item.get("reason", "Local LLM suggested this moment.")),
                    suggested_title=str(item.get("hook_text", ""))[:80],
                    suggested_caption=str(item.get("summary", "")),
                    semantic_interest_score=72,
                    hook_score=70,
                    clarity_score=65,
                    emotion_score=60,
                    novelty_score=60,
                    standalone_score=65,
                    retention_score=68,
                    speech_density_score=50,
                    audio_energy_score=50,
                    visual_energy_score=50,
                    base_score=66,
                    personal_score=66,
                    final_score=66,
                )
            )
        except (TypeError, ValueError):
            continue
    return moments
