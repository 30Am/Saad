"""Instagram fetch (spec Section 2.1: @saadsells, @saadsells.value).

Instagram lets yt-dlp fetch a single public post/reel by direct URL with no auth,
but *listing* everything on a profile needs an authenticated session — that's the
one thing an anonymous yt-dlp call can't do here (unlike YouTube). _cookie_opts()
supplies that session from either a locally logged-in browser
(SAAD_GPT_INSTAGRAM_COOKIES_FROM_BROWSER, e.g. "chrome") or an exported
cookies.txt (SAAD_GPT_INSTAGRAM_COOKIES_FILE). With neither set, listing falls
back to Apify if configured, then to manual seeding via POST /media-items.

One open item this module can't resolve on its own — flagged rather than guessed,
per spec Section 8, Q4 (PII): cold call recordings likely contain prospect
names/numbers. This module does not redact anything; it stores what it fetches.
Don't wire this up to serve content outside the core team until Q4 is answered.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import yt_dlp

from saad_sales_gpt.config import settings

APIFY_INSTAGRAM_SCRAPER_ACTOR = "apify/instagram-scraper"


def _cookie_opts() -> dict:
    """yt-dlp options that authenticate as whoever's session is configured — needed
    for profile listing, and it also makes single-post downloads less likely to hit
    Instagram's bot-detection wall (the same kind of block the YouTube run hit)."""
    if settings.instagram_cookies_from_browser:
        return {"cookiesfrombrowser": (settings.instagram_cookies_from_browser,)}
    if settings.instagram_cookies_file:
        return {"cookiefile": str(settings.instagram_cookies_file)}
    return {}


@dataclass
class FetchedMedia:
    audio_path: str | None
    caption: str | None
    published_date: datetime | None
    duration_sec: float | None


def list_instagram_media(profile_url: str, limit: int = 50) -> list[str]:
    """Best-effort enumeration of an account's post/reel URLs. Returns [] rather than
    raising when neither method works, so the caller can fall back to a manual seed list."""
    urls = _list_via_ytdlp(profile_url, limit)
    if urls:
        return urls
    if settings.apify_api_token:
        return _list_via_apify(profile_url, limit)
    return []


def _list_via_ytdlp(profile_url: str, limit: int) -> list[str]:
    ydl_opts = {"extract_flat": True, "quiet": True, "playlistend": limit, **_cookie_opts()}
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(profile_url, download=False)
        entries = info.get("entries") or []
        return [e["url"] for e in entries if e.get("url")]
    except Exception:  # noqa: BLE001 — any failure here should fall through to the Apify fallback
        return []


def _list_via_apify(profile_url: str, limit: int) -> list[str]:
    from apify_client import ApifyClient

    client = ApifyClient(settings.apify_api_token)
    run = client.actor(APIFY_INSTAGRAM_SCRAPER_ACTOR).call(
        run_input={"directUrls": [profile_url], "resultsType": "posts", "resultsLimit": limit}
    )
    if run is None:
        return []
    items = client.dataset(run.default_dataset_id).list_items().items
    return [item["url"] for item in items if item.get("url")]


def fetch_instagram_media(url: str, media_id: str) -> FetchedMedia:
    """Downloads a single post/reel. Raises on failure — the caller should route the
    MediaItem to needs_review rather than silently skip it (see pipeline.py)."""
    dest_dir = settings.media_root / "instagram"
    dest_dir.mkdir(parents=True, exist_ok=True)
    out_template = str(dest_dir / f"{media_id}.%(ext)s")

    ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": out_template,
        "postprocessors": [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "128"}],
        "quiet": True,
        **_cookie_opts(),
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)

    audio_path = str(Path(dest_dir / f"{media_id}.mp3"))
    published_date = None
    if info.get("upload_date"):
        published_date = datetime.strptime(info["upload_date"], "%Y%m%d").replace(tzinfo=UTC)

    return FetchedMedia(
        audio_path=audio_path if Path(audio_path).exists() else None,
        caption=info.get("description"),
        published_date=published_date,
        duration_sec=info.get("duration"),
    )
