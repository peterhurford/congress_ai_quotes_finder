#!/usr/bin/env python3
"""
Search the GovInfo API for mentions of AGI, AI superintelligence, AI existential risk,
and related terms in the Congressional Record (CREC) and Congressional Hearings (CHRG).

Output: govinfo_agi_results.csv
Cache: ./govinfo_cache/ (downloaded document HTML)
"""

# ==========================================================================
# ⚠️  PROJECT NON-FUNCTIONAL — UNDER CONSTRUCTION — DO NOT RUN  ⚠️
# --------------------------------------------------------------------------
# This tool cannot currently find recent congressional AI quotes. Its only
# timely data source (GovInfo CREC) contains floor speeches, never hearing
# Q&A; the hearing transcripts (GovInfo CHRG) are a print archive published
# 6–18 MONTHS after the hearing, so quotes spoken in committee last month are
# silently missed. Widening the search window does NOT fix this — it is a
# fundamental data-source problem.
#
# Full diagnosis and the plan to fix it live in TODO.md.  READ TODO.md.
#
# This guard halts the script on purpose. To run anyway while actively
# working the fix, set  ALLOW_BROKEN_RUN=1  in the environment.
# ==========================================================================
import os as _os
import sys as _sys

if _os.environ.get("ALLOW_BROKEN_RUN") != "1":
    _sys.exit(
        "\n"
        "############################################################\n"
        "#  congress_ai_quotes_finder is NON-FUNCTIONAL.            #\n"
        "#  It misses recent hearing quotes by design.             #\n"
        "#  ==>  READ TODO.md BEFORE USING THIS REPO.  <==          #\n"
        "#  Bypass (developers only): ALLOW_BROKEN_RUN=1           #\n"
        "############################################################\n"
    )

import csv
import json
import os
import re
import sys
import time
from datetime import date
from pathlib import Path

import requests
from bs4 import BeautifulSoup

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

API_KEY = os.environ.get("GOVINFO_API_KEY", "eX3RsbIRzlMVPXlBJXpp96FJkahTkRbkxIGEnSmL")
API_BASE = "https://api.govinfo.gov"
SEARCH_URL = f"{API_BASE}/search"

CACHE_DIR = Path("govinfo_cache")
CACHE_DIR.mkdir(exist_ok=True)

OUTPUT_CSV = "govinfo_agi_results.csv"

DATE_START = "2023-01-01"
DATE_END = date.today().isoformat()

# Seconds between API requests. Registered keys allow 40 req/sec,
# but we add a small delay to be respectful.
REQUEST_DELAY = 0.5  # seconds

PAGE_SIZE = 25  # results per search page

# Context window: number of characters around a match to extract
CONTEXT_CHARS = 1500  # roughly ~500 words

# ---------------------------------------------------------------------------
# Search terms
# ---------------------------------------------------------------------------

# Each entry is (search_query_fragment, human_label).
# "near" proximity is approximated with quoted phrases or AND within the query,
# since GovInfo's Solr-based search doesn't support a NEAR operator natively.
# We use quoted phrases where possible and AND for proximity concepts.
SEARCH_TERMS = [
    # --- Core AGI / ASI terminology ---
    ('"artificial general intelligence"', "artificial general intelligence"),
    ('"superintelligence"', "superintelligence"),
    ('"superintelligent"', "superintelligent"),
    ('"intelligence explosion"', "intelligence explosion"),
    ('"recursive self-improvement"', "recursive self-improvement"),
    ('"capability amplification"', "capability amplification"),
    ('"superhuman AI"', "superhuman AI"),
    ('"human-level" AND ("AI" OR "artificial intelligence")',
     "human-level + AI"),
    ('"surpass" AND ("AI" OR "artificial intelligence")',
     "surpass + AI"),
    ('"smarter than humans" AND ("AI" OR "artificial intelligence")',
     "smarter than humans + AI"),
    ('"ultra-intelligent"', "ultra-intelligent"),
    ('"god" AND ("AI" OR "artificial intelligence")',
     "god + AI"),
    ('"improve" AND ("AI" OR "artificial intelligence")',
     "improve + AI"),
    ('"Turing Test"', "Turing Test"),

    # --- Existential / catastrophic risk ---
    ('("existential risk" OR "existential threat") AND ("AI" OR "artificial intelligence")',
     "existential risk + AI"),
    ('"catastrophic risk" AND ("AI" OR "artificial intelligence")',
     "catastrophic risk + AI"),
    ('"extinction" AND ("AI" OR "artificial intelligence")',
     "extinction + AI"),
    ('"threat to humanity" AND ("AI" OR "artificial intelligence")',
     "threat to humanity + AI"),
    ('("end of humanity" OR "end of the world") AND ("AI" OR "artificial intelligence")',
     "end of humanity + AI"),
    ('"destroy" AND ("AI" OR "artificial intelligence")',
     "destroy + AI"),
    ('"kill us all" AND ("AI" OR "artificial intelligence")',
     "kill us all + AI"),
    ('"destruction" AND ("AI" OR "artificial intelligence")',
     "destruction + AI"),

    # --- Control / alignment / safety ---
    ('("loss of control" OR "lose control" OR "out of control" OR "uncontrollable") AND ("AI" OR "artificial intelligence")',
     "loss of control + AI"),
    ('"AI safety"', "AI safety"),
    ('"AI alignment"', "AI alignment"),
    ('"misalignment" AND ("AI" OR "artificial intelligence")',
     "misalignment + AI"),
    ('"self-aware" AND ("AI" OR "artificial intelligence")',
     "self-aware + AI"),
    ('"AI moratorium"', "AI moratorium"),
    ('"AI pause"', "AI pause"),
    ('"too powerful" AND ("AI" OR "artificial intelligence")',
     "too powerful + AI"),
    ('"dangerous" AND ("AI" OR "artificial intelligence")',
     "dangerous + AI"),
    ('"singularity" AND ("AI" OR "artificial intelligence")',
     "singularity + AI"),

    # --- Pop culture / metaphor ---
    ('"skynet"', "skynet"),
    ('"Terminator" AND ("AI" OR "artificial intelligence")',
     "Terminator + AI"),
    ('"rise of the machines"', "rise of the machines"),
    ('"Asimov" AND ("AI" OR "artificial intelligence" OR "robot")',
     "Asimov + AI"),
    ('"Frankenstein" AND ("AI" OR "artificial intelligence")',
     "Frankenstein + AI"),
    ('"HAL 9000"', "HAL 9000"),
    ('"The Matrix" AND ("AI" OR "artificial intelligence")',
     "The Matrix + AI"),
    ('"science fiction" AND ("AI" OR "artificial intelligence")',
     "science fiction + AI"),
    ('"rogue AI"', "rogue AI"),
    ('"If Anyone Builds It, Everyone Dies"',
     "If Anyone Builds It, Everyone Dies"),

    # --- Weaponization / autonomous systems ---
    ('"autonomous weapons"', "autonomous weapons"),
    ('"lethal autonomous"', "lethal autonomous"),
    ('"weaponized" AND ("AI" OR "artificial intelligence")',
     "weaponized + AI"),
    ('"kill chain" AND ("AI" OR "artificial intelligence")',
     "kill chain + AI"),
    ('"AI arms race"', "AI arms race"),
    ('"atomic bomb" AND ("AI" OR "artificial intelligence")',
     "atomic bomb + AI"),
    ('"Manhattan Project" AND ("AI" OR "artificial intelligence")',
     "Manhattan Project + AI"),

    # --- Deception / self-preservation ---
    ('("deception" OR "deceiving") AND ("AI" OR "artificial intelligence")',
     "deception + AI"),
    ('"blackmail" AND ("AI" OR "artificial intelligence")',
     "blackmail + AI"),

    # --- Consciousness / sentience / urgency ---
    ('"sentient" AND ("AI" OR "artificial intelligence")',
     "sentient + AI"),
    ('"AI consciousness"', "AI consciousness"),
    ('"escape velocity" AND ("AI" OR "artificial intelligence")',
     "escape velocity + AI"),
]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def api_request(method, url, **kwargs):
    """Make an API request with rate-limit delay and retries."""
    for attempt in range(5):
        if method == "POST":
            resp = requests.post(url, **kwargs)
        else:
            resp = requests.get(url, **kwargs)

        if resp.status_code == 429:
            # Respect Retry-After header if present
            retry_after = resp.headers.get("Retry-After")
            if retry_after and int(retry_after) < 300:
                wait = int(retry_after) + 5
            else:
                wait = 60 * (attempt + 1)
            print(f"  Rate limited (429). Waiting {wait}s before retry...")
            time.sleep(wait)
            continue
        elif resp.status_code >= 500:
            wait = 15 * (attempt + 1)
            print(f"  Server error ({resp.status_code}). Waiting {wait}s...")
            time.sleep(wait)
            continue

        return resp

    print(f"  Failed after 5 retries for {url}")
    return resp


def search_cache_path(label):
    """Return cache path for search results for a given term."""
    key = re.sub(r'[^\w]', '_', label)
    return CACHE_DIR / f"search__{key}.json"


def cache_path_for(package_id, granule_id):
    """Return a filesystem-safe cache path for a document."""
    key = f"{package_id}__{granule_id}" if granule_id else package_id
    # Sanitize
    key = re.sub(r'[^\w\-]', '_', key)
    return CACHE_DIR / f"{key}.html"


def fetch_document_text(txt_link, package_id, granule_id):
    """Fetch and cache document HTML text. Returns the plain text content."""
    cached = cache_path_for(package_id, granule_id)
    if cached.exists():
        return cached.read_text(encoding="utf-8", errors="replace")

    if not txt_link:
        return None

    # Append api_key if not already in URL
    sep = "&" if "?" in txt_link else "?"
    url = f"{txt_link}{sep}api_key={API_KEY}"

    print(f"    Fetching text: {package_id}/{granule_id}")
    time.sleep(REQUEST_DELAY)
    resp = api_request("GET", url)

    if resp.status_code != 200:
        print(f"    Failed to fetch text ({resp.status_code})")
        return None

    html = resp.text
    cached.write_text(html, encoding="utf-8")
    return html


def html_to_text(html):
    """Extract plain text from HTML."""
    soup = BeautifulSoup(html, "html.parser")
    # GovInfo wraps content in <pre> tags for CREC
    pre = soup.find("pre")
    if pre:
        return pre.get_text()
    return soup.get_text()


def extract_context(text, search_label, context_chars=CONTEXT_CHARS):
    """Find the search term in text and extract surrounding context.
    Returns (excerpt, matched_position) or (None, -1) if not found."""

    text_lower = text.lower()

    # Build patterns to search for based on the label
    patterns = []
    label_lower = search_label.lower()

    if " + " in label_lower:
        # For "X + AI" terms, look for the X part
        main_term = label_lower.split(" + ")[0].strip()
        patterns.append(main_term)
    else:
        patterns.append(label_lower)

    for pattern in patterns:
        idx = text_lower.find(pattern)
        if idx != -1:
            start = max(0, idx - context_chars // 2)
            end = min(len(text), idx + len(pattern) + context_chars // 2)

            # Try to start/end at paragraph boundaries
            excerpt = text[start:end].strip()

            # Clean up: collapse whitespace
            excerpt = re.sub(r'\n\s*\n', '\n\n', excerpt)
            excerpt = re.sub(r'[ \t]+', ' ', excerpt)

            return excerpt, idx

    return None, -1


def identify_speaker(text, match_position):
    """Try to identify who is speaking near the matched text.
    Looks for patterns like 'Mr. LASTNAME', 'Mrs. LASTNAME', 'Senator LASTNAME',
    'Representative LASTNAME', etc."""

    # Search backwards from match position for a speaker pattern
    search_start = max(0, match_position - 3000)
    preceding = text[search_start:match_position]

    # Patterns for speakers in Congressional Record
    speaker_patterns = [
        r'(?:Mr\.|Mrs\.|Ms\.|Miss)\s+([A-Z][A-Z\' -]+?)[\s\.\,\)]',
        r'(?:Senator|Sen\.)\s+([A-Z][A-Z\' -]+?)[\s\.\,\)]',
        r'(?:Representative|Rep\.)\s+([A-Z][A-Z\' -]+?)[\s\.\,\)]',
        r'(?:Chairman|Chairwoman|Chair)\s+([A-Z][A-Z\' -]+?)[\s\.\,\)]',
        r'(?:Secretary)\s+([A-Z][A-Z\' -]+?)[\s\.\,\)]',
        r'The\s+(?:SPEAKER|PRESIDENT)\s+pro\s+tempore',
    ]

    best_speaker = None
    best_pos = -1

    for pattern in speaker_patterns:
        for m in re.finditer(pattern, preceding):
            if m.start() > best_pos:
                best_pos = m.start()
                if m.lastindex:
                    best_speaker = m.group(1).strip().rstrip(".")
                else:
                    best_speaker = m.group(0).strip()

    return best_speaker


def determine_chamber(result):
    """Determine the chamber (House/Senate) from result metadata."""
    authors = result.get("governmentAuthor", [])
    title = (result.get("title") or "").lower()
    granule_id = result.get("granuleId") or ""

    if "House of Representatives" in authors or "house" in title:
        return "House"
    if "Senate" in authors or "senate" in title:
        return "Senate"

    # CREC granule IDs embed page numbers: PgH = House, PgS = Senate, PgE/PgD = Extensions/Daily Digest
    if "PgH" in granule_id:
        return "House"
    if "PgS" in granule_id:
        return "Senate"

    return "Unknown"


# ---------------------------------------------------------------------------
# Main search logic
# ---------------------------------------------------------------------------


def search_govinfo(query_fragment, label):
    """Run a single search query across CREC and CHRG. Returns list of result dicts.
    Results are cached locally so re-runs skip the search API calls."""

    cached = search_cache_path(label)
    if cached.exists():
        print(f"\nSearching: {label} [CACHED]")
        results = json.loads(cached.read_text(encoding="utf-8"))
        print(f"  Loaded {len(results)} cached results")
        return results

    full_query = (
        f'{query_fragment} '
        f'collection:(CREC OR CHRG) '
        f'publishdate:range({DATE_START},{DATE_END})'
    )

    print(f"\nSearching: {label}")
    print(f"  Query: {full_query}")

    results = []
    offset_mark = "*"
    page = 0

    while True:
        page += 1
        payload = {
            "query": full_query,
            "pageSize": PAGE_SIZE,
            "offsetMark": offset_mark,
            "sorts": [{"field": "publishdate", "sortOrder": "DESC"}],
        }

        time.sleep(REQUEST_DELAY)
        resp = api_request(
            "POST",
            f"{SEARCH_URL}?api_key={API_KEY}",
            json=payload,
            headers={"Content-Type": "application/json"},
        )

        if resp.status_code != 200:
            print(f"  Search failed ({resp.status_code}): {resp.text[:200]}")
            break

        data = resp.json()
        count = data.get("count", 0)
        page_results = data.get("results", [])
        new_offset = data.get("offsetMark", offset_mark)

        if page == 1:
            print(f"  Total results: {count}")

        if not page_results:
            break

        results.extend(page_results)
        print(f"  Page {page}: fetched {len(page_results)} results (total so far: {len(results)})")

        # Stop pagination if we've gotten all results or offset hasn't changed
        if len(results) >= count or new_offset == offset_mark:
            break

        offset_mark = new_offset

    # Cache search results
    cached.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"  Cached {len(results)} results to {cached}")

    return results


def process_result(result, search_label):
    """Process a single search result: fetch text, extract context, identify speaker.
    Returns a dict for CSV output, or None if no match found in text."""

    package_id = result.get("packageId") or ""
    granule_id = result.get("granuleId") or ""
    date_issued = result.get("dateIssued") or ""
    collection = result.get("collectionCode") or ""
    title = result.get("title") or ""

    # Get text download link
    download = result.get("download", {})
    txt_link = download.get("txtLink")

    # Build a GovInfo public URL
    source_url = f"https://www.govinfo.gov/app/details/{package_id}"
    if granule_id and granule_id != package_id:
        source_url += f"/{granule_id}"

    # Fetch document text
    html = fetch_document_text(txt_link, package_id, granule_id)
    if not html:
        return None

    text = html_to_text(html)
    if not text or len(text) < 50:
        return None

    # Extract relevant passage
    excerpt, match_pos = extract_context(text, search_label)
    if excerpt is None:
        # The search matched metadata/title but term not found in body text
        # Use the first ~500 words as context anyway
        excerpt = text[:CONTEXT_CHARS].strip()
        match_pos = 0
        if not excerpt:
            return None

    # Identify speaker
    speaker = identify_speaker(text, match_pos)

    # Determine chamber
    chamber = determine_chamber(result)

    return {
        "date": date_issued,
        "speaker": speaker or "",
        "party": "",  # Party info requires additional lookup; left blank
        "chamber": chamber,
        "collection": collection,
        "source_url": source_url,
        "quote_excerpt": excerpt,
        "search_term_matched": search_label,
        "title": title,
        "_dedup_key": f"{package_id}__{granule_id}",
    }


def main():
    print("=" * 70)
    print("GovInfo AGI/Superintelligence Search")
    print(f"API Key: {'DEMO_KEY' if API_KEY == 'DEMO_KEY' else 'custom key'}")
    print(f"Date range: {DATE_START} to {DATE_END}")
    print(f"Cache directory: {CACHE_DIR}")
    print("=" * 70)

    # Collect all results across all search terms
    all_rows = {}  # keyed by dedup_key

    for i, (query_fragment, label) in enumerate(SEARCH_TERMS, 1):
        print(f"\n[{i}/{len(SEARCH_TERMS)}]", end="")
        results = search_govinfo(query_fragment, label)

        new_docs = 0
        for result in results:
            dedup_key = f"{result.get('packageId')}__{result.get('granuleId')}"

            if dedup_key in all_rows:
                # Merge: add this search term to existing row
                existing_terms = all_rows[dedup_key]["search_term_matched"]
                if label not in existing_terms:
                    all_rows[dedup_key]["search_term_matched"] = (
                        f"{existing_terms}; {label}"
                    )
                continue

            row = process_result(result, label)
            if row:
                all_rows[dedup_key] = row
                new_docs += 1

        print(f"  -> {new_docs} new documents added ({len(all_rows)} total unique)")
        sys.stdout.flush()

    # Write CSV
    rows = sorted(all_rows.values(), key=lambda r: r.get("date", ""), reverse=True)

    print(f"\n{'=' * 70}")
    print(f"Writing {len(rows)} results to {OUTPUT_CSV}")

    fieldnames = [
        "date", "speaker", "party", "chamber", "collection",
        "source_url", "quote_excerpt", "search_term_matched",
    ]

    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)

    print(f"Done! Results saved to {OUTPUT_CSV}")

    # Print summary
    print(f"\nSummary:")
    print(f"  Total unique documents: {len(rows)}")

    by_collection = {}
    by_term = {}
    for row in rows:
        col = row["collection"]
        by_collection[col] = by_collection.get(col, 0) + 1
        for term in row["search_term_matched"].split("; "):
            by_term[term] = by_term.get(term, 0) + 1

    for col, count in sorted(by_collection.items()):
        print(f"  {col}: {count}")

    print(f"\n  Matches by search term:")
    for term, count in sorted(by_term.items(), key=lambda x: -x[1]):
        print(f"    {term}: {count}")


if __name__ == "__main__":
    main()
