"""Pairwise comparison ranking using Elo ratings with adaptive Swiss pairing.

Presents judges in pairs; user picks the better one. After enough comparisons,
Elo scores are mapped to the 1-7 absolute score scale using anchor judges
from the Notion database.

Adaptive Swiss: pairs judges with similar Elo ratings after initial rounds,
sharpening tier boundaries where it matters most.
"""
import random
import math


DEFAULT_ELO = 1500
K_FACTOR = 64
# Number of Swiss rounds (each judge gets ~1 match per round)
SWISS_ROUNDS = 6


class PairwiseRanker:
    """Elo-based pairwise ranking system with adaptive Swiss pairing."""

    def __init__(self, unknown_judges, anchor_judges=None):
        self.unknown = list(unknown_judges)
        self.anchors = list(anchor_judges or [])
        self.all_judges = self.unknown + self.anchors

        self.elo = {}
        for j in self.unknown:
            self.elo[j["name"]] = DEFAULT_ELO
        for j in self.anchors:
            self.elo[j["name"]] = self._score_to_elo(j["score"])

        self.comparisons_done = 0
        self.history = []
        self._pair_queue = []
        self._undo_stack = []
        self._matched_pairs = set()  # all pairs ever generated (avoid repeats)
        self._current_round = 0
        self._rounds_total = SWISS_ROUNDS
        self._build_next_round()

    @staticmethod
    def _score_to_elo(score):
        if score is None:
            return DEFAULT_ELO
        return int(2000 - (score - 1) * 300)

    @staticmethod
    def _elo_to_score(elo):
        score = 1 + (2000 - elo) / 300
        score = max(1.0, min(5.5, score))
        return round(score * 2) / 2

    def _pair_key(self, a, b):
        return tuple(sorted([a, b]))

    def _build_next_round(self):
        """Build pairs for the next Swiss round using adaptive pairing."""
        if self._current_round >= self._rounds_total:
            return
        self._current_round += 1

        n = len(self.unknown)
        if n < 2 and not self.anchors:
            return

        new_pairs = []

        # Anchor calibration: pair unknowns against anchors (original + directly rated)
        if self.anchors:
            for uj in self.unknown:
                available = [a for a in self.anchors
                             if self._pair_key(uj["name"], a["name"]) not in self._matched_pairs]
                if available:
                    # Pick anchor closest in Elo for sharper calibration
                    uj_elo = self.elo.get(uj["name"], DEFAULT_ELO)
                    available.sort(key=lambda a: abs(self.elo.get(a["name"], DEFAULT_ELO) - uj_elo))
                    aj = available[0]
                    pk = self._pair_key(uj["name"], aj["name"])
                    self._matched_pairs.add(pk)
                    new_pairs.append((uj, aj))

        # Adaptive peer pairing: sort by Elo, pair adjacent judges
        if n >= 2:
            sorted_judges = sorted(self.unknown, key=lambda j: -self.elo.get(j["name"], DEFAULT_ELO))
            # Slight randomization within similar Elo to avoid deterministic loops
            for i in range(len(sorted_judges) - 1):
                if abs(self.elo.get(sorted_judges[i]["name"], 0) - self.elo.get(sorted_judges[i+1]["name"], 0)) < 5:
                    if random.random() < 0.5:
                        sorted_judges[i], sorted_judges[i+1] = sorted_judges[i+1], sorted_judges[i]

            paired_this_round = set()
            for j in sorted_judges:
                if j["name"] in paired_this_round:
                    continue
                best = None
                best_diff = float("inf")
                for k in sorted_judges:
                    if k["name"] == j["name"] or k["name"] in paired_this_round:
                        continue
                    pk = self._pair_key(j["name"], k["name"])
                    if pk in self._matched_pairs:
                        continue
                    diff = abs(self.elo.get(j["name"], DEFAULT_ELO) - self.elo.get(k["name"], DEFAULT_ELO))
                    if diff < best_diff:
                        best_diff = diff
                        best = k
                if best:
                    pk = self._pair_key(j["name"], best["name"])
                    self._matched_pairs.add(pk)
                    paired_this_round.add(j["name"])
                    paired_this_round.add(best["name"])
                    new_pairs.append((j, best))

        random.shuffle(new_pairs)
        self._pair_queue.extend(new_pairs)

    @property
    def total_comparisons(self):
        return self.comparisons_done + len(self._pair_queue)

    @property
    def remaining(self):
        return len(self._pair_queue)

    @property
    def is_complete(self):
        return len(self._pair_queue) == 0

    def next_pair(self):
        if not self._pair_queue:
            return None
        return self._pair_queue[0]

    def record_result(self, winner, loser):
        w_elo = self.elo.get(winner["name"], DEFAULT_ELO)
        l_elo = self.elo.get(loser["name"], DEFAULT_ELO)
        exp_w = 1 / (1 + math.pow(10, (l_elo - w_elo) / 400))
        exp_l = 1 - exp_w

        self._undo_stack.append({
            "type": "result",
            "pair": (winner, loser),
            "w_elo_before": w_elo,
            "l_elo_before": l_elo,
        })

        self.elo[winner["name"]] = w_elo + K_FACTOR * (1 - exp_w)
        self.elo[loser["name"]] = l_elo + K_FACTOR * (0 - exp_l)
        self.history.append((winner["name"], loser["name"]))
        self.comparisons_done += 1

        if self._pair_queue:
            self._pair_queue.pop(0)

        # Generate next round when current round's pairs are exhausted
        if not self._pair_queue and self._current_round < self._rounds_total:
            self._build_next_round()

    def skip_pair(self):
        if self._pair_queue:
            pair = self._pair_queue.pop(0)
            self._undo_stack.append({"type": "skip", "pair": pair})
        if not self._pair_queue and self._current_round < self._rounds_total:
            self._build_next_round()

    def undo(self) -> bool:
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
        elif action["type"] == "rate":
            judge = action["judge"]
            self.elo[judge["name"]] = action["elo_before"]
            self.unknown.append(judge)
            # Remove from anchors (was promoted on rate)
            self.anchors = [a for a in self.anchors if a["name"] != judge["name"]]
            for pair in reversed(action["removed_pairs"]):
                self._pair_queue.insert(0, pair)
        return True

    def remove_judge(self, judge, score=None):
        """Remove a judge from all remaining comparisons (strike/conflict)."""
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
        if not self._pair_queue and self._current_round < self._rounds_total:
            self._build_next_round()

    def rate_judge(self, judge, score):
        """Directly rate a judge (1-5), setting their Elo and promoting to anchor."""
        removed_pairs = [
            (a, b) for a, b in self._pair_queue
            if a["name"] == judge["name"] or b["name"] == judge["name"]
        ]
        self._undo_stack.append({
            "type": "rate",
            "judge": judge,
            "score": score,
            "elo_before": self.elo.get(judge["name"], DEFAULT_ELO),
            "removed_pairs": removed_pairs,
        })
        self.elo[judge["name"]] = self._score_to_elo(score)
        self._pair_queue = [
            (a, b) for a, b in self._pair_queue
            if a["name"] != judge["name"] and b["name"] != judge["name"]
        ]
        self.unknown = [j for j in self.unknown if j["name"] != judge["name"]]
        # Promote to anchor so future rounds use this judge for calibration
        rated = dict(judge)
        rated["score"] = score
        self.anchors.append(rated)
        if not self._pair_queue and self._current_round < self._rounds_total:
            self._build_next_round()

    def get_scores(self):
        """Return derived scores based on Elo rank ordering."""
        if not self.unknown:
            return []

        ranked = sorted(self.unknown, key=lambda j: -self.elo.get(j["name"], DEFAULT_ELO))

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
            score = round(score * 10) / 10
            score = max(1.0, min(5.5, score))
            results.append((j, score))
        return results

    def get_rankings(self):
        """Return unknown judges sorted by Elo (best first)."""
        ranked = [(j, self.elo.get(j["name"], DEFAULT_ELO)) for j in self.unknown]
        ranked.sort(key=lambda x: -x[1])
        return ranked
