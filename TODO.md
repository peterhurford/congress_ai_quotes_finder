# TODO — this project does not currently work

**Status: NON-FUNCTIONAL / under construction.** The pipeline runs without error but
**silently misses the quotes it exists to find.** Do not trust its output. This
document is the full diagnosis and the plan to fix it.

Last investigated: 2026-07 (against GovInfo, congress.gov, C-SPAN, and committee video).

---

## 1. Symptom that started this

Two real, on-topic quotes were **not** found by a recent run:

- **Rep. Stephen Lynch (D-MA)** — "I see artificial superintelligence as the winner…
  We are in serious existential trouble." — House Financial Services hearing on the
  Fed's Semi-Annual Monetary Policy Report (~June 2026).
- **Rep. Jay Obernolte (R-CA)** — "…a loss of control caused by recursive
  self-improvement…" — House Science Committee markup of AI bills.

Both are textbook targets (superintelligence, existential risk, recursive
self-improvement, loss of control — all already in `SEARCH_TERMS`). The classifier
never saw them because **the text never entered the pipeline.**

---

## 2. Root cause — the data source is structurally wrong for the goal

The pipeline searches only `collection:(CREC OR CHRG)` on the GovInfo API. Neither
collection delivers timely hearing quotes:

| Collection | What it is | Timeliness | Contains member Q&A? |
|---|---|---|---|
| **CREC** — Congressional Record | Floor proceedings | Next morning ✅ | **No.** Floor speeches only. Hearing Q&A is never here. |
| **CHRG** — Congressional Hearings | Printed hearing transcripts | **6–18 months late** ❌ | Yes, eventually. |

Nearly all of the quotes we want are spoken in **committee hearings and markups**
(that's where members react to AI witnesses). That content only ever lands in CHRG,
and CHRG is a **print archive**, not a news feed.

### Evidence gathered (live API, 2026-07)

- All CHRG packages with a 2026 date: **101 total**, newest dated `2026-06-04`. No
  June 2026 Fed hearing, no 2026 House Science AI markup present.
- The **June 24, 2025** House FSC Powell hearing (`CHRG-119hhrg60984`) was only
  loaded to GovInfo on **2026-06-11** — a **~12-month** lag. Its full text (187 KB
  HTML) is available now, but its `publishdate` is backdated to the hearing date.
- `"superintelligence"` in CREC OR CHRG, last 3 months: **0 results.**
- `"recursive self-improvement"` in CREC OR CHRG, 2026 YTD: **1 result** (an AI
  Action Plan hearing that happened to print fast).

**Conclusion:** no configuration of a GovInfo-only pipeline can surface a hearing
quote within ~a year of it being spoken. This is a data-source problem, not a
tuning problem.

---

## 3. Secondary bug — the incremental window makes late prints permanently invisible

Even setting aside timeliness, the current incremental logic guarantees misses:

- The query filters `publishdate:range(last_run - 1 month, today)`.
- GovInfo's `publishdate` == **hearing date** (`dateIssued`), **not** the date the
  text was loaded.
- So a transcript printed 12 months after its hearing has a `publishdate` 12 months
  in the past — **outside every future incremental window.** It will never be picked
  up, even though its text is now available.

`govinfo_cache/processed_ids.json` confirms `CHRG-119hhrg60984` was never processed.

### Band-aids that were considered and rejected

These would reduce misses slightly but do **not** fix the fundamental problem
(they still only ever return year-old data), so they are **not** the plan:

1. Widen the CHRG lookback to a fixed 18–24 months every run. (Fetches the same
   stale data, just more of it. `processed_ids.json` dedup keeps LLM cost bounded.)
2. Filter CHRG on `lastModified` instead of `publishdate` so items are caught by
   when GovInfo *loaded* them. (Catches late prints — but still a year late.)

If you ever want partial credit on the historical backlog, #2 is the least-bad
band-aid. It is not a substitute for Section 4.

---

## 4. The range of real options (for timely hearing coverage)

Investigated 2026-07. There is **no clean official API** that returns timely,
speaker-labeled member Q&A. Every timely source requires either self-transcription
or scraping a bot-hostile site.

| Source | Timely? | Member Q&A? | Machine access | Verdict |
|---|---|---|---|---|
| **CREC** (current) | ✅ next day | ❌ floor only | ✅ clean API | Keep — but it can't cover hearings. |
| **GovInfo CHRG** (current) | ❌ 6–18 mo | ✅ full | ✅ clean API | Demote to slow backfill / correction layer. |
| **congress.gov event `/text`** | ❌ | ✅ | ❌ 403s bots; API gives metadata + *witness* statements only | Its transcript tab is populated **from CHRG** — same lag. Not a new source. |
| **C-SPAN** | ✅ ~1 day, speaker-labeled | ✅ full | ❌ redirects to `tollbit.c-span.org` (AI-crawler paywall) | Best data, but scraping is adversarial + fragile + now toll-gated. Avoid. |
| **Committee video** (YouTube via committee site) | ✅ same day | ✅ (raw audio) | ⚠️ bot-gated; needs browser cookies + transcription | **The viable path.** See below. |
| **Fed.gov / witness sites** | ✅ fast | ❌ witness prepared remarks only | ✅ | No member Q&A. Useless for our goal. |

### Useful discovery: committee sites are a clean, official spine

The committee's **own** website embeds the hearing video. Confirmed: a plain GET of
`financialservices.house.gov/calendar/eventsingle.aspx?EventID=408872` returned an
embedded YouTube video id `qmddoaBAXXk`. So we never need to scrape C-SPAN to
*find* hearings — the official committee sites tell us what happened and hand us the
video URL.

---

## 5. Recommended architecture

Replace the *ingest* only. The downstream stack (regex → `is_ai_context` →
quality score → Claude classification → attribution) survives unchanged.

1. **CREC** — keep exactly as-is (floor speeches, timely, works today).
2. **Committee-site spine** — poll House/Senate committee event pages (and/or the
   congress.gov committee-meetings API for scheduling metadata). Filter to
   AI-relevant hearings by title + witness list so we transcribe ~1% of Congress,
   not all of it. Extract the embedded video URL.
3. **Transcribe** the surviving hearings:
   - Pull audio with `yt-dlp` **`--cookies-from-browser chrome`** (YouTube hard
     bot-gates datacenter/anon IPs — confirmed it refused even metadata without
     cookies).
   - Transcribe with **Whisper** (or a diarizing ASR).
   - Recover speaker attribution from the hearing **ritual** ("the gentleman from
     Massachusetts, Mr. Lynch, is recognized for five minutes") + the committee
     roster. Diarization alone is not needed; the ritual gives names.
4. **Run the existing classifier** on the attributed transcript.
5. **CHRG demoted to backfill** — when the official print transcript lands ~a year
   later, use it to correct ASR errors and confirm already-published quotes. That is
   the correct job for a print archive.

---

## 6. Concrete next step — prototype on ONE hearing

Lowest-regret move before committing to the whole build: prove the chain
end-to-end on a single known-good target.

- **Target hearing:** House FSC Fed Semi-Annual Monetary Policy Report.
- **Video:** YouTube `qmddoaBAXXk` (from the committee event page).
- **Success criterion:** the pipeline recovers the **Lynch** "artificial
  superintelligence as the winner / serious existential trouble" quote, correctly
  attributed to Rep. Lynch, with a reasonable timestamp.
- If clean → scale to a committee list. If messy (attribution wrong, ASR mangles
  the quote) → reassess before investing further.

Suggested prototype steps:
1. `yt-dlp --cookies-from-browser chrome -x --audio-format mp3 <video>` → audio.
2. Whisper transcribe → raw text with timestamps.
3. Segment by the "recognized for five minutes" ritual → attribute each block.
4. Feed blocks through the existing `is_ai_context` + quality-score + classifier.
5. Diff the recovered Lynch quote against the transcript above. Eyeball attribution.

---

## 7. Open questions / risks

- **YouTube bot-gate durability.** `--cookies-from-browser` works from a real
  logged-in Chrome, but Google rotates the gate. Needs a fallback (e.g. the
  committee ISVP/`houselive` stream, or C-SPAN as last resort despite the toll).
- **Senate coverage.** Senate committees use YouTube less consistently than the
  House. Spine logic must handle per-committee video hosts.
- **ASR accuracy on names/jargon.** "Obernolte", "superintelligence", bill numbers
  — expect errors. The CHRG backfill (step 5) is the correction mechanism; until it
  lands, published quotes are provisional.
- **Compute cost.** Whisper per hearing is non-trivial but bounded by the ~1%
  AI-relevance filter. Log what gets dropped by the filter — do not silently cap.
- **Attribution edge cases.** Panels, yielding time, colloquy. The ritual heuristic
  covers most but not all; the classifier prompt may need a "who is speaking?" step.

---

## 8. When this is fixed

Remove the crash guards to re-enable the scripts:

- The `ALLOW_BROKEN_RUN` guard block near the top of every `*.py`
  (`run_pipeline.py`, `govinfo_agi_search.py`, `update_quotes.py`,
  `analyze_quotes.py`).
- The "UNDER CONSTRUCTION" banner in `README.md`.
- The warning block at the top of `CLAUDE.md`.

(To run a script while actively working the fix, set `ALLOW_BROKEN_RUN=1` in the
environment — it bypasses the guard without deleting it.)
