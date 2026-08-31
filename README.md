# Saad Sales GPT — Backend

Implements Phases 0-2 of the technical spec ("TECHNICAL SPECIFICATION — DRAFT
v0.1" Google Doc): the data schema and validation rules (Section 4), the source
registry (Section 2), the ingestion pipeline (Phase 2), and the Manager's
evidence-view compilation (Section 6), exposed over a small FastAPI service.

**Not yet built:** Phase 3 (Claude-assisted tagging + human review workflow) and
Phase 5 (synthesis-layer polish). The Manager's synthesis view and the tagging
data model exist and are tested, but nothing populates `Tag` rows automatically
yet — see "What's next" below.

## Setup

```bash
uv sync
cp .env.example .env   # fill in DATABASE_URL at minimum

# Postgres must be running and reachable at SAAD_GPT_DATABASE_URL.
uv run alembic upgrade head
uv run saad-gpt seed          # taxonomy (Section 5) + Appendix A sources
uv run saad-gpt serve         # http://127.0.0.1:8000
```

## CLI

```bash
uv run saad-gpt init-db       # dev-only shortcut; prefer alembic upgrade head
uv run saad-gpt seed          # idempotent — safe to re-run
uv run saad-gpt ingest        # runs pending MediaItems through download -> transcribe -> validate
uv run saad-gpt serve         # FastAPI app
```

## API

- `GET/POST /sources` — the source registry (Section 2). POST to add a new
  account/channel — the spec calls this a "live registry," not a one-time import.
- `GET/POST /media-items` — individual reels/videos/posts under a source.
- `POST /ingestion/run?limit=20` — same as `saad-gpt ingest`, over HTTP.
- `GET /manager/query?category=&topic=&source_type=&include_unreviewed=&include_synthesis=`
  — the Manager (Section 6). Always returns the evidence view (grouped, verbatim,
  attributed — R6, "No Averaging"); `include_synthesis=true` additionally asks
  Claude to build a cited synthesis strictly on top of that evidence.
- `POST /tags/{tag_id}/review` — marks a tag `reviewed=true` (R5's human-review gate).

## Architecture vs. the spec

| Spec section | Where |
| --- | --- |
| 4.1 Core entities | `models.py` |
| 4.2 Validation rules R1-R5 | `validation.py`, run from `ingestion/pipeline.py` |
| 4.3 Extensible taxonomy | `models.TaxonomyEntry`, seeded in `seed/seed_taxonomy.py` |
| Section 5 taxonomy | `seed/seed_taxonomy.py` |
| Section 6 Manager / R6 | `manager/compile.py`, `api/routes/manager.py` |
| Section 7 "Backend" | this whole service |
| Section 7 "Claude" | `manager/compile.py:generate_synthesis` (synthesis only, so far) |

## Section 8 open questions — answered by Amlan (2026-08-31)

| Q | Answer | Where it lands |
| --- | --- | --- |
| Q1: What is Osiris? | It was a mistake — not part of the architecture. | N/A |
| Q2: What does "category" mean? | Deal/industry type — **not** the prospect's personal background, which is what Section 5's draft assumed. | `validation.DEAL_INDUSTRY_DIMENSION`, `seed/seed_taxonomy.py` |
| Q3: Who reviews Claude's auto-tags (R5)? | Amlan. | `POST /tags/{tag_id}/review` |
| Q4: PII policy for cold-call recordings? | Store raw, core-team only — no redaction. | `.gitignore` excludes media/`.env` as a stopgap, not a real access control |
| Q5: Interface for asking the Manager questions? | A chat tool. | Not built yet — see "What's next" |
| Q6: Scale to plan for? | Hundreds of reels/videos, growing steadily. | Not yet addressed — current pipeline is synchronous; see "What's next" |

Other build decisions still worth knowing about:

- **Diarization:** not implemented (see `ingestion/diarization.py` docstring).
  `recording` and `podcast_insight` items will currently fail R1/R3 and land in
  `needs_review` until real diarization (e.g. pyannote.audio) is wired in —
  that's the spec-compliant behavior ("routed to review, not discarded"), not a bug.
- **Instagram media discovery:** no reliable "list all reels for an account" API
  exists without login. `ingestion/instagram.py` tries yt-dlp, then Apify's
  Instagram Scraper actor if `SAAD_GPT_APIFY_API_TOKEN` is set; otherwise media
  items must be seeded manually via `POST /media-items`.
- **Transcription:** local `faster-whisper`, not a managed API — no per-minute
  cost, no data leaving the machine (relevant to the Q4 PII answer above).

## What's next (Phase 3+)

1. Claude-assisted first-pass tagging (`segment_type`, `deal_industry`, `topic`),
   writing `Tag(tagged_by=claude_auto, reviewed=False)` rows — the Manager and
   validation layers are already built to consume these correctly (see
   `tests/test_manager_compile.py`).
2. Chat interface on top of `manager/compile.py` (Q5) — free-text question in,
   Claude maps it to filters, evidence + synthesis come back conversationally.
3. Real diarization for `recording` / `podcast_insight` sources.
4. A human review UI/workflow for `reviewed=false` tags and `needs_review` media
   items (both already modeled — `ValidationIssue`, `Tag.reviewed` — just no UI).
5. Background job processing for ingestion once volume grows toward the Q6
   estimate (hundreds of items) — the current CLI/API-triggered run is synchronous
   and will become a bottleneck well before then.

## Tests

```bash
uv run pytest
uv run ruff check .
uv run ruff format .
uv run mypy src/
```

`tests/` uses an isolated in-memory SQLite engine — no Postgres needed to run
the suite. It covers R1-R4 (`test_validation.py`) and the Manager's R6
"no averaging" compilation logic (`test_manager_compile.py`).
