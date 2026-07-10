import sqlite3

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
    monkeypatch.setattr(personal_ranker.training_service, "active_model", lambda: (FakeModel(), {"version": "test"}))

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
        personal_ranker.training_service,
        "active_model",
        lambda: (_ for _ in ()).throw(AssertionError("disabled learning must not load a model")),
    )

    ranked = personal_ranker.apply_personal_ranking([moment], settings)

    assert ranked[0].personal_score == 63
    assert ranked[0].final_score == 63
