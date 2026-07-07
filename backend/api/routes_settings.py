from fastapi import APIRouter, HTTPException

from backend.core.config import config_to_dict, load_config, save_config

router = APIRouter(prefix="/api/settings", tags=["settings"])


@router.get("")
def get_settings() -> dict:
    return config_to_dict(load_config())


@router.post("")
def update_settings(settings: dict) -> dict:
    try:
        return config_to_dict(save_config(settings))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
