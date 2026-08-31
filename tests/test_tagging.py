"""Tests for Claude-assisted first-pass tagging (spec Phase 3, R4, R5) — mocks the
Anthropic client so these run without a live API key."""

import uuid
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from sqlalchemy.orm import Session

from saad_sales_gpt.config import settings
from saad_sales_gpt.models import (
    MediaItem,
    Platform,
    Segment,
    Source,
    SourceType,
    Speaker,
    Tag,
    TaggedBy,
    Transcript,
)
from saad_sales_gpt.tagging import tag_pending_segments, tag_segment


def _fake_response(**fields):
    tool_use = SimpleNamespace(type="tool_use", input=fields)
    return SimpleNamespace(content=[tool_use])


def _make_segment(session: Session, text: str = "let's talk about your budget") -> Segment:
    source = Source(
        platform=Platform.instagram, handle_or_channel="saadsells", source_type=SourceType.recording, url="u"
    )
    session.add(source)
    session.flush()
    media_item = MediaItem(source_id=source.source_id, url=f"m-{uuid.uuid4()}")
    session.add(media_item)
    session.flush()
    transcript = Transcript(media_id=media_item.media_id, full_text=text, transcription_method="whisper")
    session.add(transcript)
    session.flush()
    segment = Segment(transcript_id=transcript.transcript_id, speaker=Speaker.saad, start_ms=0, end_ms=100, text=text)
    session.add(segment)
    session.commit()
    return segment


def test_raises_clearly_without_api_key(session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "anthropic_api_key", None)
    segment = _make_segment(session)

    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        tag_segment(session, segment)


def test_empty_queue_does_not_require_api_key(session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "anthropic_api_key", None)

    assert tag_pending_segments(session) == []


def test_confident_classification_writes_all_three_dimensions(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
    segment = _make_segment(session)

    with patch("anthropic.Anthropic") as mock_anthropic:
        mock_anthropic.return_value.messages.create.return_value = _fake_response(
            deal_industry="technology",
            deal_industry_confidence=0.9,
            topic="pricing_objection",
            topic_confidence=0.8,
            segment_type="objection_handling",
            segment_type_confidence=0.85,
        )
        result = tag_segment(session, segment)

    assert set(result.dimensions_written) == {"deal_industry", "topic", "segment_type"}
    session.refresh(segment)
    assert segment.segment_type == "objection_handling"

    tags = session.query(Tag).filter(Tag.segment_id == segment.segment_id).all()
    by_dimension = {t.tag_dimension: t for t in tags}
    assert by_dimension["deal_industry"].tag_value == "technology"
    assert by_dimension["topic"].tag_value == "pricing_objection"
    assert all(t.tagged_by == TaggedBy.claude_auto and not t.reviewed for t in tags)


def test_low_confidence_deal_industry_defaults_to_unspecified(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
    segment = _make_segment(session)

    with patch("anthropic.Anthropic") as mock_anthropic:
        mock_anthropic.return_value.messages.create.return_value = _fake_response(
            deal_industry="technology", deal_industry_confidence=0.2
        )
        tag_segment(session, segment)

    tag = session.query(Tag).filter(Tag.segment_id == segment.segment_id, Tag.tag_dimension == "deal_industry").one()
    # R4: never force a low-confidence guess into a named category.
    assert tag.tag_value == "unspecified"


def test_low_confidence_topic_and_segment_type_are_dropped_not_forced(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
    segment = _make_segment(session)

    with patch("anthropic.Anthropic") as mock_anthropic:
        mock_anthropic.return_value.messages.create.return_value = _fake_response(
            deal_industry="unspecified",
            deal_industry_confidence=0.9,
            topic="pricing_objection",
            topic_confidence=0.1,
            segment_type="objection_handling",
            segment_type_confidence=0.1,
        )
        result = tag_segment(session, segment)

    assert result.dimensions_written == ["deal_industry"]
    session.refresh(segment)
    assert segment.segment_type is None
    dims = {t.tag_dimension for t in session.query(Tag).filter(Tag.segment_id == segment.segment_id).all()}
    assert dims == {"deal_industry"}


def test_pending_segments_skips_already_tagged(session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
    segment = _make_segment(session)

    with patch("anthropic.Anthropic") as mock_anthropic:
        mock_anthropic.return_value.messages.create.return_value = _fake_response(
            deal_industry="unspecified", deal_industry_confidence=0.9
        )
        first_pass = tag_pending_segments(session)
        assert [s for s, _ in first_pass] == [segment.segment_id]

        second_pass = tag_pending_segments(session)
        assert second_pass == []


def test_batch_isolates_one_bad_segment(session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
    _make_segment(session, text="segment a")
    _make_segment(session, text="segment b")

    with patch("anthropic.Anthropic") as mock_anthropic:
        mock_anthropic.return_value.messages.create.side_effect = [
            Exception("transient API error"),
            _fake_response(deal_industry="unspecified", deal_industry_confidence=0.9),
        ]
        results = tag_pending_segments(session)

    # Order between the two segments isn't guaranteed — what matters is that the
    # failure on one didn't stop the other from being tagged (batch isolation).
    assert len(results) == 2
    dimensions_by_segment = [dims for _, dims in results]
    assert sorted(dimensions_by_segment) == [[], ["deal_industry"]]
