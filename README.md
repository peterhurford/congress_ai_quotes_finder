# Congress AI Quotes Finder

Finds and classifies quotes from U.S. Congress members about AGI, AI existential risk, superintelligence, and related topics. Searches the GovInfo congressional record, applies rule-based pre-filtering, then uses Claude to extract and attribute quotes.

## Quick start

```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY=your-key  # for LLM classification
make run                           # incremental search + classify
```

## How it works

`make run` executes `run_pipeline.py`, which:

1. **Searches** GovInfo API for 63 search terms (incremental: last run - 1 month to today)
2. **Downloads** new congressional documents (cached in `govinfo_cache/`)
3. **Pre-filters** with regex matching, AI-context validation, and quality scoring
4. **Classifies** high-scoring candidates with Claude Sonnet to extract speaker-attributed quotes
5. **Outputs** results to `new_member_quotes.md` and `govinfo_cache/latest_run_quotes.json`

## Make targets

| Command | Description |
|---|---|
| `make run` | Incremental run (default) |
| `make run-all` | Full date range (2023-01-01 to today) |
| `make run-cached` | Skip API search, use cached results |
| `make run-skip-llm` | Rule-based pre-filter only, no LLM |
| `make reprocess` | Re-analyze all documents |
| `make search` | GovInfo search only (`govinfo_agi_search.py`) |

## Files

| File | Purpose |
|---|---|
| `run_pipeline.py` | Unified pipeline (recommended entry point) |
| `govinfo_agi_search.py` | GovInfo API search + document download |
| `update_quotes.py` | LLM classification (standalone) |
| `analyze_quotes.py` | Rule-based analysis (standalone) |

## Caches

All cached data lives in `govinfo_cache/`:
- `search__*.json` — search results per term
- `*.html` — downloaded document text
- `processed_ids.json` — documents already sent to LLM
- `last_run_date.txt` — date of last pipeline run

`make clean-cache` removes search caches. `make clean` removes all state.

## Environment

- `GOVINFO_API_KEY` — GovInfo API key (has default)
- `ANTHROPIC_API_KEY` — required for LLM classification
