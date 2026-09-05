from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from saad_sales_gpt.db import get_session
from saad_sales_gpt.ingestion.instagram import discover_and_seed_media
from saad_sales_gpt.ingestion.pipeline import run_pending

router = APIRouter()


@router.post("/ingestion/run")
def trigger_ingestion(limit: int = 20, session: Session = Depends(get_session)) -> dict[str, str]:
    results = run_pending(session, limit=limit)
    return {media_id: status.value for media_id, status in results}


@router.post("/ingestion/discover-instagram")
def discover_instagram(limit: int = 50, session: Session = Depends(get_session)) -> dict[str, int]:
    """Same as `saad-gpt discover-instagram` — lists posts/reels for every Instagram
    Source and creates a pending MediaItem for each new one, so /ingestion/run has
    something to process."""
    return discover_and_seed_media(session, limit_per_source=limit)
