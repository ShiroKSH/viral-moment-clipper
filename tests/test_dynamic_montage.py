from backend.core.config import Settings
from backend.schemas.clips import ClipCandidate
from backend.schemas.transcript import Transcript, TranscriptSegment, TranscriptWord
from backend.services.edit_planner import build_edit_plan


def _clip() -> ClipCandidate:
    return ClipCandidate(
        id="clip_timed",
        moment_id="moment_timed",
        start=100,
        end=130,
        duration=30,
        final_score=91,
        moment_type="controversial_take",
        hook_text="Сначала важный тезис",
        summary="summary",
        reason="reason",
        text="Сначала важный тезис, но затем поворот, поэтому вывод.",
        suggested_title="Важный тезис",
        suggested_caption="caption",
        edit_profile="banger",
    )


def _transcript() -> Transcript:
    return Transcript(
        duration=200,
        segments=[
            TranscriptSegment(
                id=1,
                start=100.20,
                end=102.0,
                text="Сначала важный тезис.",
                words=[
                    TranscriptWord(word="Сначала", start=100.20, end=100.55),
                    TranscriptWord(word="важный", start=100.56, end=100.90),
                    TranscriptWord(word="тезис.", start=100.91, end=101.30),
                ],
            ),
            TranscriptSegment(
                id=2,
                start=108.0,
                end=110.0,
                text="Но затем поворот.",
                words=[
                    TranscriptWord(word="Но", start=108.0, end=108.18),
                    TranscriptWord(word="затем", start=108.19, end=108.55),
                    TranscriptWord(word="поворот.", start=108.56, end=109.10),
                ],
            ),
            TranscriptSegment(
                id=3,
                start=117.0,
                end=119.0,
                text="Поэтому вот вывод.",
                words=[
                    TranscriptWord(word="Поэтому", start=117.0, end=117.40),
                    TranscriptWord(word="вот", start=117.41, end=117.60),
                    TranscriptWord(word="вывод.", start=117.61, end=118.10),
                ],
            ),
        ],
    )


def test_montage_uses_word_timestamps_without_regular_intervals():
    settings = Settings()
    plan = build_edit_plan(
        _clip(),
        settings,
        transcript=_transcript(),
        scene_cuts=[],
    )

    zooms = [operation for operation in plan.operations if operation.type == "punch_zoom"]

    assert any(0.25 <= (operation.start or 0) <= 0.5 for operation in zooms)
    assert any(16.9 <= (operation.start or 0) <= 17.2 for operation in zooms)
    assert all("score=" in operation.reason for operation in zooms)


def test_montage_without_timestamps_does_not_invent_regular_beats():
    settings = Settings()
    plan = build_edit_plan(_clip(), settings)
    zooms = [operation for operation in plan.operations if operation.type == "punch_zoom"]

    assert len(zooms) == 1
    assert zooms[0].reason.startswith("hook: transcript timing unavailable")


def test_montage_uses_cut_shaped_motion_when_source_is_already_dynamic():
    settings = Settings()
    clip = _clip().model_copy(update={"end": 118, "duration": 18})
    plan = build_edit_plan(
        clip,
        settings,
        transcript=_transcript(),
        scene_cuts=[6.6, 12.8, 15.8],
    )
    zooms = [operation for operation in plan.operations if operation.type == "punch_zoom"]
    motions = [operation for operation in plan.operations if operation.type == "shot_motion"]

    assert not zooms
    assert len(motions) == 2
    assert motions[0].start == 0
    assert motions[0].end == 6.56
    assert all(1.0 <= (operation.scale_to or 1) <= 1.028 for operation in motions)


def test_semantic_montage_uses_one_timed_fact_without_extra_zoom_noise():
    settings = Settings()
    clip = _clip().model_copy(update={"end": 118, "duration": 18})
    transcript = _transcript().model_copy(
        update={
            "segments": _transcript().segments
            + [
                TranscriptSegment(
                    id=4,
                    start=102.4,
                    end=103.3,
                    text="500 лет.",
                    words=[
                        TranscriptWord(word="500", start=102.4, end=102.75),
                        TranscriptWord(word="лет.", start=102.76, end=103.3),
                    ],
                )
            ]
        }
    )

    plan = build_edit_plan(clip, settings, transcript=transcript, scene_cuts=[6.6, 12.8, 15.8])
    evidence = [operation for operation in plan.operations if operation.type == "evidence_stamp"]
    audio = [operation for operation in plan.operations if operation.type == "audio_accent"]

    assert len(evidence) == 1
    assert evidence[0].text == "500 ЛЕТ"
    assert evidence[0].start == 2.36
    assert not audio
    assert plan.strategy == "semantic_tension_v1"
    assert plan.natural_cut_count == 3
    assert plan.generated_effect_count == 3


def test_semantic_sound_is_reserved_for_one_strong_question():
    settings = Settings()
    transcript = _transcript().model_copy(
        update={
            "segments": _transcript().segments
            + [
                TranscriptSegment(
                    id=4,
                    start=112,
                    end=113,
                    text="Почему?",
                    words=[TranscriptWord(word="Почему?", start=112, end=113)],
                )
            ]
        }
    )

    plan = build_edit_plan(_clip(), settings, transcript=transcript, scene_cuts=[8.05, 20.0])
    audio = [operation for operation in plan.operations if operation.type == "audio_accent"]
    zooms = [operation for operation in plan.operations if operation.type == "punch_zoom"]

    assert len(audio) == 1
    assert audio[0].text == "question"
    assert audio[0].start == 12.06
    assert len(zooms) == 1
    assert zooms[0].start == audio[0].start
    assert 1.03 <= (zooms[0].scale_to or 1) <= 1.045


def test_semantic_sound_ignores_single_word_filler_questions():
    settings = Settings()
    transcript = _transcript().model_copy(
        update={
            "segments": _transcript().segments
            + [
                TranscriptSegment(
                    id=4 + index,
                    start=112 + index * 1.2,
                    end=113 + index * 1.2,
                    text=text,
                    words=[TranscriptWord(word=text, start=112 + index * 1.2, end=113 + index * 1.2)],
                )
                for index, text in enumerate(("Да?", "Что?", "Наверное?"))
            ]
        }
    )

    plan = build_edit_plan(_clip(), settings, transcript=transcript, scene_cuts=[8.05, 20.0])

    assert not [operation for operation in plan.operations if operation.type == "audio_accent"]


def test_semantic_question_anchors_to_meaningful_interrogative_word():
    settings = Settings()
    transcript = _transcript().model_copy(
        update={
            "segments": _transcript().segments
            + [
                TranscriptSegment(
                    id=4,
                    start=112,
                    end=114,
                    text="В плане какие рофлы?",
                    words=[
                        TranscriptWord(word="В", start=112.0, end=112.2),
                        TranscriptWord(word="плане", start=112.2, end=112.6),
                        TranscriptWord(word="какие", start=112.6, end=113.0, probability=0.95),
                        TranscriptWord(word="рофлы?", start=113.0, end=114.0),
                    ],
                )
            ]
        }
    )

    plan = build_edit_plan(_clip(), settings, transcript=transcript, scene_cuts=[8.05, 20.0])
    audio = [operation for operation in plan.operations if operation.type == "audio_accent"]

    assert len(audio) == 1
    assert audio[0].start == 12.66
    assert "какие рофлы" in audio[0].reason.lower()
