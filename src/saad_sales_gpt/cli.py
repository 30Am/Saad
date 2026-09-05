import typer
import uvicorn

from saad_sales_gpt.db import Base, SessionLocal, engine
from saad_sales_gpt.ingestion.instagram import discover_and_seed_media
from saad_sales_gpt.ingestion.pipeline import cleanup_transcribed_media, run_pending
from saad_sales_gpt.manager.chat import answer_question
from saad_sales_gpt.seed.seed_sources import seed_sources
from saad_sales_gpt.seed.seed_taxonomy import seed_taxonomy
from saad_sales_gpt.tagging import tag_pending_segments

app = typer.Typer(help="Saad Sales GPT — backend CLI")


@app.command()
def init_db() -> None:
    """Create tables. Prefer `alembic upgrade head` once migrations exist for this
    table; this is a quick path for local/dev setup."""
    Base.metadata.create_all(engine)
    typer.echo("tables created")


@app.command()
def seed() -> None:
    """Seed the starter taxonomy (Section 5) and Appendix A source list."""
    session = SessionLocal()
    try:
        seed_taxonomy(session)
        created = seed_sources(session)
        typer.echo(f"seeded taxonomy; created {len(created)} source(s)")
    finally:
        session.close()


@app.command()
def discover_instagram(limit: int = 50) -> None:
    """List posts/reels for every Instagram Source and create a pending MediaItem
    for each new one found — run this before `ingest` for Instagram content, since
    ingest only processes MediaItems that already exist. Needs
    SAAD_GPT_INSTAGRAM_COOKIES_FROM_BROWSER or SAAD_GPT_INSTAGRAM_COOKIES_FILE set
    (or SAAD_GPT_APIFY_API_TOKEN as a fallback) — see ingestion/instagram.py."""
    session = SessionLocal()
    try:
        created_counts = discover_and_seed_media(session, limit_per_source=limit)
        for handle, count in created_counts.items():
            typer.echo(f"{handle}: {count} new media item(s)")
        if not created_counts:
            typer.echo("no Instagram sources found — run `saad-gpt seed` first")
        elif not any(created_counts.values()):
            typer.echo("found 0 new items — check cookie/Apify auth is configured and working")
    finally:
        session.close()


@app.command()
def ingest(limit: int = 20) -> None:
    """Run the ingestion pipeline over pending MediaItems (Phase 2)."""
    session = SessionLocal()
    try:
        results = run_pending(session, limit=limit)
        for media_id, status in results:
            typer.echo(f"{media_id}: {status.value}")
        if not results:
            typer.echo("no pending media items")
    finally:
        session.close()


@app.command()
def cleanup_media() -> None:
    """Backfill: delete raw audio for already-transcribed MediaItems that predate the
    auto-cleanup ingestion now does after every successful transcription."""
    session = SessionLocal()
    try:
        cleaned = cleanup_transcribed_media(session)
        for media_id in cleaned:
            typer.echo(f"{media_id}: raw media deleted")
        if not cleaned:
            typer.echo("nothing to clean up")
    finally:
        session.close()


@app.command()
def tag(limit: int = 50) -> None:
    """Run Claude-assisted first-pass tagging over untagged Segments (Phase 3, R5).
    Requires SAAD_GPT_ANTHROPIC_API_KEY. Writes tagged_by=claude_auto, reviewed=False
    Tag rows — review with `POST /tags/{tag_id}/review`."""
    session = SessionLocal()
    try:
        results = tag_pending_segments(session, limit=limit)
        for segment_id, dimensions in results:
            typer.echo(f"{segment_id}: {', '.join(dimensions) or 'failed'}")
        if not results:
            typer.echo("no pending segments")
    except RuntimeError as exc:
        typer.echo(f"error: {exc}")
    finally:
        session.close()


@app.command()
def serve(host: str = "127.0.0.1", port: int = 8000, reload: bool = False) -> None:
    """Run the FastAPI app (Manager query API + admin endpoints)."""
    uvicorn.run("saad_sales_gpt.api.main:app", host=host, port=port, reload=reload)


@app.command()
def chat() -> None:
    """Interactive chat against the Manager (Section 8, Q5). Requires
    SAAD_GPT_ANTHROPIC_API_KEY. Same underlying evidence view as /manager/query —
    Claude only extracts filters here, it never answers from its own knowledge."""
    session = SessionLocal()
    typer.echo("Ask a sales question (Ctrl+D or 'exit' to quit).")
    try:
        while True:
            try:
                question = typer.prompt("you")
            except typer.Abort:  # Ctrl+D / Ctrl+C
                break
            if question.strip().lower() in {"exit", "quit"}:
                break
            try:
                result = answer_question(session, question)
            except RuntimeError as exc:
                typer.echo(f"error: {exc}")
                continue
            typer.echo(f"manager [{result.category}/{result.topic or '-'}]: {result.reply}")
    finally:
        session.close()


if __name__ == "__main__":
    app()
