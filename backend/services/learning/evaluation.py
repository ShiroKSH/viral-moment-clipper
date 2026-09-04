from __future__ import annotations

from typing import Any

import numpy as np
from sklearn.feature_extraction import DictVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import balanced_accuracy_score, brier_score_loss, log_loss, roc_auc_score
from sklearn.model_selection import StratifiedGroupKFold
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from backend.services.learning.dataset import sample_weights


MODEL_SPEC_VERSION = "personal_logistic_v2"


def build_model() -> Pipeline:
    return Pipeline([
        ("features", DictVectorizer(sparse=True)),
        ("scale", StandardScaler(with_mean=False)),
        ("classifier", LogisticRegression(C=1.0, max_iter=1000, random_state=42)),
    ])


def validation_splits(rows: list[dict[str, Any]]) -> list[tuple[np.ndarray, np.ndarray]]:
    if not rows or any(not row.get("project_id") for row in rows):
        return []
    labels = np.array([row["label"] for row in rows])
    groups = np.array([row["project_id"] for row in rows])
    class_groups = [len(set(groups[labels == label])) for label in (0, 1)]
    for count in range(min(5, *class_groups), 1, -1):
        splitter = StratifiedGroupKFold(n_splits=count, shuffle=True, random_state=42)
        splits = list(splitter.split(np.zeros(len(rows)), labels, groups))
        if all(len(set(labels[train])) == 2 for train, _ in splits):
            return splits
    return []


def evaluate_model(rows: list[dict[str, Any]], min_metrics: int) -> dict[str, Any]:
    splits = validation_splits(rows)
    if not splits:
        return {
            "status": "insufficient_projects",
            "passed": False,
            "folds": 0,
            "message": "Validation needs accepted and rejected clips across at least two source projects.",
        }
    labels = np.array([row["label"] for row in rows])
    probabilities = np.empty(len(rows))
    baseline = np.empty(len(rows))
    fold_reports = []
    for fold, (train, test) in enumerate(splits, start=1):
        training_rows = [rows[index] for index in train]
        weights, _ = sample_weights(training_rows, min_metrics)
        model = build_model()
        model.fit([row["features"] for row in training_rows], labels[train], classifier__sample_weight=weights)
        probabilities[test] = model.predict_proba([rows[index]["features"] for index in test])[:, 1]
        baseline[test] = labels[train].mean()
        fold_reports.append({
            "fold": fold,
            "training_rows": len(train),
            "validation_rows": len(test),
            "training_projects": sorted({rows[index]["project_id"] for index in train}),
            "validation_projects": sorted({rows[index]["project_id"] for index in test}),
        })
    brier = float(brier_score_loss(labels, probabilities))
    baseline_brier = float(brier_score_loss(labels, baseline))
    auc = float(roc_auc_score(labels, probabilities))
    passed = brier < baseline_brier - 1e-6 and auc > 0.5
    return {
        "status": "passed" if passed else "below_baseline",
        "passed": passed,
        "method": "stratified_group_kfold",
        "folds": len(splits),
        "validation_rows": len(rows),
        "balanced_accuracy": round(float(balanced_accuracy_score(labels, probabilities >= 0.5)), 4),
        "roc_auc": round(auc, 4),
        "brier_score": round(brier, 6),
        "baseline_brier_score": round(baseline_brier, 6),
        "log_loss": round(float(log_loss(labels, probabilities, labels=[0, 1])), 6),
        "fold_reports": fold_reports,
        "message": "Passed validation on held-out source projects." if passed else "Model did not beat the held-out class-prior baseline; online preferences remain active.",
    }
