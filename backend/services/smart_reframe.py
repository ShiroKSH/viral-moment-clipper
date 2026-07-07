from __future__ import annotations


def choose_reframe_mode(requested_mode: str, face_detected: bool = False) -> str:
    if requested_mode == "smart_face_crop" and not face_detected:
        return "center_crop"
    return requested_mode
