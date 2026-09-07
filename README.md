# Saad Sales GPT — Backend

Implements Phases 0-3 of the technical spec ("TECHNICAL SPECIFICATION — DRAFT
v0.1" Google Doc): the data schema and validation rules (Section 4), the source
registry (Section 2), the ingestion pipeline (Phase 2), Claude-assisted
first-pass tagging with a human-review gate (Phase 3, R5), and the Manager's
evidence-view compilation plus chat interface (Section 6, Section 8 Q5),
exposed over a small FastAPI service.

Diarization (`pyannote.audio`, context-based speaker identification — see
`ingestion/diarization.py`), segment merging into quote-sized spans
(`ingestion/merging.py`), and outcome tagging (did a call actually book a
meeting/close?) are now built. **Not yet built:** a review UI (the review
workflow itself is built — see the API section — just no frontend for it), and
background job processing for ingestion at scale. See "What's next" below.

Two ways to query the Manager without touching the API directly:
- **Claude Code skill** — `.claude/skills/saad-sales-gpt/SKILL.md` in this repo.
  Copy it to `~/.claude/skills/saad-sales-gpt/` to make it available in every
  Claude Code session; set `SAAD_GPT_PROJECT_DIR` to wherever you cloned this
  repo (see the skill file itself).
- **MCP server for Claude Desktop** — `src/saad_sales_gpt/mcp_server.py`, run
  via `saad-gpt mcp-serve`. Register it in `claude_desktop_config.json` (see
  "Sharing this project" below for the exact snippet).

Both work **without** `SAAD_GPT_ANTHROPIC_API_KEY` — the querying client's own
model maps your question to filters and writes the final answer; `compile_answer()`
itself is pure SQL/Python either way.

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
uv run saad-gpt discover-instagram  # lists Instagram posts/reels, creates pending MediaItems
uv run saad-gpt ingest        # runs pending MediaItems through download -> transcribe -> validate
uv run saad-gpt tag           # Claude-assisted first-pass tagging over untagged Segments (Phase 3, R5)
uv run saad-gpt serve         # FastAPI app
uv run saad-gpt chat          # interactive chat against the Manager (Section 8, Q5)
```

## API

- `GET/POST /sources` — the source registry (Section 2). POST to add a new
  account/channel — the spec calls this a "live registry," not a one-time import.
- `GET/POST /media-items` — individual reels/videos/posts under a source.
- `POST /ingestion/discover-instagram?limit=50` — same as `saad-gpt discover-instagram`.
  Lists posts/reels for every Instagram Source and creates a pending MediaItem for
  each new one — run this before ingesting Instagram content, since `/ingestion/run`
  only processes MediaItems that already exist.
- `POST /ingestion/run?limit=20` — same as `saad-gpt ingest`, over HTTP.
- `GET /manager/query?category=&topic=&source_type=&include_unreviewed=&include_synthesis=`
  — the Manager (Section 6). Always returns the evidence view (grouped, verbatim,
  attributed — R6, "No Averaging"); `include_synthesis=true` additionally asks
  Claude to build a cited synthesis strictly on top of that evidence.
- `POST /tags/{tag_id}/review` — marks a tag `reviewed=true` (R5's human-review gate;
  Amlan does this pass per the Q3 answer below).
- `POST /tagging/run?limit=50` — same as `saad-gpt tag`, over HTTP. Classifies
  `segment_type`, `deal_industry`, and `topic` for untagged Segments, choosing only
  from currently active `TaxonomyEntry` values (Section 4.3) and writing every result
  as `Tag(tagged_by=claude_auto, reviewed=False)` (R5) — including `segment_type`,
  which also sets the plain column on `Segment` but gets a Tag row too so it goes
  through the same review gate. R4's "default to unspecified, never force a guess"
  rule is enforced in code (`validation.resolve_deal_industry`), gated by
  `SAAD_GPT_TAGGING_MIN_CONFIDENCE`. Only requires the Anthropic key if there's
  actually something pending to tag.
- `POST /manager/chat` — the chat interface (Section 8, Q5). Body: `{"question": "..."}`.
  Claude only extracts filters from the question; `compile_answer`/`generate_synthesis`
  still do the actual answering, same as `/manager/query`. Returns 503 with a clear
  message if `SAAD_GPT_ANTHROPIC_API_KEY` isn't set. Also available as `saad-gpt chat`
  (interactive REPL).

## Architecture vs. the spec

| Spec section | Where |
| --- | --- |
| 4.1 Core entities | `models.py` |
| 4.2 Validation rules R1-R5 | `validation.py`, run from `ingestion/pipeline.py` |
| 4.3 Extensible taxonomy | `models.TaxonomyEntry`, seeded in `seed/seed_taxonomy.py` |
| Section 5 taxonomy | `seed/seed_taxonomy.py` |
| Section 6 Manager / R6 | `manager/compile.py`, `api/routes/manager.py` |
| Phase 3 tagging / R5 | `tagging.py`, `api/routes/tagging.py` |
| Section 7 "Backend" | this whole service |
| Section 7 "Claude" | `tagging.py`, `manager/compile.py:generate_synthesis`, `manager/chat.py` |

## Section 8 open questions — answered by Amlan (2026-08-31)

| Q | Answer | Where it lands |
| --- | --- | --- |
| Q1: What is Osiris? | It was a mistake — not part of the architecture. | N/A |
| Q2: What does "category" mean? | Deal/industry type — **not** the prospect's personal background, which is what Section 5's draft assumed. | `validation.DEAL_INDUSTRY_DIMENSION`, `seed/seed_taxonomy.py` |
| Q3: Who reviews Claude's auto-tags (R5)? | Amlan. | `POST /tags/{tag_id}/review` |
| Q4: PII policy for cold-call recordings? | Store raw, core-team only — no redaction. | `.gitignore` excludes media/`.env` as a stopgap, not a real access control |
| Q5: Interface for asking the Manager questions? | A chat tool. | `POST /manager/chat`, `saad-gpt chat` |
| Q6: Scale to plan for? | Hundreds of reels/videos, growing steadily. | Not yet addressed — current pipeline is synchronous; see "What's next" |

Other build decisions still worth knowing about:

- **Diarization:** real (`pyannote.audio`), but "plain" — it detects distinct
  speakers per recording, not WHICH one is Saad (no voice-ID/enrollment). For
  `recording`/`podcast_insight` items already ingested, speaker identity
  (`saad`/`prospect`/`host`) was instead reconstructed by reading each call's
  actual content (who opens with the pitch, who's welcomed as the guest) —
  see the per-source notes in `.claude/skills/saad-sales-gpt/SKILL.md` for
  exactly how confident that is per source. Diarization needs
  `SAAD_GPT_HF_TOKEN` (a HuggingFace token with the
  `pyannote/speaker-diarization-3.1`, `pyannote/segmentation-3.0`, and
  `pyannote/speaker-diarization-community-1` model licenses accepted) — see
  `ingestion/diarization.py`. Free to run (local compute), not a per-call API.
- **Instagram media discovery:** yt-dlp can fetch a single public post/reel by
  direct URL with no login, but *listing* everything on a profile needs an
  authenticated session. Set `SAAD_GPT_INSTAGRAM_COOKIES_FROM_BROWSER` (e.g.
  `chrome`, pulls from a logged-in local browser) or `SAAD_GPT_INSTAGRAM_COOKIES_FILE`
  (a Netscape-format `cookies.txt` export) to authenticate — see
  `ingestion/instagram.py:_cookie_opts`. Without either, listing falls back to
  Apify's Instagram Scraper actor if `SAAD_GPT_APIFY_API_TOKEN` is set, and
  finally to seeding media items manually via `POST /media-items`.
- **Transcription:** local `faster-whisper`, not a managed API — no per-minute
  cost, no data leaving the machine (relevant to the Q4 PII answer above).

## What's next (Phase 4+)

1. A human review UI for `reviewed=false` tags and `needs_review` media items
   (both already modeled and API-reachable — `ValidationIssue`,
   `POST /tags/{tag_id}/review` — just no frontend). At current volume
   (~3,000+ Tag rows), a full tag-by-tag review isn't realistic — a sampling
   tool (random batch per dimension, human judges accuracy) is the practical
   version of this, not built yet.
2. Voice-ID/speaker enrollment, if plain diarization's context-based speaker
   identification (see above) ever proves unreliable at larger scale.
3. Full manual (not keyword-based) tagging for `@saadsells`'s
   `objection_handling`/`pricing`/`rapport` segment types and the second-pass
   topic tags — currently mechanical pattern-matching, lower confidence than
   the deal_industry/speaker-identity/outcome work.
4. Background job processing for ingestion + tagging once volume grows toward
   the Q6 estimate (hundreds of items) — both are currently synchronous
   CLI/API-triggered runs and will become a bottleneck well before then.

## Sharing this project with someone else

The PII policy (Q4 above) means this only goes to people on the core team —
raw cold-call transcripts include real prospect names/numbers. For someone
who is:

1. **Get them the code**: they `git clone` this repo (or you send a copy).
2. **Get them the tagged data**: `pg_dump -F c` your local `saad_gpt` database
   and hand them the file directly (not via git — it's data, not code, and
   contains the PII from (1)). They restore it with:
   ```bash
   createdb saad_gpt   # or whatever they name it, matching their DATABASE_URL
   pg_restore -d saad_gpt --no-owner /path/to/the.dump
   ```
3. **Minimal `.env`**: just `SAAD_GPT_DATABASE_URL` pointing at their restored
   database — none of the ingestion-side keys (Anthropic/Apify/Instagram/HF)
   are needed just to *query* already-tagged content.
4. **Claude Code skill**: copy `.claude/skills/saad-sales-gpt/SKILL.md` (from
   their clone) to `~/.claude/skills/saad-sales-gpt/SKILL.md`, and set
   `SAAD_GPT_PROJECT_DIR` (e.g. in their shell profile) to wherever they
   cloned this repo. It'll then be available in every Claude Code session on
   their machine.
5. **MCP server for Claude Desktop**: add this to their
   `~/Library/Application Support/Claude/claude_desktop_config.json`
   (macOS path — adjust for their OS), replacing the path with wherever they
   cloned this repo, then fully quit and reopen Claude Desktop:
   ```json
   "saad-sales-gpt": {
     "command": "/path/to/their/uv",
     "args": ["run", "--directory", "/path/to/their/Saad/clone", "saad-gpt", "mcp-serve"]
   }
   ```
   (`which uv` finds the right value for `command` on their machine.)

## Tests

```bash
uv run pytest
uv run ruff check .
uv run ruff format .
uv run mypy src/
```

`tests/` uses an isolated in-memory SQLite engine — no Postgres needed to run
the suite. It covers R1-R4 (`test_validation.py`), the Manager's R6
"no averaging" compilation logic (`test_manager_compile.py`), the chat
interface (`test_chat.py`), and Phase 3 tagging including R4's confidence
gate and batch failure isolation (`test_tagging.py`) — Anthropic client
mocked out in all three.
