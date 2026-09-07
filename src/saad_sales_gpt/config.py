"""Application settings, loaded from environment / .env.

See README.md for the full list of open questions (spec Section 8) that
still govern some of these defaults (storage location, PII handling, etc).
"""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="SAAD_GPT_", extra="ignore")

    database_url: str = "postgresql+psycopg://saad_gpt:saad_gpt@localhost:5432/saad_gpt"

    # Local storage for downloaded media before/after transcription.
    media_root: Path = Path("./data/media")

    # Whisper model size for faster-whisper. "base" is a reasonable default;
    # bump to "small"/"medium" for better accuracy once volume is known (spec Section 8, Q6).
    whisper_model: str = "base"
    whisper_device: str = "cpu"
    whisper_compute_type: str = "int8"

    # Used only for optional Claude-assisted auto-tagging (R5), the synthesis view
    # (Section 6.1 step 4), and the chat interface (Section 8, Q5). All are skipped,
    # not faked, if unset.
    anthropic_api_key: str | None = None
    claude_model: str = "claude-sonnet-5"

    # R4: minimum confidence before an auto-classified value is trusted rather than
    # defaulted (deal_industry -> "unspecified") or dropped (topic/segment_type).
    tagging_min_confidence: float = 0.6

    # Apify token, used as a fallback fetcher for Instagram content that
    # yt-dlp cannot reach directly (see ingestion/instagram.py).
    apify_api_token: str | None = None

    # Instagram requires an authenticated session for yt-dlp to list a profile's
    # posts (not just to fetch one by direct URL) — see ingestion/instagram.py.
    # Set at most one. instagram_cookies_from_browser wins if both are set.
    instagram_cookies_from_browser: str | None = None  # e.g. "chrome", "safari", "firefox"
    instagram_cookies_file: Path | None = None  # path to a Netscape-format cookies.txt

    # HuggingFace access token for pyannote.audio's gated diarization model (see
    # ingestion/diarization.py). Requires accepting the license at
    # huggingface.co/pyannote/speaker-diarization-3.1 and .../segmentation-3.0.
    # Diarization degrades cleanly to Speaker.unknown for every segment if unset.
    hf_token: str | None = None


settings = Settings()
settings.media_root.mkdir(parents=True, exist_ok=True)
