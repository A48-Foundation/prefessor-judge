"""Pairwise comparison ranking using Elo ratings.

Presents judges in pairs; user picks the better one. After enough comparisons,
Elo scores are mapped to the 1-7 absolute score scale using anchor judges
from the Notion database.
"""
import random
import math


DEFAULT_ELO = 1500
K_FACTOR = 64


class PairwiseRanker:
    """Elo-based pairwise ranking system for unknown judges."""

    def __init__(self, unknown_judges, anchor_judges=None):
        """
        Args:
            unknown_judges: list of judge dicts (name, school, rounds)
            anchor_judges: list of judge dicts with known scores from Notion
                          (name, school, rounds, score). Used to anchor Elo → score mapping.
        """
        self.unknown = list(unknown_judges)
        self.anchors = list(anchor_judges or [])
        self.all_judges = self.unknown + self.anchors

        # Initialize Elo ratings; anchors start at score-derived Elo
        self.elo = {}
        for j in self.unknown:
            self.elo[j["name"]] = DEFAULT_ELO
        for j in self.anchors:
            self.elo[j["name"]] = self._score_to_elo(j["score"])

        self.comparisons_done = 0
        self.history = []  # list of (winner_name, loser_name)
        self._pair_queue = []
        self._undo_stack = []
        self._build_pair_queue()

    @staticmethod
    def _score_to_elo(score):
        """Map a 1-6 score to an Elo rating. 1=2000, 6=500."""
        if score is None:
            return DEFAULT_ELO
        return int(2000 - (score - 1) * 300)

    @staticmethod
    def _elo_to_score(elo):
        """Map an Elo rating back to a 1-5.5 score (snapped to 0.5)."""
        score = 1 + (2000 - elo) / 300
        score = max(1.0, min(5.5, score))
        return round(score * 2) / 2

    def _build_pair_queue(self):
        """Build queue of comparison pairs (Swiss-style, not full round-robin).

        Each unknown gets:
        1. 1-2 anchor comparisons (calibration against known judges)
        2. ~2 comparisons against other unknowns
        Total: ~3-4 comparisons per unknown judge.
        """
        pairs = set()
        n = len(self.unknown)

        # Unknown vs anchor comparisons
        if self.anchors:
            anchors_per = min(2, len(self.anchors)) if n <= 10 else min(1, len(self.anchors))
            for uj in self.unknown:
                chosen = random.sample(self.anchors, anchors_per)
                for aj in chosen:
                    pairs.add((uj["name"], aj["name"]))

        # Unknown vs unknown: each judge gets ~2 opponents
        comparisons_per_judge = min(2, n - 1)
        # Track how many comparisons each judge has
        judge_counts = {j["name"]: 0 for j in self.unknown}

        shuffled = list(self.unknown)
        random.shuffle(shuffled)
        for uj in shuffled:
            if judge_counts[uj["name"]] >= comparisons_per_judge:
                continue
            candidates = [
                j for j in self.unknown
                if j["name"] != uj["name"]
                and judge_counts[j["name"]] < comparisons_per_judge
                and (uj["name"], j["name"]) not in pairs
                and (j["name"], uj["name"]) not in pairs
            ]
            if not candidates:
                candidates = [
                    j for j in self.unknown
                    if j["name"] != uj["name"]
                    and (uj["name"], j["name"]) not in pairs
                    and (j["name"], uj["name"]) not in pairs
                ]
            needed = comparisons_per_judge - judge_counts[uj["name"]]
            chosen = random.sample(candidates, min(needed, len(candidates)))
            for cj in chosen:
                pairs.add((uj["name"], cj["name"]))
                judge_counts[uj["name"]] += 1
                judge_counts[cj["name"]] += 1

        # Convert name pairs back to judge dict pairs
        name_to_judge = {j["name"]: j for j in self.all_judges}
        pair_list = [(name_to_judge[a], name_to_judge[b]) for a, b in pairs]
        random.shuffle(pair_list)
        self._pair_queue = pair_list

    @property
    def total_comparisons(self):
        return len(self._pair_queue)

    @property
    def remaining(self):
        return len(self._pair_queue)

    @property
    def is_complete(self):
        return len(self._pair_queue) == 0

    def next_pair(self):
        """Return the next pair of judges to compare, or None if done."""
        if not self._pair_queue:
            return None
        return self._pair_queue[0]

    def record_result(self, winner, loser):
        """Record a comparison result and update Elo ratings."""
        w_elo = self.elo.get(winner["name"], DEFAULT_ELO)
        l_elo = self.elo.get(loser["name"], DEFAULT_ELO)

        # Expected scores
        exp_w = 1 / (1 + math.pow(10, (l_elo - w_elo) / 400))
        exp_l = 1 - exp_w

        # Save state for undo
        self._undo_stack.append({
            "type": "result",
            "pair": (winner, loser),
            "w_elo_before": w_elo,
            "l_elo_before": l_elo,
        })

        # Update Elo
        self.elo[winner["name"]] = w_elo + K_FACTOR * (1 - exp_w)
        self.elo[loser["name"]] = l_elo + K_FACTOR * (0 - exp_l)

        self.history.append((winner["name"], loser["name"]))
        self.comparisons_done += 1

        # Remove this pair from queue
        if self._pair_queue:
            self._pair_queue.pop(0)

    def skip_pair(self):
        """Skip the current pair without recording a result."""
        if self._pair_queue:
            pair = self._pair_queue.pop(0)
            self._undo_stack.append({"type": "skip", "pair": pair})

    def undo(self) -> bool:
        """Undo the last action (result, skip, or special). Returns True if successful."""
        if not self._undo_stack:
            return False
        action = self._undo_stack.pop()
        if action["type"] == "result":
            winner, loser = action["pair"]
            self.elo[winner["name"]] = action["w_elo_before"]
            self.elo[loser["name"]] = action["l_elo_before"]
            self.history.pop()
            self.comparisons_done -= 1
            self._pair_queue.insert(0, (winner, loser))
        elif action["type"] == "skip":
            self._pair_queue.insert(0, action["pair"])
        elif action["type"] == "special":
            judge = action["judge"]
            self.unknown.append(judge)
            for pair in reversed(action["removed_pairs"]):
                self._pair_queue.insert(0, pair)
        return True

    def remove_judge(self, judge, score=None):
        """Remove a judge from all remaining comparisons (e.g., strike/conflict)."""
        removed_pairs = [
            (a, b) for a, b in self._pair_queue
            if a["name"] == judge["name"] or b["name"] == judge["name"]
        ]
        self._undo_stack.append({
            "type": "special",
            "judge": judge,
            "score": score,
            "removed_pairs": removed_pairs,
        })
        self._pair_queue = [
            (a, b) for a, b in self._pair_queue
            if a["name"] != judge["name"] and b["name"] != judge["name"]
        ]
        self.unknown = [j for j in self.unknown if j["name"] != judge["name"]]

    def get_scores(self):
        """Return derived scores based on Elo rank ordering.

        Spreads judges across a score range based on relative Elo ranking,
        ensuring every comparison is reflected in different scores.
        Uses anchor judges (if any) to calibrate the range.
        """
        if not self.unknown:
            return []

        # Sort by Elo (best first)
        ranked = sorted(self.unknown, key=lambda j: -self.elo.get(j["name"], DEFAULT_ELO))

        # Determine score range from anchors or defaults
        if self.anchors:
            anchor_scores = [a["score"] for a in self.anchors if a.get("score")]
            range_min = min(anchor_scores) if anchor_scores else 1.0
            range_max = max(anchor_scores) if anchor_scores else 5.0
        else:
            range_min = 1.0
            range_max = 5.0

        n = len(ranked)
        results = []
        for i, j in enumerate(ranked):
            if n == 1:
                score = (range_min + range_max) / 2
            else:
                score = range_min + (range_max - range_min) * i / (n - 1)
            score = round(score * 10) / 10  # snap to 0.1
            score = max(1.0, min(5.5, score))
            results.append((j, score))
        return results

    def get_rankings(self):
        """Return unknown judges sorted by Elo (best first)."""
        ranked = [(j, self.elo.get(j["name"], DEFAULT_ELO)) for j in self.unknown]
        ranked.sort(key=lambda x: -x[1])
        return ranked
