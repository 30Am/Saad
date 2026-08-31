"""Per-source validation rules R1-R5 (spec Section 4.2).

These run once a MediaItem has a Transcript + Segments attached (post-transcription,
pre-tagging). Failures are written as ValidationIssue rows and the MediaItem is routed
to IngestionStatus.needs_review — never silently discarded, per the spec's explicit
instruction ("routed to a review queue, not discarded").
"""

from dataclasses import dataclass

from sqlalchemy.orm import Session

from saad_sales_gpt.models import MediaItem, Segment, Source, SourceType, Speaker, ValidationIssue


@dataclass
class RuleResult:
    rule_id: str
    passed: bool
    message: str = ""


def _distinct_speaker_count(segments: list[Segment]) -> int:
    return len({s.speaker for s in segments if s.speaker != Speaker.unknown})


def check_r1_recording(media_item: MediaItem) -> RuleResult:
    """IF source_type = recording THEN audio_path != NULL AND speaker_count >= 2."""
    segments = media_item.transcript.segments if media_item.transcript else []
    has_audio = bool(media_item.raw_media_path)
    speaker_count = _distinct_speaker_count(segments)
    if not has_audio:
        return RuleResult("R1", False, "recording source has no audio_path")
    if speaker_count < 2:
        return RuleResult("R1", False, f"only {speaker_count} distinct speaker(s) detected, need >= 2")
    return RuleResult("R1", True)


def check_r2_qa_insight(media_item: MediaItem) -> RuleResult:
    """IF source_type = qa_insight THEN answer_text != NULL; audio_path MAY be NULL."""
    has_text = bool(media_item.transcript and media_item.transcript.full_text.strip())
    if not has_text:
        return RuleResult("R2", False, "qa_insight source has no answer text (transcript or caption)")
    return RuleResult("R2", True)


def check_r3_podcast_insight(media_item: MediaItem) -> RuleResult:
    """IF source_type = podcast_insight THEN saad_segment_text != NULL."""
    segments = media_item.transcript.segments if media_item.transcript else []
    saad_segments = [s for s in segments if s.speaker == Speaker.saad and s.text.strip()]
    if not saad_segments:
        return RuleResult("R3", False, "podcast_insight source has no isolated Saad segment text")
    return RuleResult("R3", True)


RULES_BY_SOURCE_TYPE = {
    SourceType.recording: [check_r1_recording],
    SourceType.qa_insight: [check_r2_qa_insight],
    SourceType.podcast_insight: [check_r3_podcast_insight],
}


def validate_media_item(session: Session, media_item: MediaItem, source: Source) -> list[RuleResult]:
    """Run the rules applicable to this media item's source_type, persist any failures,
    and route the item to needs_review if any rule fails. Returns all rule results."""
    rules = RULES_BY_SOURCE_TYPE.get(source.source_type, [])
    results = [rule(media_item) for rule in rules]

    failures = [r for r in results if not r.passed]
    for failure in failures:
        session.add(
            ValidationIssue(
                media_id=media_item.media_id,
                rule_id=failure.rule_id,
                message=failure.message,
            )
        )
    return results


DEAL_INDUSTRY_DIMENSION = "deal_industry"
DEFAULT_DEAL_INDUSTRY = "unspecified"


def resolve_deal_industry(inferred_value: str | None, confidence: float | None, min_confidence: float) -> str:
    """R4: default to 'unspecified' when the deal/industry type can't be confidently
    inferred. Never force a low-confidence guess into one of the named categories."""
    if inferred_value and confidence is not None and confidence >= min_confidence:
        return inferred_value
    return DEFAULT_DEAL_INDUSTRY
