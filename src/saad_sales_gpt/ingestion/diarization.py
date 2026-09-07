"""Speaker assignment for raw Whisper segments.

Plain diarization (spec Section 8, Q6 follow-up; decision 2026-09-06): pyannote.audio
detects distinct speaker clusters per recording via a pretrained model, but cannot tell
WHICH cluster is Saad — that needs a voice-ID layer (enrolling a Saad reference
embedding from the qa_insight content and matching against it), which is a separate,
not-yet-built step. Clusters are ranked by total talk time and the top two are labeled
Speaker.speaker_a / speaker_b purely so R1's "2+ distinct speakers" check has something
to count that isn't `unknown` — they carry no identity guarantee. R3 (podcast_insight,
which needs an isolated *Saad* segment specifically) is NOT fixed by this and stays
needs_review until voice-ID exists.

Requires SAAD_GPT_HF_TOKEN (a HuggingFace token with the pyannote/speaker-diarization-3.1
and pyannote/segmentation-3.0 model licenses accepted). With it unset, or if the model
fails to load or the diarization call itself fails, every segment falls back to
Speaker.unknown — same as the original stub — so ingestion never crashes on this.

  - qa_insight sources are Saad talking alone, so every segment is confidently saad
    (unchanged from the original stub — no diarization needed here).

Swap `_get_pipeline`/`_diarize_audio` for a voice-ID-aware implementation without
touching callers once that layer exists.
"""

import logging
import os
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path

from saad_sales_gpt.config import settings
from saad_sales_gpt.ingestion.transcription import RawSegment
from saad_sales_gpt.models import SourceType, Speaker

logger = logging.getLogger(__name__)

_REEXEC_GUARD_ENV = "_SAAD_GPT_DYLD_REEXEC"


def ensure_diarization_env() -> None:
    """torchcodec (pyannote's audio backend) dlopen's Homebrew's libav* shared
    libraries by @rpath, which isn't on the dynamic linker's search path by default —
    without it, loading the pipeline fails with "Could not load libtorchcodec" even
    though ffmpeg itself is installed and working fine for whisper. Setting
    DYLD_LIBRARY_PATH via os.environ from inside an already-running process has NO
    effect on macOS — dyld only reads it at process launch — so the only fix is to
    replace this process with an identical one that has it set from the start.
    Call this ONCE, before any ingestion work begins (never from inside diarization
    itself), so a restart can never happen mid-batch. No-ops on non-macOS, if already
    re-exec'd (guarded so it can't loop), or if Homebrew's lib dir isn't present."""
    if sys.platform != "darwin" or os.environ.get(_REEXEC_GUARD_ENV):
        return
    brew_lib = "/opt/homebrew/lib"
    if not os.path.isdir(brew_lib) or brew_lib in os.environ.get("DYLD_LIBRARY_PATH", ""):
        return
    env = os.environ.copy()
    existing = env.get("DYLD_LIBRARY_PATH")
    env["DYLD_LIBRARY_PATH"] = f"{brew_lib}:{existing}" if existing else brew_lib
    env[_REEXEC_GUARD_ENV] = "1"
    os.execve(sys.executable, [sys.executable, *sys.argv], env)


_pipeline = None
_pipeline_load_attempted = False


def _get_pipeline():
    """Lazily loads the pyannote pipeline at most once per process. Returns None (and
    stays None for the rest of the process) if unconfigured or the load fails."""
    global _pipeline, _pipeline_load_attempted
    if _pipeline_load_attempted:
        return _pipeline
    _pipeline_load_attempted = True
    if not settings.hf_token:
        return None
    try:
        from pyannote.audio import Pipeline

        _pipeline = Pipeline.from_pretrained("pyannote/speaker-diarization-3.1", token=settings.hf_token)
    except Exception:  # noqa: BLE001 — model download/license/torch issues are wide; degrade, don't crash
        logger.exception("failed to load pyannote diarization pipeline")
        _pipeline = None
    return _pipeline


@contextmanager
def _as_wav(audio_path: str):
    """torchcodec's frame-accurate cropping trips on MP3 (encoder priming samples throw
    off the expected sample count — see pyannote/audio#1868-style errors); converting to
    PCM WAV first sidesteps it entirely. Yields the original path unchanged if it's
    already a WAV, otherwise a temp WAV that's deleted afterwards."""
    if audio_path.lower().endswith(".wav"):
        yield audio_path
        return
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        tmp_path = tmp.name
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-i", audio_path, "-ar", "16000", "-ac", "1", tmp_path],
            capture_output=True,
            check=True,
        )
        yield tmp_path
    finally:
        Path(tmp_path).unlink(missing_ok=True)


def _diarize_audio(audio_path: str) -> list[tuple[float, float, str]]:
    """Returns (start_sec, end_sec, raw_cluster_label) turns, or [] on any failure."""
    pipeline = _get_pipeline()
    if pipeline is None:
        return []
    try:
        with _as_wav(audio_path) as wav_path:
            result = pipeline(wav_path)
    except Exception:  # noqa: BLE001 — audio/codec/ffmpeg issues are wide; degrade, don't crash the batch
        logger.exception("diarization failed for %s", audio_path)
        return []
    return [(turn.start, turn.end, label) for turn, _, label in result.speaker_diarization.itertracks(yield_label=True)]


def _overlap_ms(seg_start_ms: int, seg_end_ms: int, turn_start_sec: float, turn_end_sec: float) -> int:
    turn_start_ms, turn_end_ms = int(turn_start_sec * 1000), int(turn_end_sec * 1000)
    return max(0, min(seg_end_ms, turn_end_ms) - max(seg_start_ms, turn_start_ms))


def _assign_from_turns(
    segments: list[RawSegment], turns: list[tuple[float, float, str]]
) -> list[tuple[RawSegment, Speaker]]:
    if not turns:
        return [(seg, Speaker.unknown) for seg in segments]

    talk_time: dict[str, float] = {}
    for start, end, label in turns:
        talk_time[label] = talk_time.get(label, 0.0) + (end - start)
    ranked = sorted(talk_time, key=lambda label: talk_time[label], reverse=True)
    label_to_speaker = dict(zip(ranked[:2], (Speaker.speaker_a, Speaker.speaker_b), strict=False))

    assigned = []
    for seg in segments:
        best_label: str | None = None
        best_overlap = 0
        for start, end, label in turns:
            overlap = _overlap_ms(seg.start_ms, seg.end_ms, start, end)
            if overlap > best_overlap:
                best_overlap, best_label = overlap, label
        speaker = label_to_speaker.get(best_label, Speaker.unknown) if best_label is not None else Speaker.unknown
        assigned.append((seg, speaker))
    return assigned


def assign_speakers(
    segments: list[RawSegment], source_type: SourceType, audio_path: str | None = None
) -> list[tuple[RawSegment, Speaker]]:
    if source_type == SourceType.qa_insight:
        return [(seg, Speaker.saad) for seg in segments]
    if not audio_path:
        return [(seg, Speaker.unknown) for seg in segments]
    return _assign_from_turns(segments, _diarize_audio(audio_path))
