"""Speaker assignment for raw Whisper segments.

Real diarization (e.g. pyannote.audio) is NOT implemented here — it needs a
HuggingFace-gated model download and materially changes accuracy/latency, so it's
left as an explicit Phase 2+ follow-up rather than faked. Until then:

  - qa_insight sources are Saad talking alone, so every segment is confidently saad.
  - recording / podcast_insight sources need a real second voice separated out, which
    we can't do yet; segments are left as `unknown` so R1/R3 correctly route the item
    to needs_review (spec Section 4.2) instead of silently pretending it's tagged right.

Swap `assign_speakers` for a pyannote-backed implementation without touching callers.
"""

from saad_sales_gpt.ingestion.transcription import RawSegment
from saad_sales_gpt.models import SourceType, Speaker


def assign_speakers(segments: list[RawSegment], source_type: SourceType) -> list[tuple[RawSegment, Speaker]]:
    if source_type == SourceType.qa_insight:
        return [(seg, Speaker.saad) for seg in segments]
    return [(seg, Speaker.unknown) for seg in segments]
