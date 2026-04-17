.PHONY: run run-all run-cached run-skip-llm search install clean help

# Default: incremental run (search from last_run - 1 month, LLM classify)
run:
	PYTHONUNBUFFERED=1 python run_pipeline.py

# Full date range (2023-01-01 to today)
run-all:
	PYTHONUNBUFFERED=1 python run_pipeline.py --all

# Skip API search, use cached search results
run-cached:
	PYTHONUNBUFFERED=1 python run_pipeline.py --skip-search

# Rule-based only, no LLM calls (fast, free)
run-skip-llm:
	PYTHONUNBUFFERED=1 python run_pipeline.py --skip-llm

# Re-analyze all documents (ignore processed_ids)
reprocess:
	PYTHONUNBUFFERED=1 python run_pipeline.py --reprocess

# Search only (update govinfo_agi_results.csv, no LLM)
search:
	PYTHONUNBUFFERED=1 python govinfo_agi_search.py

# Install dependencies
install:
	pip install -r requirements.txt

# Remove search caches (keeps downloaded HTML docs)
clean-cache:
	rm -f govinfo_cache/search__*.json

# Remove all caches and outputs
clean:
	rm -rf govinfo_cache/search__*.json
	rm -f govinfo_cache/processed_ids.json
	rm -f govinfo_cache/last_run_date.txt
	rm -f new_member_quotes.md
	rm -f quote_analysis.csv

help:
	@echo "make run          - Incremental run (default)"
	@echo "make run-all      - Full date range search"
	@echo "make run-cached   - Skip API search, use cache"
	@echo "make run-skip-llm - Rule-based only, no LLM"
	@echo "make reprocess    - Re-analyze all documents"
	@echo "make search       - GovInfo search only (no LLM)"
	@echo "make install      - Install dependencies"
	@echo "make clean-cache  - Remove search caches"
	@echo "make clean        - Remove all caches and outputs"
