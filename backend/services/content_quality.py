from __future__ import annotations

import re

from backend.schemas.moments import InterestingMoment


AD_OR_CTA_PATTERNS = (
    "реклама",
    "спонсор",
    "промокод",
    "скидк",
    "купить",
    "заказать",
    "магазин",
    "партнер",
    "интеграция",
    "ссылка в описании",
    "переходи по ссылке",
    "подпиш",
    "лайк",
    "колокольчик",
    "телеграм",
    "boosty",
    "бусти",
    "donate",
    "донат",
    "sponsor",
    "promo code",
    "discount",
    "subscribe",
)

GENERIC_CLIP_PATTERNS = (
    "в этом фрагменте есть",
    "можно превратить в короткий клип",
    "подходит для короткого вертикального ролика",
    "потенциально интересный момент",
    "сильный hook",
    "автор объясняет проблему простыми словами",
    "короткого клипа",
)

LOW_INFORMATION_PATTERNS = (
    "подписывайтесь на канал",
    "ставьте лайки",
    "приятного просмотра",
    "всем привет",
    "начинаем",
)

QUALITY_PROBLEMS = {
    "empty text",
    "ad or CTA language",
    "generic clip-analysis text",
    "low-information intro/outro",
    "too little speech",
    "repetitive speech",
}


def repair_mojibake(text: str) -> str:
    if "Ð" not in text and "Ñ" not in text:
        return text
    try:
        return text.encode("latin1").decode("utf-8")
    except UnicodeError:
        return text


def normalize_quality_text(text: str) -> str:
    return " ".join(repair_mojibake(text).lower().replace("ё", "е").split())


def quality_penalty(text: str) -> tuple[float, list[str]]:
    normalized = normalize_quality_text(text)
    if not normalized:
        return 35, ["empty text"]
    problems: list[str] = []
    penalty = 0.0
    ad_hits = [pattern for pattern in AD_OR_CTA_PATTERNS if pattern in normalized]
    generic_hits = [pattern for pattern in GENERIC_CLIP_PATTERNS if pattern in normalized]
    low_info_hits = [pattern for pattern in LOW_INFORMATION_PATTERNS if pattern in normalized]
    if ad_hits:
        penalty += min(70, 28 + len(ad_hits) * 12)
        problems.append("ad or CTA language")
    if generic_hits:
        penalty += min(60, 34 + len(generic_hits) * 8)
        problems.append("generic clip-analysis text")
    if low_info_hits:
        penalty += min(35, 15 + len(low_info_hits) * 8)
        problems.append("low-information intro/outro")
    words = re.findall(r"[a-zа-я0-9]+", normalized, flags=re.IGNORECASE)
    unique_ratio = len(set(words)) / max(1, len(words))
    if len(words) < 8:
        penalty += 12
        problems.append("too little speech")
    if len(words) >= 12 and unique_ratio < 0.45:
        penalty += 12
        problems.append("repetitive speech")
    return min(95, penalty), problems


def apply_quality_penalty(moment: InterestingMoment) -> InterestingMoment:
    if QUALITY_PROBLEMS & set(moment.problems):
        return moment
    text = " ".join(part for part in (moment.text, moment.summary, moment.hook_text) if part)
    penalty, problems = quality_penalty(text)
    if penalty <= 0:
        return moment
    moment.problems = [*moment.problems, *[problem for problem in problems if problem not in moment.problems]]
    moment.base_score = round(max(0, moment.base_score - penalty), 2)
    moment.personal_score = round(max(0, moment.personal_score - penalty), 2)
    moment.final_score = round(max(0, moment.final_score - penalty), 2)
    moment.reason += f" Quality penalty: -{penalty:.0f} for {', '.join(problems)}."
    return moment


def filter_quality_moments(moments: list[InterestingMoment], min_score: float, target_count: int) -> list[InterestingMoment]:
    filtered: list[InterestingMoment] = []
    for moment in moments:
        adjusted = apply_quality_penalty(moment)
        if adjusted.final_score >= min_score and "ad or CTA language" not in adjusted.problems:
            filtered.append(adjusted)
    return sorted(filtered, key=lambda item: item.final_score, reverse=True)[:target_count]
