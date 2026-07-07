from __future__ import annotations

from backend.core.config import Settings
from backend.schemas.clips import ClipCandidate
from backend.schemas.render import EditOperation, EditPlan
from backend.services.dynamic_montage import profile_limits


def build_edit_plan(clip: ClipCandidate, config: Settings, profile: str | None = None) -> EditPlan:
    active_profile = profile or clip.edit_profile or config.dynamic_edit.profile
    limits = profile_limits(active_profile)
    duration = max(1, clip.end - clip.start)
    operations: list[EditOperation] = [
        EditOperation(type="trim", start=clip.start, end=clip.end, reason="chosen clip boundaries")
    ]
    if not config.dynamic_edit.enabled:
        return EditPlan(clip_id=clip.id, profile=active_profile, operations=operations)
    if config.dynamic_edit.hook_title_enabled:
        operations.append(EditOperation(type="hook_title", start=0, end=min(2.5, duration), text=clip.suggested_title or clip.hook_text, reason="first seconds need a strong hook"))
    if config.dynamic_edit.punch_zoom_enabled and active_profile != "clean":
        zooms_per_10 = min(limits["zooms_per_10"], config.dynamic_edit.max_punch_zoom_per_10_sec)
        max_zooms = max(1, int(duration / 10 * zooms_per_10))
        cursor = min(1.0, duration / 4)
        for index in range(max_zooms):
            if cursor >= duration - 2:
                break
            operations.append(
                EditOperation(
                    type="punch_zoom",
                    start=round(cursor, 2),
                    end=round(min(cursor + 1.6, duration), 2),
                    scale_from=1.0,
                    scale_to=1.11 if active_profile in {"balanced", "podcast", "story"} else 1.16,
                    reason="pattern interrupt without overediting",
                )
            )
            if active_profile in {"aggressive", "gaming", "banger", "meme"}:
                operations.append(
                    EditOperation(
                        type="micro_flash",
                        start=round(cursor, 2),
                        end=round(min(cursor + 0.12, duration), 2),
                        reason="subtle visual beat without cutting quality",
                    )
                )
            if active_profile in {"banger", "gaming", "meme"} and index % 2 == 0:
                operations.append(
                    EditOperation(
                        type="focus_frame",
                        start=round(cursor, 2),
                        end=round(min(cursor + 0.55, duration), 2),
                        reason="short phone-safe focus accent",
                    )
                )
            cursor += max(1.0, config.dynamic_edit.pattern_interrupt_every_sec or limits["interrupt_sec"])
    if config.dynamic_edit.keyword_emphasis_enabled:
        operations.append(EditOperation(type="subtitle_emphasis", start=0, end=min(3.0, duration), reason="emphasize hook words"))
    if config.dynamic_edit.progress_bar_enabled:
        operations.append(EditOperation(type="progress_bar", start=0, end=duration, reason="show clip duration"))
    if config.dynamic_edit.audio_normalization_enabled:
        operations.append(EditOperation(type="audio_normalization", reason="normalize speech loudness"))
    return EditPlan(clip_id=clip.id, profile=active_profile, operations=operations)
