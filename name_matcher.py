"""Fuzzy match tournament CSV names to Notion database names."""
from thefuzz import fuzz, process


def normalize_name(name):
    """Convert 'Last, First' to 'First Last' and clean up."""
    name = name.strip()
    if "," in name:
        parts = [p.strip() for p in name.split(",", 1)]
        return f"{parts[1]} {parts[0]}".strip()
    return name


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
    notion_names = list(notion_judges.keys())
    matched = []
    unmatched = []

    for judge in csv_judges:
        normalized = normalize_name(judge["name"])
        # Try exact match first
        if normalized in notion_judges:
            matched.append((judge, normalized, notion_judges[normalized]))
            continue

        # Fuzzy match
        result = process.extractOne(normalized, notion_names, scorer=fuzz.token_sort_ratio)
        if result and result[1] >= threshold:
            best_name = result[0]
            matched.append((judge, best_name, notion_judges[best_name]))
        else:
            unmatched.append(judge)

    return matched, unmatched
