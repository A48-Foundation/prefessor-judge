"""Generate test CSV files from Notion judge data."""
import json, csv, random

with open("notion_judges.json") as f:
    judges = json.load(f)

# Convert "First Last" to "Last, First" for CSV format
def to_csv_name(name):
    parts = name.strip().split()
    if len(parts) >= 2:
        return f"{parts[-1]}, {' '.join(parts[:-1])}"
    return name

schools = [
    "Georgetown", "Harvard", "Emory", "Michigan", "Wake Forest",
    "Northwestern", "Kansas", "Berkeley", "Dartmouth", "NYU",
    "Iowa", "Gonzaga", "Liberty", "Samford", "Kentucky",
    "Baylor", "Texas", "Pittsburgh", "Rutgers", "USC"
]

# --- Test 1: All known judges (subset of 40 from Notion) ---
random.seed(42)
known = random.sample(judges, 40)
with open("test_known_judges.csv", "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["Name", "School", "Rounds", "Your Rating"])
    for j in known:
        w.writerow([to_csv_name(j["name"]), random.choice(schools), random.randint(2, 8), ""])
print(f"Created test_known_judges.csv with {len(known)} judges (all in Notion)")

# --- Test 2: Mix of known + unknown judges ---
unknown_judges = [
    "Sarah Johnson", "Mike Thompson", "Lisa Chen",
    "David Park", "Rachel Green", "James Wilson",
    "Amanda Foster", "Kevin O'Brien", "Maria Santos",
    "Chris Patterson"
]
mixed = random.sample(judges, 30)
with open("test_mixed_judges.csv", "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["Name", "School", "Rounds", "Your Rating"])
    for j in mixed:
        w.writerow([to_csv_name(j["name"]), random.choice(schools), random.randint(2, 8), ""])
    for name in unknown_judges:
        w.writerow([to_csv_name(name), random.choice(schools), random.randint(2, 8), ""])
print(f"Created test_mixed_judges.csv with {len(mixed) + len(unknown_judges)} judges ({len(unknown_judges)} unknown)")
