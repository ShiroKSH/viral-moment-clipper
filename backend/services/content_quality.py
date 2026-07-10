from __future__ import annotations

import re

from backend.schemas.moments import InterestingMoment


PROMO_DISCLOSURE_PATTERNS = (
    "реклама",
    "спонсор",
    "партнер",
    "интеграция",
    "sponsor",
)

PROMO_CTA_PATTERNS = (
    "промокод",
    "ссылка в описании",
    "переходи по ссылке",
    "подпиш",
    "promo code",
    "subscribe",
    "скачивай ",
    "установи ",
    "регистрируйся",
    "зарегистрируйся",
    "попробуй бесплатно",
    "boosty",
    "бусти",
    "donate",
    "донат",
)

PROMO_OFFER_PATTERNS = (
    "скидк",
    "кэшбэк",
    "призовой фонд",
    "миллион рублей",
    "бесплатн",
    "discount",
)

PROMO_URGENCY_PATTERNS = (
    "успей до ",
    "только до ",
    "ограниченн",
    "пропадает с каждым",
    "потом эта штука исчезнет",
)

PROMO_CONTEXT_PATTERNS = (
    "в новом обновлении",
    "редкий легендарный дроп",
    "шанс получить",
    "одного из ста",
    "сражайся с ",
    "буст к скорости",
    "получи возможность",
    "в событии участвует",
    "событии также участвует",
    "начинай охоту",
)

LATIN_BRAND_RE = re.compile(r"\b[A-Z][A-Za-z0-9]+(?:\s+[A-Z][A-Za-z0-9]+)+\b")

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
    if not text:
        return text
    candidates = [text]
    for encoding in ("cp1251", "latin1"):
        try:
            candidates.append(text.encode(encoding).decode("utf-8"))
        except UnicodeError:
            pass
    return min(candidates, key=_mojibake_score)


def _mojibake_score(text: str) -> int:
    markers = (
        "Ð",
        "Ñ",
        "Рџ",
        "Рђ",
        "Р‘",
        "Р“",
        "Р”",
        "Р•",
        "Р°",
        "Р±",
        "РІ",
        "Рі",
        "Рґ",
        "Рµ",
        "Рё",
        "Р№",
        "Рє",
        "Р»",
        "Рј",
        "РЅ",
        "Рѕ",
        "Рї",
        "СЂ",
        "СЃ",
        "С‚",
        "Сѓ",
        "С„",
        "С…",
        "С†",
        "С‡",
        "С€",
        "С‹",
        "СЊ",
        "СЌ",
        "СЋ",
        "СЏ",
        "С‘",
        "Р¶",
        "Гђ",
        "Г‘",
    )
    return text.count("�") * 20 + sum(text.count(marker) * 3 for marker in markers)


def normalize_quality_text(text: str) -> str:
    return " ".join(repair_mojibake(text).lower().replace("ё", "е").split())


def commercial_evidence(text: str) -> set[str]:
    repaired = repair_mojibake(text)
    normalized = normalize_quality_text(repaired)
    evidence: set[str] = set()
    if any(pattern in normalized for pattern in PROMO_DISCLOSURE_PATTERNS):
        evidence.add("disclosure")
    if any(pattern in normalized for pattern in PROMO_CTA_PATTERNS) or (
        "ссыл" in normalized and "в описани" in normalized
    ):
        evidence.add("cta")
    if any(pattern in normalized for pattern in PROMO_OFFER_PATTERNS):
        evidence.add("offer")
    if any(pattern in normalized for pattern in PROMO_URGENCY_PATTERNS):
        evidence.add("urgency")
    if any(pattern in normalized for pattern in PROMO_CONTEXT_PATTERNS):
        evidence.add("context")
    if LATIN_BRAND_RE.search(repaired):
        evidence.add("brand")
    return evidence


def is_commercial_language(evidence: set[str]) -> bool:
    return bool(
        evidence & {"disclosure", "cta"}
        or {"offer", "urgency"}.issubset(evidence)
        or {"brand", "offer", "context"}.issubset(evidence)
    )


def quality_penalty(text: str) -> tuple[float, list[str]]:
    normalized = normalize_quality_text(text)
    if not normalized:
        return 35, ["empty text"]
    problems: list[str] = []
    penalty = 0.0
    commercial = commercial_evidence(text)
    generic_hits = [pattern for pattern in GENERIC_CLIP_PATTERNS if pattern in normalized]
    low_info_hits = [pattern for pattern in LOW_INFORMATION_PATTERNS if pattern in normalized]
    if is_commercial_language(commercial):
        penalty += min(70, 28 + len(commercial) * 12)
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
