"""Tests for R1-R5 (spec Section 4.2)."""

from sqlalchemy.orm import Session

from saad_sales_gpt.models import (
    MediaItem,
    Platform,
    Segment,
    Source,
    SourceType,
    Speaker,
    Transcript,
)
from saad_sales_gpt.validation import (
    DEFAULT_DEAL_INDUSTRY,
    check_r1_recording,
    check_r2_qa_insight,
    check_r3_podcast_insight,
    resolve_deal_industry,
)


def _make_media_item(session: Session, source: Source, **overrides) -> MediaItem:
    media_item = MediaItem(source_id=source.source_id, url=overrides.pop("url", "https://example.com/1"), **overrides)
    session.add(media_item)
    session.flush()
    return media_item


def test_r1_fails_without_audio(session: Session) -> None:
    source = Source(
        platform=Platform.instagram, handle_or_channel="saadsells", source_type=SourceType.recording, url="u"
    )
    session.add(source)
    session.flush()
    media_item = _make_media_item(session, source, raw_media_path=None)

    result = check_r1_recording(media_item)

    assert not result.passed
    assert "audio_path" in result.message


def test_r1_fails_with_single_speaker(session: Session) -> None:
    source = Source(
        platform=Platform.instagram, handle_or_channel="saadsells", source_type=SourceType.recording, url="u"
    )
    session.add(source)
    session.flush()
    media_item = _make_media_item(session, source, raw_media_path="/tmp/a.mp3")
    transcript = Transcript(media_id=media_item.media_id, full_text="hi", transcription_method="whisper")
    session.add(transcript)
    session.flush()
    session.add(
        Segment(transcript_id=transcript.transcript_id, speaker=Speaker.saad, start_ms=0, end_ms=100, text="hi")
    )
    session.flush()
    session.refresh(media_item)

    result = check_r1_recording(media_item)

    assert not result.passed
    assert "speaker" in result.message


def test_r1_passes_with_audio_and_two_speakers(session: Session) -> None:
    source = Source(
        platform=Platform.instagram, handle_or_channel="saadsells", source_type=SourceType.recording, url="u"
    )
    session.add(source)
    session.flush()
    media_item = _make_media_item(session, source, raw_media_path="/tmp/a.mp3")
    transcript = Transcript(media_id=media_item.media_id, full_text="hi there", transcription_method="whisper")
    session.add(transcript)
    session.flush()
    session.add_all(
        [
            Segment(transcript_id=transcript.transcript_id, speaker=Speaker.saad, start_ms=0, end_ms=100, text="hi"),
            Segment(
                transcript_id=transcript.transcript_id, speaker=Speaker.prospect, start_ms=100, end_ms=200, text="hey"
            ),
        ]
    )
    session.flush()
    session.refresh(media_item)

    result = check_r1_recording(media_item)

    assert result.passed


def test_r2_qa_insight_requires_answer_text(session: Session) -> None:
    source = Source(
        platform=Platform.instagram, handle_or_channel="saadsells.value", source_type=SourceType.qa_insight, url="u"
    )
    session.add(source)
    session.flush()
    media_item = _make_media_item(session, source, raw_media_path=None)

    assert not check_r2_qa_insight(media_item).passed

    transcript = Transcript(media_id=media_item.media_id, full_text="the answer", transcription_method="caption_direct")
    session.add(transcript)
    session.flush()
    session.refresh(media_item)

    assert check_r2_qa_insight(media_item).passed


def test_r3_podcast_requires_isolated_saad_segment(session: Session) -> None:
    source = Source(
        platform=Platform.youtube, handle_or_channel="host_channel", source_type=SourceType.podcast_insight, url="u"
    )
    session.add(source)
    session.flush()
    media_item = _make_media_item(session, source, raw_media_path="/tmp/pod.mp3")
    transcript = Transcript(media_id=media_item.media_id, full_text="talk", transcription_method="whisper")
    session.add(transcript)
    session.flush()
    session.add(
        Segment(transcript_id=transcript.transcript_id, speaker=Speaker.unknown, start_ms=0, end_ms=100, text="talk")
    )
    session.flush()
    session.refresh(media_item)

    assert not check_r3_podcast_insight(media_item).passed

    session.add(
        Segment(transcript_id=transcript.transcript_id, speaker=Speaker.saad, start_ms=100, end_ms=200, text="my take")
    )
    session.flush()
    session.refresh(media_item)

    assert check_r3_podcast_insight(media_item).passed


def test_r4_defaults_to_unspecified_below_confidence_threshold() -> None:
    assert resolve_deal_industry("technology", confidence=0.4, min_confidence=0.6) == DEFAULT_DEAL_INDUSTRY
    assert resolve_deal_industry(None, confidence=None, min_confidence=0.6) == DEFAULT_DEAL_INDUSTRY
    assert resolve_deal_industry("technology", confidence=0.9, min_confidence=0.6) == "technology"
