from fastapi import APIRouter, HTTPException

from backend.schemas.clips import ClipUpdate
from backend.schemas.feedback import FeedbackRequest
from backend.services import project_store
from backend.services.learning.feedback_store import store_feedback

router = APIRouter(prefix="/api/projects/{project_id}/clips", tags=["clips"])


@router.get("")
def list_project_clips(project_id: str) -> list[dict]:
    return [clip.model_dump() for clip in project_store.list_clips(project_id)]


@router.patch("/{clip_id}")
def patch_clip(project_id: str, clip_id: str, payload: ClipUpdate) -> dict:
    old_clip = project_store.get_clip(project_id, clip_id)
    clip = project_store.update_clip(
        project_id,
        clip_id,
        start=payload.start,
        end=payload.end,
        selected=payload.selected,
        edit_profile=payload.edit_profile,
    )
    if not clip:
        raise HTTPException(status_code=404, detail="Clip not found")
    if old_clip and (payload.start is not None or payload.end is not None):
        store_feedback(
            project_id,
            clip.id,
            clip.moment_id,
            FeedbackRequest(action="edited", old_start=old_clip.start, old_end=old_clip.end, new_start=clip.start, new_end=clip.end),
        )
    return clip.model_dump()


@router.post("/{clip_id}/accept")
def accept_clip(project_id: str, clip_id: str) -> dict:
    clip = project_store.update_clip(project_id, clip_id, selected=True)
    if not clip:
        raise HTTPException(status_code=404, detail="Clip not found")
    store_feedback(project_id, clip.id, clip.moment_id, FeedbackRequest(action="accept"))
    return clip.model_dump()


@router.post("/{clip_id}/reject")
def reject_clip(project_id: str, clip_id: str) -> dict:
    clip = project_store.update_clip(project_id, clip_id, selected=False)
    if not clip:
        raise HTTPException(status_code=404, detail="Clip not found")
    store_feedback(project_id, clip.id, clip.moment_id, FeedbackRequest(action="reject"))
    return clip.model_dump()
