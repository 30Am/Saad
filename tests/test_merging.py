"""Tests for merging consecutive same-speaker segments into quote-sized spans."""

from saad_sales_gpt.ingestion.merging import MAX_GAP_MS, MAX_SPAN_MS, Span, merge_spans


def test_merges_consecutive_same_speaker_spans() -> None:
    spans = [
        Span(start_ms=0, end_ms=2000, text="Hello there."),
        Span(start_ms=2000, end_ms=4000, text="How are you?"),
    ]

    result = merge_spans(spans)

    assert len(result) == 1
    assert result[0].text == "Hello there. How are you?"
    assert result[0].start_ms == 0
    assert result[0].end_ms == 4000


def test_does_not_merge_across_speaker_change() -> None:
    spans = [
        Span(start_ms=0, end_ms=2000, text="Hello there.", speaker="saad"),
        Span(start_ms=2000, end_ms=4000, text="Hi.", speaker="prospect"),
    ]

    result = merge_spans(spans)

    assert len(result) == 2
    assert [s.text for s in result] == ["Hello there.", "Hi."]


def test_does_not_merge_across_a_real_pause() -> None:
    spans = [
        Span(start_ms=0, end_ms=2000, text="First thought."),
        Span(start_ms=2000 + MAX_GAP_MS + 1, end_ms=5000, text="Unrelated later thought."),
    ]

    result = merge_spans(spans)

    assert len(result) == 2


def test_merges_across_a_small_gap_within_threshold() -> None:
    spans = [
        Span(start_ms=0, end_ms=2000, text="First thought."),
        Span(start_ms=2000 + MAX_GAP_MS, end_ms=5000, text="Continuation."),
    ]

    result = merge_spans(spans)

    assert len(result) == 1


def test_caps_merged_span_at_max_duration() -> None:
    # Three same-speaker segments back-to-back that together would exceed MAX_SPAN_MS.
    spans = [
        Span(start_ms=0, end_ms=MAX_SPAN_MS - 1000, text="Long monologue part one."),
        Span(start_ms=MAX_SPAN_MS - 1000, end_ms=MAX_SPAN_MS + 3000, text="Part two pushes it over."),
    ]

    result = merge_spans(spans)

    assert len(result) == 2  # the cap forces a split rather than one oversized span


def test_tracks_provenance_ids_through_merge() -> None:
    spans = [
        Span(start_ms=0, end_ms=1000, text="a", ids=["seg-1"]),
        Span(start_ms=1000, end_ms=2000, text="b", ids=["seg-2"]),
    ]

    result = merge_spans(spans)

    assert result[0].ids == ["seg-1", "seg-2"]


def test_empty_input_returns_empty_list() -> None:
    assert merge_spans([]) == []
