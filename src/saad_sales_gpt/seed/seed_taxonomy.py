"""Seeds the starter taxonomy (spec Section 5) into TaxonomyEntry.

This is a starting point, not a fixed enum — per Section 4.3, more categories
and topics get added later as rows, with no code or schema change.
"""

from sqlalchemy.orm import Session

from saad_sales_gpt.models import TaxonomyEntry

PROSPECT_BACKGROUND = [
    ("sales", "Prospect already comes from a sales/business role."),
    ("social_media", "Prospect comes from a content/social/creator background."),
    ("technology", "Prospect comes from a technical/product/engineering background."),
    ("unspecified", "Default bucket when background isn't stated or can't be confidently inferred."),
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

    add_all("prospect_background", PROSPECT_BACKGROUND)
    add_all("segment_type", SEGMENT_TYPE)
    add_all("topic", TOPIC)

    session.commit()
