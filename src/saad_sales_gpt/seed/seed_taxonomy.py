"""Seeds the starter taxonomy (spec Section 5) into TaxonomyEntry.

This is a starting point, not a fixed enum — per Section 4.3, more categories
and topics get added later as rows, with no code or schema change.
"""

from sqlalchemy.orm import Session

from saad_sales_gpt.models import TaxonomyEntry
from saad_sales_gpt.validation import DEAL_INDUSTRY_DIMENSION

# Category = the deal/industry type, per Amlan's answer to spec Section 8, Q2
# (not the prospect's personal background, which is what Section 5's draft assumed).
DEAL_INDUSTRY = [
    ("sales", "The deal is in the sales/business services industry."),
    ("social_media", "The deal is in the content/social/creator industry."),
    ("technology", "The deal is in the tech/product/engineering industry."),
    ("unspecified", "Default bucket when the deal's industry isn't stated or can't be confidently inferred."),
]

SEGMENT_TYPE = [
    ("opening", "Cold-open / opening lines of a call."),
    ("objection_handling", "Handling a prospect's objection."),
    ("pricing", "Pricing discussion."),
    ("closing", "Closing the call/deal."),
    ("rapport", "Rapport-building."),
    ("qa_answer", "An answer given in the @saadsells.value Q&A format."),
    ("insight", "General sales insight, e.g. from a podcast appearance."),
]

# Illustrative starters only (spec Section 6.2 examples) — expected to grow.
TOPIC = [
    ("pricing_objection", "Objection specifically about price."),
    ("opening", "Cold-open lines."),
    ("cold_open", "Alias/variant of opening, kept distinct pending Amlan confirmation."),
]


def seed_taxonomy(session: Session) -> None:
    existing = {(t.dimension, t.value) for t in session.query(TaxonomyEntry).all()}

    def add_all(dimension: str, entries: list[tuple[str, str]]) -> None:
        for value, description in entries:
            if (dimension, value) in existing:
                continue
            session.add(TaxonomyEntry(dimension=dimension, value=value, description=description))

    add_all(DEAL_INDUSTRY_DIMENSION, DEAL_INDUSTRY)
    add_all("segment_type", SEGMENT_TYPE)
    add_all("topic", TOPIC)

    session.commit()
