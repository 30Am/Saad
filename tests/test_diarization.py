"""Tests for plain diarization (ingestion/diarization.py)."""

from saad_sales_gpt.ingestion.diarization import _assign_from_turns, assign_speakers
from saad_sales_gpt.ingestion.transcription import RawSegment
from saad_sales_gpt.models import SourceType, Speaker


def test_qa_insight_ignores_audio_and_labels_everything_saad() -> None:
    segments = [RawSegment(start_ms=0, end_ms=100, text="hi")]

    result = assign_speakers(segments, SourceType.qa_insight, audio_path="/some/path.mp3")

    assert result == [(segments[0], Speaker.saad)]


def test_recording_without_audio_path_falls_back_to_unknown() -> None:
    segments = [RawSegment(start_ms=0, end_ms=100, text="hi")]

    result = assign_speakers(segments, SourceType.recording, audio_path=None)

    assert result == [(segments[0], Speaker.unknown)]


def test_recording_without_hf_token_configured_falls_back_to_unknown() -> None:
    # settings.hf_token is unset in the test environment, so the pipeline never loads —
    # this exercises the "diarization unconfigured" degrade path end-to-end.
    segments = [RawSegment(start_ms=0, end_ms=100, text="hi")]

    result = assign_speakers(segments, SourceType.recording, audio_path="/some/path.mp3")

    assert result == [(segments[0], Speaker.unknown)]


def test_assign_from_turns_maps_top_two_speakers_by_talk_time() -> None:
    segments = [
        RawSegment(start_ms=0, end_ms=1000, text="hello"),
        RawSegment(start_ms=1000, end_ms=2000, text="hi there"),
    ]
    # SPEAKER_00 talks 5s total (the most), SPEAKER_01 talks 2s — 00 should win speaker_a.
    turns = [(0.0, 1.0, "SPEAKER_00"), (1.0, 2.0, "SPEAKER_01"), (2.0, 6.0, "SPEAKER_00")]

    result = _assign_from_turns(segments, turns)

    assert result == [(segments[0], Speaker.speaker_a), (segments[1], Speaker.speaker_b)]


def test_assign_from_turns_collapses_third_speaker_to_unknown() -> None:
    # A segment that overlaps only the third-most-talkative speaker's turn.
    segments = [RawSegment(start_ms=11200, end_ms=11800, text="crosstalk")]
    turns = [(0.0, 6.0, "SPEAKER_00"), (6.0, 11.0, "SPEAKER_01"), (11.0, 12.0, "SPEAKER_02")]

    result = _assign_from_turns(segments, turns)

    assert result == [(segments[0], Speaker.unknown)]


def test_assign_from_turns_with_no_turns_falls_back_to_unknown() -> None:
    segments = [RawSegment(start_ms=0, end_ms=100, text="hi")]

    result = _assign_from_turns(segments, [])

    assert result == [(segments[0], Speaker.unknown)]
