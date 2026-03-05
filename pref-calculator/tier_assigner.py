"""Core tier assignment algorithm.

Maps absolute scores to tiers and adjusts to satisfy round quotas.
"""
import math

TOURNAMENT_QUALITY_BASELINE = 3.5
TOURNAMENT_QUALITY_FACTOR_STRONG = 0.25  # gentle when pool is strong (scores shift up)
TOURNAMENT_QUALITY_FACTOR_WEAK = 0.75    # moderate when pool is weak (scores improve)


def tournament_quality_adjustment(judges_with_scores):
    """Calculate tournament pool quality adjustment.
    
    Computes the average score of rated judges (excluding strikes/conflicts)
    and returns an adjustment value. Strong pool (low avg) → positive adjustment
    (shifts scores up/worse). Weak pool (high avg) → negative adjustment
    (shifts scores down/better).
    """
    rated = [j["score"] for j in judges_with_scores
             if j["score"] is not None and j["score"] < 6.0]
    if not rated:
        return 0.0
    pool_avg = sum(rated) / len(rated)
    diff = TOURNAMENT_QUALITY_BASELINE - pool_avg
    # Asymmetric: gentle for strong pools (diff > 0), moderate for weak pools (diff < 0)
    factor = TOURNAMENT_QUALITY_FACTOR_STRONG if diff > 0 else TOURNAMENT_QUALITY_FACTOR_WEAK
    adjustment = diff * factor
    return round(adjustment * 2) / 2  # snap to 0.5


def apply_quality_adjustment(judges_with_scores):
    """Apply tournament quality adjustment to judge scores.
    
    Returns the adjustment value applied. Strikes (6) and conflicts (7) are not adjusted.
    Adjusted scores are clamped to [1.0, 5.5].
    """
    adj = tournament_quality_adjustment(judges_with_scores)
    if adj == 0:
        return adj
    for judge in judges_with_scores:
        if judge["score"] is None or judge["score"] >= 6.0:
            continue  # don't adjust strikes/conflicts
        judge["score"] = max(1.0, min(5.5, round((judge["score"] + adj) * 2) / 2))
    return adj


def natural_tier(score):
    """Map an absolute score (1-7) to its natural tier (1-7).
    
    1.0-1.5 → Tier 1
    2.0-2.5 → Tier 2
    3.0-3.5 → Tier 3
    4.0-4.5 → Tier 4
    5.0-5.5 → Tier 5
    6.0      → Tier 6 (strike)
    7.0      → Tier 7 (conflict)
    """
    if score is None:
        return 4  # fallback
    if score >= 7:
        return 7
    tier = math.ceil(score)
    if score == int(score) and score >= 1:
        tier = int(score)
    # x.5 rounds up: 1.5→T1, 2.5→T2, etc. (belongs to lower tier)
    if score - int(score) == 0.5:
        tier = int(score)
    return max(1, min(7, tier))


def assign_tiers(judges_with_scores, quotas, quota_mode="rounds"):
    """Assign tiers to judges satisfying quota constraints.
    
    Args:
        judges_with_scores: list of dicts with keys:
            name, school, rounds, score (absolute 1-6)
        quotas: dict of tier -> {"min": int, "max": int}
            e.g., {1: {"min": 10, "max": 20}, 2: {"min": 15, "max": 30}, ...}
        quota_mode: "rounds" (sum of available rounds) or "judges" (judge count)
    
    Returns:
        list of dicts with added "tier" key, plus a report dict
    """
    # Sort judges by score (best first)
    sorted_judges = sorted(judges_with_scores, key=lambda j: (j["score"] or 99))

    # Phase 0: Apply tournament quality adjustment
    quality_adj = apply_quality_adjustment(sorted_judges)

    # Phase 1: Assign natural tiers
    for judge in sorted_judges:
        judge["tier"] = natural_tier(judge["score"])
        judge["is_boundary"] = False
        # Flag boundary judges (score ends in .5)
        if judge["score"] is not None and judge["score"] - int(judge["score"]) == 0.5:
            judge["is_boundary"] = True

    # Separate conflicts (tier 7) — they are excluded from quota logic
    conflicts = [j for j in sorted_judges if j["tier"] == 7]
    active_judges = [j for j in sorted_judges if j["tier"] != 7]

    # Phase 2: Measure function based on quota mode
    def tier_total(judges, tier):
        if quota_mode == "judges":
            return sum(1 for j in judges if j["tier"] == tier)
        return sum(j["rounds"] for j in judges if j["tier"] == tier)

    def judge_cost(j):
        """How much a single judge contributes to the tier total."""
        return 1 if quota_mode == "judges" else j["rounds"]

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
            current = tier_total(active_judges, tier)
            q = quotas[tier]
            q_max = q.get("max", float("inf"))

            if current > q_max:
                tier_judges = [j for j in active_judges if j["tier"] == tier]
                tier_judges.sort(key=lambda j: -j["score"])
                for j in tier_judges:
                    if current <= q_max:
                        break
                    j["tier"] = tier + 1
                    current -= judge_cost(j)
                    adjustments_made = True

        # Pass 2 (bottom-up): push overflow UP from strikes and tier 5
        for tier in range(6, 0, -1):
            if tier not in quotas:
                continue
            current = tier_total(active_judges, tier)
            q = quotas[tier]
            q_max = q.get("max", float("inf"))

            if current > q_max:
                # Move best judges in this tier UP to the tier above
                # Prefer promoting judges with better scores; keep score>=5 low
                tier_judges = [j for j in active_judges if j["tier"] == tier]
                tier_judges.sort(key=lambda j: (1 if j["score"] >= 5.0 else 0, j["score"]))
                target = tier - 1
                # Find the nearest tier above that can accept judges
                while target >= 1:
                    target_current = tier_total(active_judges, target)
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
                    current -= judge_cost(j)
                    adjustments_made = True

        # Pass 3: handle under-min by pulling from tier below
        # Deprioritize score>=5.0 judges — only pull them as last resort
        for tier in range(1, 7):
            if tier not in quotas:
                continue
            current = tier_total(active_judges, tier)
            q = quotas[tier]
            q_min = q.get("min", 0)

            if current < q_min:
                next_tier = tier + 1
                next_judges = [j for j in active_judges if j["tier"] == next_tier]
                next_judges.sort(key=lambda j: (1 if j["score"] >= 5.0 else 0, j["score"]))
                for j in next_judges:
                    if current >= q_min:
                        break
                    if j["tier"] == 6 and tier < 5:
                        continue
                    j["tier"] = tier
                    current += judge_cost(j)
                    adjustments_made = True

        if not adjustments_made:
            break

    # Pass 4: Post-stabilization swap — push score>=5 judges back to tier 5
    # If a score>=5 judge got promoted above tier 5, try to swap with a
    # better-scored judge in tier 5 (keeps quotas intact via 1-for-1 swap)
    promoted_bad = [j for j in active_judges if j["score"] >= 5.0 and j["tier"] < 5]
    promoted_bad.sort(key=lambda j: -j["score"])  # worst first
    for bad in promoted_bad:
        bad_tier = bad["tier"]
        # Find a swap candidate in tier 5 with a better score
        candidates = [j for j in active_judges
                      if j["tier"] == 5 and j["score"] < 5.0]
        candidates.sort(key=lambda j: j["score"])  # best first
        for good in candidates:
            # Swap: move good judge up, bad judge down to 5
            good["tier"] = bad_tier
            bad["tier"] = 5
            # Verify quotas still hold after swap
            ok = True
            for t in [bad_tier, 5]:
                q = quotas.get(t, {})
                total = tier_total(active_judges, t)
                if "min" in q and total < q["min"]:
                    ok = False
                if "max" in q and total > q["max"]:
                    ok = False
            if ok:
                break  # swap succeeded
            else:
                # Revert swap
                bad["tier"] = bad_tier
                good["tier"] = 5

    # Build report
    report = {"quota_mode": quota_mode, "quality_adjustment": quality_adj}
    for tier in range(1, 7):
        total = tier_total(active_judges, tier)
        count = sum(1 for j in active_judges if j["tier"] == tier)
        rounds = sum(j["rounds"] for j in active_judges if j["tier"] == tier)
        q = quotas.get(tier, {})
        met = True
        if "min" in q and total < q["min"]:
            met = False
        if "max" in q and total > q["max"]:
            met = False
        report[tier] = {
            "judges": count,
            "total_rounds": rounds,
            "quota_total": total,
            "quota_min": q.get("min", "-"),
            "quota_max": q.get("max", "-"),
            "met": met,
        }
    # Conflict tier (no quotas)
    report[7] = {
        "judges": len(conflicts),
        "total_rounds": sum(j["rounds"] for j in conflicts),
        "quota_total": len(conflicts),
        "quota_min": "-",
        "quota_max": "-",
        "met": True,
    }

    return active_judges + conflicts, report


def format_report(report):
    """Format the tier assignment report as a readable string."""
    mode = report.get("quota_mode", "rounds")
    mode_label = "Judges" if mode == "judges" else "Rounds"
    lines = []
    adj = report.get("quality_adjustment", 0)
    if adj != 0:
        direction = "stronger pool → scores shifted up" if adj > 0 else "weaker pool → scores improved"
        lines.append(f"Tournament quality adjustment: {adj:+.1f} ({direction})")
    lines.append(f"Quota mode: {mode_label}")
    lines.append(f"{'Tier':<6} {'Judges':<8} {'Rounds':<8} {mode_label + ' (quota)':<16} {'Min':<6} {'Max':<6} {'Status'}")
    lines.append("-" * 60)
    for tier in range(1, 8):
        r = report.get(tier, {"judges": 0, "total_rounds": 0, "quota_total": 0, "quota_min": "-", "quota_max": "-", "met": True})
        if tier == 7:
            label = "C"
        elif tier == 6:
            label = "S"
        else:
            label = str(tier)
        status = "✓" if r["met"] else "✗ UNMET"
        if tier == 7:
            status = "-"  # conflicts don't have quota status
        lines.append(f"{label:<6} {r['judges']:<8} {r['total_rounds']:<8} {r['quota_total']:<16} {str(r['quota_min']):<6} {str(r['quota_max']):<6} {status}")
    return "\n".join(lines)
