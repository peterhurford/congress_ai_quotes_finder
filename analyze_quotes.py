#!/usr/bin/env python3
"""
Analyze cached GovInfo documents to extract speaker-attributed quotes
from members of Congress about AGI/x-risk topics.

Reads: govinfo_cache/*.html, govinfo_agi_results.csv
Outputs: analysis results to stdout + quote_analysis.csv
"""

import csv
import re
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

from bs4 import BeautifulSoup

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

CACHE_DIR = Path("govinfo_cache")
INPUT_CSV = "govinfo_agi_results.csv"
OUTPUT_CSV = "quote_analysis.csv"
LAST_RUN_FILE = Path(".last_run")

CONTEXT_WORDS = 300  # words around match for quote excerpt

# ---------------------------------------------------------------------------
# Known members — tracked list
# ---------------------------------------------------------------------------

TRACKED_MEMBERS = [
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
]

# Build lookup by uppercase last name
TRACKED_BY_LASTNAME = {}
for full_name, party, title, state in TRACKED_MEMBERS:
    parts = full_name.split()
    lastname = parts[-1].upper()
    TRACKED_BY_LASTNAME[lastname] = (full_name, party, title, state)
    if len(parts) > 2:
        compound = " ".join(parts[1:]).upper()
        TRACKED_BY_LASTNAME[compound] = (full_name, party, title, state)

# ---------------------------------------------------------------------------
# Comprehensive Congress member lookup (not on tracked list)
# Maps UPPERCASE last name -> (full_name, party, title, state)
# This lets us distinguish members from witnesses
# ---------------------------------------------------------------------------

OTHER_CONGRESS_MEMBERS = {
    # Senate (118th-119th)
    "BALDWIN": ("Tammy Baldwin", "D", "Sen.", "WI"),
    "BARRASSO": ("John Barrasso", "R", "Sen.", "WY"),
    "BENNET": ("Michael Bennet", "D", "Sen.", "CO"),
    "BOOKER": ("Cory Booker", "D", "Sen.", "NJ"),
    "BOOZMAN": ("John Boozman", "R", "Sen.", "AR"),
    "BRAUN": ("Mike Braun", "R", "Sen.", "IN"),
    "BRITT": ("Katie Britt", "R", "Sen.", "AL"),
    "BROWN": ("Sherrod Brown", "D", "Sen.", "OH"),
    "BUDD": ("Ted Budd", "R", "Sen.", "NC"),
    "CANTWELL": ("Maria Cantwell", "D", "Sen.", "WA"),
    "CARDIN": ("Ben Cardin", "D", "Sen.", "MD"),
    "CARPER": ("Tom Carper", "D", "Sen.", "DE"),
    "CASEY": ("Bob Casey", "D", "Sen.", "PA"),
    "CASSIDY": ("Bill Cassidy", "R", "Sen.", "LA"),
    "COLLINS": ("Susan Collins", "R", "Sen.", "ME"),
    "COONS": ("Chris Coons", "D", "Sen.", "DE"),
    "CORNYN": ("John Cornyn", "R", "Sen.", "TX"),
    "CORTEZ MASTO": ("Catherine Cortez Masto", "D", "Sen.", "NV"),
    "COTTON": ("Tom Cotton", "R", "Sen.", "AR"),
    "CRAMER": ("Kevin Cramer", "R", "Sen.", "ND"),
    "CRAPO": ("Mike Crapo", "R", "Sen.", "ID"),
    "CRUZ": ("Ted Cruz", "R", "Sen.", "TX"),
    "DAINES": ("Steve Daines", "R", "Sen.", "MT"),
    "DUCKWORTH": ("Tammy Duckworth", "D", "Sen.", "IL"),
    "DURBIN": ("Dick Durbin", "D", "Sen.", "IL"),
    "ERNST": ("Joni Ernst", "R", "Sen.", "IA"),
    "FEINSTEIN": ("Dianne Feinstein", "D", "Sen.", "CA"),
    "FISCHER": ("Deb Fischer", "R", "Sen.", "NE"),
    "GALLEGO": ("Ruben Gallego", "D", "Sen.", "AZ"),
    "GILLIBRAND": ("Kirsten Gillibrand", "D", "Sen.", "NY"),
    "GRAHAM": ("Lindsey Graham", "R", "Sen.", "SC"),
    "GRASSLEY": ("Chuck Grassley", "R", "Sen.", "IA"),
    "HAGERTY": ("Bill Hagerty", "R", "Sen.", "TN"),
    "HASSAN": ("Maggie Hassan", "D", "Sen.", "NH"),
    "HEINRICH": ("Martin Heinrich", "D", "Sen.", "NM"),
    "HOEVEN": ("John Hoeven", "R", "Sen.", "ND"),
    "HYDE-SMITH": ("Cindy Hyde-Smith", "R", "Sen.", "MS"),
    "JOHNSON": ("Ron Johnson", "R", "Sen.", "WI"),
    "KAINE": ("Tim Kaine", "D", "Sen.", "VA"),
    "KELLY": ("Mark Kelly", "D", "Sen.", "AZ"),
    "KING": ("Angus King", "I", "Sen.", "ME"),
    "KLOBUCHAR": ("Amy Klobuchar", "D", "Sen.", "MN"),
    "LANKFORD": ("James Lankford", "R", "Sen.", "OK"),
    "LUJAN": ("Ben Ray Lujan", "D", "Sen.", "NM"),
    "MANCHIN": ("Joe Manchin", "I", "Sen.", "WV"),
    "MARKEY": ("Ed Markey", "D", "Sen.", "MA"),
    "MARSHALL": ("Roger Marshall", "R", "Sen.", "KS"),
    "MCCONNELL": ("Mitch McConnell", "R", "Sen.", "KY"),
    "MENENDEZ": ("Bob Menendez", "D", "Sen.", "NJ"),
    "MERKLEY": ("Jeff Merkley", "D", "Sen.", "OR"),
    "MORAN": ("Jerry Moran", "R", "Sen.", "KS"),
    "MULLIN": ("Markwayne Mullin", "R", "Sen.", "OK"),
    "MURKOWSKI": ("Lisa Murkowski", "R", "Sen.", "AK"),
    "OSSOFF": ("Jon Ossoff", "D", "Sen.", "GA"),
    "PADILLA": ("Alex Padilla", "D", "Sen.", "CA"),
    "PAUL": ("Rand Paul", "R", "Sen.", "KY"),
    "PETERS": ("Gary Peters", "D", "Sen.", "MI"),
    "REED": ("Jack Reed", "D", "Sen.", "RI"),
    "RICKETTS": ("Pete Ricketts", "R", "Sen.", "NE"),
    "RISCH": ("Jim Risch", "R", "Sen.", "ID"),
    "ROMNEY": ("Mitt Romney", "R", "Sen.", "UT"),
    "ROSEN": ("Jacky Rosen", "D", "Sen.", "NV"),
    "RUBIO": ("Marco Rubio", "R", "Sen.", "FL"),
    "SCOTT": ("Tim Scott", "R", "Sen.", "SC"),
    "SHAHEEN": ("Jeanne Shaheen", "D", "Sen.", "NH"),
    "SINEMA": ("Kyrsten Sinema", "I", "Sen.", "AZ"),
    "SMITH": ("Tina Smith", "D", "Sen.", "MN"),
    "STABENOW": ("Debbie Stabenow", "D", "Sen.", "MI"),
    "SULLIVAN": ("Dan Sullivan", "R", "Sen.", "AK"),
    "TESTER": ("Jon Tester", "D", "Sen.", "MT"),
    "THUNE": ("John Thune", "R", "Sen.", "SD"),
    "TILLIS": ("Thom Tillis", "R", "Sen.", "NC"),
    "TUBERVILLE": ("Tommy Tuberville", "R", "Sen.", "AL"),
    "VAN HOLLEN": ("Chris Van Hollen", "D", "Sen.", "MD"),
    "VANCE": ("JD Vance", "R", "Sen.", "OH"),
    "WARNER": ("Mark Warner", "D", "Sen.", "VA"),
    "WARNOCK": ("Raphael Warnock", "D", "Sen.", "GA"),
    "WARREN": ("Elizabeth Warren", "D", "Sen.", "MA"),
    "WELCH": ("Peter Welch", "D", "Sen.", "VT"),
    "WHITEHOUSE": ("Sheldon Whitehouse", "D", "Sen.", "RI"),
    "WICKER": ("Roger Wicker", "R", "Sen.", "MS"),
    "WYDEN": ("Ron Wyden", "D", "Sen.", "OR"),
    "YOUNG": ("Todd Young", "R", "Sen.", "IN"),
    "KYL": ("Jon Kyl", "R", "Sen.", "AZ"),  # former, sometimes appears in hearings
    # House members likely to appear in these hearings
    "KHANNA": ("Ro Khanna", "D", "Rep.", "CA"),
    "GALLAGHER": ("Mike Gallagher", "R", "Rep.", "WI"),
    "BUCK": ("Ken Buck", "R", "Rep.", "CO"),
    "MCBATH": ("Lucy McBath", "D", "Rep.", "GA"),
    "SWALWELL": ("Eric Swalwell", "D", "Rep.", "CA"),
    "GARBARINO": ("Andrew Garbarino", "R", "Rep.", "NY"),
    "BURCHETT": ("Tim Burchett", "R", "Rep.", "TN"),
    "SEWELL": ("Terri Sewell", "D", "Rep.", "AL"),
    "CORREA": ("Lou Correa", "D", "Rep.", "CA"),
    "CARSON": ("Andre Carson", "D", "Rep.", "IN"),
    "FOUSHEE": ("Valerie Foushee", "D", "Rep.", "NC"),
    "OGLES": ("Andy Ogles", "R", "Rep.", "TN"),
    "SCHWEIKERT": ("David Schweikert", "R", "Rep.", "AZ"),
    "BRECHEEN": ("Josh Brecheen", "R", "Rep.", "OK"),
    "HIGGINS": ("Clay Higgins", "R", "Rep.", "LA"),
    "SUBRAMANYAM": ("Suhas Subramanyam", "D", "Rep.", "VA"),
    "MCGUIRE": ("Rich McGuire", "R", "Rep.", "OK"),
    "WILLIAMS": ("Roger Williams", "R", "Rep.", "TX"),
    "OBERNOLTE": ("Jay Obernolte", "R", "Rep.", "CA"),
    "LOFGREN": ("Zoe Lofgren", "D", "Rep.", "CA"),
    "ISSA": ("Darrell Issa", "R", "Rep.", "CA"),
    "MASSIE": ("Thomas Massie", "R", "Rep.", "KY"),
    "RASKIN": ("Jamie Raskin", "D", "Rep.", "MD"),
    "JORDAN": ("Jim Jordan", "R", "Rep.", "OH"),
    "NADLER": ("Jerry Nadler", "D", "Rep.", "NY"),
    "BISHOP": ("Dan Bishop", "R", "Rep.", "NC"),
    "JACKSON": ("Ronny Jackson", "R", "Rep.", "TX"),
    "GARCIA": ("Mike Garcia", "R", "Rep.", "CA"),
    "MCCLINTOCK": ("Tom McClintock", "R", "Rep.", "CA"),
    "DAVIDSON": ("Warren Davidson", "R", "Rep.", "OH"),
    "EZELL": ("Mike Ezell", "R", "Rep.", "MS"),
    "STRONG": ("Dale Strong", "R", "Rep.", "AL"),
    "IVEY": ("Glenn Ivey", "D", "Rep.", "MD"),
    "THANEDAR": ("Shri Thanedar", "D", "Rep.", "MI"),
    "RAMIREZ": ("Delia Ramirez", "D", "Rep.", "IL"),
    "CLARKE": ("Yvette Clarke", "D", "Rep.", "NY"),
    "KELLY": ("Mike Kelly", "R", "Rep.", "PA"),
    "MCDOWELL": ("Patrick McDowell", "R", "Rep.", "FL"),
    "KNOTT": ("Bob Knott", "R", "Rep.", "FL"),
    "KILMER": ("Derek Kilmer", "D", "Rep.", "WA"),
    "STEIL": ("Bryan Steil", "R", "Rep.", "WI"),
    "CONNOLLY": ("Gerry Connolly", "D", "Rep.", "VA"),
    "BROWN": ("Shontel Brown", "D", "Rep.", "OH"),
}

# Members who share a last name but differ by gender prefix.
# Maps (LASTNAME, gender_prefix) -> member info
# gender_prefix: "Ms"/"Mrs"/"Miss" = female, "Mr"/"Dr" = male (Dr. can be either, handled below)
GENDERED_OVERRIDES = {
    ("LEE", "Ms"): ("Summer Lee", "D", "Rep.", "PA"),
    ("LEE", "Mrs"): ("Summer Lee", "D", "Rep.", "PA"),
    ("LEE", "Mr"): ("Mike Lee", "R", "Sen.", "UT"),     # tracked
    ("MURPHY", "Dr"): ("Gregory Murphy", "R", "Rep.", "NC"),
    ("MURPHY", "Mr"): ("Chris Murphy", "D", "Sen.", "CT"),  # tracked
    ("JOHNSON", "Mr"): ("Dusty Johnson", "R", "Rep.", "SD"),  # tracked (ambiguous but default)
    ("BROWN", "Ms"): ("Shontel Brown", "D", "Rep.", "OH"),
}

# Merge: everything in TRACKED goes into a single ALL_MEMBERS dict
ALL_MEMBERS = {}
ALL_MEMBERS.update(OTHER_CONGRESS_MEMBERS)
for full_name, party, title, state in TRACKED_MEMBERS:
    parts = full_name.split()
    lastname = parts[-1].upper()
    ALL_MEMBERS[lastname] = (full_name, party, title, state)


# ---------------------------------------------------------------------------
# Search terms
# ---------------------------------------------------------------------------

SEARCH_REGEXES = [
    # Core AGI / ASI
    (re.compile(r'artificial\s+general\s+intelligence', re.I), "artificial general intelligence"),
    (re.compile(r'artificial\s+superintelligence', re.I), "artificial superintelligence"),
    (re.compile(r'superintelligen(?:ce|t)', re.I), "superintelligence"),
    (re.compile(r'intelligence\s+explosion', re.I), "intelligence explosion"),
    (re.compile(r'recursive\s+self[- ]improvement', re.I), "recursive self-improvement"),
    (re.compile(r'capability\s+amplification', re.I), "capability amplification"),
    (re.compile(r'superhuman\s+AI', re.I), "superhuman AI"),
    (re.compile(r'human[- ]level', re.I), "human-level"),
    (re.compile(r'surpass\s+human', re.I), "surpass human"),
    (re.compile(r'smarter\s+than\s+humans?', re.I), "smarter than humans"),
    (re.compile(r'ultra[- ]intelligent', re.I), "ultra-intelligent"),
    (re.compile(r'digital\s+god', re.I), "digital god"),
    (re.compile(r'Turing\s+Test', re.I), "Turing Test"),
    # Existential / catastrophic
    (re.compile(r'existential\s+risk', re.I), "existential risk"),
    (re.compile(r'existential\s+threat', re.I), "existential threat"),
    (re.compile(r'catastrophic\s+risk', re.I), "catastrophic risk"),
    (re.compile(r'extinction', re.I), "extinction"),
    (re.compile(r'threat\s+to\s+humanity', re.I), "threat to humanity"),
    (re.compile(r'end\s+of\s+humanity', re.I), "end of humanity"),
    (re.compile(r'end\s+of\s+the\s+world', re.I), "end of the world"),
    (re.compile(r'destroy\s+the\s+world', re.I), "destroy the world"),
    (re.compile(r'kill\s+us\s+all', re.I), "kill us all"),
    (re.compile(r'most\s+dangerous', re.I), "most dangerous"),
    (re.compile(r'engineering\s+our\s+own\s+destruction', re.I), "engineering our own destruction"),
    # Control / alignment / safety
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
    (re.compile(r'too\s+dangerous', re.I), "too dangerous"),
    (re.compile(r'singularity', re.I), "singularity"),
    # Pop culture / metaphor
    (re.compile(r'skynet', re.I), "skynet"),
    (re.compile(r'terminator', re.I), "Terminator"),
    (re.compile(r'rise\s+of\s+the\s+machines', re.I), "rise of the machines"),
    (re.compile(r'asimov', re.I), "Asimov"),
    (re.compile(r'frankenstein', re.I), "Frankenstein"),
    (re.compile(r'HAL\s+9000', re.I), "HAL 9000"),
    (re.compile(r'the\s+matrix', re.I), "The Matrix"),
    (re.compile(r'science\s+fiction', re.I), "science fiction"),
    (re.compile(r'rogue\s+AI', re.I), "rogue AI"),
    (re.compile(r'If\s+Anyone\s+Builds\s+It,?\s+Everyone\s+Dies', re.I), "If Anyone Builds It Everyone Dies"),
    # Weaponization / autonomous systems
    (re.compile(r'autonomous\s+weapons?', re.I), "autonomous weapons"),
    (re.compile(r'lethal\s+autonomous', re.I), "lethal autonomous"),
    (re.compile(r'weaponized', re.I), "weaponized"),
    (re.compile(r'kill\s+chain', re.I), "kill chain"),
    (re.compile(r'AI\s+arms\s+race', re.I), "AI arms race"),
    (re.compile(r'weapons?\s+of\s+mass\s+destruction', re.I), "weapons of mass destruction"),
    (re.compile(r'atomic\s+bomb', re.I), "atomic bomb"),
    (re.compile(r'Manhattan\s+Project', re.I), "Manhattan Project"),
    # Deception / self-preservation
    (re.compile(r'deception', re.I), "deception"),
    (re.compile(r'deceiv(?:ing|e)', re.I), "deceiving"),
    (re.compile(r'blackmail', re.I), "blackmail"),
    # Consciousness / sentience / urgency
    (re.compile(r'sentient', re.I), "sentient"),
    (re.compile(r'AI\s+consciousness', re.I), "AI consciousness"),
    (re.compile(r'escape\s+velocity', re.I), "escape velocity"),
]

SPEAKER_PATTERN = re.compile(
    r'(?:^|\n)\s*'
    r'(Mr\.|Mrs\.|Ms\.|Miss|Dr\.|Chairman|Chairwoman|Chair|Ranking\s+Member|Senator|Sen\.|Representative|Rep\.)'
    r'\s+'
    r'([A-Z][A-Za-z\' -]+?)'
    r'\s*[\.\?]',
    re.MULTILINE
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def html_to_text(html):
    soup = BeautifulSoup(html, "html.parser")
    pre = soup.find("pre")
    if pre:
        return pre.get_text()
    return soup.get_text()


def extract_witness_names(text):
    """Extract witness last names from CHRG hearing text."""
    witnesses = set()

    # Pattern 1: WITNESS(ES) section
    witness_section = re.search(
        r'WITNESS(?:ES)?\s*\n(.*?)(?:\n\s*\n\s*\n|\nOPENING|\nCONTENTS|\nSTATEMENT\s+OF)',
        text[:8000], re.DOTALL | re.IGNORECASE
    )
    if witness_section:
        block = witness_section.group(1)
        for m in re.finditer(r'(?:Mr\.|Mrs\.|Ms\.|Dr\.)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)', block):
            parts = m.group(1).split()
            if parts:
                witnesses.add(parts[-1].upper())

    # Pattern 2: "STATEMENT OF FIRSTNAME LASTNAME, TITLE" headers
    for m in re.finditer(
        r'STATEMENT\s+OF\s+([A-Z][A-Z\s,.-]+?)(?:\n|,\s*(?:Ph\.?D|M\.?D|J\.?D|PRESIDENT|DIRECTOR|CHIEF|PROFESSOR|EXECUTIVE|FOUNDER|SENIOR|VICE|ASSISTANT|DEPUTY|MANAGING|GENERAL|CEO|COUNSEL|ADMINISTRATOR|COMMISSIONER|CHAIR(?:MAN|WOMAN)?|SECRETARY|SUPERINTENDENT))',
        text
    ):
        name_str = m.group(1).strip().rstrip(",")
        parts = name_str.split()
        if len(parts) >= 2:
            witnesses.add(parts[-1].upper())

    # Pattern 3: Look for "witness" table-of-contents entries
    for m in re.finditer(r'(?:Mr\.|Mrs\.|Ms\.|Dr\.)\s+([A-Za-z]+),?\s+(?:President|Director|CEO|Chief|Professor|Counsel|Founder|Executive|Senior|Vice)', text[:10000]):
        witnesses.add(m.group(1).upper())

    return witnesses


def extract_member_names_from_header(text):
    """Extract Congress member last names from hearing header (Members present line)."""
    members = set()
    # "Members present:" or "Present:" lines
    present_match = re.search(
        r'(?:Members\s+)?[Pp]resent:\s*(?:Representatives?|Senators?)\s+(.+?)(?:\n\n|\.\s*\n)',
        text[:5000], re.DOTALL
    )
    if present_match:
        block = present_match.group(1)
        # Names are comma-separated, sometimes with "and"
        names = re.split(r'[,;]\s*|\s+and\s+', block)
        for name in names:
            name = name.strip().rstrip(".")
            # Could be "Also present: Representative Raskin"
            name = re.sub(r'^(?:Representatives?|Senators?|Also present:)\s*', '', name).strip()
            if name and name[0].isupper() and len(name) > 2:
                members.add(name.upper().split()[-1])

    return members


def is_ai_context(text, match_start, match_end, search_label):
    """Check whether the search term match is actually in an AI-related context.
    Some terms like 'existential risk', 'loss of control', 'self-aware', 'destroy the world',
    'end of humanity', 'singularity' can appear in non-AI contexts."""

    # These terms are inherently AI-specific, always pass
    always_ai = {
        "artificial general intelligence", "artificial superintelligence",
        "superintelligence", "intelligence explosion",
        "recursive self-improvement", "capability amplification",
        "superhuman AI", "ultra-intelligent",
        "AI safety", "AI alignment", "AI moratorium", "AI pause",
        "AI consciousness", "AI arms race", "rogue AI",
        "autonomous weapons", "lethal autonomous",
        "Turing Test", "HAL 9000", "rise of the machines",
        "If Anyone Builds It Everyone Dies", "skynet",
        "engineering our own destruction",
    }
    if search_label in always_ai:
        return True

    # For ambiguous terms, check for AI-related words nearby (tighter window)
    window_start = max(0, match_start - 800)
    window_end = min(len(text), match_end + 800)
    window = text[window_start:window_end].lower()

    ai_indicators = [
        "artificial intelligence", " ai ", " ai.", " ai,", " ai;",
        "machine learning", "algorithm", "chatgpt", "openai",
        "large language model", "neural network", "deep learning",
        "automation", "autonomous", "robot", "generative ai",
        "superintelligen", "agi", "artificial general",
        "machine intelligence", "computer intelligence",
        "anthropic", "claude", "gemini", " gpt", " llm",
        "frontier model", "agentic", "transformer",
    ]

    matches = sum(1 for indicator in ai_indicators if indicator in window)

    # Terms very common in non-AI contexts — require stronger AI signal (2+)
    high_ambiguity = {
        "existential risk", "existential threat", "catastrophic risk",
        "end of humanity", "end of the world", "destroy the world",
        "loss of control", "lose control", "out of control",
        "extinction", "kill us all", "most dangerous",
        "too powerful", "too dangerous",
        "deception", "deceiving", "blackmail",
        "science fiction", "escape velocity", "weaponized",
        "atomic bomb", "Manhattan Project", "weapons of mass destruction",
    }
    if search_label in high_ambiguity:
        return matches >= 2
    return matches >= 1


def find_speaker_at_position(text, pos):
    """Find the nearest speaker attribution BEFORE the given position.
    Returns (LASTNAME_UPPER, distance_chars, raw_match, prefix) or None.
    prefix is 'Mr', 'Ms', 'Mrs', 'Dr', 'Chairman', etc."""
    search_start = max(0, pos - 3000)
    preceding = text[search_start:pos]

    best = None
    best_pos = -1

    for m in SPEAKER_PATTERN.finditer(preceding):
        if m.start() > best_pos:
            best_pos = m.start()
            prefix = m.group(1).strip().rstrip(".")
            raw_name = m.group(2).strip().rstrip(".")
            raw_name = re.sub(r'\s+of\s+.*', '', raw_name)
            best = (raw_name.upper().strip(), len(preceding) - m.end(), m.group(0).strip(), prefix)

    return best


def extract_quote_around(text, match_start, match_end, context_words=CONTEXT_WORDS):
    """Extract ~context_words words centered on the match."""
    words_before = text[:match_start].split()
    match_text = text[match_start:match_end]
    words_after = text[match_end:].split()

    half = context_words // 2
    before_words = words_before[-half:]
    after_words = words_after[:half]

    quote = " ".join(before_words) + " " + match_text + " " + " ".join(after_words)
    quote = re.sub(r'\s+', ' ', quote).strip()
    return quote


def is_member_speaking(text, speaker_pos, match_pos, speaker_lastname, witness_names):
    """Verify the speaker is a member of Congress, not a witness answering a question."""
    # If the speaker is in our known witness list, reject
    if speaker_lastname in witness_names:
        return False

    # If the speaker is in ALL_MEMBERS, accept
    if speaker_lastname in ALL_MEMBERS or speaker_lastname in TRACKED_BY_LASTNAME:
        return True

    # Unknown speaker — likely a witness
    return False


def quality_score(quote, search_label, speaker_distance, is_ai_ctx):
    """Rate quote strength. Returns (score 0-10, reason)."""
    score = 5
    reasons = []
    ql = quote.lower()

    if not is_ai_ctx:
        return (0, "not AI context")

    if speaker_distance < 200:
        score += 1
        reasons.append("speaker close to term")

    term_count = sum(1 for regex, _ in SEARCH_REGEXES if regex.search(quote))
    if term_count >= 3:
        score += 2
        reasons.append(f"{term_count} search terms")
    elif term_count >= 2:
        score += 1
        reasons.append(f"{term_count} search terms")

    substantive = [
        "we need to", "we must", "we should", "i believe", "i think",
        "concerned about", "worry about", "worried about", "threat",
        "dangerous", "catastroph", "regulation", "regulate", "guardrail",
        "safeguard", "safety", "alignment", "oversight",
    ]
    sub_count = sum(1 for s in substantive if s in ql)
    if sub_count >= 2:
        score += 2
        reasons.append("substantive language")
    elif sub_count == 1:
        score += 1

    word_count = len(quote.split())
    if word_count < 50:
        score -= 2
        reasons.append("very short")

    procedural_words = ["yield back", "unanimous consent", "without objection",
                        "ordered to be printed", "point of order"]
    if any(p in ql for p in procedural_words):
        score -= 1
        reasons.append("procedural")

    if "short title" in ql or "be it enacted" in ql:
        score -= 3
        reasons.append("bill text")

    strong_phrases = [
        "existential", "extinction", "end of human", "destroy",
        "catastrophic", "loss of control", "out of control",
        "lose control", "uncontrollable",
        "superintelligen", "artificial general intelligence",
        "artificial superintelligence", "intelligence explosion",
        " agi ", "skynet", "terminator", "self-aware",
        "survival instinct", "threat to human",
        "rogue ai", "autonomous weapon", "lethal autonomous",
        "weaponized", "kill chain", "arms race",
        "misalignment", "ai safety", "ai alignment",
        "deception", "deceiv", "blackmail",
        "rise of the machines", "frankenstein", "hal 9000",
        "the matrix", "asimov", "manhattan project", "atomic bomb",
        "engineering our own destruction", "escape velocity",
        "too powerful", "too dangerous", "digital god",
        "capability amplification",
    ]
    strong_count = sum(1 for s in strong_phrases if s in ql)
    if strong_count >= 2:
        score += 2
        reasons.append("strong x-risk language")
    elif strong_count >= 1:
        score += 1

    return (max(0, min(10, score)), "; ".join(reasons) if reasons else "baseline")


# ---------------------------------------------------------------------------
# Main analysis
# ---------------------------------------------------------------------------


def analyze_document(filepath, csv_row):
    """Analyze one cached document. Returns list of quote dicts."""

    html = filepath.read_text(encoding="utf-8", errors="replace")
    text = html_to_text(html)
    if not text or len(text) < 100:
        return []

    collection = csv_row.get("collection", "")
    date = csv_row.get("date", "")
    source_url = csv_row.get("source_url", "")
    chamber = csv_row.get("chamber", "")
    is_hearing = collection == "CHRG"

    # Extract witness names and member names from hearing headers
    witness_names = extract_witness_names(text) if is_hearing else set()
    header_members = extract_member_names_from_header(text) if is_hearing else set()

    # Find all search term matches
    matches = []
    for regex, label in SEARCH_REGEXES:
        for m in regex.finditer(text):
            matches.append((m.start(), m.end(), label))

    if not matches:
        return []

    matches.sort(key=lambda x: x[0])

    quotes = []
    seen = set()

    for match_start, match_end, search_label in matches:
        # AI-context check
        ai_ctx = is_ai_context(text, match_start, match_end, search_label)

        speaker_info = find_speaker_at_position(text, match_start)
        if not speaker_info:
            continue

        speaker_lastname, distance, raw_match, prefix = speaker_info

        # Dedup
        dedup_key = (speaker_lastname, match_start // 800)
        if dedup_key in seen:
            continue
        seen.add(dedup_key)

        # Check this is actually a member of Congress speaking
        if not is_member_speaking(text, 0, match_start, speaker_lastname, witness_names):
            continue

        # Resolve member info — use gendered overrides for ambiguous last names
        prefix_key = prefix.rstrip(".")  # "Mr." -> "Mr", "Ms." -> "Ms"
        gendered_key = (speaker_lastname, prefix_key)

        if gendered_key in GENDERED_OVERRIDES:
            full_name, party, title, state = GENDERED_OVERRIDES[gendered_key]
            is_tracked = speaker_lastname in TRACKED_BY_LASTNAME and TRACKED_BY_LASTNAME[speaker_lastname][0] == full_name
        elif speaker_lastname in TRACKED_BY_LASTNAME:
            full_name, party, title, state = TRACKED_BY_LASTNAME[speaker_lastname]
            is_tracked = True
        elif speaker_lastname in ALL_MEMBERS:
            full_name, party, title, state = ALL_MEMBERS[speaker_lastname]
            is_tracked = False
        else:
            continue  # unknown, skip

        quote = extract_quote_around(text, match_start, match_end)

        score, score_reason = quality_score(quote, search_label, distance, ai_ctx)

        # Collect all search terms in this quote
        terms_in_quote = []
        for regex, label in SEARCH_REGEXES:
            if regex.search(quote):
                terms_in_quote.append(label)

        quotes.append({
            "date": date,
            "speaker_name": full_name,
            "party": party,
            "title": title,
            "state": state,
            "chamber": chamber,
            "collection": collection,
            "source_url": source_url,
            "quote": quote,
            "search_terms": "; ".join(sorted(set(terms_in_quote))),
            "quality_score": score,
            "quality_reason": score_reason,
            "is_tracked": is_tracked,
            "speaker_distance": distance,
        })

    return quotes


def wrap_quote(quote, indent=6, width=100):
    """Word-wrap a quote for display."""
    words = quote.split()
    lines = []
    line = " " * indent + "\""
    for w in words:
        if len(line) + len(w) + 1 > width:
            lines.append(line)
            line = " " * (indent + 1)
        line += w + " "
    line = line.rstrip() + "\""
    lines.append(line)
    return "\n".join(lines)


def main():
    # Determine date cutoff: 1 month before the last time this script was run
    cutoff_date = None
    if LAST_RUN_FILE.exists():
        try:
            last_run = date.fromisoformat(LAST_RUN_FILE.read_text().strip())
            cutoff_date = last_run - timedelta(days=30)
        except ValueError:
            pass  # malformed file, ignore and process all

    with open(INPUT_CSV, encoding="utf-8") as f:
        csv_rows = list(csv.DictReader(f))

    total_rows = len(csv_rows)
    if cutoff_date:
        csv_rows = [r for r in csv_rows if r.get("date", "") >= cutoff_date.isoformat()]
        print(f"Date cutoff: {cutoff_date.isoformat()} (1 month before last run)")
        print(f"Rows after date filter: {len(csv_rows)} / {total_rows}")

    all_quotes = []

    for row in csv_rows:
        url = row["source_url"]
        parts = url.replace("https://www.govinfo.gov/app/details/", "").split("/")
        package_id = parts[0]
        granule_id = parts[1] if len(parts) >= 2 else parts[0]

        key = f"{package_id}__{granule_id}" if granule_id else package_id
        key = re.sub(r'[^\w\-]', '_', key)
        filepath = CACHE_DIR / f"{key}.html"

        if not filepath.exists():
            continue

        doc_quotes = analyze_document(filepath, row)
        all_quotes.extend(doc_quotes)

    # Deduplicate: same speaker + date + similar quote
    deduped = {}
    for q in all_quotes:
        dk = (q["speaker_name"], q["date"], q["quote"][:150])
        if dk not in deduped or q["quality_score"] > deduped[dk]["quality_score"]:
            deduped[dk] = q
    all_quotes = list(deduped.values())

    # Filter: exclude score <= 2 (non-AI context, procedural, etc.)
    filtered = [q for q in all_quotes if q["quality_score"] > 2]
    excluded_count = len(all_quotes) - len(filtered)

    new_member_quotes = [q for q in filtered if not q["is_tracked"]]
    existing_member_quotes = [q for q in filtered if q["is_tracked"]]

    new_member_quotes.sort(key=lambda q: (-q["quality_score"], q["date"]))
    existing_member_quotes.sort(key=lambda q: (-q["quality_score"], q["date"]))

    # -----------------------------------------------------------------------
    # Output
    # -----------------------------------------------------------------------

    print("=" * 80)
    print("CONGRESSIONAL QUOTE ANALYSIS: AGI / AI X-RISK TOPICS")
    print("=" * 80)
    print(f"\nDocuments analyzed: {len(csv_rows)}")
    print(f"Total speaker-attributed quotes found: {len(all_quotes)}")
    print(f"Excluded by quality filter (score<=2): {excluded_count}")
    print(f"Remaining quotes: {len(filtered)}")
    print(f"  NEW members (not on tracked list): {len(new_member_quotes)} quotes from {len(set(q['speaker_name'] for q in new_member_quotes))} members")
    print(f"  EXISTING tracked members: {len(existing_member_quotes)} quotes from {len(set(q['speaker_name'] for q in existing_member_quotes))} members")

    # --- NEW MEMBERS ---
    print("\n")
    print("=" * 80)
    print("NEW MEMBERS — NOT ON TRACKED LIST")
    print("Sorted by quality score (strongest/most direct quotes first)")
    print("=" * 80)

    new_by_speaker = defaultdict(list)
    for q in new_member_quotes:
        new_by_speaker[q["speaker_name"]].append(q)

    sorted_new_speakers = sorted(
        new_by_speaker.items(),
        key=lambda x: max(q["quality_score"] for q in x[1]),
        reverse=True,
    )

    for speaker, speaker_quotes in sorted_new_speakers:
        best = max(speaker_quotes, key=lambda q: q["quality_score"])
        print(f"\n{'─' * 70}")
        print(f"  {best['title']} {speaker} ({best['party']}-{best['state']})")
        print(f"  Quotes: {len(speaker_quotes)} | Best score: {best['quality_score']}/10")
        print(f"{'─' * 70}")

        for i, q in enumerate(sorted(speaker_quotes, key=lambda x: -x["quality_score"]), 1):
            print(f"\n  [{i}] {q['date']} | {q['collection']} | Score: {q['quality_score']}/10 | {q['quality_reason']}")
            print(f"      Terms: {q['search_terms']}")
            print(f"      Source: {q['source_url']}")
            print(wrap_quote(q["quote"]))

    # --- EXISTING MEMBERS ---
    print("\n\n")
    print("=" * 80)
    print("EXISTING TRACKED MEMBERS — NEW QUOTES")
    print("=" * 80)

    existing_by_speaker = defaultdict(list)
    for q in existing_member_quotes:
        existing_by_speaker[q["speaker_name"]].append(q)

    sorted_existing = sorted(
        existing_by_speaker.items(),
        key=lambda x: max(q["quality_score"] for q in x[1]),
        reverse=True,
    )

    for speaker, speaker_quotes in sorted_existing:
        best = max(speaker_quotes, key=lambda q: q["quality_score"])
        print(f"\n{'─' * 70}")
        print(f"  {best['title']} {speaker} ({best['party']}-{best['state']})")
        print(f"  Quotes: {len(speaker_quotes)} | Best score: {best['quality_score']}/10")
        print(f"{'─' * 70}")

        for i, q in enumerate(sorted(speaker_quotes, key=lambda x: -x["quality_score"]), 1):
            print(f"\n  [{i}] {q['date']} | {q['collection']} | Score: {q['quality_score']}/10 | {q['quality_reason']}")
            print(f"      Terms: {q['search_terms']}")
            print(f"      Source: {q['source_url']}")
            print(wrap_quote(q["quote"]))

    # --- Write CSV ---
    fieldnames = [
        "date", "speaker_name", "party", "title", "state", "chamber",
        "collection", "source_url", "search_terms", "quality_score",
        "quality_reason", "is_tracked", "quote",
    ]
    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for q in sorted(filtered, key=lambda x: (-x["quality_score"], x["date"])):
            writer.writerow(q)

    print(f"\n\nWrote {len(filtered)} quotes to {OUTPUT_CSV}")

    # Record this run's date for next time
    LAST_RUN_FILE.write_text(date.today().isoformat())
    print(f"Saved last-run date: {date.today().isoformat()}")


if __name__ == "__main__":
    main()
