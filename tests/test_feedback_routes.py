from backend.api import routes_feedback


def test_train_endpoint_reports_real_training_result(monkeypatch):
    monkeypatch.setattr(
        routes_feedback,
        "train_personal_ranker",
        lambda: {
            "trained": True,
            "training_ready": True,
            "active_ranker_version": "personal_ranker_test",
            "message": "Local sklearn ranker trained and activated.",
        },
    )
    monkeypatch.setattr(
        routes_feedback,
        "ranker_summary",
        lambda: {
            "feedback_count": 31,
            "active_ranker_version": "personal_ranker_test",
            "training_ready": True,
        },
    )

    response = routes_feedback.train_learning()

    assert response["ok"] is True
    assert response["trained"] is True
    assert response["training_ready"] is True
    assert "trained" in response["message"]
