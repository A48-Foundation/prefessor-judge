"""Core tier assignment algorithm.

Maps absolute scores to tiers and adjusts to satisfy round quotas.
"""
import math


def natural_tier(score):
    """Map an absolute score (1-6) to its natural tier (1-6).
    
    1.0-1.5 → Tier 1
    2.0-2.5 → Tier 2
    3.0-3.5 → Tier 3
    4.0-4.5 → Tier 4
    5.0-5.5 → Tier 5
    6.0      → Tier 6 (strike)
    """
    if score is None:
        return 4  # fallback
    tier = math.ceil(score)
    if score == int(score) and score >= 1:
        tier = int(score)
    # x.5 rounds up: 1.5→T1, 2.5→T2, etc. (belongs to lower tier)
    if score - int(score) == 0.5:
        tier = int(score)
    return max(1, min(6, tier))


def assign_tiers(judges_with_scores, quotas):
    """Assign tiers to judges satisfying quota constraints.
    
    Args:
        judges_with_scores: list of dicts with keys:
            name, school, rounds, score (absolute 1-6)
        quotas: dict of tier -> {"min": int, "max": int}
            e.g., {1: {"min": 10, "max": 20}, 2: {"min": 15, "max": 30}, ...}
    
    Returns:
        list of dicts with added "tier" key, plus a report dict
    """
    # Sort judges by score (best first)
    sorted_judges = sorted(judges_with_scores, key=lambda j: (j["score"] or 99))

    # Phase 1: Assign natural tiers
    for judge in sorted_judges:
        judge["tier"] = natural_tier(judge["score"])
        judge["is_boundary"] = False
        # Flag boundary judges (score ends in .5)
        if judge["score"] is not None and judge["score"] - int(judge["score"]) == 0.5:
            judge["is_boundary"] = True

    # Phase 2: Calculate current round totals per tier
    def tier_rounds(judges, tier):
        return sum(j["rounds"] for j in judges if j["tier"] == tier)

    # Phase 3: Adjust to meet quotas
    # Strategy: iterate tiers top-down for over-max (push down),
    # then bottom-up for over-max on lower tiers (push up),
    # then handle under-min by pulling from adjacent tiers
    max_iterations = 100
    for _ in range(max_iterations):
        adjustments_made = False

        # Pass 1 (top-down): push overflow DOWN from tiers 1-5
        for tier in range(1, 6):
            if tier not in quotas:
                continue
            current = tier_rounds(sorted_judges, tier)
            q = quotas[tier]
            q_max = q.get("max", float("inf"))

            if current > q_max:
                tier_judges = [j for j in sorted_judges if j["tier"] == tier]
                tier_judges.sort(key=lambda j: -j["score"])
                for j in tier_judges:
                    if current <= q_max:
                        break
                    j["tier"] = tier + 1
                    current -= j["rounds"]
                    adjustments_made = True

        # Pass 2 (bottom-up): push overflow UP from strikes and tier 5
        for tier in range(6, 0, -1):
            if tier not in quotas:
                continue
            current = tier_rounds(sorted_judges, tier)
            q = quotas[tier]
            q_max = q.get("max", float("inf"))

            if current > q_max:
                # Move best judges in this tier UP to the tier above
                tier_judges = [j for j in sorted_judges if j["tier"] == tier]
                tier_judges.sort(key=lambda j: j["score"])
                target = tier - 1
                # Find the nearest tier above that can accept judges
                while target >= 1:
                    target_current = tier_rounds(sorted_judges, target)
                    target_max = quotas.get(target, {}).get("max", float("inf"))
                    if target_current < target_max:
                        break
                    target -= 1
                if target < 1:
                    target = tier - 1  # fallback: push up anyway

                for j in tier_judges:
                    if current <= q_max:
                        break
                    # Strikes only move up to tier 5 (conservative)
                    if tier == 6:
                        j["tier"] = max(target, 5)
                    else:
                        j["tier"] = target
                    current -= j["rounds"]
                    adjustments_made = True

        # Pass 3: handle under-min by pulling from tier below
        for tier in range(1, 7):
            if tier not in quotas:
                continue
            current = tier_rounds(sorted_judges, tier)
            q = quotas[tier]
            q_min = q.get("min", 0)

            if current < q_min:
                next_tier = tier + 1
                next_judges = [j for j in sorted_judges if j["tier"] == next_tier]
                next_judges.sort(key=lambda j: j["score"])
                for j in next_judges:
                    if current >= q_min:
                        break
                    if j["tier"] == 6 and tier < 5:
                        continue
                    j["tier"] = tier
                    current += j["rounds"]
                    adjustments_made = True

        if not adjustments_made:
            break

    # Build report
    report = {}
    for tier in range(1, 7):
        current = tier_rounds(sorted_judges, tier)
        count = sum(1 for j in sorted_judges if j["tier"] == tier)
        q = quotas.get(tier, {})
        met = True
        if "min" in q and current < q["min"]:
            met = False
        if "max" in q and current > q["max"]:
            met = False
        report[tier] = {
            "judges": count,
            "total_rounds": current,
            "quota_min": q.get("min", "-"),
            "quota_max": q.get("max", "-"),
            "met": met,
        }

    return sorted_judges, report


def format_report(report):
    """Format the tier assignment report as a readable string."""
    lines = []
    lines.append(f"{'Tier':<6} {'Judges':<8} {'Rounds':<8} {'Min':<6} {'Max':<6} {'Status'}")
    lines.append("-" * 46)
    for tier in range(1, 7):
        r = report.get(tier, {"judges": 0, "total_rounds": 0, "quota_min": "-", "quota_max": "-", "met": True})
        label = "S" if tier == 6 else str(tier)
        status = "✓" if r["met"] else "✗ UNMET"
        lines.append(f"{label:<6} {r['judges']:<8} {r['total_rounds']:<8} {str(r['quota_min']):<6} {str(r['quota_max']):<6} {status}")
    return "\n".join(lines)
