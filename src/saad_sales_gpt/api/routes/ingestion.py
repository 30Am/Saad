from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from saad_sales_gpt.db import get_session
from saad_sales_gpt.ingestion.pipeline import run_pending

router = APIRouter()


@router.post("/ingestion/run")
def trigger_ingestion(limit: int = 20, session: Session = Depends(get_session)) -> dict[str, str]:
    results = run_pending(session, limit=limit)
    return {media_id: status.value for media_id, status in results}
