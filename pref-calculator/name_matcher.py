"""Fuzzy match tournament CSV names to Notion database names."""
import re
import unicodedata
from thefuzz import fuzz, process


def normalize_name(name):
    """Convert 'Last, First' to 'First Last' and clean up."""
    name = name.strip()
    # Strip invisible Unicode chars (LTR marks, zero-width spaces, etc.)
    name = re.sub(r'[\u200e\u200f\u200b\u200c\u200d\ufeff]', '', name)
    # Normalize Unicode (e.g., accented chars)
    name = unicodedata.normalize('NFKC', name)
    if "," in name:
        parts = [p.strip() for p in name.split(",", 1)]
        name = f"{parts[1]} {parts[0]}".strip()
    # Normalize apostrophes and special chars for matching
    name = name.replace("'", "").replace("'", "").replace("`", "")
    return name


def _match_key(name):
    """Lowercase key for case-insensitive exact matching."""
    return normalize_name(name).lower().strip()


def match_judges(csv_judges, notion_judges, threshold=75):
    """Match CSV judge names to Notion judge names.
    
    Args:
        csv_judges: list of judge dicts from CSV (name in "Last, First" format)
        notion_judges: dict of {name: score} from Notion (name in "First Last" format)
        threshold: minimum fuzzy match score (0-100)
    
    Returns:
        matched: list of (csv_judge, notion_name, score) tuples
        unmatched: list of csv_judge dicts with no Notion match
    """
    # Build case-insensitive lookup: normalized_key → (original_name, score)
    notion_lookup = {}
    for name, score in notion_judges.items():
        key = _match_key(name)
        notion_lookup[key] = (name, score)

    # Also build list of normalized notion names for fuzzy matching
    notion_names = list(notion_judges.keys())
    notion_names_normalized = [normalize_name(n) for n in notion_names]

    matched = []
    unmatched = []

    for judge in csv_judges:
        key = _match_key(judge["name"])

        # Try case-insensitive exact match (with normalized chars)
        if key in notion_lookup:
            orig_name, score = notion_lookup[key]
            matched.append((judge, orig_name, score))
            continue

        # Fuzzy match against normalized names
        normalized = normalize_name(judge["name"])
        result = process.extractOne(normalized, notion_names_normalized,
                                    scorer=fuzz.token_sort_ratio)
        if result and result[1] >= threshold:
            # Map back to original Notion name
            idx = notion_names_normalized.index(result[0])
            best_name = notion_names[idx]
            matched.append((judge, best_name, notion_judges[best_name]))
        else:
            unmatched.append(judge)

    return matched, unmatched
