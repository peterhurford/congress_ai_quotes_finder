# CLAUDE.md

## Project overview

Pipeline for finding quotes from U.S. Congress members about AGI/AI existential risk. Searches GovInfo congressional records, pre-filters with regex + AI-context validation + quality scoring, then classifies with Claude Sonnet.

## Architecture

- `run_pipeline.py` — unified entry point. Run with `make run`.
- `govinfo_agi_search.py` — GovInfo API search + document download + CSV output
- `update_quotes.py` — LLM classification pipeline (standalone alternative)
- `analyze_quotes.py` — rule-based analysis (standalone alternative)

All three standalone scripts share search terms and regexes but maintain their own copies. `run_pipeline.py` is the canonical source.

## Key concepts

- **Search terms**: 63 GovInfo Solr queries (quoted phrases with AND/OR). Defined in SEARCH_TERMS lists.
- **SEARCH_REGEXES**: regex patterns for matching terms within downloaded document text.
- **AI-context filter** (`is_ai_context`): checks for AI-related words near ambiguous matches (e.g., "extinction" about species vs AI). Terms in `_ALWAYS_AI` skip this check. Terms in `_HIGH_AMBIGUITY` require 2+ AI indicators nearby.
- **Quality scoring**: rates passages 0-10 based on substantive language, search term density, strong x-risk phrases. Used as pre-filter before LLM (default threshold: 4).
- **Processed IDs**: `govinfo_cache/processed_ids.json` tracks which documents have been sent to the LLM to avoid re-processing.
- **Last run date**: `govinfo_cache/last_run_date.txt` — incremental runs search from (last_run - 1 month) to today.

## Conventions

- GovInfo documents are cached as HTML in `govinfo_cache/`. Cache keys use `{packageId}__{granuleId}` format, sanitized with `re.sub(r'[^\w\-]', '_', key)`.
- API results can have `None` for granuleId — always use `r.get("granuleId") or ""` not `r.get("granuleId", "")`.
- Run with `PYTHONUNBUFFERED=1` when backgrounding to get real-time output.
- The `dateutil.relativedelta` import is deferred (inside function) since it's only needed for incremental date math.

## Common tasks

- **Add a search term**: update SEARCH_TERMS and SEARCH_REGEXES in `run_pipeline.py`, `govinfo_agi_search.py`, `update_quotes.py`, and `analyze_quotes.py`. Update `_ALWAYS_AI` or `_HIGH_AMBIGUITY` sets if the term is ambiguous.
- **Add a tracked member**: update TRACKED_MEMBERS_LIST in `run_pipeline.py` and the equivalent lists in `update_quotes.py` and `analyze_quotes.py`.
- **Run without LLM costs**: `make run-skip-llm` or `make run-cached --skip-llm`.
