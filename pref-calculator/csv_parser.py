"""Parse tournament judge CSV files."""
import csv


def parse_tournament_csv(filepath):
    """Parse a tournament CSV and return list of judge dicts.
    
    Supports two formats:
    - Format A: First, Last, School, Online, Rounds, Rating
    - Format B: Name, School, Rounds, Your Rating (Name is "Last, First")
    """
    judges = []
    with open(filepath, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        headers = reader.fieldnames
        # Detect format
        if "First" in headers and "Last" in headers:
            # Format A: First, Last, School, Online, Rounds, Rating
            for row in reader:
                first = row["First"].strip()
                last = row["Last"].strip()
                name = f"{last}, {first}"
                judges.append({
                    "name": name,
                    "school": row.get("School", "").strip(),
                    "rounds": int(row.get("Rounds", "0").strip() or "0"),
                    "rating": row.get("Rating", "").strip(),
                })
        else:
            # Format B: Name, School, Rounds, Your Rating
            for row in reader:
                judges.append({
                    "name": row["Name"].strip(),
                    "school": row.get("School", "").strip(),
                    "rounds": int(row.get("Rounds", "0").strip() or "0"),
                    "rating": row.get("Your Rating", "").strip(),
                })
    return judges
