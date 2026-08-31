"""Chat interface on top of the Manager (spec Section 8, Q5: "a chat tool").

A free-text question comes in, Claude maps it to the same filters the API's
GET /manager/query already takes (Section 6.1 step 1), then compile_answer()
and generate_synthesis() do the actual work — this module never lets Claude
answer from its own knowledge. If nothing matches, the reply says so plainly
(same R6 "no silent fallback" rule the API endpoint follows).
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from saad_sales_gpt.config import settings
from saad_sales_gpt.manager.compile import ALL, CompiledAnswer, compile_answer, generate_synthesis
from saad_sales_gpt.models import SourceType, TaxonomyEntry
from saad_sales_gpt.validation import DEAL_INDUSTRY_DIMENSION

EXTRACT_FILTERS_TOOL = "extract_filters"

CHAT_SYSTEM_PROMPT = (
    "You turn a sales-knowledge-base question into a structured filter for a search "
    "system. You do not answer the question yourself — you only extract filters. "
    "Call the extract_filters tool with your best reading of the question. If the "
    "question doesn't specify a category or topic, use the defaults (category='all', "
    "topic=null). Never invent a category or topic value that isn't in the allowed list."
)


@dataclass
class ChatAnswer:
    question: str
    category: str
    topic: str | None
    source_type: str | None
    reply: str
    compiled: CompiledAnswer


def _active_values(session: Session, dimension: str) -> list[str]:
    rows = session.query(TaxonomyEntry.value).filter(
        TaxonomyEntry.dimension == dimension, TaxonomyEntry.active.is_(True)
    )
    return [r[0] for r in rows.all()]


def _build_tool_schema(session: Session) -> dict:
    categories = [ALL, *_active_values(session, DEAL_INDUSTRY_DIMENSION)]
    topics = _active_values(session, "topic")
    return {
        "name": EXTRACT_FILTERS_TOOL,
        "description": "Extract search filters from a natural-language question.",
        "input_schema": {
            "type": "object",
            "properties": {
                "category": {"type": "string", "enum": categories, "description": "Deal/industry type, or 'all'."},
                "topic": {
                    "type": ["string", "null"],
                    "enum": [*topics, None],
                    "description": "Topic/segment focus, or null if the question doesn't narrow to one.",
                },
                "source_type": {
                    "type": ["string", "null"],
                    "enum": [s.value for s in SourceType] + [None],
                    "description": "Restrict to one source type, or null for all.",
                },
            },
            "required": ["category"],
        },
    }


def _extract_filters(session: Session, question: str) -> tuple[str, str | None, SourceType | None]:
    import anthropic

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    tool = _build_tool_schema(session)

    response = client.messages.create(
        model=settings.claude_model,
        max_tokens=256,
        system=CHAT_SYSTEM_PROMPT,
        tools=[tool],  # type: ignore[call-overload]  # dynamic schema, built at runtime from the taxonomy table
        tool_choice={"type": "tool", "name": EXTRACT_FILTERS_TOOL},
        messages=[{"role": "user", "content": question}],
    )

    tool_use = next(block for block in response.content if block.type == "tool_use")
    parsed = tool_use.input
    category = parsed.get("category", ALL) or ALL
    topic = parsed.get("topic") or None
    raw_source_type = parsed.get("source_type") or None
    source_type = SourceType(raw_source_type) if raw_source_type else None
    return category, topic, source_type


def answer_question(session: Session, question: str) -> ChatAnswer:
    if not settings.anthropic_api_key:
        raise RuntimeError("SAAD_GPT_ANTHROPIC_API_KEY is not set — the chat interface needs it to parse questions.")

    category, topic, source_type = _extract_filters(session, question)
    compiled = compile_answer(session, category=category, topic=topic, source_type=source_type)

    if compiled.empty_categories:
        missed = ", ".join(compiled.empty_categories)
        reply = f"No tagged material yet for: {missed}. Nothing to answer from — not falling back to a guess."
    else:
        generate_synthesis(compiled)
        reply = compiled.synthesis or "Evidence found, but synthesis is unavailable right now — see the evidence view."

    return ChatAnswer(
        question=question,
        category=category,
        topic=topic,
        source_type=source_type.value if source_type else None,
        reply=reply,
        compiled=compiled,
    )
