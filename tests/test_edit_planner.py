from backend.core.config import Settings
from backend.schemas.clips import ClipCandidate
from backend.services.edit_planner import build_edit_plan


def _clip(duration: float = 35) -> ClipCandidate:
    return ClipCandidate(
        id="clip_001",
        moment_id="moment_001",
        start=10,
        end=10 + duration,
        duration=duration,
        final_score=90,
        moment_type="insight",
        hook_text="Почему это важно",
        summary="summary",
        reason="reason",
        text="Почему это важно для зрителя",
        suggested_title="Почему это важно",
        suggested_caption="caption",
    )


def test_edit_plan_generates_banger_dynamic_operations_without_overediting():
    settings = Settings()
    plan = build_edit_plan(_clip(), settings, profile="banger")
    types = [operation.type for operation in plan.operations]

    assert "trim" in types
    assert "progress_bar" not in types
    assert "micro_flash" not in types
    assert "focus_frame" not in types
    assert types.count("punch_zoom") <= 3
    assert any(operation.reason.startswith("hook") for operation in plan.operations if operation.type == "punch_zoom")


def test_edit_plan_respects_dynamic_disable_and_zoom_caps():
    settings = Settings()
    settings.dynamic_edit.enabled = False
    disabled = build_edit_plan(_clip(), settings, profile="banger")
    assert [operation.type for operation in disabled.operations] == ["trim"]

    settings = Settings()
    settings.dynamic_edit.max_punch_zoom_per_10_sec = 1
    settings.dynamic_edit.pattern_interrupt_every_sec = 10
    capped = build_edit_plan(_clip(), settings, profile="banger")
    zooms = [operation for operation in capped.operations if operation.type == "punch_zoom"]
    assert len(zooms) <= 3
    assert all((right.start or 0) - (left.start or 0) >= 4.4 for left, right in zip(zooms, zooms[1:]))


def test_clean_profile_records_distinct_grammar_without_generated_effects():
    plan = build_edit_plan(_clip(), Settings(), profile="clean", scene_cuts=[8.0, 16.0])

    assert plan.strategy == "clean_native_v1"
    assert plan.generated_effect_count == 0
    assert not any(operation.type in {"punch_zoom", "shot_motion", "evidence_stamp"} for operation in plan.operations)
