"""Write the output CSV with tier assignments."""
import csv


def write_output_csv(judges, filepath):
    """Write judges with tier assignments to CSV.
    
    Tier 6 is converted to 'S' (strike) in output.
    Output format: First, Last, School, Rounds, Rating
    """
    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["First", "Last", "School", "Rounds", "Rating"])
        for judge in judges:
            tier = judge["tier"]
            rating = "C" if tier == 7 else ("S" if tier == 6 else str(tier))
            name = judge["name"]
            # Split "Last, First" back to separate columns
            if ", " in name:
                last, first = name.split(", ", 1)
            else:
                parts = name.split()
                first = parts[0] if parts else ""
                last = " ".join(parts[1:]) if len(parts) > 1 else ""
            writer.writerow([first, last, judge["school"], judge["rounds"], rating])
    
    print(f"Output written to {filepath} ({len(judges)} judges)")
