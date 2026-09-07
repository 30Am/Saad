---
name: saad-sales-gpt
description: Answer sales questions using Saad's real cold-call/Q&A content, compiling exact quotes from Postgres (spec Section 6, R6 "no averaging") — use when the user asks a sales question meant to be answered from Saad's own material, or explicitly invokes this skill.
---

# Saad Sales GPT — query skill

Answers a sales question by compiling the **exact, verbatim** matching quotes from
Saad's tagged transcript segments in Postgres — never by paraphrasing or averaging
multiple sources into one generic answer (spec Section 6, R6). This skill exists so
the Manager can be used **without** `SAAD_GPT_ANTHROPIC_API_KEY` — the project's own
`saad-gpt chat` CLI / `manager/chat.py` normally calls the Anthropic API twice (once to
extract filters from the question, once to synthesize the final answer), which costs
money outside this session. This skill has *you* — the Claude Code session already
running — do both of those steps yourself, for free, instead of the app billing a
separate API key for them. `compile_answer()` itself is pure SQL/Python, no API needed
either way.

This skill is global (lives in `~/.claude/skills/`), so it's available in every Claude
Code session regardless of your current working directory — every command below uses
`--directory "$SAAD_GPT_PROJECT_DIR"` rather than assuming you're already `cd`'d into
the project. **Set `SAAD_GPT_PROJECT_DIR` once** to wherever you cloned this repo (e.g.
in your shell profile: `export SAAD_GPT_PROJECT_DIR=/path/to/your/Saad/clone`) — this
makes the skill portable across machines/users instead of hardcoding one person's path.
If it's unset, the commands below fall back to `/Users/amlannttripathy/Downloads/Saad`.

## Current data scope (as of 2026-09-06 — re-check if this feels stale)

All 5 sources are tagged now: both Instagram accounts and all 3 YouTube podcast
appearances (220 `ready` MediaItems total). Coverage and confidence differ a lot by
source and dimension though — read the per-source notes below before trusting a thin
result as "there's nothing on this," since for several dimensions it may just mean
"not tagged at that granularity yet."

**Segments are merged, quote-sized spans, not raw Whisper chunks.** Whisper's VAD-based
segmentation originally produced ~9,788 fragments across these 220 items — often
sub-sentence, median ~2 seconds each — which made every compiled "quote" a wall of
disconnected one-liners. `ingestion/merging.py`'s `merge_spans()` collapses consecutive
same-speaker fragments (within an 800ms gap, capped at 15s total span so a 2+ minute
monologue doesn't become one unreadable block) into coherent spans; this ran as a
backfill on all existing content (9,788 → 2,772 segments, tags migrated onto the merged
result) and is now wired into `pipeline.py` itself, so all future ingestion produces
properly-sized segments from the start — nothing extra to do here going forward. A
Postgres backup from just before the backfill exists at
`/private/tmp/claude-501/.../scratchpad/pre_merge_backup.dump` (session-scoped path —
may not survive between sessions; re-dump before any future destructive migration).

- Every tag was written with `tagged_by=claude_auto, reviewed=False` — nobody has
  human-reviewed them yet (that's `POST /tags/{tag_id}/review`, still a manual TODO).
  Because of this, **you must call `compile_answer(..., include_unreviewed=True)`** —
  the default (`False`) will silently return nothing, since every tag in the DB right
  now is unreviewed.

**`@saadsells.value`** (qa_insight, 108 items / 395 merged segments — Saad talking
alone, Q&A format):
- `deal_industry` is overwhelmingly `"unspecified"` (by design, per R4 — this is
  general sales coaching illustrated with varied hypothetical scenarios, not
  documentation of one specific deal's industry). Only one item is `"technology"`
  (an AI-voice-bots answer). `topic` is the more useful filter here.
- `topic`: `pricing_objection` (~7 items), `opening` (~2 items). Everything else has no
  topic tag — most content doesn't fit the current thin topic taxonomy (R4's "don't
  force it" applies to topic too).
- `segment_type` is uniformly `"qa_answer"` (matches this source's taxonomy description
  exactly).

**`@saadsells`** (recording, **98 ready items** / 1,083 merged segments — real
two-person cold calls; originally 109, but 11 turned out to be the same underlying
call re-posted at a different URL — confirmed by identical `duration_sec`, not just
similar text, since Saad genuinely reuses scripts across different real prospects too
and that's legitimate distinct evidence, not duplication. Deduped items are marked
`IngestionStatus.duplicate` with their Transcript/Segments/Tags removed, so they can
never surface in a query — see `ingestion/models.py`'s `IngestionStatus` enum):
- **`outcome` is tagged on every call** — `meeting_booked` (39), `undetermined` (31),
  `next_call_scheduled` (19), `rejected` (5), `closed_deal` (4) — determined by reading
  each call's actual ending, not inferred from technique. This is what makes the skill
  useful for cold-calling specifically rather than just a searchable transcript
  archive: filter compile_answer results to segments whose *call* had a given outcome
  (join on `Segment.transcript_id` matching a transcript that has an `outcome` tag of
  the value you want) to answer "how does Saad open a call that actually got a meeting
  booked," not just "here's an example of Saad opening a call." `undetermined` is
  honest, not a failure to classify — many of these calls end on a vague "I'll be in
  touch" with no confirmable next step either way.
- **Speaker identity was reconstructed from context**, not from voice-ID: plain
  diarization (see `ingestion/diarization.py`) only gives anonymous `speaker_a`/
  `speaker_b`, but reading every call, `speaker_a` (the higher-talk-time cluster) was
  Saad with zero ambiguous cases *except* one call (`78de81ad-...`) with genuinely
  unclear turn-taking in short, choppy exchanges — already tagged `unspecified` for
  that reason. Segments are relabeled to real `Speaker.saad` / `Speaker.prospect`
  values, so citing "Saad said X" from a recording is trustworthy, but treat any single
  very short, ambiguous-sounding quote with a little more skepticism than a long clear
  one.
- `deal_industry`: mostly `"social_media"` (Saad pitching his own organic-content/video
  production company — HOS/HHS/H2S/TCU are all the same business, differently
  introduced call to call), a smaller `"sales"` cluster (his own sales-coaching program,
  "House of Saad"), and `"unspecified"` for calls with no identifiable deal (a food-order
  incentive program called House of Biryani, training/roleplay recordings, generic
  negotiation fragments where the actual deal isn't clear).
- `segment_type`: `"opening"`/`"closing"` via a narrow keyword rule on Saad's own
  first/last couple of turns (e.g. "this is a cold call", "have an amazing day"), plus
  `"objection_handling"`/`"pricing"`/`"rapport"` via broader keyword rules — all of this
  is mechanical pattern-matching, not a full per-span manual read, so treat it as
  lower-confidence than the deal_industry/speaker-identity work (spot-checking found
  mostly-good but not perfect results — e.g. an occasional false-positive
  `objection_handling` tag from a coincidental keyword match with no real objection in
  it). Most segments still have no segment_type at all; absence doesn't mean "not
  applicable," it may just mean "not yet classified at that granularity."
- `topic`: `pricing_objection` on the 2-3 calls with explicit price negotiation, plus a
  second pass added `follow_up`/`enterprise_sales`/`disqualification`/`trust_building`/
  `referrals`/`mindset`/`discovery`/`lead_generation`/`high_ticket` via keyword match —
  see the taxonomy expansion note below.

**`podcast_insight`** (3 YouTube appearances — Peter Cardoz's "Student of Sales", the
saadsells channel's own masterclass livestream, and a Think School interview; 220
media items overall now includes these 3; 1,294 merged segments combined — 539 Peter
Cardoz / 412 saadsells masterclass / 343 Think School):
- Their raw audio had been deleted after the original ingestion (before diarization
  existed), so this required a full re-download + re-transcribe + re-diarize backfill,
  not just a tagging pass on top of existing segments.
- **Speaker identity** (`saad` vs `host`) was determined the same context-based way as
  `@saadsells` — reading each video's opening (the host's welcome/intro) and closing
  (the host's thank-you) to confirm which diarized cluster is Saad. All 3 confirmed
  cleanly, including the masterclass video which is really a solo livestream (originally
  658 Saad segments vs. 4 stray secondary-voice ones, pre-merge) rather than a
  two-person interview, so `host` there loosely means "any other voice," not literally
  an interviewer.
- `deal_industry` is blanket `"unspecified"` for every segment in these 3 videos — same
  R4 rationale as `@saadsells.value` (general interview/training content, not one
  documented deal), applied without per-segment judgment given the volume.
- `segment_type` is `"insight"` on every Saad segment (matches the taxonomy's own
  description of that value: "General sales insight, e.g. from a podcast appearance").
  Host segments have no segment_type.
- `topic`: same keyword-pattern scan as the second Instagram pass (see below) — not a
  full manual read given the volume, so treat topic coverage here as an aid to
  retrieval, not a precise index.

**Topic taxonomy was expanded** beyond the original 3 values (`pricing_objection`,
`opening`, `cold_open`) to 9 more, reflecting recurring themes actually seen across all
sources: `follow_up`, `discovery`, `disqualification`, `referrals`, `enterprise_sales`,
`high_ticket`, `lead_generation`, `trust_building`, `mindset`. These 9 were applied via
keyword-pattern matching (e.g. `\bdisqualif`, `\bhigh[\s-]?ticket\b`) chosen for
specificity over broad common words — this is meaningfully lower-confidence and lower-
context than the original per-item topic tags (a Whisper segment is short, so a keyword
hit tags one small fragment, not the surrounding discussion it's part of). Good for
casting a wider net, not a substitute for reading the returned quote in context.

## Steps

1. **Check the live taxonomy** (it can grow independently of this doc):
   ```bash
   uv run --directory "${SAAD_GPT_PROJECT_DIR:-/Users/amlannttripathy/Downloads/Saad}" python -c "
   from saad_sales_gpt.db import SessionLocal
   from saad_sales_gpt.models import TaxonomyEntry
   session = SessionLocal()
   for dim in ('deal_industry', 'topic', 'segment_type', 'outcome'):
       vals = [t.value for t in session.query(TaxonomyEntry).filter_by(dimension=dim, active=True)]
       print(dim, vals)
   "
   ```

2. **Map the user's question to filters yourself** — category (`deal_industry` value or
   `'all'`), topic (or `None`), source_type (`'recording'` / `'qa_insight'` /
   `'podcast_insight'` or `None`), **and outcome** (`'meeting_booked'` /
   `'next_call_scheduled'` / `'closed_deal'` / `'rejected'` / `'undetermined'` or `None`
   — only meaningful for `@saadsells` recordings; other sources have no outcome tags).
   This is exactly what `manager/chat.py`'s `_extract_filters()` would ask the Anthropic
   API to do — do it with your own judgment instead. Never invent a value that isn't in
   the list from step 1. If the question is about what technique to use or asks "what
   works," lean toward `outcome='meeting_booked'` (or `'closed_deal'` for anything about
   actually closing) rather than leaving it `None` — that's the whole point of having
   it. If the question doesn't clearly narrow to a category/topic, use `category='all'`,
   `topic=None` — don't force a guess (same R4 spirit).

3. **Run `compile_answer()` directly** (no API call, pure DB read):
   ```bash
   uv run --directory "${SAAD_GPT_PROJECT_DIR:-/Users/amlannttripathy/Downloads/Saad}" python -c "
   from saad_sales_gpt.db import SessionLocal
   from saad_sales_gpt.manager.compile import compile_answer
   session = SessionLocal()
   answer = compile_answer(session, category='<category>', topic=<topic-or-None>, outcome=<outcome-or-None>, include_unreviewed=True)
   if answer.empty_categories:
       print('EMPTY:', answer.empty_categories)
   for category, by_source in answer.grouped.items():
       for source_type, items in by_source.items():
           print(f'=== {category} / {source_type} ({len(items)}) ===')
           for item in items:
               print(item.segment_id, item.speaker, item.outcome, '|', item.text)
   "
   ```

4. **If `empty_categories` is non-empty, say so plainly** — "No tagged material yet
   for X" — never fall back to answering from your own general knowledge. This is the
   same R6/R4 "no silent fallback" rule the app's own code follows everywhere else in
   this project.

5. **Otherwise, write the answer yourself**, following the exact rules
   `generate_synthesis()`'s system prompt would give a separate API call — but you're
   doing it directly now:
   - Only rearrange and lightly connect the evidence quotes returned in step 3.
   - Never invent a claim, phrasing, or piece of advice not grounded in those quotes.
   - After every claim, cite the `segment_id`(s) it came from in square brackets, e.g.
     `[a1b2c3d4-...]`.
   - If the evidence is too thin to really answer the question, say that plainly
     instead of stretching a weak match into a confident answer.

## Extending this skill

When more content gets tagged, reviewed, or the taxonomy grows further, update the
"Current data scope" section above rather than trusting it blindly — it's a snapshot,
not a live query. If tagging changes materially, re-run step 1 before trusting any
assumption here about what values exist.

Nobody has done a human review pass on any tag yet (R5's actual design intent — Claude
marking its own tags reviewed would defeat the point). With the current volume, a full
tag-by-tag review is impractical; if this content is ever used somewhere the accuracy
really matters, spot-check a sample first rather than assuming every quote is exactly
right — especially `@saadsells`'s `objection_handling`/`pricing`/`rapport` segment_types
and the second-pass keyword-based topics, both flagged above as lower-confidence than
the rest.
