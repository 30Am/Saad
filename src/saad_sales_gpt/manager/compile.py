"""The Manager's compilation logic (spec Section 6).

R6 ("No Averaging") is the load-bearing rule here: this module returns the UNION
of matching segments, grouped by category then source, verbatim and attributed.
It never blends multiple segments into one paraphrased statement — see evidence_view
below, which is always the plain compiled facts. Synthesis (if requested) is built
strictly on top of that evidence and is generated separately, never silently merged in.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy.orm import Session, joinedload

from saad_sales_gpt.config import settings
from saad_sales_gpt.models import MediaItem, Segment, Source, SourceType, Tag, Transcript

ALL = "all"


@dataclass
class EvidenceItem:
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


@dataclass
class CompiledAnswer:
    category_filter: str
    topic_filter: str | None
    # grouped[category][source_type] -> list[EvidenceItem], per Section 6.1 step 3.
    grouped: dict[str, dict[str, list[EvidenceItem]]] = field(default_factory=dict)
    empty_categories: list[str] = field(default_factory=list)
    synthesis: str | None = None
    synthesis_citations: list[str] = field(default_factory=list)


def _segment_ids_for_tag(session: Session, dimension: str, value: str, include_unreviewed: bool) -> set[str]:
    query = session.query(Tag.segment_id).filter(Tag.tag_dimension == dimension, Tag.tag_value == value)
    if not include_unreviewed:
        query = query.filter(Tag.reviewed.is_(True))
    return {row[0] for row in query.all()}


def _tag_value(segment: Segment, dimension: str) -> str | None:
    for tag in segment.tags:
        if tag.tag_dimension == dimension:
            return tag.tag_value
    return None


def compile_answer(
    session: Session,
    category: str = ALL,
    topic: str | None = None,
    source_type: SourceType | None = None,
    include_unreviewed: bool = False,
) -> CompiledAnswer:
    """Section 6.1, steps 1-4 (evidence view). Synthesis (step 4b) is a separate call —
    see generate_synthesis() — so the two outputs stay "kept visibly separate" per spec.
    """
    result = CompiledAnswer(category_filter=category, topic_filter=topic)

    candidate_ids: set[str] | None = None
    if category != ALL:
        candidate_ids = _segment_ids_for_tag(session, "prospect_background", category, include_unreviewed)
    if topic:
        topic_ids = _segment_ids_for_tag(session, "topic", topic, include_unreviewed)
        candidate_ids = topic_ids if candidate_ids is None else candidate_ids & topic_ids

    query = session.query(Segment).options(
        joinedload(Segment.tags),
        joinedload(Segment.transcript).joinedload(Transcript.media_item).joinedload(MediaItem.source),
    )
    if candidate_ids is not None:
        if not candidate_ids:
            # Section 6.1 step 5: say so explicitly, never silently fall back.
            result.empty_categories.append(category if category != ALL else (topic or "requested filter"))
            return result
        query = query.filter(Segment.segment_id.in_(candidate_ids))

    segments = query.all()

    for segment in segments:
        media_item = segment.transcript.media_item
        source: Source = media_item.source
        if source_type is not None and source.source_type != source_type:
            continue

        seg_category = _tag_value(segment, "prospect_background") or "unspecified"
        seg_topic = _tag_value(segment, "topic")

        item = EvidenceItem(
            segment_id=segment.segment_id,
            text=segment.text,
            speaker=segment.speaker.value,
            start_ms=segment.start_ms,
            end_ms=segment.end_ms,
            source_type=source.source_type.value,
            source_url=source.url,
            media_url=media_item.url,
            category=seg_category,
            topic=seg_topic,
        )
        result.grouped.setdefault(seg_category, {}).setdefault(item.source_type, []).append(item)

    if not result.grouped:
        result.empty_categories.append(category if category != ALL else (topic or "requested filter"))

    return result


SYNTHESIS_SYSTEM_PROMPT = (
    "You write sales call scripts/playbooks strictly by rearranging and lightly connecting the "
    "provided evidence quotes. You must not invent claims, phrasing, or advice that is not "
    "grounded in the quotes given. After every claim, cite the segment_id(s) it came from in "
    "square brackets, e.g. [seg-123]. If the evidence is too thin to answer, say so."
)


def generate_synthesis(answer: CompiledAnswer) -> None:
    """Section 6.1 step 4, synthesis view — Claude-authored, built only on top of the
    evidence view, always cited. No-ops (leaves synthesis=None) if no API key is configured
    or there's no evidence to build from, rather than fabricating a Claude call."""
    if not settings.anthropic_api_key:
        return

    all_items = [item for by_source in answer.grouped.values() for items in by_source.values() for item in items]
    if not all_items:
        return

    import anthropic

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    evidence_block = "\n".join(f"[{i.segment_id}] ({i.category}/{i.source_type}) {i.text}" for i in all_items)

    response = client.messages.create(
        model=settings.claude_model,
        max_tokens=1024,
        system=SYNTHESIS_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": f"Evidence:\n{evidence_block}\n\nBuild the requested synthesis."}],
    )
    answer.synthesis = "".join(block.text for block in response.content if block.type == "text")
    answer.synthesis_citations = [i.segment_id for i in all_items]
