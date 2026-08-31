from fastapi import FastAPI

from saad_sales_gpt.api.routes import ingestion, manager, sources, tagging

app = FastAPI(title="Saad Sales GPT", version="0.1.0")

app.include_router(sources.router, tags=["sources"])
app.include_router(ingestion.router, tags=["ingestion"])
app.include_router(tagging.router, tags=["tagging"])
app.include_router(manager.router, tags=["manager"])


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
