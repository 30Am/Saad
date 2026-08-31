"""Pydantic request/response models for the API layer."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from saad_sales_gpt.models import IngestionStatus, Platform, SourceType


class SourceCreate(BaseModel):
    platform: Platform
    handle_or_channel: str
    source_type: SourceType
    url: str


class SourceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    source_id: str
    platform: Platform
    handle_or_channel: str
    source_type: SourceType
    url: str
    created_at: datetime


class MediaItemCreate(BaseModel):
    source_id: str
    url: str


class MediaItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    media_id: str
    source_id: str
    url: str
    published_date: datetime | None
    duration_sec: float | None
    ingestion_status: IngestionStatus


class EvidenceItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    segment_id: str
    text: str
    speaker: str
    start_ms: int
    end_ms: int
    source_type: str
    source_url: str
    media_url: str
    category: str | None
    topic: str | None


class ManagerQueryOut(BaseModel):
    category_filter: str
    topic_filter: str | None
    grouped: dict[str, dict[str, list[EvidenceItemOut]]]
    empty_categories: list[str]
    synthesis: str | None = None
    synthesis_citations: list[str] = []


class ChatIn(BaseModel):
    question: str


class ChatOut(BaseModel):
    question: str
    category: str
    topic: str | None
    source_type: str | None
    reply: str
    evidence: ManagerQueryOut
