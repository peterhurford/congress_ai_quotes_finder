#!/usr/bin/env python3
"""
Unified pipeline for finding congressional AI quotes.

Combines govinfo_agi_search, analyze_quotes (rule-based), and update_quotes
(LLM-based) into a single workflow:

  1. Search GovInfo incrementally (last_run - 1 month to today)
  2. Download new documents
  3. Rule-based pre-filter (regex + AI-context + quality score)
  4. LLM classification on promising candidates only
  5. Combined output

Usage:
  python run_pipeline.py                # incremental run
  python run_pipeline.py --all          # full date range (DATE_START to today)
  python run_pipeline.py --skip-search  # skip API search, use cached results
  python run_pipeline.py --skip-llm     # rule-based only, no LLM calls
  python run_pipeline.py --reprocess    # re-analyze all documents
  python run_pipeline.py --min-score N  # minimum quality score for LLM (default: 4)
"""

import csv
import json
import os
import re
import sys
import time
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path

import anthropic
import requests
from bs4 import BeautifulSoup

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

GOVINFO_API_KEY = os.environ.get(
    "GOVINFO_API_KEY", "eX3RsbIRzlMVPXlBJXpp96FJkahTkRbkxIGEnSmL"
)
GOVINFO_BASE = "https://api.govinfo.gov"

CACHE_DIR = Path("govinfo_cache")
CACHE_DIR.mkdir(exist_ok=True)

PROCESSED_IDS_FILE = CACHE_DIR / "processed_ids.json"
LAST_RUN_FILE = CACHE_DIR / "last_run_date.txt"
OUTPUT_MD = Path("new_member_quotes.md")
OUTPUT_CSV = Path("quote_analysis.csv")
SEARCH_RESULTS_CSV = Path("govinfo_agi_results.csv")

DATE_START = "2023-01-01"
REQUEST_DELAY = 0.5
PAGE_SIZE = 25

# ---------------------------------------------------------------------------
# Tracked members
# ---------------------------------------------------------------------------

TRACKED_MEMBERS_LIST = [
    ("John Kennedy", "R", "Sen.", "LA"),
    ("Mazie Hirono", "D", "Sen.", "HI"),
    ("Seth Moulton", "D", "Rep.", "MA"),
    ("Ted Lieu", "D", "Rep.", "CA"),
    ("Chuck Schumer", "D", "Sen.", "NY"),
    ("John Hickenlooper", "D", "Sen.", "CO"),
    ("Don Beyer", "D", "Rep.", "VA"),
    ("Richard Blumenthal", "D", "Sen.", "CT"),
    ("John Fetterman", "D", "Sen.", "PA"),
    ("Marjorie Taylor Greene", "R", "Rep.", "GA"),
    ("Scott Perry", "R", "Rep.", "PA"),
    ("Cynthia Lummis", "R", "Sen.", "WY"),
    ("Chris Murphy", "D", "Sen.", "CT"),
    ("Dusty Johnson", "R", "Rep.", "SD"),
    ("Nathaniel Moran", "R", "Rep.", "TX"),
    ("Neal Dunn", "R", "Rep.", "FL"),
    ("Jill Tokuda", "D", "Rep.", "HI"),
    ("Raja Krishnamoorthi", "D", "Rep.", "IL"),
    ("Bernie Sanders", "I", "Sen.", "VT"),
    ("Andy Biggs", "R", "Rep.", "AZ"),
    ("Eli Crane", "R", "Rep.", "AZ"),
    ("Nancy Mace", "R", "Rep.", "SC"),
    ("Eric Burlison", "R", "Rep.", "MO"),
    ("Kevin Kiley", "R", "Rep.", "CA"),
    ("Josh Hawley", "R", "Sen.", "MO"),
    ("Mike Lee", "R", "Sen.", "UT"),
    ("Bill Foster", "D", "Rep.", "IL"),
    ("Brad Sherman", "D", "Rep.", "CA"),
    ("George Whitesides", "D", "Rep.", "CA"),
    ("Jim Banks", "R", "Sen.", "IN"),
    ("Sean Casten", "D", "Rep.", "IL"),
    ("Sam Liccardo", "D", "Rep.", "CA"),
    ("Shelley Moore Capito", "R", "Sen.", "WV"),
    ("Marsha Blackburn", "R", "Sen.", "TN"),
    ("Mike Rounds", "R", "Sen.", "SD"),
    ("Ro Khanna", "D", "Rep.", "CA"),
    ("Jon Ossoff", "D", "Sen.", "GA"),
    ("John McGuire", "R", "Rep.", "VA"),
]

TRACKED_MEMBERS = {name for name, _, _, _ in TRACKED_MEMBERS_LIST}

TRACKED_BY_LASTNAME = {}
for full_name, party, title, state in TRACKED_MEMBERS_LIST:
    parts = full_name.split()
    lastname = parts[-1].upper()
    TRACKED_BY_LASTNAME[lastname] = (full_name, party, title, state)
    if len(parts) > 2:
        compound = " ".join(parts[1:]).upper()
        TRACKED_BY_LASTNAME[compound] = (full_name, party, title, state)


# ---------------------------------------------------------------------------
# Search terms (single source of truth)
# ---------------------------------------------------------------------------

SEARCH_TERMS = [
    # --- Core AGI / ASI terminology ---
    ('"artificial general intelligence"', "artificial general intelligence"),
    ('"superintelligence"', "superintelligence"),
    ('"superintelligent"', "superintelligent"),
    ('"intelligence explosion"', "intelligence explosion"),
    ('"recursive self-improvement"', "recursive self-improvement"),
    ('"capability amplification"', "capability amplification"),
    ('"superhuman AI"', "superhuman AI"),
    ('"human-level" AND ("AI" OR "artificial intelligence")', "human-level + AI"),
    ('"surpass" AND ("AI" OR "artificial intelligence")', "surpass + AI"),
    ('"smarter than humans" AND ("AI" OR "artificial intelligence")', "smarter than humans + AI"),
    ('"ultra-intelligent"', "ultra-intelligent"),
    ('"god" AND ("AI" OR "artificial intelligence")', "god + AI"),
    ('"improve" AND ("AI" OR "artificial intelligence")', "improve + AI"),
    ('"Turing Test"', "Turing Test"),
    # --- Existential / catastrophic risk ---
    ('("existential risk" OR "existential threat") AND ("AI" OR "artificial intelligence")', "existential risk + AI"),
    ('"catastrophic risk" AND ("AI" OR "artificial intelligence")', "catastrophic risk + AI"),
    ('"extinction" AND ("AI" OR "artificial intelligence")', "extinction + AI"),
    ('"threat to humanity" AND ("AI" OR "artificial intelligence")', "threat to humanity + AI"),
    ('("end of humanity" OR "end of the world") AND ("AI" OR "artificial intelligence")', "end of humanity + AI"),
    ('"destroy" AND ("AI" OR "artificial intelligence")', "destroy + AI"),
    ('"kill us all" AND ("AI" OR "artificial intelligence")', "kill us all + AI"),
    ('"destruction" AND ("AI" OR "artificial intelligence")', "destruction + AI"),
    # --- Control / alignment / safety ---
    ('("loss of control" OR "lose control" OR "out of control" OR "uncontrollable") AND ("AI" OR "artificial intelligence")', "loss of control + AI"),
    ('"AI safety"', "AI safety"),
    ('"AI alignment"', "AI alignment"),
    ('"misalignment" AND ("AI" OR "artificial intelligence")', "misalignment + AI"),
    ('"self-aware" AND ("AI" OR "artificial intelligence")', "self-aware + AI"),
    ('"AI moratorium"', "AI moratorium"),
    ('"AI pause"', "AI pause"),
    ('"too powerful" AND ("AI" OR "artificial intelligence")', "too powerful + AI"),
    ('"dangerous" AND ("AI" OR "artificial intelligence")', "dangerous + AI"),
    ('"singularity" AND ("AI" OR "artificial intelligence")', "singularity + AI"),
    # --- Pop culture / metaphor ---
    ('"skynet"', "skynet"),
    ('"Terminator" AND ("AI" OR "artificial intelligence")', "Terminator + AI"),
    ('"rise of the machines"', "rise of the machines"),
    ('"Asimov" AND ("AI" OR "artificial intelligence" OR "robot")', "Asimov + AI"),
    ('"Frankenstein" AND ("AI" OR "artificial intelligence")', "Frankenstein + AI"),
    ('"HAL 9000"', "HAL 9000"),
    ('"The Matrix" AND ("AI" OR "artificial intelligence")', "The Matrix + AI"),
    ('"science fiction" AND ("AI" OR "artificial intelligence")', "science fiction + AI"),
    ('"rogue AI"', "rogue AI"),
    ('"If Anyone Builds It, Everyone Dies"', "If Anyone Builds It, Everyone Dies"),
    # --- Weaponization / autonomous systems ---
    ('"autonomous weapons"', "autonomous weapons"),
    ('"lethal autonomous"', "lethal autonomous"),
    ('"weaponized" AND ("AI" OR "artificial intelligence")', "weaponized + AI"),
    ('"kill chain" AND ("AI" OR "artificial intelligence")', "kill chain + AI"),
    ('"AI arms race"', "AI arms race"),
    ('"atomic bomb" AND ("AI" OR "artificial intelligence")', "atomic bomb + AI"),
    ('"Manhattan Project" AND ("AI" OR "artificial intelligence")', "Manhattan Project + AI"),
    # --- Deception / self-preservation ---
    ('("deception" OR "deceiving") AND ("AI" OR "artificial intelligence")', "deception + AI"),
    ('"blackmail" AND ("AI" OR "artificial intelligence")', "blackmail + AI"),
    # --- Consciousness / sentience / urgency ---
    ('"sentient" AND ("AI" OR "artificial intelligence")', "sentient + AI"),
    ('"AI consciousness"', "AI consciousness"),
    ('"escape velocity" AND ("AI" OR "artificial intelligence")', "escape velocity + AI"),
]

# Regex versions with labels for text matching + AI-context checks
SEARCH_REGEXES = [
    (re.compile(r'artificial\s+general\s+intelligence', re.I), "artificial general intelligence"),
    (re.compile(r'superintelligen(?:ce|t)', re.I), "superintelligence"),
    (re.compile(r'intelligence\s+explosion', re.I), "intelligence explosion"),
    (re.compile(r'recursive\s+self[- ]improvement', re.I), "recursive self-improvement"),
    (re.compile(r'capability\s+amplification', re.I), "capability amplification"),
    (re.compile(r'superhuman\s+AI', re.I), "superhuman AI"),
    (re.compile(r'human[- ]level', re.I), "human-level"),
    (re.compile(r'\bsurpass\b', re.I), "surpass"),
    (re.compile(r'smarter\s+than\s+humans?', re.I), "smarter than humans"),
    (re.compile(r'ultra[- ]intelligent', re.I), "ultra-intelligent"),
    (re.compile(r'\bgod\b', re.I), "god"),
    (re.compile(r'\bimprove\b', re.I), "improve"),
    (re.compile(r'Turing\s+Test', re.I), "Turing Test"),
    (re.compile(r'existential\s+risk', re.I), "existential risk"),
    (re.compile(r'existential\s+threat', re.I), "existential threat"),
    (re.compile(r'catastrophic\s+risk', re.I), "catastrophic risk"),
    (re.compile(r'extinction', re.I), "extinction"),
    (re.compile(r'threat\s+to\s+humanity', re.I), "threat to humanity"),
    (re.compile(r'end\s+of\s+humanity', re.I), "end of humanity"),
    (re.compile(r'end\s+of\s+the\s+world', re.I), "end of the world"),
    (re.compile(r'\bdestroy\b', re.I), "destroy"),
    (re.compile(r'kill\s+us\s+all', re.I), "kill us all"),
    (re.compile(r'\bdestruction\b', re.I), "destruction"),
    (re.compile(r'loss\s+of\s+control', re.I), "loss of control"),
    (re.compile(r'lose\s+control', re.I), "lose control"),
    (re.compile(r'out\s+of\s+control', re.I), "out of control"),
    (re.compile(r'uncontrollable', re.I), "uncontrollable"),
    (re.compile(r'AI\s+safety', re.I), "AI safety"),
    (re.compile(r'AI\s+alignment', re.I), "AI alignment"),
    (re.compile(r'misalignment', re.I), "misalignment"),
    (re.compile(r'self[- ]aware', re.I), "self-aware"),
    (re.compile(r'AI\s+moratorium', re.I), "AI moratorium"),
    (re.compile(r'AI\s+pause', re.I), "AI pause"),
    (re.compile(r'too\s+powerful', re.I), "too powerful"),
    (re.compile(r'\bdangerous\b', re.I), "dangerous"),
    (re.compile(r'singularity', re.I), "singularity"),
    (re.compile(r'skynet', re.I), "skynet"),
    (re.compile(r'terminator', re.I), "Terminator"),
    (re.compile(r'rise\s+of\s+the\s+machines', re.I), "rise of the machines"),
    (re.compile(r'asimov', re.I), "Asimov"),
    (re.compile(r'frankenstein', re.I), "Frankenstein"),
    (re.compile(r'HAL\s+9000', re.I), "HAL 9000"),
    (re.compile(r'the\s+matrix', re.I), "The Matrix"),
    (re.compile(r'science\s+fiction', re.I), "science fiction"),
    (re.compile(r'rogue\s+AI', re.I), "rogue AI"),
    (re.compile(r'If\s+Anyone\s+Builds\s+It', re.I), "If Anyone Builds It Everyone Dies"),
    (re.compile(r'autonomous\s+weapons?', re.I), "autonomous weapons"),
    (re.compile(r'lethal\s+autonomous', re.I), "lethal autonomous"),
    (re.compile(r'weaponized', re.I), "weaponized"),
    (re.compile(r'kill\s+chain', re.I), "kill chain"),
    (re.compile(r'AI\s+arms\s+race', re.I), "AI arms race"),
    (re.compile(r'atomic\s+bomb', re.I), "atomic bomb"),
    (re.compile(r'Manhattan\s+Project', re.I), "Manhattan Project"),
    (re.compile(r'deception', re.I), "deception"),
    (re.compile(r'deceiv(?:ing|e)', re.I), "deceiving"),
    (re.compile(r'blackmail', re.I), "blackmail"),
    (re.compile(r'sentient', re.I), "sentient"),
    (re.compile(r'AI\s+consciousness', re.I), "AI consciousness"),
    (re.compile(r'escape\s+velocity', re.I), "escape velocity"),
]

# ---------------------------------------------------------------------------
# AI-context filter
# ---------------------------------------------------------------------------

_ALWAYS_AI = {
    "artificial general intelligence",
    "superintelligence", "intelligence explosion",
    "recursive self-improvement", "capability amplification",
    "superhuman AI", "ultra-intelligent",
    "AI safety", "AI alignment", "AI moratorium", "AI pause",
    "AI consciousness", "AI arms race", "rogue AI",
    "autonomous weapons", "lethal autonomous",
    "Turing Test", "HAL 9000", "rise of the machines",
    "If Anyone Builds It Everyone Dies", "skynet",
}

_HIGH_AMBIGUITY = {
    "existential risk", "existential threat", "catastrophic risk",
    "end of humanity", "end of the world",
    "loss of control", "lose control", "out of control",
    "extinction", "kill us all",
    "too powerful", "dangerous",
    "surpass", "god", "destroy", "destruction", "improve",
    "deception", "deceiving", "blackmail",
    "science fiction", "escape velocity", "weaponized",
    "atomic bomb", "Manhattan Project",
}

_AI_INDICATORS = [
    "artificial intelligence", " ai ", " ai.", " ai,", " ai;",
    "machine learning", "algorithm", "chatgpt", "openai",
    "large language model", "neural network", "deep learning",
    "automation", "autonomous", "robot", "generative ai",
    "superintelligen", "agi", "artificial general",
    "machine intelligence", "computer intelligence",
    "anthropic", "claude", "gemini", " gpt", " llm",
    "frontier model", "agentic", "transformer",
]


def is_ai_context(text, match_start, match_end, label):
    if label in _ALWAYS_AI:
        return True
    window_start = max(0, match_start - 800)
    window_end = min(len(text), match_end + 800)
    window = text[window_start:window_end].lower()
    indicator_count = sum(1 for ind in _AI_INDICATORS if ind in window)
    if label in _HIGH_AMBIGUITY:
        return indicator_count >= 2
    return indicator_count >= 1


# ---------------------------------------------------------------------------
# Quality scoring (from analyze_quotes.py)
# ---------------------------------------------------------------------------

_STRONG_PHRASES = [
    "existential", "extinction", "end of human", "destroy",
    "catastrophic", "loss of control", "out of control",
    "lose control", "uncontrollable",
    "superintelligen", "artificial general intelligence",
    "intelligence explosion",
    " agi ", "skynet", "terminator", "self-aware",
    "survival instinct", "threat to human",
    "rogue ai", "autonomous weapon", "lethal autonomous",
    "weaponized", "kill chain", "arms race",
    "misalignment", "ai safety", "ai alignment",
    "deception", "deceiv", "blackmail",
    "rise of the machines", "frankenstein", "hal 9000",
    "the matrix", "asimov", "manhattan project", "atomic bomb",
    "escape velocity",
    "too powerful",
    "capability amplification",
]


def quality_score(passage, is_ai_ctx):
    """Quick quality score for a passage. Returns 0-10."""
    if not is_ai_ctx:
        return 0
    score = 5
    pl = passage.lower()

    substantive = [
        "we need to", "we must", "we should", "i believe", "i think",
        "concerned about", "worry about", "worried about", "threat",
        "dangerous", "catastroph", "regulation", "regulate", "guardrail",
        "safeguard", "safety", "alignment", "oversight",
    ]
    sub_count = sum(1 for s in substantive if s in pl)
    if sub_count >= 2:
        score += 2
    elif sub_count == 1:
        score += 1

    term_count = sum(1 for regex, _ in SEARCH_REGEXES if regex.search(passage))
    if term_count >= 3:
        score += 2
    elif term_count >= 2:
        score += 1

    strong_count = sum(1 for s in _STRONG_PHRASES if s in pl)
    if strong_count >= 2:
        score += 2
    elif strong_count >= 1:
        score += 1

    word_count = len(passage.split())
    if word_count < 50:
        score -= 2

    procedural = ["yield back", "unanimous consent", "without objection",
                   "ordered to be printed", "point of order"]
    if any(p in pl for p in procedural):
        score -= 1

    if "short title" in pl or "be it enacted" in pl:
        score -= 3

    return max(0, min(10, score))


# ---------------------------------------------------------------------------
# State management
# ---------------------------------------------------------------------------

def load_processed_ids():
    if PROCESSED_IDS_FILE.exists():
        return set(json.loads(PROCESSED_IDS_FILE.read_text()))
    return set()


def save_processed_ids(ids):
    PROCESSED_IDS_FILE.write_text(json.dumps(sorted(ids), indent=2))


def load_last_run_date():
    if LAST_RUN_FILE.exists():
        return LAST_RUN_FILE.read_text().strip()
    return None


def save_last_run_date():
    LAST_RUN_FILE.write_text(date.today().isoformat())


# ---------------------------------------------------------------------------
# GovInfo API
# ---------------------------------------------------------------------------

def govinfo_request(method, url, **kwargs):
    for attempt in range(5):
        resp = (requests.post if method == "POST" else requests.get)(url, **kwargs)
        if resp.status_code == 429:
            retry = resp.headers.get("Retry-After")
            wait = min(int(retry) + 5, 120) if retry and retry.isdigit() else 60 * (attempt + 1)
            print(f"  Rate limited. Waiting {wait}s …")
            time.sleep(wait)
            continue
        if resp.status_code >= 500:
            time.sleep(15 * (attempt + 1))
            continue
        return resp
    return resp


def search_cache_path(label):
    key = re.sub(r'[^\w]', '_', label)
    return CACHE_DIR / f"search__{key}.json"


def search_govinfo(full_range=False):
    """Search GovInfo API for all terms. Returns dict of doc_id -> API result."""
    all_results = {}
    today = date.today().isoformat()

    if full_range:
        start = DATE_START
        print(f"  Full range: {start} to {today}")
    else:
        last_run = load_last_run_date()
        if last_run:
            from dateutil.relativedelta import relativedelta
            last_dt = datetime.strptime(last_run, "%Y-%m-%d").date()
            start = (last_dt - relativedelta(months=1)).isoformat()
            print(f"  Last run: {last_run} → searching from {start}")
        else:
            start = DATE_START
            print(f"  First run → searching from {start}")

    for i, (query_fragment, label) in enumerate(SEARCH_TERMS, 1):
        print(f"  [{i}/{len(SEARCH_TERMS)}] {label}", end=" … ", flush=True)

        full_query = (
            f'{query_fragment} '
            f'collection:(CREC OR CHRG) '
            f'publishdate:range({start},{today})'
        )

        results = []
        offset_mark = "*"

        while True:
            time.sleep(REQUEST_DELAY)
            resp = govinfo_request(
                "POST",
                f"{GOVINFO_BASE}/search?api_key={GOVINFO_API_KEY}",
                json={
                    "query": full_query,
                    "pageSize": PAGE_SIZE,
                    "offsetMark": offset_mark,
                    "sorts": [{"field": "publishdate", "sortOrder": "DESC"}],
                },
                headers={"Content-Type": "application/json"},
            )
            if resp.status_code != 200:
                print(f"FAIL ({resp.status_code})")
                break

            data = resp.json()
            page_results = data.get("results", [])
            new_offset = data.get("offsetMark", offset_mark)
            if not page_results:
                break
            results.extend(page_results)
            if len(results) >= data.get("count", 0) or new_offset == offset_mark:
                break
            offset_mark = new_offset

        print(f"{len(results)} results")

        # Update search cache
        cached = search_cache_path(label)
        cached.write_text(json.dumps(results, indent=2), encoding="utf-8")

        for r in results:
            pid = r.get('packageId') or ''
            gid = r.get('granuleId') or ''
            doc_id = f"{pid}__{gid}"
            if doc_id not in all_results:
                all_results[doc_id] = r

    return all_results


def load_from_cache():
    """Load documents from search cache files."""
    cache_files = sorted(CACHE_DIR.glob("search__*.json"))
    if not cache_files:
        print("Error: No search cache files found. Run with --all first.")
        sys.exit(1)

    docs = {}
    for f in cache_files:
        for r in json.loads(f.read_text(encoding="utf-8")):
            pid = r.get('packageId') or ''
            gid = r.get('granuleId') or ''
            doc_id = f"{pid}__{gid}"
            if doc_id not in docs:
                docs[doc_id] = r
    return docs


# ---------------------------------------------------------------------------
# Document handling
# ---------------------------------------------------------------------------

def html_cache_path(doc_id):
    parts = doc_id.split("__", 1)
    package_id = parts[0]
    granule_id = parts[1] if len(parts) > 1 else ""
    if granule_id and granule_id not in ("None", ""):
        key = f"{package_id}__{granule_id}"
    else:
        key = package_id
    key = re.sub(r'[^\w\-]', '_', key)
    return CACHE_DIR / f"{key}.html"


def fetch_document_html(txt_link, package_id, granule_id):
    key = f"{package_id}__{granule_id}" if granule_id else package_id
    key = re.sub(r'[^\w\-]', '_', key)
    cached = CACHE_DIR / f"{key}.html"
    if cached.exists():
        return cached.read_text(encoding="utf-8", errors="replace")
    if not txt_link:
        return None
    sep = "&" if "?" in txt_link else "?"
    url = f"{txt_link}{sep}api_key={GOVINFO_API_KEY}"
    time.sleep(REQUEST_DELAY)
    resp = govinfo_request("GET", url)
    if resp.status_code != 200:
        return None
    cached.write_text(resp.text, encoding="utf-8")
    return resp.text


def html_to_text(html):
    soup = BeautifulSoup(html, "html.parser")
    pre = soup.find("pre")
    return pre.get_text() if pre else soup.get_text()


# ---------------------------------------------------------------------------
# Passage extraction with AI-context + quality pre-filter
# ---------------------------------------------------------------------------

def extract_passages_scored(text, max_passages=5):
    """Find search-term matches in AI context, score them, return passages + scores.
    Returns list of (passage_text, max_score) tuples."""
    matches = []
    for regex, label in SEARCH_REGEXES:
        for m in regex.finditer(text):
            ai_ctx = is_ai_context(text, m.start(), m.end(), label)
            matches.append((m.start(), m.end(), label, ai_ctx))
    if not matches:
        return []

    matches.sort(key=lambda x: x[0])

    passages = []
    last_end = -1

    for pos, end_pos, label, ai_ctx in matches:
        start = max(0, pos - 750)
        end = min(len(text), pos + 750)
        if start < last_end:
            continue
        passage = text[start:end].strip()
        passage = re.sub(r'\s+', ' ', passage)
        score = quality_score(passage, ai_ctx)
        passages.append((passage, score))
        last_end = end
        if len(passages) >= max_passages:
            break

    return passages


# ---------------------------------------------------------------------------
# LLM classification
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """\
You are an analyst identifying quotes from **members of the U.S. Congress** \
that substantively engage with advanced AI risks. Target topics include:
- AGI / artificial general intelligence / artificial superintelligence
- AI existential risk, catastrophic risk, or extinction risk
- AI loss of control, alignment, misalignment, or AI safety concerns
- Recursive self-improvement, intelligence explosion, capability amplification
- The Singularity, superhuman AI, human-level AI
- AI deception, self-preservation, or autonomous behavior concerns
- Autonomous weapons, weaponized AI, or AI arms race
- Pop-culture AI risk references (Skynet, Terminator, The Matrix, etc.)

You will receive metadata about a congressional document plus several text \
passages from it that contain relevant search-term matches. Your job:

1. For each passage, determine whether a **member of Congress** (not a \
witness, expert, or other non-member) is speaking or asking a question \
that substantively engages with one of the target topics.

2. EXCLUDE passages where:
   - The search term appears only in witness/expert testimony, not member speech.
   - The member is just reading a bill title or procedural text.
   - The match is incidental and NOT about AI risks. Common false positives: \
"existential risk/threat" about climate, debt, or geopolitics; \
"loss of control" / "out of control" about aviation, spending, or borders; \
"extinction" about species or languages; "weapons of mass destruction" about \
nuclear/chemical/biological weapons (not AI); "deception" about fraud or politics; \
"blackmail" about non-AI crimes; "The Matrix" / "Terminator" / "science fiction" \
in non-AI context; "Manhattan Project" about the historical project (not AI analogy); \
"too powerful" / "dangerous" about non-AI topics; \
"destroy" / "destruction" about war, property, or the environment (not AI); \
"god" in religious/rhetorical references unrelated to AI; \
"surpass" about athletic, economic, or other non-AI achievements; \
"improve" about generic policy, products, or services (not AI capability gains); \
"sentient" about animals; "escape velocity" about space; "Frankenstein" about \
biotech or literature; "uncontrollable" about spending or bureaucracy; \
"catastrophic risk" about natural disasters or finance.
   - The member is merely quoting someone else without expressing their own view.

3. For each passage that DOES qualify, extract:
   - **speaker_name**: Full name of the Congress member (e.g., "Bernie Sanders").
   - **speaker_title**: "Sen." or "Rep."
   - **party**: "D", "R", or "I"
   - **state**: Two-letter state abbreviation
   - **quote**: A clean, readable excerpt of ONLY the member's own words \
(100-250 words). Use "[...]" for omissions. Do not include witness responses or \
other speakers' words.
   - **source_description**: A one-line description of the source (e.g., \
"Senate HELP Committee hearing on AI governance, Mar 8 2023").
   - **search_terms_matched**: Which of the target terms appear in or near \
the member's speech.
   - **directness**: "direct" if the member is expressing their own substantive \
view or concern about AGI/x-risk, "indirect" if they are asking a question about \
it or mentioning it in passing.

Return valid JSON: a list of objects (one per qualifying quote), or an empty \
list [] if no passages qualify. No commentary outside the JSON."""

TRACKED_MEMBERS_STR = ", ".join(sorted(TRACKED_MEMBERS))


def classify_document(client, doc_meta, passages):
    user_msg = f"""## Document metadata
- Collection: {doc_meta['collection']}
- Date: {doc_meta['date']}
- Title: {doc_meta['title']}
- Chamber: {doc_meta['chamber']}
- Source URL: {doc_meta['source_url']}

## Already-tracked members (for reference — still extract their quotes, but flag them)
{TRACKED_MEMBERS_STR}

## Passages to analyze
"""
    for i, p in enumerate(passages, 1):
        user_msg += f"\n### Passage {i}\n{p}\n"

    resp = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=4096,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_msg}],
    )

    text = resp.content[0].text.strip()
    text = re.sub(r'^```(?:json)?\s*', '', text)
    text = re.sub(r'\s*```$', '', text)

    try:
        results = json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r'\[.*\]', text, re.DOTALL)
        if not m:
            print(f"    LLM returned non-JSON: {text[:120]}")
            return []
        try:
            results = json.loads(m.group(0))
        except json.JSONDecodeError:
            print(f"    LLM returned non-JSON: {text[:120]}")
            return []

    if not isinstance(results, list):
        return []

    for r in results:
        r["date"] = doc_meta["date"]
        r["source_url"] = doc_meta["source_url"]
        r["collection"] = doc_meta["collection"]
        r["is_tracked"] = r.get("speaker_name", "") in TRACKED_MEMBERS

    return results


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def format_date_short(iso_date):
    try:
        dt = datetime.strptime(iso_date, "%Y-%m-%d")
        return dt.strftime("%b %-d, %Y")
    except (ValueError, TypeError):
        return iso_date


def write_markdown(new_quotes, existing_quotes):
    lines = []

    if new_quotes:
        lines.append("# New Members\n")
        for i, q in enumerate(new_quotes, 1):
            lines.append(f"## {i}. {q.get('speaker_title', '')} {q['speaker_name']}\n")
            lines.append(f"**{format_date_short(q['date'])}**")
            lines.append(
                f"**{q.get('speaker_title', '')} {q['speaker_name']} "
                f"({q.get('party', '?')}-{q.get('state', '?')})**\n"
            )
            lines.append(f"{q['quote']}\n")
            lines.append(f"[GovInfo]({q['source_url']})\n")
            lines.append(f"{q.get('source_description', '')}\n")
            lines.append("---\n")

    if existing_quotes:
        lines.append("# New Quotes from Tracked Members\n")
        for i, q in enumerate(existing_quotes, 1):
            lines.append(f"## {i}. {q.get('speaker_title', '')} {q['speaker_name']}\n")
            lines.append(f"**{format_date_short(q['date'])}**")
            lines.append(
                f"**{q.get('speaker_title', '')} {q['speaker_name']} "
                f"({q.get('party', '?')}-{q.get('state', '?')})**\n"
            )
            lines.append(f"{q['quote']}\n")
            lines.append(f"[GovInfo]({q['source_url']})\n")
            lines.append(f"{q.get('source_description', '')}\n")
            lines.append("---\n")

    if not new_quotes and not existing_quotes:
        lines.append("No new quotes found in this run.\n")

    OUTPUT_MD.write_text("\n".join(lines), encoding="utf-8")


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Unified congressional AI quote pipeline")
    parser.add_argument("--all", action="store_true",
                        help="Search full date range (DATE_START to today)")
    parser.add_argument("--skip-search", action="store_true",
                        help="Skip GovInfo API search, use cached results")
    parser.add_argument("--skip-llm", action="store_true",
                        help="Rule-based analysis only, no LLM calls")
    parser.add_argument("--reprocess", action="store_true",
                        help="Ignore processed_ids, re-analyze all documents")
    parser.add_argument("--min-score", type=int, default=4,
                        help="Minimum quality score to send to LLM (default: 4)")
    args = parser.parse_args()

    print("=" * 60)
    print("Congressional AI Quote Pipeline")
    print("=" * 60)

    processed_ids = set() if args.reprocess else load_processed_ids()
    print(f"Already processed: {len(processed_ids)} documents")

    # ── Step 1: Get document list ──────────────────────────────────
    if args.skip_search:
        print("\n── Loading from search cache ──")
        all_docs = load_from_cache()
    else:
        print("\n── Step 1: Searching GovInfo API ──")
        all_docs = search_govinfo(full_range=args.all)

    print(f"Total unique documents: {len(all_docs)}")
    new_ids = set(all_docs.keys()) - processed_ids
    print(f"New (unprocessed): {len(new_ids)}")

    if not new_ids:
        print("\nNothing new to process.")
        save_last_run_date()
        return

    # ── Step 2: Download + rule-based pre-filter ───────────────────
    print(f"\n── Step 2: Extracting passages (min score: {args.min_score}) ──")
    docs_to_analyze = []
    rule_based_results = []  # all passages with scores (for CSV output)
    skipped_no_html = 0
    skipped_no_passages = 0
    skipped_low_score = 0

    for count, doc_id in enumerate(sorted(new_ids), 1):
        if count % 200 == 0:
            print(f"  Scanned {count}/{len(new_ids)} documents …")

        r = all_docs[doc_id]
        doc_date = r.get("dateIssued") or ""
        doc_title = r.get("title") or ""
        collection = r.get("collectionCode") or ""
        package_id = r.get("packageId") or ""
        granule_id = r.get("granuleId") or ""

        cached_html = html_cache_path(doc_id)
        if not cached_html.exists():
            txt_link = (r.get("download") or {}).get("txtLink")
            html = fetch_document_html(txt_link, package_id, granule_id)
            if not html:
                processed_ids.add(doc_id)
                skipped_no_html += 1
                continue
        else:
            html = cached_html.read_text(encoding="utf-8", errors="replace")

        text = html_to_text(html)
        if not text or len(text) < 200:
            processed_ids.add(doc_id)
            skipped_no_html += 1
            continue

        scored_passages = extract_passages_scored(text)
        if not scored_passages:
            processed_ids.add(doc_id)
            skipped_no_passages += 1
            continue

        max_score = max(s for _, s in scored_passages)

        # Determine chamber
        gid_upper = (granule_id or "").upper()
        chamber = "House" if "PgH" in gid_upper or "hhrg" in doc_id.lower() else (
            "Senate" if "PgS" in gid_upper or "shrg" in doc_id.lower() else "Unknown"
        )

        source_url = f"https://www.govinfo.gov/app/details/{package_id}"
        if granule_id and granule_id not in ("", "None") and granule_id != package_id:
            source_url += f"/{granule_id}"

        doc_meta = {
            "doc_id": doc_id,
            "collection": collection,
            "date": doc_date,
            "title": doc_title,
            "chamber": chamber,
            "source_url": source_url,
        }

        # Save all scored passages for the rule-based CSV output
        for passage_text, score in scored_passages:
            rule_based_results.append({
                **doc_meta,
                "passage": passage_text[:500],
                "quality_score": score,
            })

        # Only send high-scoring docs to LLM
        if max_score >= args.min_score:
            passages_text = [p for p, s in scored_passages]
            docs_to_analyze.append({**doc_meta, "passages": passages_text, "max_score": max_score})
        else:
            processed_ids.add(doc_id)
            skipped_low_score += 1

    print(f"\n  Scanned: {len(new_ids)}")
    print(f"  Skipped (no HTML): {skipped_no_html}")
    print(f"  Skipped (no AI-context matches): {skipped_no_passages}")
    print(f"  Skipped (score < {args.min_score}): {skipped_low_score}")
    print(f"  Candidates for LLM: {len(docs_to_analyze)}")

    save_processed_ids(processed_ids)

    # ── Step 3: LLM classification ──────────────────────────────────
    all_new_quotes = []
    all_existing_quotes = []

    if args.skip_llm:
        print("\n── Skipping LLM (--skip-llm) ──")
    elif not docs_to_analyze:
        print("\n── No candidates above score threshold ──")
    else:
        print(f"\n── Step 3: Classifying {len(docs_to_analyze)} documents with Claude ──")
        client = anthropic.Anthropic()

        for j, doc in enumerate(docs_to_analyze, 1):
            title_short = (doc['title'] or '')[:60]
            print(f"  [{j}/{len(docs_to_analyze)}] {doc['date']} {title_short}… (score={doc['max_score']})", flush=True)

            try:
                quotes = classify_document(client, doc, doc["passages"])
            except Exception as e:
                print(f"    Error: {e}")
                quotes = []

            if quotes:
                names = [q.get("speaker_name", "?") for q in quotes]
                print(f"    -> {len(quotes)} quote(s): {', '.join(names)}")

            for q in quotes:
                if q.get("is_tracked"):
                    all_existing_quotes.append(q)
                else:
                    all_new_quotes.append(q)

            processed_ids.add(doc["doc_id"])
            save_processed_ids(processed_ids)

    # ── Step 4: Output ──────────────────────────────────────────────
    print(f"\n── Results ──")
    print(f"  New member quotes: {len(all_new_quotes)}")
    print(f"  Tracked member quotes: {len(all_existing_quotes)}")
    print(f"  Rule-based passages found: {len(rule_based_results)}")

    def sort_key(q):
        direct = 0 if q.get("directness") == "direct" else 1
        return (direct, q.get("date", ""), q.get("speaker_name", ""))

    all_new_quotes.sort(key=sort_key)
    all_existing_quotes.sort(key=sort_key)

    write_markdown(all_new_quotes, all_existing_quotes)
    print(f"  Wrote {OUTPUT_MD}")

    raw_output = CACHE_DIR / "latest_run_quotes.json"
    raw_output.write_text(json.dumps(
        {"new_members": all_new_quotes, "tracked_members": all_existing_quotes},
        indent=2,
    ))
    print(f"  Wrote {raw_output}")

    save_processed_ids(processed_ids)
    save_last_run_date()
    print(f"  Processed IDs: {len(processed_ids)} total")
    print(f"  Last run date: {date.today().isoformat()}")


if __name__ == "__main__":
    main()
