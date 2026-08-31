"""Tests for the chat interface (spec Section 8, Q5) — mocks the Anthropic client so
these run without a live API key, and asserts the plumbing: Claude only extracts
filters, compile_answer()/generate_synthesis() still do the actual answering."""

from types import SimpleNamespace
from unittest.mock import patch

import pytest
from sqlalchemy.orm import Session

from saad_sales_gpt.config import settings
from saad_sales_gpt.manager.chat import answer_question
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


def _fake_tool_response(**filters):
    tool_use = SimpleNamespace(type="tool_use", input=filters)
    return SimpleNamespace(content=[tool_use])


def _fake_text_response(text: str):
    text_block = SimpleNamespace(type="text", text=text)
    return SimpleNamespace(content=[text_block])


def test_raises_clearly_without_api_key(session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "anthropic_api_key", None)

    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        answer_question(session, "what does saad say about pricing?")


def test_no_evidence_says_so_without_calling_synthesis(session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")

    with patch("anthropic.Anthropic") as mock_anthropic:
        mock_anthropic.return_value.messages.create.return_value = _fake_tool_response(
            category="technology", topic=None, source_type=None
        )
        result = answer_question(session, "what does saad say to technology prospects?")

    assert "No tagged material yet" in result.reply
    assert result.category == "technology"
    # Only the filter-extraction call happened — generate_synthesis short-circuits on empty evidence.
    mock_anthropic.return_value.messages.create.assert_called_once()


def test_evidence_found_triggers_synthesis(session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")

    source = Source(
        platform=Platform.instagram, handle_or_channel="saadsells", source_type=SourceType.recording, url="u"
    )
    session.add(source)
    session.flush()
    media_item = MediaItem(source_id=source.source_id, url="m")
    session.add(media_item)
    session.flush()
    transcript = Transcript(media_id=media_item.media_id, full_text="t", transcription_method="whisper")
    session.add(transcript)
    session.flush()
    segment = Segment(
        transcript_id=transcript.transcript_id, speaker=Speaker.saad, start_ms=0, end_ms=100, text="quote"
    )
    session.add(segment)
    session.flush()
    session.add(
        Tag(
            segment_id=segment.segment_id,
            tag_dimension="deal_industry",
            tag_value="technology",
            tagged_by=TaggedBy.human,
            reviewed=True,
        )
    )
    session.commit()

    with patch("anthropic.Anthropic") as mock_anthropic:
        mock_anthropic.return_value.messages.create.side_effect = [
            _fake_tool_response(category="technology", topic=None, source_type=None),
            _fake_text_response("Here's what Saad said, citing [seg-1]."),
        ]
        result = answer_question(session, "what does saad say to technology prospects?")

    assert result.reply == "Here's what Saad said, citing [seg-1]."
    assert mock_anthropic.return_value.messages.create.call_count == 2
