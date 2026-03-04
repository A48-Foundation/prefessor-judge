"""Prompt user for scores of unknown judges."""


def prompt_for_scores(unmatched_judges):
    """Prompt user one-by-one for absolute scores for unmatched judges.
    
    Returns list of (judge_dict, score) tuples.
    """
    results = []
    if not unmatched_judges:
        return results

    print(f"\n{'='*50}")
    print(f"{len(unmatched_judges)} judge(s) not found in Notion database.")
    print("Please enter an absolute score (1-7) for each:")
    print("  (6 = Strike, 7 = Conflict/same school)")
    print(f"{'='*50}\n")

    for judge in unmatched_judges:
        while True:
            try:
                raw = input(f"  {judge['name']} ({judge['school']}): ")
                score = float(raw.strip())
                if score < 1 or score > 7:
                    print("    Score must be between 1 and 7.")
                    continue
                # Snap to nearest 0.5
                score = round(score * 2) / 2
                results.append((judge, score))
                break
            except ValueError:
                print("    Please enter a number (e.g., 3 or 3.5).")
            except (EOFError, KeyboardInterrupt):
                print("\n    Skipping remaining judges (defaulting to 4.0).")
                results.append((judge, 4.0))
                break

    return results
