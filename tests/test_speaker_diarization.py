import math
import struct
import wave

import numpy as np

from backend.core.config import Settings
from backend.schemas.transcript import Transcript, TranscriptSegment, TranscriptWord
from backend.services import speaker_diarization
from backend.services.speaker_diarization import (
    SPEAKER_PIPELINE_VERSION,
    assign_speakers,
    has_speaker_labels,
    inherit_speakers_from_reference,
    speaker_summary,
)


def _write_tone_wav(path, tones: list[tuple[float, float]], sample_rate: int = 16_000) -> None:
    frames = bytearray()
    for frequency, duration in tones:
        total = int(sample_rate * duration)
        for index in range(total):
            value = int(math.sin(2 * math.pi * frequency * index / sample_rate) * 12_000)
            frames.extend(struct.pack("<h", value))
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(bytes(frames))


def test_assign_speakers_clusters_repeated_voice(tmp_path):
    audio_path = tmp_path / "voices.wav"
    _write_tone_wav(audio_path, [(170, 1.0), (340, 1.0), (170, 1.0)])
    transcript = Transcript(
        language="ru",
        duration=3,
        engine="test",
        segments=[
            TranscriptSegment(id=1, start=0.0, end=1.0, text="voice one", words=[TranscriptWord(word="one", start=0.0, end=1.0)]),
            TranscriptSegment(id=2, start=1.0, end=2.0, text="voice two", words=[TranscriptWord(word="two", start=1.0, end=2.0)]),
            TranscriptSegment(id=3, start=2.0, end=3.0, text="voice one again", words=[TranscriptWord(word="again", start=2.0, end=3.0)]),
        ],
    )
    settings = Settings()
    settings.speakers.distance_threshold = 0.08

    result = assign_speakers(audio_path, transcript, settings)

    labels = [segment.speaker for segment in result.segments]
    assert labels[0] == labels[2]
    assert labels[0] != labels[1]
    assert result.segments[0].words[0].speaker == labels[0]
    assert "S1:" in speaker_summary(result)


def test_speechbrain_backend_falls_back_to_local_embeddings(monkeypatch, tmp_path):
    audio_path = tmp_path / "voices.wav"
    _write_tone_wav(audio_path, [(170, 1.0), (340, 1.0)])
    transcript = Transcript(
        language="ru",
        duration=2,
        engine="test",
        segments=[
            TranscriptSegment(id=1, start=0.0, end=1.0, text="voice one", words=[TranscriptWord(word="one", start=0.0, end=1.0)]),
            TranscriptSegment(id=2, start=1.0, end=2.0, text="voice two", words=[TranscriptWord(word="two", start=1.0, end=2.0)]),
        ],
    )
    settings = Settings()
    settings.speakers.embedding_backend = "speechbrain"
    settings.speakers.distance_threshold = 0.08
    monkeypatch.setattr(speaker_diarization, "_speechbrain_segment_embedding", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("missing model")))

    result = assign_speakers(audio_path, transcript, settings)

    assert all(segment.speaker for segment in result.segments)


def test_short_turn_uses_nearest_voice_instead_of_previous_label(monkeypatch, tmp_path):
    audio_path = tmp_path / "voices.wav"
    _write_tone_wav(audio_path, [(170, 4.0)])
    transcript = Transcript(
        duration=4,
        segments=[
            TranscriptSegment(id=1, start=0.0, end=1.2, text="voice one long"),
            TranscriptSegment(id=2, start=1.2, end=1.5, text="short reply"),
            TranscriptSegment(id=3, start=1.5, end=2.7, text="voice two long"),
            TranscriptSegment(id=4, start=2.7, end=4.0, text="voice one again"),
        ],
    )
    vectors = {
        0.0: speaker_diarization.np.array([1.0, 0.0]),
        1.2: speaker_diarization.np.array([0.0, 1.0]),
        1.5: speaker_diarization.np.array([0.0, 1.0]),
        2.7: speaker_diarization.np.array([1.0, 0.0]),
    }
    monkeypatch.setattr(
        speaker_diarization,
        "_embedding_for_segment",
        lambda _samples, _rate, start, _end, _config: vectors[start],
    )

    result = assign_speakers(audio_path, transcript, Settings())
    labels = [segment.speaker for segment in result.segments]

    assert labels[0] == labels[3]
    assert labels[1] == labels[2]
    assert labels[0] != labels[1]
    assert result.speaker_model_version == SPEAKER_PIPELINE_VERSION


def test_clustering_ignores_single_embedding_outlier():
    settings = Settings()
    settings.speakers.max_speakers = 4
    speaker_a = [speaker_diarization.SegmentEmbedding(index, np.array([1.0, offset])) for index, offset in enumerate(np.linspace(-0.08, 0.08, 12))]
    speaker_b = [
        speaker_diarization.SegmentEmbedding(index + 12, np.array([offset, 1.0]))
        for index, offset in enumerate(np.linspace(-0.08, 0.08, 12))
    ]
    outlier = speaker_diarization.SegmentEmbedding(24, np.array([-1.0, 0.0]))
    items = [
        speaker_diarization.SegmentEmbedding(item.index, speaker_diarization._safe_normalize(item.embedding), 2.0)
        for item in [*speaker_a, *speaker_b, outlier]
    ]

    labels = speaker_diarization._cluster_segment_embeddings(items, settings)
    counts = {label: list(labels.values()).count(label) for label in set(labels.values())}

    assert len(counts) == 2
    assert min(counts.values()) >= 12


def test_clip_transcript_inherits_project_speaker_ids():
    reference = Transcript(
        duration=20,
        speaker_model_version=SPEAKER_PIPELINE_VERSION,
        speaker_backend="test",
        speaker_coverage=1.0,
        segments=[
            TranscriptSegment(id=1, start=10.0, end=11.0, text="first", speaker="S1"),
            TranscriptSegment(id=2, start=11.0, end=12.0, text="second", speaker="S2"),
        ],
    )
    local = Transcript(
        duration=2,
        segments=[
            TranscriptSegment(
                id=1,
                start=0,
                end=2,
                text="first second",
                words=[
                    TranscriptWord(word="first", start=0.1, end=0.8),
                    TranscriptWord(word="second", start=1.1, end=1.8),
                ],
            )
        ],
    )

    inherited = inherit_speakers_from_reference(local, reference, offset=10.0)

    assert [word.speaker for word in inherited.segments[0].words] == ["S1", "S2"]
    assert has_speaker_labels(inherited)


def test_old_unversioned_speaker_cache_is_not_ready():
    transcript = Transcript(segments=[TranscriptSegment(id=1, start=0, end=1, text="old", speaker="S1")])

    assert not has_speaker_labels(transcript)
