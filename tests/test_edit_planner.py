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
    assert "progress_bar" in types
    assert "micro_flash" in types
    assert "focus_frame" in types
    assert types.count("punch_zoom") <= 11


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
    assert all((right.start or 0) - (left.start or 0) >= 10 for left, right in zip(zooms, zooms[1:]))
