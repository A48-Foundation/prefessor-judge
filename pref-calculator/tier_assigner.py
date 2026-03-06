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


def _find_optimal_partition(rateable, quotas, quota_mode):
    """Find the optimal partition of sorted judges into tiers satisfying all quotas.

    Judges must be pre-sorted worst→best (highest score first).
    The partition is sequential: first k5 judges → tier 5, next k4 → tier 4, etc.
    Searches all valid (k5, k4, k3, k2) combinations; k1 = remainder.
    Minimises total deviation from natural tiers among feasible solutions.
    Enforces ±1 tier constraint: no judge moves more than 1 tier from natural.

    Returns True if a feasible partition was found and applied, False otherwise.
    """
    N = len(rateable)
    if N == 0:
        return True

    costs = [1 if quota_mode == "judges" else j["rounds"] for j in rateable]
    prefix = [0] * (N + 1)
    for i in range(N):
        prefix[i + 1] = prefix[i] + costs[i]

    tiers = [5, 4, 3, 2, 1]
    t_min = [quotas.get(t, {}).get("min", 0) for t in tiers]
    t_max = [quotas.get(t, {}).get("max", float("inf")) for t in tiers]

    total_available = prefix[N]
    total_min_needed = sum(t_min)
    if total_available < total_min_needed:
        return False

    sfx_min = [0] * (len(tiers) + 1)
    for i in range(len(tiers) - 1, -1, -1):
        sfx_min[i] = sfx_min[i + 1] + t_min[i]

    nat = [natural_tier(j["score"]) for j in rateable]
    best = {"cuts": None, "dev": float("inf")}

    def search(ti, start, cuts, dev_so_far):
        if dev_so_far >= best["dev"]:
            return

        if ti == len(tiers) - 1:
            k = N - start
            s = prefix[N] - prefix[start]
            if s < t_min[ti] or s > t_max[ti]:
                return
            # Check ±1 constraint for remaining judges
            d = 0
            for j in range(start, N):
                if abs(1 - nat[j]) > 1:
                    return  # violates ±1 constraint
                d += abs(1 - nat[j])
            d += dev_so_far
            if d < best["dev"]:
                best["dev"] = d
                best["cuts"] = cuts + (k,)
            return

        min_above = sfx_min[ti + 1]
        cumcost = 0
        tier_dev = 0
        tier = tiers[ti]

        for k in range(N - start + 1):
            if k > 0:
                idx = start + k - 1
                # Check ±1 constraint for this judge in this tier
                if abs(tier - nat[idx]) > 1:
                    break  # sorted order means all subsequent will also violate
                cumcost += costs[idx]
                tier_dev += abs(tier - nat[idx])
            if cumcost > t_max[ti]:
                break
            remaining = prefix[N] - prefix[start + k]
            if remaining < min_above:
                break
            if cumcost >= t_min[ti]:
                search(ti + 1, start + k, cuts + (k,), dev_so_far + tier_dev)

    search(0, 0, (), 0)

    if best["cuts"] is None:
        return False

    idx = 0
    for ti, k in enumerate(best["cuts"]):
        for _ in range(k):
            rateable[idx]["tier"] = tiers[ti]
            idx += 1
    return True


def _flexible_assign(rateable, quotas, quota_mode):
    """Flexible assignment with ±1 tier constraint.

    Uses iterative repair: starts at natural tiers, then moves judges
    between adjacent tiers only (±1 from natural) to fix deficits.

    Returns True if all quotas were met, False otherwise.
    """
    cost_fn = (lambda j: 1) if quota_mode == "judges" else (lambda j: j["rounds"])

    # Start at natural tier (clamped to 1-5)
    for j in rateable:
        nt = natural_tier(j["score"])
        j["tier"] = max(1, min(5, nt))
        j["_natural"] = j["tier"]  # remember natural tier for ±1 constraint

    max_iters = len(rateable) * 10

    for _ in range(max_iters):
        totals = {t: sum(cost_fn(j) for j in rateable if j["tier"] == t) for t in range(1, 6)}
        deficits = {}
        for t in range(1, 6):
            q = quotas.get(t, {})
            t_min, t_max = q.get("min", 0), q.get("max", float("inf"))
            if totals[t] < t_min:
                deficits[t] = t_min - totals[t]
            elif totals[t] > t_max:
                deficits[t] = -(totals[t] - t_max)

        if not deficits:
            # Clean up temp attribute
            for j in rateable:
                j.pop("_natural", None)
            return True

        under = {t: d for t, d in deficits.items() if d > 0}
        over = {t: -d for t, d in deficits.items() if d < 0}

        if over:
            target = max(over, key=over.get)
            judges_in = sorted([j for j in rateable if j["tier"] == target],
                               key=lambda j: -j["score"])
            moved = False
            for j in judges_in:
                # Only move to adjacent tiers within ±1 of natural
                for dest in [target + 1, target - 1]:
                    if dest < 1 or dest > 5 or dest == target:
                        continue
                    if abs(dest - j["_natural"]) > 1:
                        continue
                    d_max = quotas.get(dest, {}).get("max", float("inf"))
                    if totals[dest] + cost_fn(j) <= d_max:
                        j["tier"] = dest
                        moved = True
                        break
                if moved:
                    break
            if not moved:
                for j in rateable:
                    j.pop("_natural", None)
                return False
            continue

        target = max(under, key=under.get)

        best_judge = None
        best_priority = float("inf")
        for src in range(1, 6):
            if src == target:
                continue
            src_min = quotas.get(src, {}).get("min", 0)
            for j in rateable:
                if j["tier"] != src:
                    continue
                # ±1 constraint: target must be within 1 of natural tier
                if abs(target - j["_natural"]) > 1:
                    continue
                if totals[src] - cost_fn(j) < src_min:
                    continue
                p = abs(j["_natural"] - target) * 10 + abs(src - target)
                if p < best_priority:
                    best_priority = p
                    best_judge = j

        if best_judge is None:
            # Force move from largest surplus (still respecting ±1)
            surplus_tiers = sorted(range(1, 6),
                                   key=lambda t: totals[t] - quotas.get(t, {}).get("min", 0),
                                   reverse=True)
            for src in surplus_tiers:
                if src == target:
                    continue
                candidates = [j for j in rateable if j["tier"] == src
                              and abs(target - j["_natural"]) <= 1]
                if candidates:
                    candidates.sort(key=lambda j: abs(j["_natural"] - target))
                    best_judge = candidates[0]
                    break

        if best_judge is None:
            for j in rateable:
                j.pop("_natural", None)
            return False

        best_judge["tier"] = target

    for j in rateable:
        j.pop("_natural", None)
    return False


def _greedy_fallback(rateable, quotas, quota_mode):
    """Best-effort greedy assignment when quotas are truly infeasible.

    Fills tier minimums bottom-up, then assigns leftovers to tier 1.
    """
    cost_fn = (lambda j: 1) if quota_mode == "judges" else (lambda j: j["rounds"])

    for j in rateable:
        j["tier"] = None

    for tier in range(5, 0, -1):
        q_min = quotas.get(tier, {}).get("min", 0)
        current = 0
        for j in rateable:
            if j["tier"] is not None:
                continue
            j["tier"] = tier
            current += cost_fn(j)
            if current >= q_min:
                break

    for j in rateable:
        if j["tier"] is None:
            j["tier"] = 1


def assign_tiers(judges_with_scores, quotas, quota_mode="rounds"):
    """Assign tiers to judges guaranteeing quota constraints when feasible.

    Strategy:
      1. Optimal sequential partition (fast, preserves score ordering)
      2. If that fails, try alternative sort order
      3. If still fails, flexible assignment (any judge to any tier)
      4. Only truly infeasible when strikes leave insufficient total rounds

    Args:
        judges_with_scores: list of dicts with keys:
            name, school, rounds, score (absolute 1-7)
        quotas: dict of tier -> {"min": int, "max": int}
        quota_mode: "rounds" (sum of available rounds) or "judges" (judge count)

    Returns:
        list of dicts with added "tier" key, plus a report dict
    """
    # Sort judges by score (worst first), ties broken by rounds desc for packing
    sorted_judges = sorted(judges_with_scores,
                           key=lambda j: (-(j["score"] or 99), -(j.get("rounds", 0))))

    # Phase 0: Apply tournament quality adjustment
    quality_adj = apply_quality_adjustment(sorted_judges)

    # Measure function
    def judge_cost(j):
        return 1 if quota_mode == "judges" else j["rounds"]

    # Phase 1: Separate conflicts (tier 7) and strikes (score 6.0)
    conflicts = [j for j in sorted_judges if j["score"] is not None and j["score"] >= 7.0]
    strikes = [j for j in sorted_judges if j["score"] is not None and 6.0 <= j["score"] < 7.0]
    rateable = [j for j in sorted_judges
                if j["score"] is not None and j["score"] < 6.0]

    for j in conflicts:
        j["tier"] = 7
    for j in strikes:
        j["tier"] = 6

    # Check if quotas are possible at all (only infeasible if strikes eat too many rounds)
    total_rateable = sum(judge_cost(j) for j in rateable)
    total_min_needed = sum(quotas.get(t, {}).get("min", 0) for t in range(1, 6))
    truly_infeasible = total_rateable < total_min_needed

    feasible = False
    if not truly_infeasible:
        # Phase 2a: Try optimal sequential partition (high-round judges first for ties)
        rateable.sort(key=lambda j: (-j["score"], -(j.get("rounds", 0))))
        feasible = _find_optimal_partition(rateable, quotas, quota_mode)

        if not feasible:
            # Phase 2b: Try alternative sort (low-round judges first for ties)
            rateable.sort(key=lambda j: (-j["score"], j.get("rounds", 0)))
            feasible = _find_optimal_partition(rateable, quotas, quota_mode)

        if not feasible:
            # Phase 3: Flexible assignment — any judge can go to any tier
            rateable.sort(key=lambda j: (-j["score"], -(j.get("rounds", 0))))
            feasible = _flexible_assign(rateable, quotas, quota_mode)

    if not feasible:
        # Truly infeasible (strikes consumed too many rounds) — best effort
        rateable.sort(key=lambda j: (-j["score"], -(j.get("rounds", 0))))
        _greedy_fallback(rateable, quotas, quota_mode)

    active_judges = rateable + strikes

    # Build report
    report = {
        "quota_mode": quota_mode,
        "quality_adjustment": quality_adj,
        "feasible": feasible,
    }
    for tier in range(1, 7):
        total = sum(judge_cost(j) for j in active_judges if j["tier"] == tier)
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
    if not report.get("feasible", True):
        lines.append("⚠️  Quotas infeasible — best-effort assignment used")
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
