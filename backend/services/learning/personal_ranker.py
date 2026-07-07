from __future__ import annotations

from collections import Counter
import re

from backend.core.config import Settings
from backend.db.database import get_connection
from backend.schemas.moments import InterestingMoment
from backend.services.content_quality import repair_mojibake
from backend.services.viral_score import combine_personal_score


STOPWORDS = {
    "это",
    "как",
    "что",
    "для",
    "или",
    "уже",
    "еще",
    "там",
    "вот",
    "если",
    "потому",
    "когда",
    "можно",
    "нужно",
    "shorts",
    "tiktok",
    "reels",
}


def feedback_count() -> int:
    with get_connection() as connection:
        row = connection.execute("SELECT COUNT(*) AS count FROM feedback").fetchone()
    return int(row["count"] if row else 0)


def preferred_types() -> set[str]:
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT moments.moment_type
            FROM feedback
            JOIN moments ON moments.id = feedback.moment_id
            WHERE feedback.action = 'accept' OR feedback.user_rating >= 4
            """
        ).fetchall()
    counts = Counter(row["moment_type"] for row in rows)
    return {moment_type for moment_type, count in counts.items() if count >= 2}


def extract_rank_terms(text: str) -> set[str]:
    words = re.findall(r"[a-zа-я0-9]+", repair_mojibake(text).lower().replace("ё", "е"), flags=re.IGNORECASE)
    return {word for word in words if len(word) >= 4 and word not in STOPWORDS}


def rejected_terms() -> Counter[str]:
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT moments.text, moments.summary, moments.hook_text
            FROM feedback
            JOIN moments ON moments.id = feedback.moment_id
            WHERE feedback.action = 'reject' OR feedback.user_rating <= 2
            """
        ).fetchall()
    terms: Counter[str] = Counter()
    for row in rows:
        terms.update(extract_rank_terms(" ".join([row["text"] or "", row["summary"] or "", row["hook_text"] or ""])))
    return terms


def rejection_overlap_penalty(text: str, rejected: Counter[str]) -> float:
    if not rejected:
        return 0
    overlap = extract_rank_terms(text) & set(rejected)
    return min(18, sum(min(3, rejected[term]) for term in overlap) * 2)


def apply_personal_ranking(moments: list[InterestingMoment], config: Settings) -> list[InterestingMoment]:
    preferred = preferred_types()
    rejected = rejected_terms()
    for moment in moments:
        learned = moment.base_score
        if moment.moment_type in preferred:
            learned = min(100, learned + 8)
            moment.reason += " Personal ranking boost: similar accepted clips."
        penalty = rejection_overlap_penalty(" ".join([moment.text, moment.summary, moment.hook_text]), rejected)
        if penalty:
            learned = max(0, learned - penalty)
            if "similar to rejected clips" not in moment.problems:
                moment.problems.append("similar to rejected clips")
            moment.reason += f" Personal ranking penalty: -{penalty:.0f} for rejected-term overlap."
        moment.personal_score = learned
        moment.final_score = combine_personal_score(moment.base_score, learned, config.learning.personal_score_weight)
    return sorted(moments, key=lambda item: item.final_score, reverse=True)


def ranker_summary() -> dict:
    count = feedback_count()
    return {
        "feedback_count": count,
        "active_ranker_version": "rule_based_rejection_v002",
        "training_ready": ranker_mode(count) == "trainable",
        "preferred_types": sorted(preferred_types()),
        "rejected_terms": [term for term, _ in rejected_terms().most_common(12)],
    }


def ranker_mode(feedback_items: int, min_feedback: int = 30) -> str:
    return "trainable" if feedback_items >= min_feedback else "rule_based"
