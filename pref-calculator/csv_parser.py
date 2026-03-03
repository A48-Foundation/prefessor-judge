"""Parse tournament judge CSV files."""
import csv


def parse_tournament_csv(filepath):
    """Parse a tournament CSV and return list of judge dicts.
    
    CSV format: Name, School, Rounds, Your Rating
    Name is in "Last, First" format.
    """
    judges = []
    with open(filepath, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            judges.append({
                "name": row["Name"].strip(),
                "school": row["School"].strip(),
                "rounds": int(row["Rounds"].strip()),
                "rating": row.get("Your Rating", "").strip(),
            })
    return judges
