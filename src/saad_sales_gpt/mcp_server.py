"""MCP server exposing the Manager's compiled-quote search (spec Section 6) to any
MCP client — built specifically so Claude Desktop can query this project's tagged
Saad content directly, without needing SAAD_GPT_ANTHROPIC_API_KEY: the client's own
model does the natural-language-to-filter mapping (same job `manager/chat.py`'s
`_extract_filters()` would ask the Anthropic API to do), and `compile_answer()` itself
is pure SQL/Python — no API key needed either way. Mirrors the same process documented
in `.claude/skills/saad-sales-gpt/SKILL.md` for Claude Code, just reached through MCP
instead of a skill file.

Run with `uv run saad-gpt mcp-serve` (stdio transport — Claude Desktop launches it
itself per its config, so this is not meant to be started by hand day-to-day).
"""

from __future__ import annotations

from mcp.server.mcpserver import MCPServer

from saad_sales_gpt.db import SessionLocal
from saad_sales_gpt.manager.compile import ALL, compile_answer
from saad_sales_gpt.models import SourceType, TaxonomyEntry

INSTRUCTIONS = """
Answers sales/cold-calling questions using exact, verbatim quotes from Saad's real
recorded cold calls, Q&A coaching content, and podcast appearances (spec Section 6,
R6 "no averaging" — never paraphrase or blend multiple sources into one answer).

Always call list_taxonomy first if you haven't already this conversation, so you know
the current valid category/topic/outcome values — never invent one that isn't listed.

Then call query_saad_calls with your best reading of the question:
- category: a deal_industry value, or "all". Mostly "unspecified" in the data (most
  content is general coaching, not tied to one deal's industry) — don't over-rely on
  this filter.
- topic: narrows to a specific theme (e.g. "pricing_objection", "follow_up",
  "discovery"). Some topic tags are keyword-matched on short fragments, not a full
  read, so treat a thin result as "cast a wider net" rather than "nothing exists."
- source_type: "recording" (real 2-person cold calls, @saadsells), "qa_insight"
  (Saad solo, Q&A format, @saadsells.value), or "podcast_insight" (3 long-form
  appearances). Leave unset to search everything.
- outcome: ONLY meaningful for source_type="recording" — "meeting_booked",
  "closed_deal", "next_call_scheduled", "rejected", "undetermined". This is what
  turns "an example of Saad opening a call" into "an example from a call that
  actually got a meeting booked." If the question is about what technique works,
  set outcome="meeting_booked" or "closed_deal" rather than leaving it unset —
  that's the point of this field existing.

If the result says empty, say so plainly to the user — never fall back to answering
from your own general sales knowledge instead (same R6/R4 rule the rest of this
project follows). Otherwise, write your answer by rearranging and lightly connecting
the returned quotes — never invent a claim not grounded in them — and cite each
claim's segment_id in brackets, e.g. [a1b2c3d4-...].

Nothing returned here has been human-reviewed yet (R5) — treat it as Claude's own
first-pass judgment, not verified ground truth, if the stakes of being wrong are high.
""".strip()

server = MCPServer(name="saad-sales-gpt", instructions=INSTRUCTIONS)


@server.tool()
def list_taxonomy() -> dict[str, list[str]]:
    """Lists the current valid values for each filter dimension (deal_industry, topic,
    segment_type, outcome). Call this before query_saad_calls so you never pass a
    category/topic/outcome value that doesn't exist — the taxonomy grows over time and
    this is always the live, current list, not a fixed enum."""
    session = SessionLocal()
    try:
        dims = ("deal_industry", "topic", "segment_type", "outcome")
        return {
            dim: [t.value for t in session.query(TaxonomyEntry).filter_by(dimension=dim, active=True).all()]
            for dim in dims
        }
    finally:
        session.close()


@server.tool()
def query_saad_calls(
    category: str = ALL,
    topic: str | None = None,
    source_type: str | None = None,
    outcome: str | None = None,
) -> str:
    """Searches Saad's tagged content and returns verbatim matching quotes, grouped by
    category and source, each labeled with its speaker and segment_id for citation.
    Returns an explicit "no matches" message rather than ever falling back to nothing
    or guessing — never treat an empty result as license to answer from general
    knowledge instead. Unreviewed tags are included (nothing has been human-reviewed
    yet in this project), so treat results as Claude's first-pass judgment.
    """
    session = SessionLocal()
    try:
        parsed_source_type = SourceType(source_type) if source_type else None
        answer = compile_answer(
            session,
            category=category,
            topic=topic,
            source_type=parsed_source_type,
            outcome=outcome,
            include_unreviewed=True,
        )

        if answer.empty_categories:
            return f"No tagged material found for: {', '.join(answer.empty_categories)}. Nothing to answer from."

        lines = []
        for group_category, by_source in answer.grouped.items():
            for group_source_type, items in by_source.items():
                lines.append(f"=== category={group_category} source_type={group_source_type} ({len(items)}) ===")
                for item in items:
                    outcome_note = f" [outcome={item.outcome}]" if item.outcome else ""
                    lines.append(f"[{item.segment_id}] ({item.speaker}){outcome_note}: {item.text}")
        return "\n".join(lines)
    finally:
        session.close()


def main() -> None:
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
