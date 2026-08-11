from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, ValidationError

from backend.core.paths import PROJECT_ROOT
from backend.core.utils import atomic_write_text


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
    device: str = "cuda"
    compute_type: str = "float16"
    require_gpu: bool = False
    cpu_fallback: bool = True
    fallback_compute_type: str = "int8"
    allow_synthetic_fallback: bool = False
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
    temperature: float = Field(default=0.15, ge=0.0, le=2.0)
    seed: int = 7


class ClipConfig(BaseModel):
    target_count: int = 8
    min_duration_sec: float = 18
    max_duration_sec: float = 48
    preferred_duration_sec: float = 28
    avoid_cutting_sentences: bool = True
    ending_strategy: str = "complete_sentence"
    cliffhanger_min_duration_sec: float = 14
    cliffhanger_max_duration_sec: float = 28
    cliffhanger_preferred_duration_sec: float = 21
    pad_before_sec: float = 0.35
    pad_after_sec: float = 0.45
    min_score: float = 70


class RenderConfig(BaseModel):
    width: int = 1080
    height: int = 1920
    fps: int = 30
    video_codec: str = "h264_nvenc"
    fallback_video_codec: str = "libx264"
    require_gpu: bool = False
    hwaccel: str | None = "cuda"
    gpu_filters: bool = True
    nvenc_preset: str = "p5"
    nvenc_cq: int = 19
    audio_codec: str = "aac"
    audio_bitrate: str = "192k"
    video_bitrate: str = "12M"
    mode: str = "blurred_background"


class BrandingConfig(BaseModel):
    handle: str = "@my_youtube_nick"
    show_badge: bool = True
    badge_position: str = "bottom_center"
    badge_text: str = "@my_youtube_nick"
    badge_width: int = 520
    badge_safe_bottom_px: int = 250
    opacity: float = 0.72


class SubtitleConfig(BaseModel):
    enabled: bool = True
    max_words_per_line: int = 3
    font_size: int = 68
    highlight_current_word: bool = True
    speaker_colors_enabled: bool = True
    speaker_labels_enabled: bool = False
    safe_bottom_margin_px: int = 430


class SpeakerConfig(BaseModel):
    enabled: bool = True
    embedding_backend: str = "local"
    neural_model: str = "speechbrain/spkrec-ecapa-voxceleb"
    max_speakers: int = 4
    min_segment_sec: float = 0.6
    distance_threshold: float = 0.22


class DynamicEditConfig(BaseModel):
    enabled: bool = True
    profile: str = "story"
    max_pause_sec: float = 0.65
    punch_zoom_enabled: bool = True
    max_punch_zoom_per_10_sec: int = 3
    pattern_interrupt_every_sec: float = 3.2
    scene_detection_enabled: bool = True
    scene_threshold: float = Field(default=0.10, ge=0.03, le=0.80)
    scene_guard_sec: float = Field(default=0.90, ge=0.25, le=3.0)
    hook_title_enabled: bool = False
    progress_bar_enabled: bool = False
    audio_normalization_enabled: bool = True


class EndCardConfig(BaseModel):
    enabled: bool = True
    duration_sec: float = 1.0
    headline: str = "Продолжение на YouTube"
    subheadline: str = ""
    channel_text: str = "@my_youtube_nick"
    sound_enabled: bool = True
    sound_volume: float = 0.30


class LearningConfig(BaseModel):
    enabled: bool = True
    min_feedback_before_training: int = 12
    min_metrics_before_training: int = 8
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
    speakers: SpeakerConfig = Field(default_factory=SpeakerConfig)
    dynamic_edit: DynamicEditConfig = Field(default_factory=DynamicEditConfig)
    end_card: EndCardConfig = Field(default_factory=EndCardConfig)
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
    serialized = yaml.safe_dump(settings.model_dump(), sort_keys=False, allow_unicode=True)
    atomic_write_text(CONFIG_PATH, serialized)
    load_config.cache_clear()
    return load_config()


def config_to_dict(settings: Settings) -> dict[str, Any]:
    return settings.model_dump()
