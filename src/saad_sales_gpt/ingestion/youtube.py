"""YouTube fetch: metadata + audio download via yt-dlp (spec Section 2.2)."""

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import yt_dlp

from saad_sales_gpt.config import settings


@dataclass
class FetchedMedia:
    audio_path: str
    channel_name: str
    published_date: datetime | None
    duration_sec: float | None


def fetch_youtube_audio(url: str, media_id: str) -> FetchedMedia:
    dest_dir = settings.media_root / "youtube"
    dest_dir.mkdir(parents=True, exist_ok=True)
    out_template = str(dest_dir / f"{media_id}.%(ext)s")

    ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": out_template,
        "postprocessors": [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "128"}],
        "quiet": True,
        "noplaylist": True,
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)

    audio_path = str(Path(dest_dir / f"{media_id}.mp3"))
    published_date = None
    if info.get("upload_date"):
        published_date = datetime.strptime(info["upload_date"], "%Y%m%d").replace(tzinfo=UTC)

    return FetchedMedia(
        audio_path=audio_path,
        channel_name=info.get("channel") or info.get("uploader") or "unresolved",
        published_date=published_date,
        duration_sec=info.get("duration"),
    )
