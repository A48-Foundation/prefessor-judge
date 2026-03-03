"""Prefessor Judge - Pref Sheet Generator CLI.

Reads a tournament judge CSV, looks up absolute scores from Notion,
assigns tiers to satisfy round quotas, and outputs a filled CSV.
"""
import sys
import os
from csv_parser import parse_tournament_csv
from notion_reader import fetch_notion_judges
from name_matcher import match_judges
from score_prompter import prompt_for_scores
from tier_assigner import assign_tiers, format_report
from csv_writer import write_output_csv


def get_quotas():
    """Prompt user for tier quotas (min/max rounds per tier)."""
    print("\n" + "=" * 50)
    print("Enter round quotas for each tier.")
    print("Format: min,max  (leave blank to skip, use - for no limit)")
    print("Example: 10,25 means min 10 rounds, max 25 rounds")
    print("=" * 50)

    quotas = {}
    for tier in range(1, 7):
        label = "S (strike)" if tier == 6 else str(tier)
        while True:
            raw = input(f"  Tier {label} [min,max]: ").strip()
            if not raw:
                break
            try:
                parts = raw.split(",")
                q = {}
                if len(parts) >= 1 and parts[0].strip() != "-":
                    q["min"] = int(parts[0].strip())
                if len(parts) >= 2 and parts[1].strip() != "-":
                    q["max"] = int(parts[1].strip())
                if q:
                    quotas[tier] = q
                break
            except ValueError:
                print("    Invalid format. Use: min,max (e.g., 10,25)")
    return quotas


def main():
    # Get input CSV path
    if len(sys.argv) > 1:
        csv_path = sys.argv[1]
    else:
        csv_path = input("Enter tournament CSV path: ").strip().strip('"')

    if not os.path.exists(csv_path):
        print(f"Error: File not found: {csv_path}")
        sys.exit(1)

    # Parse tournament CSV
    print(f"\nLoading tournament CSV: {csv_path}")
    csv_judges = parse_tournament_csv(csv_path)
    print(f"  Found {len(csv_judges)} judges")

    # Fetch Notion data
    print("\nFetching absolute scores from Notion...")
    notion_judges = fetch_notion_judges()
    print(f"  Found {len(notion_judges)} judges in database")

    # Match names
    print("\nMatching judge names...")
    matched, unmatched = match_judges(csv_judges, notion_judges)
    print(f"  Matched: {len(matched)}")
    print(f"  Unmatched: {len(unmatched)}")

    # Prompt for unknown judges
    prompted = prompt_for_scores(unmatched)

    # Build unified judge list with scores
    all_judges = []
    for csv_judge, notion_name, score in matched:
        all_judges.append({
            "name": csv_judge["name"],
            "school": csv_judge["school"],
            "rounds": csv_judge["rounds"],
            "score": score if score is not None else 4.0,
            "notion_name": notion_name,
        })

    for csv_judge, score in prompted:
        all_judges.append({
            "name": csv_judge["name"],
            "school": csv_judge["school"],
            "rounds": csv_judge["rounds"],
            "score": score,
            "notion_name": None,
        })

    # Show judges sorted by score
    all_judges.sort(key=lambda j: j["score"])
    print(f"\n{'='*60}")
    print(f"{'Judge':<30} {'Score':<8} {'Rounds':<8}")
    print("-" * 60)
    for j in all_judges:
        print(f"{j['name']:<30} {j['score']:<8} {j['rounds']:<8}")

    # Get quotas
    quotas = get_quotas()

    if not quotas:
        print("\nNo quotas provided. Using natural tier mapping only.")

    # Run assignment
    print("\nAssigning tiers...")
    assigned, report = assign_tiers(all_judges, quotas)

    # Display report
    print(f"\n{'='*50}")
    print("TIER ASSIGNMENT REPORT")
    print("=" * 50)
    print(format_report(report))

    # Show assignments
    print(f"\n{'='*60}")
    print(f"{'Judge':<30} {'Score':<8} {'Tier':<8} {'Rounds':<8}")
    print("-" * 60)
    assigned.sort(key=lambda j: (j["tier"], j["score"]))
    for j in assigned:
        tier_label = "S" if j["tier"] == 6 else str(j["tier"])
        boundary = " *" if j.get("is_boundary") else ""
        print(f"{j['name']:<30} {j['score']:<8} {tier_label:<8} {j['rounds']:<8}{boundary}")
    print("\n* = boundary judge (score ends in .5)")

    # Write output
    base = os.path.splitext(os.path.basename(csv_path))[0]
    output_path = f"{base}_prefs.csv"
    write_output_csv(assigned, output_path)

    return output_path


if __name__ == "__main__":
    main()
