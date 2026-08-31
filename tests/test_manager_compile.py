"""Tests for the Manager's evidence-view compilation (spec Section 6, rule R6)."""

from sqlalchemy.orm import Session

from saad_sales_gpt.manager.compile import ALL, compile_answer
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


def _seed_two_matching_segments(session: Session) -> None:
    """Two segments across two different sources, both tagged category=technology,
    topic=pricing_objection — R6 requires both to come back verbatim, not blended."""
    recording_source = Source(
        platform=Platform.instagram, handle_or_channel="saadsells", source_type=SourceType.recording, url="ig-url"
    )
    podcast_source = Source(
        platform=Platform.youtube, handle_or_channel="host", source_type=SourceType.podcast_insight, url="yt-url"
    )
    session.add_all([recording_source, podcast_source])
    session.flush()

    media_1 = MediaItem(source_id=recording_source.source_id, url="m1")
    media_2 = MediaItem(source_id=podcast_source.source_id, url="m2")
    session.add_all([media_1, media_2])
    session.flush()

    t1 = Transcript(media_id=media_1.media_id, full_text="...", transcription_method="whisper")
    t2 = Transcript(media_id=media_2.media_id, full_text="...", transcription_method="whisper")
    session.add_all([t1, t2])
    session.flush()

    seg1 = Segment(transcript_id=t1.transcript_id, speaker=Speaker.saad, start_ms=0, end_ms=100, text="quote one")
    seg2 = Segment(transcript_id=t2.transcript_id, speaker=Speaker.saad, start_ms=0, end_ms=100, text="quote two")
    session.add_all([seg1, seg2])
    session.flush()

    for seg in (seg1, seg2):
        session.add_all(
            [
                Tag(
                    segment_id=seg.segment_id,
                    tag_dimension="prospect_background",
                    tag_value="technology",
                    tagged_by=TaggedBy.human,
                    reviewed=True,
                ),
                Tag(
                    segment_id=seg.segment_id,
                    tag_dimension="topic",
                    tag_value="pricing_objection",
                    tagged_by=TaggedBy.human,
                    reviewed=True,
                ),
            ]
        )
    session.commit()


def test_returns_union_of_matching_segments_grouped_by_category_and_source(session: Session) -> None:
    _seed_two_matching_segments(session)

    answer = compile_answer(session, category="technology", topic="pricing_objection")

    assert not answer.empty_categories
    assert set(answer.grouped.keys()) == {"technology"}
    by_source = answer.grouped["technology"]
    assert set(by_source.keys()) == {"recording", "podcast_insight"}
    all_texts = {item.text for items in by_source.values() for item in items}
    # R6: both quotes come back verbatim, never blended into one paraphrase.
    assert all_texts == {"quote one", "quote two"}


def test_no_match_says_so_explicitly_instead_of_falling_back(session: Session) -> None:
    _seed_two_matching_segments(session)

    answer = compile_answer(session, category="sales")

    assert answer.grouped == {}
    assert answer.empty_categories == ["sales"]


def test_unreviewed_auto_tags_excluded_by_default(session: Session) -> None:
    source = Source(
        platform=Platform.instagram, handle_or_channel="saadsells.value", source_type=SourceType.qa_insight, url="u"
    )
    session.add(source)
    session.flush()
    media_item = MediaItem(source_id=source.source_id, url="m")
    session.add(media_item)
    session.flush()
    transcript = Transcript(media_id=media_item.media_id, full_text="a", transcription_method="caption_direct")
    session.add(transcript)
    session.flush()
    segment = Segment(transcript_id=transcript.transcript_id, speaker=Speaker.saad, start_ms=0, end_ms=0, text="answer")
    session.add(segment)
    session.flush()
    session.add(
        Tag(
            segment_id=segment.segment_id,
            tag_dimension="prospect_background",
            tag_value="social_media",
            tagged_by=TaggedBy.claude_auto,
            reviewed=False,  # R5: unreviewed auto-tags are not trusted by default
        )
    )
    session.commit()

    excluded = compile_answer(session, category="social_media")
    assert excluded.empty_categories == ["social_media"]

    included = compile_answer(session, category="social_media", include_unreviewed=True)
    assert included.grouped["social_media"]["qa_insight"][0].text == "answer"


def test_category_all_returns_everything_grouped(session: Session) -> None:
    _seed_two_matching_segments(session)

    answer = compile_answer(session, category=ALL)

    assert answer.category_filter == ALL
    assert list(answer.grouped.keys()) == ["technology"]
