"""Seeds Source rows from the Appendix A raw source list in the spec doc.

The doc explicitly says the source spreadsheet "must be treated as a live registry,
not a one-time import" (Section 2) — this seed is the bootstrap for that registry,
not a replacement for it. Re-run is idempotent (matched by url).
"""

from sqlalchemy.orm import Session

from saad_sales_gpt.models import MediaItem, Platform, Source, SourceType

INSTAGRAM_SOURCES = [
    {
        "handle_or_channel": "saadsells",
        "source_type": SourceType.recording,
        "url": "https://www.instagram.com/saadsells/",
    },
    {
        "handle_or_channel": "saadsells.value",
        "source_type": SourceType.qa_insight,
        "url": "https://www.instagram.com/saadsells.value/",
    },
]

# One Source per video for now — the real host channel name is filled in by the
# ingestion pipeline once yt-dlp resolves the video's metadata (see ingestion/youtube.py).
YOUTUBE_PODCAST_URLS = [
    "https://www.youtube.com/watch?v=Moi2mxV3tE8",
    "https://www.youtube.com/watch?v=x3Rf2Yy97LM",
    "https://www.youtube.com/watch?v=BZv_N4I_THQ",
]


def seed_sources(session: Session) -> list[Source]:
    created: list[Source] = []

    existing_urls = {s.url for s in session.query(Source).all()}

    for entry in INSTAGRAM_SOURCES:
        if entry["url"] in existing_urls:
            continue
        source = Source(platform=Platform.instagram, **entry)
        session.add(source)
        created.append(source)

    for url in YOUTUBE_PODCAST_URLS:
        if url in existing_urls:
            continue
        source = Source(
            platform=Platform.youtube,
            handle_or_channel="unresolved",
            source_type=SourceType.podcast_insight,
            url=url,
        )
        session.add(source)
        session.flush()
        # An Instagram account is a feed (many MediaItems discovered by the ingestion
        # pipeline); a single podcast URL *is* the one MediaItem, so seed it directly.
        session.add(MediaItem(source_id=source.source_id, url=url))
        created.append(source)

    session.commit()
    return created
