from collections import Counter

from backend.services.learning.personal_ranker import extract_rank_terms, ranker_mode, rejection_overlap_penalty


def test_personal_ranker_mode_changes_after_min_feedback():
    assert ranker_mode(29, min_feedback=30) == "rule_based"
    assert ranker_mode(30, min_feedback=30) == "trainable"


def test_rejection_overlap_penalty_uses_learned_terms():
    rejected = Counter({"промокод": 2, "ссылка": 1})

    assert "промокод" in extract_rank_terms("Этот промокод надо запомнить")
    assert rejection_overlap_penalty("Промокод и ссылка в описании", rejected) > 0
    assert rejection_overlap_penalty("Сильный вывод без рекламы", rejected) == 0
