"""Claude-assisted first-pass segment tagging (spec Phase 3, Section 7 "Claude" (b)).

Writes segment_type, deal_industry, and topic. Every classification this module
produces is written as a Tag with tagged_by=claude_auto, reviewed=False (R5) —
including segment_type, which also lives as a plain column on Segment (per Section
4.1's schema) but gets a Tag row too so it goes through the same human-review gate
as everything else Claude classifies, via POST /tags/{tag_id}/review.

R4 (deal_industry must default to "unspecified" rather than a forced low-confidence
guess) and the equivalent "don't force it" behavior for topic/segment_type are
enforced here in code, not just by prompting — see tag_segment's confidence checks
against settings.tagging_min_confidence.

Only ever chooses from the currently active TaxonomyEntry values (Section 4.3) —
it does not invent new categories/topics; growing the taxonomy is a human decision.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from saad_sales_gpt.config import settings
from saad_sales_gpt.models import Segment, Tag, TaggedBy, TaxonomyEntry
from saad_sales_gpt.validation import DEAL_INDUSTRY_DIMENSION, resolve_deal_industry

logger = logging.getLogger(__name__)

SEGMENT_TYPE_DIMENSION = "segment_type"
TOPIC_DIMENSION = "topic"

CLASSIFY_TOOL = "classify_segment"

CLASSIFY_SYSTEM_PROMPT = (
    "You classify one sales-call transcript segment for a knowledge base index. You "
    "are not summarizing or paraphrasing the segment. You only pick taxonomy labels "
    "that best fit, from the allowed lists given to you — never invent a label that "
    "isn't in an allowed list. For deal_industry, if you can't confidently tell which "
    "industry the deal is in, choose 'unspecified' and report low confidence rather "
    "than guessing one of the named industries. For segment_type and topic, if nothing "
    "in the allowed list fits well, return null for that field with low confidence "
    "rather than forcing the closest option."
)


@dataclass
class TagResult:
    dimensions_written: list[str]


def _active_values(session: Session, dimension: str) -> list[str]:
    rows = session.query(TaxonomyEntry.value).filter(
        TaxonomyEntry.dimension == dimension, TaxonomyEntry.active.is_(True)
    )
    return [r[0] for r in rows.all()]


def _build_tool_schema(session: Session) -> dict:
    segment_types = _active_values(session, SEGMENT_TYPE_DIMENSION)
    deal_industries = _active_values(session, DEAL_INDUSTRY_DIMENSION)
    topics = _active_values(session, TOPIC_DIMENSION)

    def confidence_field(description: str) -> dict:
        return {"type": "number", "minimum": 0, "maximum": 1, "description": description}

    return {
        "name": CLASSIFY_TOOL,
        "description": "Classify a transcript segment against the current taxonomy.",
        "input_schema": {
            "type": "object",
            "properties": {
                "segment_type": {"type": ["string", "null"], "enum": [*segment_types, None]},
                "segment_type_confidence": confidence_field("Confidence in segment_type, 0-1."),
                "deal_industry": {"type": "string", "enum": deal_industries},
                "deal_industry_confidence": confidence_field("Confidence in deal_industry, 0-1."),
                "topic": {"type": ["string", "null"], "enum": [*topics, None]},
                "topic_confidence": confidence_field("Confidence in topic, 0-1."),
            },
            "required": ["deal_industry", "deal_industry_confidence"],
        },
    }


def _classify(session: Session, segment: Segment) -> dict:
    import anthropic

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    tool = _build_tool_schema(session)
    source = segment.transcript.media_item.source

    context = (
        f"Source type: {source.source_type.value}. Speaker: {segment.speaker.value}.\nSegment text:\n{segment.text}"
    )

    response = client.messages.create(
        model=settings.claude_model,
        max_tokens=256,
        system=CLASSIFY_SYSTEM_PROMPT,
        tools=[tool],  # type: ignore[call-overload]  # dynamic schema, built at runtime from the taxonomy table
        tool_choice={"type": "tool", "name": CLASSIFY_TOOL},
        messages=[{"role": "user", "content": context}],
    )
    tool_use = next(block for block in response.content if block.type == "tool_use")
    return dict(tool_use.input)


def tag_segment(session: Session, segment: Segment) -> TagResult:
    """Classifies one segment and writes claude_auto/unreviewed Tag rows (R5).
    Idempotent-ish in intent, not enforced here — callers should filter to
    untagged segments first (see tag_pending_segments)."""
    if not settings.anthropic_api_key:
        raise RuntimeError("SAAD_GPT_ANTHROPIC_API_KEY is not set — auto-tagging needs it to classify segments.")

    parsed = _classify(session, segment)
    written: list[str] = []

    deal_industry_raw = parsed.get("deal_industry")
    deal_industry_confidence = parsed.get("deal_industry_confidence")
    deal_industry_value = resolve_deal_industry(
        deal_industry_raw, deal_industry_confidence, settings.tagging_min_confidence
    )
    session.add(
        Tag(
            segment_id=segment.segment_id,
            tag_dimension=DEAL_INDUSTRY_DIMENSION,
            tag_value=deal_industry_value,
            tagged_by=TaggedBy.claude_auto,
            confidence=deal_industry_confidence,
            reviewed=False,
        )
    )
    written.append(DEAL_INDUSTRY_DIMENSION)

    topic_value = parsed.get("topic")
    topic_confidence = parsed.get("topic_confidence") or 0.0
    if topic_value and topic_confidence >= settings.tagging_min_confidence:
        session.add(
            Tag(
                segment_id=segment.segment_id,
                tag_dimension=TOPIC_DIMENSION,
                tag_value=topic_value,
                tagged_by=TaggedBy.claude_auto,
                confidence=topic_confidence,
                reviewed=False,
            )
        )
        written.append(TOPIC_DIMENSION)

    segment_type_value = parsed.get("segment_type")
    segment_type_confidence = parsed.get("segment_type_confidence") or 0.0
    if segment_type_value and segment_type_confidence >= settings.tagging_min_confidence:
        segment.segment_type = segment_type_value
        session.add(
            Tag(
                segment_id=segment.segment_id,
                tag_dimension=SEGMENT_TYPE_DIMENSION,
                tag_value=segment_type_value,
                tagged_by=TaggedBy.claude_auto,
                confidence=segment_type_confidence,
                reviewed=False,
            )
        )
        written.append(SEGMENT_TYPE_DIMENSION)

    session.commit()
    return TagResult(dimensions_written=written)


def _pending_segment_ids(session: Session, limit: int) -> list[str]:
    already_tagged = select(Tag.segment_id).where(Tag.tag_dimension == DEAL_INDUSTRY_DIMENSION)
    rows = (
        session.query(Segment.segment_id)
        .filter(Segment.text != "", ~Segment.segment_id.in_(already_tagged))
        .limit(limit)
        .all()
    )
    return [r[0] for r in rows]


def tag_pending_segments(session: Session, limit: int = 50) -> list[tuple[str, list[str]]]:
    """Tags every Segment that doesn't have a deal_industry Tag yet — that dimension
    is always written per segment (R4's default), so its presence means "already
    classified" regardless of what value it holds.

    Only requires the API key if there's actually something to tag — matches
    ingestion/pipeline.py's run_pending, which doesn't fail on an empty queue
    either. Isolates per-segment errors (e.g. a transient Anthropic API failure)
    so one bad segment doesn't lose progress on the rest of the batch.
    """
    pending_ids = _pending_segment_ids(session, limit)
    if pending_ids and not settings.anthropic_api_key:
        raise RuntimeError("SAAD_GPT_ANTHROPIC_API_KEY is not set — auto-tagging needs it to classify segments.")

    results: list[tuple[str, list[str]]] = []
    for segment_id in pending_ids:
        segment = session.get(Segment, segment_id)
        if segment is None:
            continue
        try:
            result = tag_segment(session, segment)
            results.append((segment_id, result.dimensions_written))
        except Exception as exc:  # noqa: BLE001 — isolate one bad segment, keep the batch going
            session.rollback()
            logger.error("segment=%s tagging failed: %s", segment_id, exc)
            results.append((segment_id, []))
    return results
