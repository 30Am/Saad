import typer
import uvicorn

from saad_sales_gpt.db import Base, SessionLocal, engine
from saad_sales_gpt.ingestion.pipeline import run_pending
from saad_sales_gpt.manager.chat import answer_question
from saad_sales_gpt.seed.seed_sources import seed_sources
from saad_sales_gpt.seed.seed_taxonomy import seed_taxonomy

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
