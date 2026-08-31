from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from saad_sales_gpt.db import get_session
from saad_sales_gpt.models import MediaItem, Source
from saad_sales_gpt.schemas import MediaItemCreate, MediaItemOut, SourceCreate, SourceOut

router = APIRouter()


@router.get("/sources", response_model=list[SourceOut])
def list_sources(session: Session = Depends(get_session)) -> list[Source]:
    return session.query(Source).all()


@router.post("/sources", response_model=SourceOut)
def create_source(body: SourceCreate, session: Session = Depends(get_session)) -> Source:
    """Manual registry addition — the spec's "live registry" (Section 2) note means
    new accounts/channels get added over time, not just at seed time."""
    source = Source(**body.model_dump())
    session.add(source)
    session.commit()
    session.refresh(source)
    return source


@router.get("/media-items", response_model=list[MediaItemOut])
def list_media_items(
    status: str | None = None, source_id: str | None = None, session: Session = Depends(get_session)
) -> list[MediaItem]:
    query = session.query(MediaItem)
    if status:
        query = query.filter(MediaItem.ingestion_status == status)
    if source_id:
        query = query.filter(MediaItem.source_id == source_id)
    return query.all()


@router.post("/media-items", response_model=MediaItemOut)
def create_media_item(body: MediaItemCreate, session: Session = Depends(get_session)) -> MediaItem:
    media_item = MediaItem(**body.model_dump())
    session.add(media_item)
    session.commit()
    session.refresh(media_item)
    return media_item
