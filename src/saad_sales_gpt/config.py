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

    # Used only for optional Claude-assisted auto-tagging (R5) and the
    # synthesis view (Section 6.1 step 4). Both are skipped, not faked, if unset.
    anthropic_api_key: str | None = None
    claude_model: str = "claude-sonnet-5"

    # Apify token, used as a fallback fetcher for Instagram content that
    # yt-dlp cannot reach directly (see ingestion/instagram.py).
    apify_api_token: str | None = None


settings = Settings()
settings.media_root.mkdir(parents=True, exist_ok=True)
