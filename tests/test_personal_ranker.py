import sqlite3

import pytest

from backend.services.learning import personal_ranker
from backend.schemas.moments import InterestingMoment
from backend.core.config import Settings


def test_feedback_count_ignores_render_events_and_deduplicates_clips(monkeypatch):
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.execute(
        """
        CREATE TABLE feedback (
            clip_id TEXT,
            moment_id TEXT,
            action TEXT,
            user_rating INTEGER
        )
        """
    )
    connection.executemany(
        "INSERT INTO feedback VALUES (?, ?, ?, ?)",
        [
            ("clip_a", "moment_a", "rendered", None),
            ("clip_a", "moment_a", "rendered", None),
            ("clip_a", "moment_a", "accept", None),
            ("clip_a", "moment_a", "reject", None),
            ("clip_b", "moment_b", "edited", 4),
        ],
    )
    monkeypatch.setattr(personal_ranker, "get_connection", lambda: connection)

    assert personal_ranker.feedback_count() == 2


def test_active_sklearn_prediction_drives_personal_score(monkeypatch):
    class FakeModel:
        classes_ = [0, 1]

        def predict_proba(self, rows):
            assert rows[0]["moment_type"] == "insight"
            return [[0.1, 0.9]]

    moment = InterestingMoment(
        id="moment", start=0, end=20, duration=20, text="A useful idea", summary="Summary",
        moment_type="insight", hook_text="Hook", base_score=50,
    )
    monkeypatch.setattr(personal_ranker.model_registry, "active_model", lambda: (FakeModel(), {"version": "test"}))

    ranked = personal_ranker.apply_personal_ranking([moment], Settings())

    assert ranked[0].personal_score == 90
    assert "local sklearn model prediction" in ranked[0].reason


def test_disabled_learning_uses_only_base_score(monkeypatch):
    moment = InterestingMoment(
        id="moment", start=0, end=20, duration=20, text="A useful idea", summary="Summary",
        moment_type="insight", hook_text="Hook", base_score=63, personal_score=99, final_score=99,
    )
    settings = Settings()
    settings.learning.enabled = False
    monkeypatch.setattr(
        personal_ranker.model_registry,
        "active_model",
        lambda: (_ for _ in ()).throw(AssertionError("disabled learning must not load a model")),
    )

    ranked = personal_ranker.apply_personal_ranking([moment], settings)

    assert ranked[0].personal_score == 63
    assert ranked[0].final_score == 63


def _moment(index=0, **changes):
    return InterestingMoment(
        id=f"moment_{index}", start=0, end=20, duration=20,
        text="A useful idea", summary="Summary", moment_type="insight", hook_text="Hook", base_score=50,
    ).model_copy(update=changes)


def test_inference_is_batched_and_repeated_ranking_keeps_one_explanation(monkeypatch):
    class BatchModel:
        classes_ = [1, 0]

        def __init__(self):
            self.calls = 0

        def predict_proba(self, rows):
            self.calls += 1
            assert len(rows) == 80
            return [[0.9, 0.1] for _ in rows]

    model = BatchModel()
    monkeypatch.setattr(personal_ranker.model_registry, "active_model", lambda: (model, {"version": "test"}))
    monkeypatch.setattr(personal_ranker.dataset, "labeled_training_rows", lambda: pytest.fail("valid model needs no feedback query"))
    moments = [_moment(index, reason="Content arc.") for index in range(80)]
    for _ in range(2):
        ranked = personal_ranker.apply_personal_ranking(moments, Settings())
    assert model.calls == 2
    assert all(moment.personal_score == 90 for moment in ranked)
    assert all(moment.reason.count(personal_ranker.MODEL_REASON) == 1 for moment in ranked)
    assert all(moment.reason.startswith("Content arc.") for moment in ranked)


@pytest.mark.parametrize("probabilities", [
    [[float("nan"), 0.7]], [[0.3, float("inf")]], [[0.2, 1.1]], [[0.1, 0.1]], [],
])
def test_invalid_prediction_falls_back_once_for_the_batch(monkeypatch, probabilities):
    class BrokenModel:
        classes_ = [0, 1]

        def predict_proba(self, rows):
            return probabilities

    reads = []
    monkeypatch.setattr(personal_ranker.model_registry, "active_model", lambda: (BrokenModel(), {}))
    monkeypatch.setattr(personal_ranker.dataset, "labeled_training_rows", lambda: reads.append(True) or [])
    ranked = personal_ranker.apply_personal_ranking([_moment(index) for index in range(3)], Settings())
    assert len(reads) == 1
    assert all(moment.personal_score == moment.base_score for moment in ranked)


def test_invalid_probability_does_not_discard_other_valid_predictions(monkeypatch):
    class PartlyValidModel:
        classes_ = [0, 1]

        def predict_proba(self, rows):
            return [[0.1, 0.9], [float("nan"), 0.3]]

    monkeypatch.setattr(personal_ranker.model_registry, "active_model", lambda: (PartlyValidModel(), {}))
    monkeypatch.setattr(personal_ranker.dataset, "labeled_training_rows", lambda: [])
    ranked = personal_ranker.apply_personal_ranking([_moment(0), _moment(1)], Settings())
    assert [moment.personal_score for moment in ranked] == [90, 50]


def test_online_numeric_preferences_are_invariant_to_feature_units():
    rows = [
        {"label": 1, "features": {"moment_type": "insight", "speaker_switches": 4}},
        {"label": 1, "features": {"moment_type": "insight", "speaker_switches": 8}},
        {"label": 0, "features": {"moment_type": "insight", "speaker_switches": 1}},
        {"label": 0, "features": {"moment_type": "insight", "speaker_switches": 2}},
    ]
    before = personal_ranker.online_preference_adjustment(_moment(speaker_switches=6), rows)
    for row in rows:
        row["features"]["speaker_switches"] *= 1000
    after = personal_ranker.online_preference_adjustment(_moment(speaker_switches=6000), rows)
    assert before > 0
    assert after == pytest.approx(before)


def test_empty_batch_needs_no_model_or_database(monkeypatch):
    monkeypatch.setattr(personal_ranker.model_registry, "active_model", lambda: pytest.fail("empty batch loaded model"))
    assert personal_ranker.apply_personal_ranking([], Settings()) == []


def test_database_failure_preserves_base_ranking(monkeypatch):
    def unavailable():
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(personal_ranker.model_registry, "active_model", lambda: None)
    monkeypatch.setattr(personal_ranker.dataset, "labeled_training_rows", unavailable)
    ranked = personal_ranker.apply_personal_ranking([_moment(base_score=64)], Settings())
    assert ranked[0].final_score == 64
