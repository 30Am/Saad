"""Merges consecutive same-speaker transcript spans into coherent, quote-sized units.

Whisper's VAD-based segmentation cuts on brief pauses, producing segments that are
often sub-sentence or single-sentence fragments (median ~2s duration) even during
continuous, uninterrupted speech from one speaker -- real silence between same-speaker
segments is rare (median gap between them is 0ms; checked against real transcripts).
Left as-is, this makes every "atomic queryable unit" too atomic to work as a citation:
a compiled answer surfaces a wall of disconnected one-liners instead of a readable
quote, and per-segment tagging (topic keyword matches especially) lands on isolated
fragments disconnected from the sentence around them.

merge_spans() groups consecutive same-speaker spans into one, as long as the gap
between them stays under MAX_GAP_MS (a real continuation, not a pause) and merging
wouldn't push the group's total duration past MAX_SPAN_MS -- some of Saad's monologues
run 2+ minutes uninterrupted (checked against real data), and capping keeps merged
spans "quote sized" rather than becoming an unreadable wall of text under one citation.
"""

from dataclasses import dataclass, field

MAX_GAP_MS = 800
MAX_SPAN_MS = 15_000


@dataclass
class Span:
    start_ms: int
    end_ms: int
    text: str
    speaker: object = None  # opaque to this module -- compared by ==, never interpreted
    ids: list[str] = field(default_factory=list)  # optional provenance for callers that need it (e.g. a backfill)


def merge_spans(spans: list[Span]) -> list[Span]:
    """`spans` must already be ordered by start_ms. Never merges across a speaker
    change, a gap larger than MAX_GAP_MS, or past MAX_SPAN_MS total duration."""
    if not spans:
        return []

    merged: list[Span] = [spans[0]]
    for span in spans[1:]:
        current = merged[-1]
        gap = span.start_ms - current.end_ms
        combined_span_ms = span.end_ms - current.start_ms
        if span.speaker == current.speaker and gap <= MAX_GAP_MS and combined_span_ms <= MAX_SPAN_MS:
            merged[-1] = Span(
                start_ms=current.start_ms,
                end_ms=span.end_ms,
                text=f"{current.text} {span.text}".strip(),
                speaker=current.speaker,
                ids=current.ids + span.ids,
            )
        else:
            merged.append(span)
    return merged
