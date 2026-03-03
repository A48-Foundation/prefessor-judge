"""Write the output CSV with tier assignments."""
import csv


def write_output_csv(judges, filepath):
    """Write judges with tier assignments to CSV.
    
    Tier 6 is converted to 'S' (strike) in output.
    Format: Name, School, Rounds, Your Rating
    """
    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["Name", "School", "Rounds", "Your Rating"])
        for judge in judges:
            tier = judge["tier"]
            rating = "S" if tier == 6 else str(tier)
            writer.writerow([judge["name"], judge["school"], judge["rounds"], rating])
    
    print(f"Output written to {filepath} ({len(judges)} judges)")
