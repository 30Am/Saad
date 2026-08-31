"""Whisper-based transcription (faster-whisper, runs locally — see spec Section 7 note
that transcription tooling is "intentionally left open for the developer to propose").
"""

from dataclasses import dataclass
from functools import lru_cache

from faster_whisper import WhisperModel

from saad_sales_gpt.config import settings


@dataclass
class RawSegment:
    start_ms: int
    end_ms: int
    text: str


@dataclass
class TranscriptionResult:
    full_text: str
    language: str
    confidence: float
    segments: list[RawSegment]


@lru_cache(maxsize=1)
def _model() -> WhisperModel:
    return WhisperModel(
        settings.whisper_model, device=settings.whisper_device, compute_type=settings.whisper_compute_type
    )


def transcribe(audio_path: str) -> TranscriptionResult:
    segments_iter, info = _model().transcribe(audio_path, vad_filter=True)
    raw_segments = [
        RawSegment(start_ms=int(seg.start * 1000), end_ms=int(seg.end * 1000), text=seg.text.strip())
        for seg in segments_iter
    ]
    full_text = " ".join(s.text for s in raw_segments).strip()
    return TranscriptionResult(
        full_text=full_text,
        language=info.language,
        confidence=float(info.language_probability),
        segments=raw_segments,
    )
