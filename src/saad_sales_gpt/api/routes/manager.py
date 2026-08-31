from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from saad_sales_gpt.db import get_session
from saad_sales_gpt.manager.compile import ALL, compile_answer, generate_synthesis
from saad_sales_gpt.models import SourceType, Tag
from saad_sales_gpt.schemas import ManagerQueryOut

router = APIRouter()


@router.get("/manager/query", response_model=ManagerQueryOut)
def query_manager(
    category: str = ALL,
    topic: str | None = None,
    source_type: SourceType | None = None,
    include_unreviewed: bool = False,
    include_synthesis: bool = False,
    session: Session = Depends(get_session),
) -> ManagerQueryOut:
    """Section 6: evidence view always returned; synthesis view only if asked for,
    and only ever built on top of the same evidence (R6 — never a blended average)."""
    answer = compile_answer(
        session,
        category=category,
        topic=topic,
        source_type=source_type,
        include_unreviewed=include_unreviewed,
    )
    if include_synthesis:
        generate_synthesis(answer)
    return ManagerQueryOut(**answer.__dict__)


@router.post("/tags/{tag_id}/review")
def review_tag(tag_id: str, session: Session = Depends(get_session)) -> dict[str, bool]:
    """R5: an auto-tag only becomes trusted for high-stakes answers once a human sets reviewed=True."""
    tag = session.get(Tag, tag_id)
    if tag is None:
        return {"reviewed": False}
    tag.reviewed = True
    session.commit()
    return {"reviewed": True}
