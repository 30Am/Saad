from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from saad_sales_gpt.db import get_session
from saad_sales_gpt.tagging import tag_pending_segments

router = APIRouter()


@router.post("/tagging/run")
def trigger_tagging(limit: int = 50, session: Session = Depends(get_session)) -> dict[str, list[str]]:
    """Phase 3: Claude-assisted first-pass tagging (R5) over untagged segments."""
    try:
        results = tag_pending_segments(session, limit=limit)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {segment_id: dimensions for segment_id, dimensions in results}
