from __future__ import annotations

from backend.core.config import Settings
from backend.schemas.clips import ClipCandidate
from backend.schemas.render import EditOperation, EditPlan
from backend.schemas.transcript import Transcript
from backend.services.dynamic_montage import montage_profile, plan_montage_beats, plan_semantic_accents, plan_shot_motion


GENERATED_EFFECT_TYPES = {
    "audio_accent",
    "evidence_stamp",
    "hook_title",
    "micro_flash",
    "progress_bar",
    "punch_zoom",
    "shot_motion",
}


def build_edit_plan(
    clip: ClipCandidate,
    config: Settings,
    profile: str | None = None,
    *,
    transcript: Transcript | None = None,
    scene_cuts: list[float] | None = None,
) -> EditPlan:
    active_profile = profile or clip.edit_profile or config.dynamic_edit.profile
    duration = max(1.0, clip.end - clip.start)
    operations: list[EditOperation] = [
        EditOperation(type="trim", start=clip.start, end=clip.end, reason="chosen clip boundaries")
    ]
    if not config.dynamic_edit.enabled:
        return EditPlan(clip_id=clip.id, profile=active_profile, strategy="disabled", operations=operations)

    cuts = sorted(cut for cut in (scene_cuts or []) if 0.08 < cut < duration - 0.4)
    operations.extend(
        EditOperation(
            type="source_cut",
            start=round(cut, 2),
            end=round(min(duration, cut + 0.04), 2),
            reason="existing shot change; suppress nearby generated effects",
        )
        for cut in cuts
    )

    if config.dynamic_edit.hook_title_enabled:
        operations.append(
            EditOperation(
                type="hook_title",
                start=0,
                end=min(2.5, duration),
                text=clip.suggested_title or clip.hook_text,
                reason="first seconds need a clear premise",
            )
        )

    semantic_visual_added = False
    if active_profile != "clean":
        for accent in plan_semantic_accents(clip, transcript, scene_cuts=cuts):
            if accent.text:
                operations.append(
                    EditOperation(
                        type="evidence_stamp",
                        start=accent.timestamp,
                        end=round(min(duration, accent.timestamp + accent.duration), 2),
                        text=accent.text,
                        reason=f"{accent.reason}; score={accent.score:.1f}",
                    )
                )
            if accent.kind in {"question", "reveal", "contrast"}:
                operations.append(
                    EditOperation(
                        type="audio_accent",
                        start=accent.timestamp,
                        end=round(min(duration, accent.timestamp + 0.18), 2),
                        text=accent.kind,
                        reason=f"single semantic sound cue; {accent.reason}",
                    )
                )
                if config.dynamic_edit.punch_zoom_enabled and not semantic_visual_added:
                    semantic_scale = min(1.045, max(1.032, montage_profile(active_profile).zoom_scale))
                    operations.append(
                        EditOperation(
                            type="punch_zoom",
                            start=accent.timestamp,
                            end=round(min(duration, accent.timestamp + 0.82), 2),
                            scale_from=1.0,
                            scale_to=round(semantic_scale, 3),
                            reason=f"paired semantic visual cue; {accent.reason}; score={accent.score:.1f}",
                        )
                    )
                    semantic_visual_added = True

    shot_motions = plan_shot_motion(clip, profile_name=active_profile, scene_cuts=cuts)
    operations.extend(
        EditOperation(
            type="shot_motion",
            start=motion.start,
            end=motion.end,
            scale_from=motion.scale_from,
            scale_to=motion.scale_to,
            reason=motion.reason,
        )
        for motion in shot_motions
    )

    if config.dynamic_edit.punch_zoom_enabled and not shot_motions and not semantic_visual_added:
        beats = plan_montage_beats(
            clip,
            config.dynamic_edit,
            profile_name=active_profile,
            transcript=transcript,
            scene_cuts=cuts,
        )
        for beat in beats:
            operations.append(
                EditOperation(
                    type="punch_zoom",
                    start=beat.timestamp,
                    end=round(min(duration, beat.timestamp + beat.duration), 2),
                    scale_from=1.0,
                    scale_to=beat.scale_to,
                    reason=f"{beat.reason}; score={beat.score:.1f}",
                )
            )
            if active_profile in {"gaming", "meme"} and beat.kind in {"question", "reveal"}:
                operations.append(
                    EditOperation(
                        type="micro_flash",
                        start=beat.timestamp,
                        end=round(min(duration, beat.timestamp + 0.10), 2),
                        reason=f"accent {beat.kind} beat",
                    )
                )

    if config.dynamic_edit.progress_bar_enabled:
        operations.append(EditOperation(type="progress_bar", start=0, end=duration, reason="show clip duration"))
    if config.dynamic_edit.audio_normalization_enabled:
        operations.append(EditOperation(type="audio_normalization", reason="normalize speech loudness"))
    generated_effect_count = sum(operation.type in GENERATED_EFFECT_TYPES for operation in operations)
    return EditPlan(
        clip_id=clip.id,
        profile=active_profile,
        strategy="clean_native_v1" if active_profile == "clean" else "semantic_tension_v1",
        natural_cut_count=len(cuts),
        generated_effect_count=generated_effect_count,
        operations=operations,
    )
