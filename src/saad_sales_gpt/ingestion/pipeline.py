"""Ingestion orchestrator (spec Phase 2): download -> transcribe -> validate (R1-R3).

Deliberately stops short of Phase 3 (Claude-assisted tagging) — see manager/compile.py
and tests/test_manager_compile.py for the tagging-dependent Manager logic, which is
ready to receive Tag rows once that phase starts.
"""

import logging

from sqlalchemy.orm import Session

from saad_sales_gpt.config import settings
from saad_sales_gpt.ingestion import instagram, youtube
from saad_sales_gpt.ingestion.diarization import assign_speakers
from saad_sales_gpt.ingestion.transcription import transcribe
from saad_sales_gpt.models import (
    IngestionStatus,
    MediaItem,
    Platform,
    Segment,
    Source,
    SourceType,
    Transcript,
    ValidationIssue,
)
from saad_sales_gpt.validation import validate_media_item

logger = logging.getLogger(__name__)


def _fail(session: Session, media_item: MediaItem, message: str) -> None:
    media_item.ingestion_status = IngestionStatus.failed
    session.add(ValidationIssue(media_id=media_item.media_id, rule_id="INGEST", message=message))
    session.commit()
    logger.error("media_item=%s failed: %s", media_item.media_id, message)


def _download(session: Session, media_item: MediaItem, source: Source) -> bool:
    media_item.ingestion_status = IngestionStatus.downloading
    session.commit()

    try:
        if source.platform == Platform.youtube:
            fetched_yt = youtube.fetch_youtube_audio(media_item.url, media_item.media_id)
            if source.handle_or_channel == "unresolved":
                source.handle_or_channel = fetched_yt.channel_name
            media_item.raw_media_path = fetched_yt.audio_path
            media_item.published_date = fetched_yt.published_date
            media_item.duration_sec = fetched_yt.duration_sec
        else:
            fetched_ig = instagram.fetch_instagram_media(media_item.url, media_item.media_id)
            media_item.raw_media_path = fetched_ig.audio_path
            media_item.published_date = fetched_ig.published_date
            media_item.duration_sec = fetched_ig.duration_sec
            if fetched_ig.audio_path is None and source.source_type == SourceType.qa_insight and fetched_ig.caption:
                # R2: qa_insight with no audio is normal — use the caption as the answer text directly.
                transcript = Transcript(
                    media_id=media_item.media_id,
                    full_text=fetched_ig.caption,
                    language=None,
                    transcription_method="caption_direct",
                )
                session.add(transcript)
                session.flush()
                session.add(
                    Segment(
                        transcript_id=transcript.transcript_id,
                        text=fetched_ig.caption,
                        start_ms=0,
                        end_ms=0,
                        segment_type="qa_answer",
                    )
                )
                media_item.ingestion_status = IngestionStatus.transcribed
    except Exception as exc:  # noqa: BLE001 — yt-dlp/apify errors are wide; route to review, don't crash the batch
        _fail(session, media_item, f"download failed: {exc}")
        return False

    media_item.ingestion_status = IngestionStatus.downloaded
    session.commit()
    return True


def _transcribe(session: Session, media_item: MediaItem, source: Source) -> bool:
    if media_item.ingestion_status == IngestionStatus.transcribed:
        return True  # caption_direct path already produced a transcript
    if not media_item.raw_media_path:
        # R2 allows this for qa_insight without a caption either; nothing more to do here.
        return True

    media_item.ingestion_status = IngestionStatus.transcribing
    session.commit()

    try:
        result = transcribe(media_item.raw_media_path)
        transcript = Transcript(
            media_id=media_item.media_id,
            full_text=result.full_text,
            language=result.language,
            transcription_method=f"faster-whisper:{settings.whisper_model}",
            transcription_confidence=result.confidence,
        )
        session.add(transcript)
        session.flush()

        for raw_segment, speaker in assign_speakers(result.segments, source.source_type):
            session.add(
                Segment(
                    transcript_id=transcript.transcript_id,
                    speaker=speaker,
                    start_ms=raw_segment.start_ms,
                    end_ms=raw_segment.end_ms,
                    text=raw_segment.text,
                )
            )
    except Exception as exc:  # noqa: BLE001 — whisper/ffmpeg errors are wide; route to review, don't crash the batch
        _fail(session, media_item, f"transcription failed: {exc}")
        return False

    media_item.ingestion_status = IngestionStatus.transcribed
    session.commit()
    return True


def _validate(session: Session, media_item: MediaItem, source: Source) -> None:
    session.refresh(media_item)
    results = validate_media_item(session, media_item, source)
    media_item.ingestion_status = (
        IngestionStatus.needs_review if any(not r.passed for r in results) else IngestionStatus.ready
    )
    session.commit()


def ingest_media_item(session: Session, media_item: MediaItem) -> IngestionStatus:
    source = media_item.source
    if not _download(session, media_item, source):
        return media_item.ingestion_status
    if not _transcribe(session, media_item, source):
        return media_item.ingestion_status
    _validate(session, media_item, source)
    return media_item.ingestion_status


def run_pending(session: Session, limit: int = 20) -> list[tuple[str, IngestionStatus]]:
    pending = session.query(MediaItem).filter(MediaItem.ingestion_status == IngestionStatus.pending).limit(limit).all()
    return [(item.media_id, ingest_media_item(session, item)) for item in pending]
