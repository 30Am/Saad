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
| Section 7 "Osiris" | **unplaced — still an open question, see below** |

## Design decisions made without a confirmed answer

The spec's own Section 8 flags these rather than blocking the draft; this build
made the following calls to keep moving, and they should be revisited with Amlan:

- **PII (Q4):** nothing is redacted. Cold-call recordings/transcripts are stored
  as fetched. Do not expose this service outside the core team until a redaction
  policy is decided — see `.gitignore` (media/`.env` excluded) as a stopgap, not
  a real control.
- **Diarization:** not implemented (see `ingestion/diarization.py` docstring).
  `recording` and `podcast_insight` items will currently fail R1/R3 and land in
  `needs_review` until real diarization (e.g. pyannote.audio) is wired in —
  that's the spec-compliant behavior ("routed to review, not discarded"), not a bug.
- **Instagram media discovery:** no reliable "list all reels for an account" API
  exists without login. `ingestion/instagram.py` tries yt-dlp, then Apify's
  Instagram Scraper actor if `SAAD_GPT_APIFY_API_TOKEN` is set; otherwise media
  items must be seeded manually via `POST /media-items`.
- **Transcription:** local `faster-whisper`, not a managed API — no per-minute
  cost, no data leaving the machine (relevant to the Q4 PII question above).
- **What "Osiris" is (Q1):** unknown. Nothing in this build assumes an Osiris
  component exists; if it turns out to be an orchestration/rules layer, the
  natural seam is `validation.py` + `ingestion/pipeline.py`.
- **What "category" means (Q2):** built as Section 5 describes — prospect's
  professional background — since that's what Section 5's working definition
  states. Flagged, not re-litigated here.

## What's next (Phase 3+)

1. Answer Section 8's open questions with Amlan — several (Q2, Q4, Q5) change
   what gets built next, not just how.
2. Claude-assisted first-pass tagging (`segment_type`, `prospect_background`,
   `topic`), writing `Tag(tagged_by=claude_auto, reviewed=False)` rows — the
   Manager and validation layers are already built to consume these correctly
   (see `tests/test_manager_compile.py`).
3. Real diarization for `recording` / `podcast_insight` sources.
4. A human review UI/workflow for `reviewed=false` tags and `needs_review` media
   items (both already modeled — `ValidationIssue`, `Tag.reviewed` — just no UI).

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
