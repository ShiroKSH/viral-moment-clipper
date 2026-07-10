from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import os
from pathlib import Path
import math
import warnings
import wave

import numpy as np

from backend.core.config import Settings
from backend.core.paths import resolve_project_path, slugify
from backend.schemas.transcript import Transcript


SPEAKER_PIPELINE_VERSION = "speaker_turn_v3"


@dataclass
class VoiceProfile:
    label: str
    centroid: np.ndarray
    count: int = 1


@dataclass
class SegmentEmbedding:
    index: int
    embedding: np.ndarray
    duration: float = 0.0


def _read_wav_mono(path: Path) -> tuple[np.ndarray, int]:
    with wave.open(str(path), "rb") as wav:
        sample_rate = wav.getframerate()
        channels = wav.getnchannels()
        sample_width = wav.getsampwidth()
        frames = wav.readframes(wav.getnframes())
    if sample_width != 2:
        raise ValueError("speaker detection expects 16-bit PCM WAV")
    samples = np.frombuffer(frames, dtype="<i2").astype(np.float32)
    if channels > 1:
        samples = samples.reshape(-1, channels).mean(axis=1)
    return samples / 32768.0, sample_rate


def _safe_normalize(vector: np.ndarray) -> np.ndarray:
    norm = float(np.linalg.norm(vector))
    if norm <= 1e-8:
        return vector
    return vector / norm


def _band_ratio(spectrum: np.ndarray, freqs: np.ndarray, low: float, high: float, total: float) -> float:
    mask = (freqs >= low) & (freqs < high)
    if not np.any(mask):
        return 0.0
    return float(spectrum[mask].sum() / total)


def _pitch_feature(samples: np.ndarray, sample_rate: int) -> tuple[float, float]:
    if samples.size < int(sample_rate * 0.12):
        return 0.0, 0.0
    window = samples[: min(samples.size, sample_rate * 2)]
    window = window - float(window.mean())
    fft_size = 1 << (2 * window.size - 1).bit_length()
    spectrum = np.fft.rfft(window, fft_size)
    corr = np.fft.irfft(spectrum * np.conj(spectrum), fft_size)[: window.size]
    if not np.any(corr):
        return 0.0, 0.0
    min_lag = max(1, int(sample_rate / 360))
    max_lag = min(corr.size - 1, int(sample_rate / 70))
    if max_lag <= min_lag:
        return 0.0, 0.0
    local = corr[min_lag:max_lag]
    lag = int(np.argmax(local)) + min_lag
    confidence = float(local[lag - min_lag] / max(corr[0], 1e-8))
    pitch_hz = sample_rate / lag
    return pitch_hz / 360.0, max(0.0, min(confidence, 1.0))


def _segment_embedding(samples: np.ndarray, sample_rate: int, start: float, end: float) -> np.ndarray | None:
    start_index = max(0, int(start * sample_rate))
    end_index = min(samples.size, int(end * sample_rate))
    segment = samples[start_index:end_index]
    if segment.size < int(sample_rate * 0.25):
        return None
    segment = segment - float(segment.mean())
    rms = float(np.sqrt(np.mean(np.square(segment)) + 1e-9))
    if rms < 0.002:
        return None
    crossings = float(np.mean(np.abs(np.diff(np.signbit(segment)))))
    fft_window = segment[: min(segment.size, sample_rate * 3)]
    spectrum = np.abs(np.fft.rfft(fft_window * np.hanning(fft_window.size)))
    freqs = np.fft.rfftfreq(fft_window.size, d=1 / sample_rate)
    total = float(spectrum.sum() + 1e-9)
    centroid = float((spectrum * freqs).sum() / total / (sample_rate / 2))
    rolloff_index = int(np.searchsorted(np.cumsum(spectrum), total * 0.85))
    rolloff = float(freqs[min(rolloff_index, freqs.size - 1)] / (sample_rate / 2))
    pitch, pitch_confidence = _pitch_feature(segment, sample_rate)
    vector = np.array(
        [
            np.log10(rms + 1e-6),
            crossings,
            centroid,
            rolloff,
            _band_ratio(spectrum, freqs, 80, 250, total),
            _band_ratio(spectrum, freqs, 250, 700, total),
            _band_ratio(spectrum, freqs, 700, 1600, total),
            _band_ratio(spectrum, freqs, 1600, 3400, total),
            pitch,
            pitch_confidence,
        ],
        dtype=np.float32,
    )
    return _safe_normalize(vector)


@lru_cache(maxsize=2)
def _speechbrain_classifier(model_name: str, savedir: str, device: str):
    os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
    warnings.filterwarnings("ignore", category=FutureWarning, module=r"speechbrain\.utils\.autocast")
    try:
        from speechbrain.inference.speaker import EncoderClassifier
    except Exception:
        from speechbrain.pretrained import EncoderClassifier
    from speechbrain.utils.fetching import LocalStrategy

    run_opts = {"device": device} if device else {}
    return EncoderClassifier.from_hparams(source=model_name, savedir=savedir, run_opts=run_opts, local_strategy=LocalStrategy.COPY)


def _speechbrain_segment_embedding(samples: np.ndarray, sample_rate: int, start: float, end: float, config: Settings) -> np.ndarray | None:
    start_index = max(0, int(start * sample_rate))
    end_index = min(samples.size, int(end * sample_rate))
    segment = samples[start_index:end_index]
    if segment.size < int(sample_rate * 0.25):
        return None
    rms = float(np.sqrt(np.mean(np.square(segment)) + 1e-9))
    if rms < 0.002:
        return None
    import torch

    device = "cuda" if config.transcription.device == "cuda" and torch.cuda.is_available() else "cpu"
    model_dir = resolve_project_path(config.paths.models_dir) / "speechbrain" / slugify(config.speakers.neural_model, "speaker-model")
    model_dir.mkdir(parents=True, exist_ok=True)
    classifier = _speechbrain_classifier(config.speakers.neural_model, str(model_dir), device)
    minimum_samples = int(sample_rate * 0.90)
    if segment.size < minimum_samples:
        segment = np.tile(segment, math.ceil(minimum_samples / segment.size))[:minimum_samples]
    waveform = torch.from_numpy(segment.astype(np.float32)).unsqueeze(0)
    embedding = classifier.encode_batch(waveform).detach().cpu().numpy().reshape(-1).astype(np.float32)
    return _safe_normalize(embedding)


def _embedding_for_segment(samples: np.ndarray, sample_rate: int, start: float, end: float, config: Settings) -> np.ndarray | None:
    if config.speakers.embedding_backend == "speechbrain":
        try:
            embedding = _speechbrain_segment_embedding(samples, sample_rate, start, end, config)
            if embedding is not None:
                return embedding
        except Exception:
            pass
    return _segment_embedding(samples, sample_rate, start, end)


def _distance(left: np.ndarray, right: np.ndarray) -> float:
    return 1.0 - float(np.dot(left, right))


def _assign_profile(embedding: np.ndarray, profiles: list[VoiceProfile], config: Settings) -> str:
    if not profiles:
        profiles.append(VoiceProfile(label="S1", centroid=embedding))
        return "S1"
    distances = [_distance(embedding, profile.centroid) for profile in profiles]
    best_index = int(np.argmin(distances))
    best_distance = distances[best_index]
    if best_distance > config.speakers.distance_threshold and len(profiles) < config.speakers.max_speakers:
        label = f"S{len(profiles) + 1}"
        profiles.append(VoiceProfile(label=label, centroid=embedding))
        return label
    profile = profiles[best_index]
    profile.centroid = _safe_normalize((profile.centroid * profile.count + embedding) / (profile.count + 1))
    profile.count += 1
    return profile.label


def _labels_by_first_seen(raw_labels: list[int]) -> dict[int, str]:
    mapping: dict[int, str] = {}
    for raw_label in raw_labels:
        if raw_label not in mapping:
            mapping[raw_label] = f"S{len(mapping) + 1}"
    return mapping


def _cluster_segment_embeddings(items: list[SegmentEmbedding], config: Settings) -> dict[int, str]:
    if not items:
        return {}
    if len(items) == 1:
        return {items[0].index: "S1"}
    if len(items) == 2:
        second_label = "S2" if _distance(items[0].embedding, items[1].embedding) >= config.speakers.distance_threshold else "S1"
        return {items[0].index: "S1", items[1].index: second_label}
    try:
        from sklearn.cluster import KMeans
        from sklearn.metrics import silhouette_score
    except Exception:
        return _online_segment_labels(items, config)

    matrix = np.stack([item.embedding for item in items])
    try:
        maximum = min(config.speakers.max_speakers, len(items) - 1)
        minimum_cluster_size = 1 if len(items) < 8 else max(2, math.ceil(len(items) * 0.03))
        best_labels: list[int] | None = None
        best_adjusted_score = float("-inf")
        minimum_separation = max(0.06, config.speakers.distance_threshold * 0.35)
        for cluster_count in range(2, maximum + 1):
            model = KMeans(n_clusters=cluster_count, n_init=20, random_state=7)
            candidate_labels = [int(label) for label in model.fit_predict(matrix)]
            counts = [candidate_labels.count(label) for label in set(candidate_labels)]
            if min(counts) < minimum_cluster_size:
                continue
            centroids = [
                _safe_normalize(matrix[np.array(candidate_labels) == label].mean(axis=0))
                for label in sorted(set(candidate_labels))
            ]
            separation = min(
                (_distance(left, right) for index, left in enumerate(centroids) for right in centroids[index + 1 :]),
                default=0.0,
            )
            if separation < minimum_separation:
                continue
            score = float(silhouette_score(matrix, candidate_labels, metric="cosine"))
            adjusted_score = score - max(0, cluster_count - 2) * 0.008
            if adjusted_score > best_adjusted_score:
                best_adjusted_score = adjusted_score
                best_labels = candidate_labels
        raw_labels = best_labels if best_labels is not None and best_adjusted_score >= 0.10 else [0] * len(items)
    except Exception:
        return _online_segment_labels(items, config)

    label_map = _labels_by_first_seen(raw_labels)
    return {item.index: label_map[raw_label] for item, raw_label in zip(items, raw_labels)}


def _speaker_centroids(items: list[SegmentEmbedding], labels: dict[int, str]) -> dict[str, np.ndarray]:
    grouped: dict[str, list[np.ndarray]] = {}
    for item in items:
        label = labels.get(item.index)
        if label:
            grouped.setdefault(label, []).append(item.embedding)
    return {label: _safe_normalize(np.stack(vectors).mean(axis=0)) for label, vectors in grouped.items()}


def _speaker_assignment_limits(
    items: list[SegmentEmbedding],
    labels: dict[int, str],
    centroids: dict[str, np.ndarray],
    config: Settings,
) -> dict[str, float]:
    grouped: dict[str, list[float]] = {}
    for item in items:
        label = labels.get(item.index)
        centroid = centroids.get(label or "")
        if label and centroid is not None:
            grouped.setdefault(label, []).append(_distance(item.embedding, centroid))
    minimum = max(0.28, config.speakers.distance_threshold * 1.45)
    return {
        label: min(0.82, max(minimum, float(np.percentile(distances, 95)) + 0.08))
        for label, distances in grouped.items()
    }


def _nearest_speaker(embedding: np.ndarray, centroids: dict[str, np.ndarray]) -> tuple[str | None, float, float]:
    ranked = sorted((_distance(embedding, centroid), label) for label, centroid in centroids.items())
    if not ranked:
        return None, 1.0, 0.0
    nearest_distance, nearest_label = ranked[0]
    margin = (ranked[1][0] - nearest_distance) if len(ranked) > 1 else 1.0
    return nearest_label, nearest_distance, margin


def _online_segment_labels(items: list[SegmentEmbedding], config: Settings) -> dict[int, str]:
    profiles: list[VoiceProfile] = []
    labels: dict[int, str] = {}
    for item in items:
        labels[item.index] = _assign_profile(item.embedding, profiles, config)
    return labels


def assign_speakers(audio_path: Path, transcript: Transcript, config: Settings) -> Transcript:
    if not config.speakers.enabled or not transcript.segments:
        return transcript
    samples, sample_rate = _read_wav_mono(audio_path)
    embeddings: list[SegmentEmbedding] = []
    for index, segment in enumerate(transcript.segments):
        duration = max(0.0, segment.end - segment.start)
        if duration < min(0.25, config.speakers.min_segment_sec) or not segment.text.strip():
            continue
        embedding = _embedding_for_segment(samples, sample_rate, segment.start, segment.end, config)
        if embedding is not None:
            embeddings.append(SegmentEmbedding(index=index, embedding=embedding, duration=duration))

    anchor_duration = max(1.0, config.speakers.min_segment_sec)
    anchors = [
        item
        for item in embeddings
        if item.duration >= anchor_duration and len(transcript.segments[item.index].text.split()) >= 2
    ]
    cluster_items = anchors if len(anchors) >= 2 else embeddings
    labels = _cluster_segment_embeddings(cluster_items, config)
    centroids = _speaker_centroids(cluster_items, labels)
    assignment_limits = _speaker_assignment_limits(cluster_items, labels, centroids, config)
    for item in embeddings:
        if item.index in labels:
            continue
        label, distance, margin = _nearest_speaker(item.embedding, centroids)
        limit = assignment_limits.get(label or "", max(0.28, config.speakers.distance_threshold * 1.45))
        if label is not None and distance <= limit and margin >= 0.012:
            labels[item.index] = label

    for item in embeddings:
        if item.index in labels:
            continue
        previous_index = next((index for index in range(item.index - 1, -1, -1) if index in labels), None)
        next_index = next((index for index in range(item.index + 1, len(transcript.segments)) if index in labels), None)
        previous = labels.get(previous_index) if previous_index is not None else None
        following = labels.get(next_index) if next_index is not None else None
        if previous and previous == following:
            previous_gap = max(0.0, transcript.segments[item.index].start - transcript.segments[previous_index].end)
            next_gap = max(0.0, transcript.segments[next_index].start - transcript.segments[item.index].end)
            if previous_gap <= 0.75 and next_gap <= 0.75:
                labels[item.index] = previous

    for index, segment in enumerate(transcript.segments):
        label = labels.get(index)
        segment.speaker = label
        for word in segment.words:
            word.speaker = label
    transcript.speaker_model_version = SPEAKER_PIPELINE_VERSION
    transcript.speaker_backend = (
        "speechbrain+local-fallback" if config.speakers.embedding_backend == "speechbrain" else "local"
    )
    transcript.speaker_coverage = round(
        sum(segment.speaker is not None for segment in transcript.segments) / max(1, len(transcript.segments)),
        4,
    )
    return transcript


def _reference_speaker(reference: Transcript, start: float, end: float) -> str | None:
    scores: dict[str, float] = {}
    for segment in reference.segments:
        if segment.end <= start or segment.start >= end or not segment.speaker:
            continue
        overlap = max(0.0, min(end, segment.end) - max(start, segment.start))
        if overlap > 0:
            scores[segment.speaker] = scores.get(segment.speaker, 0.0) + overlap
    if scores:
        return max(scores.items(), key=lambda item: item[1])[0]
    midpoint = (start + end) / 2
    nearby = [
        (min(abs(midpoint - segment.start), abs(midpoint - segment.end)), segment.speaker)
        for segment in reference.segments
        if segment.speaker and min(abs(midpoint - segment.start), abs(midpoint - segment.end)) <= 0.35
    ]
    return min(nearby, default=(1.0, None), key=lambda item: item[0])[1]


def inherit_speakers_from_reference(transcript: Transcript, reference: Transcript, *, offset: float) -> Transcript:
    for segment in transcript.segments:
        absolute_start = segment.start + offset
        absolute_end = segment.end + offset
        segment.speaker = _reference_speaker(reference, absolute_start, absolute_end)
        for word in segment.words:
            word.speaker = _reference_speaker(reference, word.start + offset, word.end + offset) or segment.speaker
    transcript.speaker_model_version = SPEAKER_PIPELINE_VERSION
    transcript.speaker_backend = f"reference:{reference.speaker_backend or 'project'}"
    transcript.speaker_coverage = round(
        sum(segment.speaker is not None for segment in transcript.segments) / max(1, len(transcript.segments)),
        4,
    )
    return transcript


def has_speaker_labels(transcript: Transcript) -> bool:
    return transcript.speaker_model_version == SPEAKER_PIPELINE_VERSION and any(segment.speaker for segment in transcript.segments)


def speaker_summary(transcript: Transcript) -> str:
    counts: dict[str, int] = {}
    for segment in transcript.segments:
        if segment.speaker:
            counts[segment.speaker] = counts.get(segment.speaker, 0) + 1
    if not counts:
        return "speakers=none"
    parts = [f"{speaker}:{count}" for speaker, count in sorted(counts.items())]
    backend = transcript.speaker_backend or "unknown"
    return f"speakers={', '.join(parts)}; coverage={transcript.speaker_coverage:.0%}; backend={backend}"
