"""Tests for turning discovered Instagram URLs into pending MediaItem rows —
the wiring that makes list_instagram_media's results actually reach the pipeline."""

from unittest.mock import patch

from sqlalchemy.orm import Session

from saad_sales_gpt.ingestion.instagram import discover_and_seed_media
from saad_sales_gpt.models import IngestionStatus, MediaItem, Platform, Source, SourceType


def test_creates_pending_media_items_for_new_urls(session: Session) -> None:
    source = Source(
        platform=Platform.instagram, handle_or_channel="saadsells", source_type=SourceType.recording, url="ig-url"
    )
    session.add(source)
    session.commit()

    with patch(
        "saad_sales_gpt.ingestion.instagram.list_instagram_media",
        return_value=["https://instagram.com/p/a", "https://instagram.com/p/b"],
    ):
        counts = discover_and_seed_media(session)

    assert counts == {"saadsells": 2}
    media_items = session.query(MediaItem).filter(MediaItem.source_id == source.source_id).all()
    assert {m.url for m in media_items} == {"https://instagram.com/p/a", "https://instagram.com/p/b"}
    assert all(m.ingestion_status == IngestionStatus.pending for m in media_items)


def test_does_not_duplicate_already_seeded_urls(session: Session) -> None:
    source = Source(
        platform=Platform.instagram, handle_or_channel="saadsells", source_type=SourceType.recording, url="ig-url"
    )
    session.add(source)
    session.flush()
    session.add(MediaItem(source_id=source.source_id, url="https://instagram.com/p/a"))
    session.commit()

    with patch(
        "saad_sales_gpt.ingestion.instagram.list_instagram_media",
        return_value=["https://instagram.com/p/a", "https://instagram.com/p/b"],
    ):
        counts = discover_and_seed_media(session)

    assert counts == {"saadsells": 1}  # only the new one
    urls = {m.url for m in session.query(MediaItem).filter(MediaItem.source_id == source.source_id).all()}
    assert urls == {"https://instagram.com/p/a", "https://instagram.com/p/b"}


def test_ignores_non_instagram_sources(session: Session) -> None:
    source = Source(
        platform=Platform.youtube, handle_or_channel="somechannel", source_type=SourceType.podcast_insight, url="yt-url"
    )
    session.add(source)
    session.commit()

    with patch("saad_sales_gpt.ingestion.instagram.list_instagram_media") as mock_list:
        counts = discover_and_seed_media(session)

    mock_list.assert_not_called()
    assert counts == {}
