"""Tests for the raw-media cleanup behavior in ingestion/pipeline.py — deleting the
audio file after a successful transcription to keep disk usage down at scale."""

import uuid
from pathlib import Path

from sqlalchemy.orm import Session

from saad_sales_gpt.ingestion.pipeline import _cleanup_raw_media, cleanup_transcribed_media
from saad_sales_gpt.models import IngestionStatus, MediaItem, Platform, Source, SourceType


def _make_media_item(session: Session, tmp_path: Path, *, status: IngestionStatus) -> MediaItem:
    unique = uuid.uuid4()
    source = Source(
        platform=Platform.youtube, handle_or_channel="saadsells", source_type=SourceType.podcast_insight, url="u"
    )
    session.add(source)
    session.flush()
    audio_path = tmp_path / f"audio-{unique}.mp3"
    audio_path.write_bytes(b"fake audio")
    media_item = MediaItem(
        source_id=source.source_id, url=f"m-{unique}", raw_media_path=str(audio_path), ingestion_status=status
    )
    session.add(media_item)
    session.commit()
    return media_item


def test_cleanup_deletes_file_and_marks_timestamp(session: Session, tmp_path: Path) -> None:
    media_item = _make_media_item(session, tmp_path, status=IngestionStatus.transcribed)
    audio_path = Path(media_item.raw_media_path)
    assert audio_path.exists()

    _cleanup_raw_media(session, media_item)

    assert not audio_path.exists()
    assert media_item.raw_media_deleted_at is not None
    # raw_media_path itself is kept as a record that audio existed (R1).
    assert media_item.raw_media_path == str(audio_path)


def test_cleanup_is_a_noop_second_time(session: Session, tmp_path: Path) -> None:
    media_item = _make_media_item(session, tmp_path, status=IngestionStatus.transcribed)
    _cleanup_raw_media(session, media_item)
    first_deleted_at = media_item.raw_media_deleted_at

    _cleanup_raw_media(session, media_item)  # already gone — should not error or re-stamp

    assert media_item.raw_media_deleted_at == first_deleted_at


def test_cleanup_noop_when_no_path(session: Session) -> None:
    source = Source(
        platform=Platform.instagram, handle_or_channel="saadsells.value", source_type=SourceType.qa_insight, url="u"
    )
    session.add(source)
    session.flush()
    media_item = MediaItem(source_id=source.source_id, url="m", raw_media_path=None)
    session.add(media_item)
    session.commit()

    _cleanup_raw_media(session, media_item)  # no raw_media_path — nothing to do, no error

    assert media_item.raw_media_deleted_at is None


def test_backfill_cleans_up_transcribed_and_needs_review_items(session: Session, tmp_path: Path) -> None:
    transcribed = _make_media_item(session, tmp_path, status=IngestionStatus.transcribed)
    needs_review = _make_media_item(session, tmp_path, status=IngestionStatus.needs_review)
    still_pending = _make_media_item(session, tmp_path, status=IngestionStatus.pending)

    cleaned = cleanup_transcribed_media(session)

    assert set(cleaned) == {transcribed.media_id, needs_review.media_id}
    assert not Path(transcribed.raw_media_path).exists()
    assert not Path(needs_review.raw_media_path).exists()
    # Pending items haven't been transcribed yet — their audio is still needed.
    assert Path(still_pending.raw_media_path).exists()
