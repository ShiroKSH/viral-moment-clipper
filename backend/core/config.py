from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, ValidationError

from backend.core.paths import PROJECT_ROOT


class AppConfig(BaseModel):
    host: str = "127.0.0.1"
    port: int = 7878
    open_browser_on_start: bool = True


class PathConfig(BaseModel):
    ffmpeg_path: str = "ffmpeg"
    ffprobe_path: str = "ffprobe"
    output_dir: str = "./output"
    temp_dir: str = "./temp"
    models_dir: str = "./models"


class TranscriptionConfig(BaseModel):
    engine: str = "faster-whisper"
    model: str = "large-v3-turbo"
    language: str = "ru"
    device: str = "cpu"
    compute_type: str = "int8"
    vad_filter: bool = True
    word_timestamps: bool = True
    whisperx_enabled: bool = False


class LocalLLMConfig(BaseModel):
    enabled: bool = True
    provider: str = "ollama"
    base_url: str = "http://127.0.0.1:11434"
    model: str = "qwen2.5:7b-instruct"
    timeout_sec: int = 120
    max_window_sec: int = 120
    overlap_sec: int = 20
    strict_json: bool = True
    fallback_to_heuristics: bool = True


class ClipConfig(BaseModel):
    target_count: int = 15
    min_duration_sec: float = 18
    max_duration_sec: float = 58
    preferred_duration_sec: float = 35
    avoid_cutting_sentences: bool = True
    pad_before_sec: float = 0.35
    pad_after_sec: float = 0.45
    min_score: float = 60


class RenderConfig(BaseModel):
    width: int = 1080
    height: int = 1920
    fps: int = 30
    video_codec: str = "h264_nvenc"
    fallback_video_codec: str = "libx264"
    require_gpu: bool = True
    audio_codec: str = "aac"
    audio_bitrate: str = "192k"
    video_bitrate: str = "12M"
    mode: str = "blurred_background"


class BrandingConfig(BaseModel):
    handle: str = "@my_youtube_nick"
    show_badge: bool = True
    badge_position: str = "bottom_center"
    badge_text: str = "@my_youtube_nick"
    badge_width: int = 620
    badge_safe_bottom_px: int = 235
    opacity: float = 0.86


class SubtitleConfig(BaseModel):
    enabled: bool = True
    style: str = "organic_bold"
    max_words_per_line: int = 3
    max_lines: int = 2
    font_size: int = 74
    uppercase_keywords: bool = True
    highlight_current_word: bool = True
    safe_bottom_margin_px: int = 430


class DynamicEditConfig(BaseModel):
    enabled: bool = True
    profile: str = "banger"
    remove_silence: bool = True
    max_pause_sec: float = 0.65
    punch_zoom_enabled: bool = True
    max_punch_zoom_per_10_sec: int = 3
    pattern_interrupt_every_sec: float = 3.2
    hook_title_enabled: bool = False
    progress_bar_enabled: bool = True
    keyword_emphasis_enabled: bool = True
    audio_normalization_enabled: bool = True


class LearningConfig(BaseModel):
    enabled: bool = True
    min_feedback_before_training: int = 30
    min_metrics_before_training: int = 15
    exploration_rate: float = 0.12
    personal_score_weight: float = 0.35
    save_training_rows: bool = True


class Settings(BaseModel):
    app: AppConfig = Field(default_factory=AppConfig)
    paths: PathConfig = Field(default_factory=PathConfig)
    transcription: TranscriptionConfig = Field(default_factory=TranscriptionConfig)
    local_llm: LocalLLMConfig = Field(default_factory=LocalLLMConfig)
    clips: ClipConfig = Field(default_factory=ClipConfig)
    render: RenderConfig = Field(default_factory=RenderConfig)
    branding: BrandingConfig = Field(default_factory=BrandingConfig)
    subtitles: SubtitleConfig = Field(default_factory=SubtitleConfig)
    dynamic_edit: DynamicEditConfig = Field(default_factory=DynamicEditConfig)
    learning: LearningConfig = Field(default_factory=LearningConfig)


CONFIG_PATH = PROJECT_ROOT / "config.yaml"
EXAMPLE_CONFIG_PATH = PROJECT_ROOT / "config.example.yaml"


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as file:
        data = yaml.safe_load(file) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{path.name} must contain a YAML object")
    return data


@lru_cache(maxsize=1)
def load_config() -> Settings:
    source = CONFIG_PATH if CONFIG_PATH.exists() else EXAMPLE_CONFIG_PATH
    return Settings.model_validate(_read_yaml(source))


def save_config(raw: dict[str, Any]) -> Settings:
    try:
        settings = Settings.model_validate(raw)
    except ValidationError as exc:
        raise ValueError(str(exc)) from exc
    with CONFIG_PATH.open("w", encoding="utf-8") as file:
        yaml.safe_dump(settings.model_dump(), file, sort_keys=False, allow_unicode=True)
    load_config.cache_clear()
    return load_config()


def config_to_dict(settings: Settings) -> dict[str, Any]:
    return settings.model_dump()
