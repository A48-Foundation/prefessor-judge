# Pref Calculator — Algorithm Deep Dive

This document explains the two core algorithms behind Prefessor Judge: the **Pairwise Comparison Ranker** (`pairwise_ranker.py`) and the **Tier Assignment Algorithm** (`tier_assigner.py`).

---

## Pairwise Comparison Ranker

**File:** `pairwise_ranker.py`

The pairwise ranker converts subjective "who is better?" comparisons into a continuous score (1.0–5.0) for each judge. It uses an **Elo rating system** with **adaptive Swiss-style pairing** to minimize the number of comparisons needed.

### Core Concepts

#### Elo Rating System

Every unknown judge starts at an Elo rating of **1500**. When the user picks Judge A over Judge B:

```
expected_A = 1 / (1 + 10^((elo_B - elo_A) / 400))
new_elo_A  = elo_A + K × (1 - expected_A)
new_elo_B  = elo_B + K × (0 - expected_B)
```

- **K-factor = 64** — high sensitivity so ratings converge quickly with few comparisons
- **Upset bonus** — if a low-rated judge beats a high-rated one, the Elo shift is larger (the expected result was the opposite)
- Anchor judges (from Notion or pre-filled CSV) have their Elo set from their known score: `elo = 2000 - (score - 1) × 300`

#### Anchor Judges

Anchor judges are judges with **known scores** — either from the Notion database, pre-filled CSV ratings, or judges directly rated during pairwise comparison. They serve two purposes:

1. **Calibration** — Unknown judges are paired against nearby anchors every round to ground their Elo relative to known quantities
2. **Score range** — After comparison, the anchor score range defines the mapping from Elo to absolute scores

When a user directly rates a judge during pairwise comparison (via the dropdown), that judge is **promoted to anchor** — their Elo is set to match the chosen score, and they're used for calibration in subsequent rounds.

### Adaptive Swiss Pairing

A full round-robin of N judges requires N×(N-1)/2 comparisons (e.g., 3,570 for 85 judges). Swiss pairing reduces this dramatically.

#### Round Structure (6 rounds)

Each round has two phases:

**Phase 1 — Anchor Calibration:**
Every unknown judge is paired against their **closest-Elo anchor**. This grounds each judge's rating against a known reference point. As more judges are directly rated (becoming anchors), calibration improves.

```
For each unknown judge U:
    Find anchor A where |elo(U) - elo(A)| is minimized
    If (U, A) hasn't been paired before:
        Queue pair (U, A)
```

**Phase 2 — Adaptive Peer Pairing:**
Remaining unknown judges are sorted by Elo and paired against their **closest-rated peer**. This sharpens tier boundaries where it matters most — you compare judges that are close in quality, not ones that are obviously different.

```
Sort unknowns by Elo (descending)
For each unpaired judge J:
    Find unpaired judge K where |elo(J) - elo(K)| is minimized
    If (J, K) hasn't been paired before:
        Queue pair (J, K)
```

Slight randomization is applied when two judges have nearly identical Elo (within 5 points) to avoid deterministic loops.

#### Comparison Count

Each round generates ~N/2 anchor pairs + ~N/2 peer pairs. With 6 rounds:
- **85 judges → ~250 comparisons** (vs 3,570 round-robin)
- **30 judges → ~90 comparisons** (vs 435 round-robin)

Rounds are generated lazily — the next round's pairs are only computed when the current round's queue is exhausted.

### Hybrid Mode: Direct Rating During Comparison

During any pairwise comparison, the user can:

- **Rate Judge A or B directly** (dropdown: 1–N, Strike, Conflict)
- **Strike or Conflict** either judge (buttons)

When a judge is directly rated:
1. Their Elo is set to match the chosen score
2. They're **removed** from all remaining comparisons
3. They're **promoted to anchor** — used for calibration in future rounds
4. Their score is stored in `scores_map` and used directly in tier assignment

When a judge is struck or conflicted:
1. Their score is set to 6.0 (strike) or 7.0 (conflict)
2. They're removed from all remaining comparisons
3. They are **not** promoted to anchor (strikes/conflicts don't calibrate)

### Score Derivation

After all comparisons complete, unknown judges are sorted by final Elo and **linearly spread** across the score range:

```
If anchors exist:
    range_min = min(anchor_scores)
    range_max = max(anchor_scores)
Else:
    range_min = 1.0
    range_max = 5.0

For rank i of N judges (0-indexed, best first):
    score = range_min + (range_max - range_min) × i / (N - 1)
    score = clamp(score, 1.0, 5.5)
    score = round to nearest 0.1
```

This means the best judge gets the best anchor score, the worst gets the worst, and everyone else is proportionally spaced.

### Undo System

Every action (result, skip, direct rate, strike/conflict) is pushed onto an undo stack. The undo operation:

- **Result**: Restores both judges' Elo to pre-comparison values, re-queues the pair
- **Skip**: Re-queues the skipped pair
- **Direct rate**: Restores Elo, moves judge back to unknown pool, removes from anchors, re-queues removed pairs
- **Strike/Conflict**: Moves judge back to unknown pool, re-queues removed pairs, removes score from `scores_map`

---

## Score Normalization

**File:** `main.py` — `_normalize_score()` function

All user-facing scores are normalized to the **internal [1.0, 5.0] scale** at the input boundary:

```
internal = 1.0 + (raw - 1) × 4.0 / (rating_max - 1)
```

| User Scale | Raw Input | Internal Score |
|-----------|-----------|----------------|
| 1–5       | 3         | 3.0            |
| 1–7       | 4         | 3.0            |
| 1–6       | 3.5       | 3.0            |
| Any       | Strike    | 6.0            |
| Any       | Conflict  | 7.0            |

This means **all internal logic** (tier assignment, Elo conversion, quality adjustment) operates on a consistent 1–5 scale regardless of the tournament's rating range. The tier_assigner.py module is never modified for UI changes.

---

## Tier Assignment Algorithm

**File:** `tier_assigner.py`

The tier assignment algorithm converts continuous scores (1.0–5.5) into discrete tiers (1–5, Strike, Conflict) while **guaranteeing** that quota constraints are satisfied when mathematically possible.

### Input

```python
assign_tiers(judges_with_scores, quotas, quota_mode)
```

- `judges_with_scores` — list of `{"name", "school", "rounds", "score"}` dicts (score on internal 1–5 scale, 6.0 = strike, 7.0 = conflict)
- `quotas` — `{tier: {"min": int, "max": int}}` for tiers 1–6
- `quota_mode` — `"rounds"` (sum of judge rounds per tier) or `"judges"` (count of judges per tier)

### Phase 0 — Tournament Quality Adjustment

Before tier assignment, the algorithm detects the **overall quality** of the judge pool:

```
pool_average = mean(all rated scores)
diff = 3.5 - pool_average
```

- **Strong pool** (avg < 3.5): scores shift up slightly (factor 0.25) — makes tiers harder to earn
- **Weak pool** (avg > 3.5): scores shift down more aggressively (factor 0.75) — improves placements

The asymmetry is intentional: a weak pool benefits more from adjustment than a strong pool is harmed. Strikes and conflicts are never adjusted. All adjusted scores are clamped to [1.0, 5.5].

### Phase 1 — Separation

Judges are immediately separated into three groups:

| Score     | Group    | Tier |
|-----------|----------|------|
| ≥ 7.0     | Conflict | 7    |
| 6.0–6.99  | Strike   | 6    |
| < 6.0     | Rateable | 1–5  |

Conflicts and strikes are **locked** — they cannot be reassigned by the algorithm. The remaining rateable judges proceed to Phases 2–3.

### Phase 2a — Optimal Sequential Partition

This is the primary algorithm. Judges are sorted by score (worst first), and the algorithm searches for **cut-points** (k₅, k₄, k₃, k₂) that divide the sorted list into contiguous groups:

```
[0..k₅) → Tier 5
[k₅..k₅+k₄) → Tier 4
[k₅+k₄..k₅+k₄+k₃) → Tier 3
[k₅+k₄+k₃..k₅+k₄+k₃+k₂) → Tier 2
[remainder] → Tier 1
```

**Optimization objective:** Minimize total deviation from natural tiers (the tier each judge would naturally belong to based on their score).

**Constraints enforced:**
- Each tier's total (rounds or judges) must be within [min, max] from quotas
- **±1 tier constraint** — no judge moves more than 1 tier from their natural tier (a natural-3 can only be in tiers 2, 3, or 4)
- Remaining capacity must be sufficient to fill subsequent tiers (prefix-sum pruning)

**Performance:** Uses O(1) prefix-sum range queries and aggressive branch pruning. Explores ~10K iterations for 30 judges. The search terminates early when it finds a perfect (zero-deviation) solution or when all remaining branches exceed the best solution found.

### Phase 2b — Alternative Sort Order

If Phase 2a fails, the algorithm re-sorts rateable judges with **different tie-breaking**: low-rounds-first instead of high-rounds-first. This can unlock solutions when round-based quotas are tight and judges with the same score have different round counts.

### Phase 3 — Flexible Assignment (Iterative Repair)

If no sequential partition satisfies all quotas, the algorithm switches to iterative repair:

1. **Initialize** each judge at their natural tier (clamped to 1–5)
2. **Find the most under-filled tier** (largest deficit)
3. **Move a judge** from a surplus tier to the deficit tier, preferring:
   - Judges whose natural tier is closest to the destination
   - Source tiers with the largest surplus
4. **Constraint**: a judge can only move to a tier within ±1 of their natural tier
5. **Repeat** until all quotas are met (max N×10 iterations)

If a tier is over-filled (exceeds max), judges are moved to adjacent tiers first.

This phase can handle cases where the sequential partition fails — e.g., when a cluster of judges at the tier boundary needs to be split across two tiers.

### Phase 4 — Greedy Fallback

Only triggered when quotas are **truly infeasible** — specifically when strikes/conflicts consume so many rounds that remaining rateable judges cannot fill all tier minimums.

The greedy algorithm fills tiers **bottom-up**:
1. Tier 5 (worst judges first, up to minimum)
2. Tier 4
3. Tier 3
4. Tier 2
5. Tier 1 (everything remaining)

### Natural Tier Mapping

The `natural_tier()` function maps continuous scores to discrete tiers:

| Score     | Natural Tier |
|-----------|-------------|
| 1.0–1.5   | 1           |
| 2.0–2.5   | 2           |
| 3.0–3.5   | 3           |
| 4.0–4.5   | 4           |
| 5.0–5.5   | 5           |
| 6.0       | 6 (strike)  |
| 7.0       | 7 (conflict)|

Half-scores (e.g., 2.5) belong to the **lower** tier (tier 2, not tier 3).

### Infeasibility

Quotas are reported as infeasible **only** when:

```
total_rateable_rounds < sum(tier_minimums for tiers 1-5)
```

In other words, infeasibility occurs only when too many judges are struck/conflicted, leaving insufficient rounds to fill all tiers. The algorithm can always shuffle remaining judges between tiers to meet quotas — the ±1 constraint is relaxed in Phase 3 to allow any-to-any movement within the ±1 band.

### Report Output

After assignment, the algorithm returns a detailed report:

```
Quota mode: Rounds
Tier   Judges   Rounds   Rounds (quota)   Min    Max    Status
------------------------------------------------------------
1      5        20       20               10     50     ✓
2      8        32       32               10     -      ✓
3      10       40       40               10     -      ✓
4      8        32       32               10     -      ✓
5      4        16       16               5      -      ✓
S      2        8        8                -      5      ✓
C      1        4        4                -      -      -
```

The CSV output uses `C` for conflict, `S` for strike, and tier numbers (1–5) for rated judges.

---

## End-to-End Flow

```
CSV Upload
    ↓
Rating Scale Selection (1–5, 1–6, 1–7, etc.)
    ↓
Pre-filled Rating Extraction (S, C, numeric → internal 1–5 scale)
    ↓
Source Choice: Notion Database or From Scratch
    ↓
Unmatched Judge Handling: Direct Rating / Pairwise Compare / Skip
    ↓
[Direct Rating]                    [Pairwise Compare]
Button scores normalized           Elo comparison with
to internal 1–5 scale              adaptive Swiss pairing
    ↓                                  ↓
                                   Score derivation via
                                   linear Elo→score mapping
    ↓                                  ↓
Score Review & Edit (all scores in internal scale)
    ↓
Quota Mode Selection (rounds or judges)
    ↓
Quota Entry (min/max per tier)
    ↓
Tournament Quality Adjustment (Phase 0)
    ↓
Tier Assignment (Phases 1–4)
    ↓
Output CSV: First, Last, School, Rounds, Rating (1–5, S, C)
```
