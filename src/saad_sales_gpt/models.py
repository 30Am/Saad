"""ORM models for the entities defined in the spec, Section 4.1.

Fixed vocabularies (platform, source_type, ingestion_status, speaker, tagged_by)
are modeled as Python enums stored as plain strings (native_enum=False) so a new
value never requires a Postgres ALTER TYPE migration.

Open-ended vocabularies (tag_dimension / tag_value, segment_type) are NOT enums —
per Section 4.3 they are governed by the TaxonomyEntry lookup table instead, so
new categories/topics can be added with a row insert, not a schema change.
"""

import enum
import uuid
from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, Enum, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from saad_sales_gpt.db import Base


def _uuid() -> str:
    return str(uuid.uuid4())


class Platform(enum.StrEnum):
    instagram = "instagram"
    youtube = "youtube"


class SourceType(enum.StrEnum):
    recording = "recording"  # @saadsells — cold call recordings (R1)
    qa_insight = "qa_insight"  # @saadsells.value — Q&A / objection insight (R2)
    podcast_insight = "podcast_insight"  # YouTube podcasts (R3)


class IngestionStatus(enum.StrEnum):
    pending = "pending"
    downloading = "downloading"
    downloaded = "downloaded"
    transcribing = "transcribing"
    transcribed = "transcribed"
    tagging = "tagging"
    ready = "ready"
    failed = "failed"
    needs_review = "needs_review"  # routed here by R1-R3 validation, not discarded
    duplicate = "duplicate"  # same underlying recording re-posted at a different URL, transcript/segments removed


class Speaker(enum.StrEnum):
    saad = "saad"
    prospect = "prospect"
    host = "host"
    unknown = "unknown"  # pending diarization / review
    # Plain diarization (pyannote) distinguishes speakers per-recording but can't tell
    # WHICH one is Saad without a voice-ID layer (not built) — these two carry no
    # identity guarantee, they only exist so R1's "2+ distinct speakers" check has
    # something to count that isn't `unknown`. See ingestion/diarization.py.
    speaker_a = "speaker_a"
    speaker_b = "speaker_b"


class TaggedBy(enum.StrEnum):
    human = "human"
    claude_auto = "claude_auto"


class Source(Base):
    """One row per account/channel (spec Section 4.1)."""

    __tablename__ = "sources"

    source_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    platform: Mapped[Platform] = mapped_column(Enum(Platform, native_enum=False, length=20), nullable=False)
    handle_or_channel: Mapped[str] = mapped_column(String(255), nullable=False)
    source_type: Mapped[SourceType] = mapped_column(Enum(SourceType, native_enum=False, length=20), nullable=False)
    url: Mapped[str] = mapped_column(String(500), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))

    media_items: Mapped[list["MediaItem"]] = relationship(back_populates="source", cascade="all, delete-orphan")


class MediaItem(Base):
    """One row per reel/video/post (spec Section 4.1)."""

    __tablename__ = "media_items"

    media_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    source_id: Mapped[str] = mapped_column(ForeignKey("sources.source_id"), nullable=False)
    url: Mapped[str] = mapped_column(String(500), nullable=False, unique=True)
    published_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_sec: Mapped[float | None] = mapped_column(Float, nullable=True)
    raw_media_path: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    # Set once the raw file at raw_media_path is deleted post-transcription to save disk
    # (see ingestion/pipeline.py:_cleanup_raw_media). raw_media_path itself is kept as a
    # record that audio existed and was processed — R1's "audio_path != NULL" check is
    # about that, not about whether the file is still retained on disk.
    raw_media_deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ingestion_status: Mapped[IngestionStatus] = mapped_column(
        Enum(IngestionStatus, native_enum=False, length=20), default=IngestionStatus.pending
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC)
    )

    source: Mapped[Source] = relationship(back_populates="media_items")
    transcript: Mapped["Transcript | None"] = relationship(
        back_populates="media_item", uselist=False, cascade="all, delete-orphan"
    )
    validation_issues: Mapped[list["ValidationIssue"]] = relationship(
        back_populates="media_item", cascade="all, delete-orphan"
    )


class Transcript(Base):
    """spec Section 4.1."""

    __tablename__ = "transcripts"

    transcript_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    media_id: Mapped[str] = mapped_column(ForeignKey("media_items.media_id"), nullable=False, unique=True)
    full_text: Mapped[str] = mapped_column(Text, nullable=False)
    language: Mapped[str | None] = mapped_column(String(10), nullable=True)
    transcription_method: Mapped[str] = mapped_column(String(100), nullable=False)
    transcription_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    transcribed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))

    media_item: Mapped[MediaItem] = relationship(back_populates="transcript")
    segments: Mapped[list["Segment"]] = relationship(back_populates="transcript", cascade="all, delete-orphan")


class Segment(Base):
    """The atomic, queryable unit (spec Section 4.1)."""

    __tablename__ = "segments"

    segment_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    transcript_id: Mapped[str] = mapped_column(ForeignKey("transcripts.transcript_id"), nullable=False)
    speaker: Mapped[Speaker] = mapped_column(Enum(Speaker, native_enum=False, length=20), default=Speaker.unknown)
    start_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    end_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    # Free string, validated against TaxonomyEntry(dimension="segment_type") — see Section 4.3.
    segment_type: Mapped[str | None] = mapped_column(String(100), nullable=True)

    transcript: Mapped[Transcript] = relationship(back_populates="segments")
    tags: Mapped[list["Tag"]] = relationship(back_populates="segment", cascade="all, delete-orphan")


class Tag(Base):
    """spec Section 4.1 / R5."""

    __tablename__ = "tags"

    tag_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    segment_id: Mapped[str] = mapped_column(ForeignKey("segments.segment_id"), nullable=False)
    tag_dimension: Mapped[str] = mapped_column(String(100), nullable=False)
    tag_value: Mapped[str] = mapped_column(String(100), nullable=False)
    tagged_by: Mapped[TaggedBy] = mapped_column(Enum(TaggedBy, native_enum=False, length=20), nullable=False)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    reviewed: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))

    segment: Mapped[Segment] = relationship(back_populates="tags")


class TaxonomyEntry(Base):
    """Lookup table backing tag_dimension/tag_value and segment_type (spec Section 4.3).

    Adding a new category or topic is a row insert here, never a schema migration.
    """

    __tablename__ = "taxonomy_entries"
    __table_args__ = (UniqueConstraint("dimension", "value", name="uq_taxonomy_dimension_value"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    dimension: Mapped[str] = mapped_column(String(100), nullable=False)
    value: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class ValidationIssue(Base):
    """Review queue for records that fail R1-R3 (spec Section 4.2) — flagged, not discarded."""

    __tablename__ = "validation_issues"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    media_id: Mapped[str] = mapped_column(ForeignKey("media_items.media_id"), nullable=False)
    rule_id: Mapped[str] = mapped_column(String(10), nullable=False)
    message: Mapped[str] = mapped_column(String(1000), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    resolved: Mapped[bool] = mapped_column(Boolean, default=False)

    media_item: Mapped[MediaItem] = relationship(back_populates="validation_issues")
