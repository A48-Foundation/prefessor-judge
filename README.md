# Prefessor Judge 🎓⚖️

A tournament judge preference sheet generator for the A48 debate program. Built as a Discord bot ("Prefessor Judge") that automates the process of ranking judges for upcoming tournaments.

## Overview

Prefessor Judge has three components:

1. **Absolute Ranking Database** — Takes CSV input of judges and rankings from past tournaments, stores absolute scores in a Notion database.
2. **Pref Calculator** — Given a list of judges for an upcoming tournament and tier quotas, algorithmically assigns optimal tier rankings (1–5, Strike, Conflict) that satisfy round/judge count requirements.
3. **Discord Bot UI** — Users interact with Prefessor Judge through Discord: upload a CSV, score unknown judges with Tabroom paradigm data, review/edit scores, set quotas, and receive a filled pref sheet.

## How It Works

### Rating Modes

After uploading a tournament CSV, users choose between two sources:

1. **Notion Database** — Matches CSV judges to existing rankings in the Notion database. Only unmatched (new) judges need to be rated.
2. **Rank from Scratch** — All judges start unrated. Choose from:
   - **Manual Rating** — View each judge's Tabroom paradigm and assign a score (1–7) via buttons.
   - **Pairwise Comparison** — An Elo-based system that presents judges in pairs; pick the better one.

### Pairwise Comparison (Elo + Adaptive Swiss)

The pairwise ranker uses an **Elo rating system** (the same model used in chess rankings) with **adaptive Swiss-style pairing** to efficiently rank judges through head-to-head comparisons.

#### How Elo Works
- Every unknown judge starts at an Elo rating of **1500**.
- When you pick Judge A over Judge B, A's rating goes **up** and B's goes **down**.
- The magnitude of the shift depends on the **upset factor** — if a low-rated judge beats a high-rated one, the shift is larger. The K-factor is 64.
- Formula: `new_rating = old_rating + 64 × (actual_result - expected_result)`

#### Adaptive Swiss Pairing
A full round-robin of 85 judges would require **3,570** comparisons. Instead, the system uses Swiss-style pairing across **6 rounds**:

1. **Rounds 1–2 (Calibration):** Each unknown judge is paired against an **anchor judge** with a known Notion score. This calibrates the Elo scale — a judge who beats a known "2" gets pulled toward that rating.
2. **Rounds 3–6 (Adaptive):** Judges are sorted by current Elo and paired against their **closest-rated opponent**. This sharpens the tier boundaries where it matters most — you compare judges that are close in quality, not ones that are obviously different.

Each round generates ~N/2 comparisons (one per judge pair), so 6 rounds × ~42 pairs = **~250 comparisons** for 85 judges — far fewer than 3,570.

#### Hybrid Mode
During pairwise comparison, you can **directly rate** either judge at any time using the dropdown selects (1–5, Strike, Conflict). This removes the judge from all future comparisons and sets their Elo to match the chosen score. Use this for:
- **Obvious strikes** — don't waste comparisons on judges you already know you want to strike.
- **Clear favorites** — if you immediately know a judge is a "1", rate them directly.
- **The uncertain middle** — let pairwise comparisons handle the judges you're unsure about.

#### Score Derivation
After all comparisons, judges are sorted by final Elo and **linearly spread** across the 1.0–5.0 score range:
- Rank 1 (highest Elo) → score 1.0
- Rank N (lowest Elo) → score 5.0
- Everyone in between gets proportionally spaced scores (snapped to 0.1)

If anchor judges from Notion exist, their scores define the range boundaries instead of the default 1.0–5.0.

### Tier Assignment Algorithm

The tier assignment algorithm converts continuous scores (1.0–5.5) into discrete tiers (1–5, Strike, Conflict) while **guaranteeing** that quota constraints are satisfied.

#### Why This Is Hard
Each tier has a minimum (and optional maximum) number of rounds or judges. Simply rounding scores to natural tiers often violates these constraints — you might get 12 judges in tier 2 but need 15, or 5 strikes but the maximum is 3. The algorithm must move judges between tiers while keeping the overall ranking as close to the "natural" ordering as possible.

#### Three-Phase Algorithm

**Phase 1 — Optimal Partition Search:**
Judges are sorted by score (worst first). The algorithm searches for cut-points (k₅, k₄, k₃, k₂) that divide the sorted list into tiers 5, 4, 3, 2, 1 (with tier 1 being the remainder). It uses prefix sums for O(1) range queries and prunes branches where:
- A tier exceeds its maximum
- Remaining rounds can't fill remaining tiers
- Deviation from natural tiers exceeds the best found so far

This explores ~10K iterations for 30 judges and finds the assignment closest to natural tiers.

**Phase 2 — Flexible Assignment (Fallback):**
If no valid partition exists in Phase 1, the algorithm starts each judge at their natural tier and uses **iterative repair**:
1. Find the most under-filled tier (largest deficit)
2. Move a judge from a surplus tier (preferring the closest natural-tier match)
3. Force-move from the largest surplus if all sources are at minimum
4. Repeat until all quotas are met (max N×10 iterations)

This can move judges between **any** tiers — e.g., promoting a natural-3 to tier 2, or demoting a natural-2 to tier 3.

**Phase 3 — Greedy Fallback:**
If flexible assignment also fails (extremely rare), a greedy algorithm fills tiers bottom-up: strikes first, then tier 5, 4, 3, 2, and finally tier 1.

#### Infeasibility
Quotas are **only** reported as infeasible when the total available rounds from non-struck judges are less than the sum of all tier minimums. In other words, infeasibility only occurs when too many judges are struck/conflicted — the algorithm can always shuffle the remaining judges to meet quotas.

#### Fill Order (Bottom-Up)
The algorithm fills **lower tiers first** and **higher tiers last**:
1. Strikes and Conflicts (locked — cannot be reassigned)
2. Tier 5 (worst judges)
3. Tier 4
4. Tier 3
5. Tier 2
6. Tier 1 (best judges — most selective)

If lower tiers are still unmet, judges **trickle down** from the worst of the tier above. This ensures tier 1 is reserved for only the best judges.

### MPJ Optimization Strategy

Tournament judge placement uses **Mutually Preferred Judging (MPJ)**, which scores each judge/round pair:

```
Score = |your_pref - opponent_pref| × 40  +  (your_pref + opponent_pref) × 20
```

Lower score = algorithm prefers to place that judge. A mutual 1-1 match (score 40) is far cheaper than a non-mutual 1-5 match (score 280). A mutual 3-3 (score 120) is preferred over a non-mutual 1-5 (score 280).

The tier assignment algorithm is designed to maximize the probability of getting your top-ranked judges:

- **Tier 1 is kept tight** — exactly the quota minimum, concentrating the strongest signal on your best judges
- **Tiers 2–3 are filled generously** — giving the MPJ algorithm flexibility to find good mutual matches
- **Strikes are aggressive** — forcing unwanted judges into other teams' rounds
- **Tier 5 acts as a soft strike** — the 1-5 penalty (280) is so high it almost never places

## Features

### Interactive Discord Bot
- **Rich embeds** — All messages use Discord embeds with color-coded status indicators
- **Button-based scoring** — Score judges 1–7 with a single click instead of typing numbers
- **Navigation controls** — Previous / Next / Skip buttons to move between judges
- **Judge comparison** — Side-by-side paradigm comparison using the 🔍 Compare button
- **Pairwise comparison** — Elo-based ranking with adaptive Swiss pairing and direct rating dropdowns
- **Review & Edit** — After scoring all judges, see a summary and change any score before proceeding
- **Resume support** — Type `resume` to get fresh buttons if the old ones stop responding
- **Quota mode buttons** — Choose between round count and judge count quotas with a button press

### Tabroom Integration
- Authenticates with a Tabroom.com account to fetch judge paradigm data
- Searches judges by name and scrapes their philosophy/judging approach
- Pre-fetches paradigms for all unmatched judges when a CSV is uploaded
- In-memory cache (1-hour TTL) prevents redundant scraping
- Paradigm text is displayed as separate messages below the scoring UI

### Name Matching
- Case-insensitive fuzzy matching between CSV and Notion names
- Strips invisible Unicode characters (U+200E, U+200F, etc.)
- Normalizes apostrophes and special characters
- Threshold-based matching (score ≥ 85) with manual disambiguation

## Project Structure

```
prefessor-judge/
├── pref-calculator/
│   ├── main.py                 # Discord bot (entry point)
│   ├── cli.py                  # CLI version (standalone)
│   ├── csv_parser.py           # Parse tournament judge CSV files
│   ├── csv_writer.py           # Write output CSV with tier assignments
│   ├── name_matcher.py         # Fuzzy match CSV names to Notion database
│   ├── notion_reader.py        # Fetch absolute scores from Notion
│   ├── pairwise_ranker.py      # Elo + adaptive Swiss pairwise ranking
│   ├── score_prompter.py       # CLI score prompting for unknown judges
│   ├── tier_assigner.py        # Core tier assignment algorithm
│   ├── tabroom_scraper.py      # Tabroom.com paradigm scraper
│   ├── tabroom_cache.py        # In-memory cache for paradigm data
│   ├── requirements.txt        # Python dependencies
│   └── generate_test_data.py   # Test data generator
├── Procfile                    # Railway deployment
├── railway.toml                # Railway config
├── run_bot.ps1                 # PowerShell launcher for the bot
└── .gitignore
```

## Setup

### Prerequisites
- Python 3.10+
- A Discord bot token ([Discord Developer Portal](https://discord.com/developers/applications))
- A Notion integration API key and database ID
- A Tabroom.com account (for paradigm fetching)

### Installation

```bash
cd pref-calculator
pip install -r requirements.txt
```

### Environment Variables

Create a `.env` file in the `pref-calculator/` directory:

```env
DISCORD_BOT_TOKEN=your_discord_bot_token
NOTION_API_KEY=your_notion_api_key
NOTION_DATABASE_ID=your_notion_database_id
TABROOM_EMAIL=your_tabroom_email
TABROOM_PASSWORD=your_tabroom_password
```

### Running the Bot

```bash
cd pref-calculator
python main.py
```

Or use the PowerShell launcher:

```powershell
.\run_bot.ps1
```

### Deployment (Railway)

The bot is configured for Railway deployment:
- `Procfile` and `railway.toml` define the start command
- Set environment variables in Railway's service settings
- Deploys automatically on push to `main`

## Discord Bot Usage

1. **Start a session** — Mention the bot: `@Prefessor Judge do prefs`
2. **Upload CSV** — Attach a tournament judge CSV file (columns: `Name, School, Rounds, Your Rating` or `First, Last, School, Online, Rounds, Rating`)
3. **Choose rating source** — Use Notion database or rank from scratch
4. **Rate judges** — For unmatched/all judges:
   - **Manual**: View each judge's Tabroom paradigm, click a score button (1–7)
   - **Pairwise**: Pick the better judge in each pair, or rate directly via dropdown
   - **Skip**: Leave unmatched judges with default ratings
5. **Review scores** — See a summary of all scored judges; use the dropdown to edit any score
6. **Set quotas** — Choose quota mode (rounds or judges), then enter min/max for each tier
7. **Get results** — Receive a tier assignment report and the filled CSV file

Type `cancel` to abort or `resume` to refresh buttons if they stop responding.

## Score & Tier Reference

| Score | Tier | Meaning |
|-------|------|---------|
| 1–1.5 | 1 | Best judges |
| 2–2.5 | 2 | Good judges |
| 3–3.5 | 3 | Average judges |
| 4–4.5 | 4 | Below average |
| 5–5.5 | 5 | Worst judges |
| 6 | S | Strike (will not judge our debaters) |
| 7 | C | Conflict (same school as our program) |

## Changelog

### v3 — Adaptive Pairwise & Guaranteed Quotas (2026-03-05)
- **Rank from scratch** mode — rate all judges fresh without Notion data
- **Pairwise comparison** with Elo + adaptive Swiss pairing (6 rounds, ~250 comparisons for 85 judges)
- **Hybrid rating** — direct rating dropdowns (1–5, Strike, Conflict) during pairwise comparison
- **Guaranteed tier quotas** — 3-phase algorithm (optimal partition → flexible assignment → greedy fallback)
- **Infeasibility only from strikes** — algorithm shuffles judges between any tiers to meet quotas
- **Improved name matching** — case-insensitive, Unicode stripping, apostrophe normalization
- **No view timeouts** — buttons stay active as long as the bot is running
- **Resume command** — type `resume` to get fresh buttons
- **Full results display** — all judges shown (ranked + struck/conflicted), split across multiple embeds
- **Railway deployment** — Procfile and railway.toml for cloud hosting

### v2 — Interactive UI & Judge Comparison (2026-03-05)
- Rewrote Discord bot with interactive components (buttons, select menus, modals)
- Added **ScoringView**: score buttons (1–7), Previous/Next/Skip/Compare navigation
- Added **CompareSelectView**: side-by-side judge paradigm comparison via Discord embeds
- Added **ReviewView**: summary of all scored judges with ability to edit any score
- Added **Tabroom scraper** (`tabroom_scraper.py`): authenticates with Tabroom, fetches paradigm data
- Added **paradigm cache** (`tabroom_cache.py`): in-memory cache with 1-hour TTL
- Added `requirements.txt` with all Python dependencies
- All bot messages now use rich Discord embeds with consistent color-coded styling
- Pre-fetches Tabroom paradigms for all unmatched judges on CSV upload

### v1 — Initial Release (2026-03-03 to 2026-03-04)
- Pref calculator with tier assignment algorithm
- Notion database integration for absolute judge scores
- Fuzzy name matching between CSV and Notion
- Discord bot with text-based workflow
- Support for both round count and judge count quota modes
- Conflict tier (C) for same-school judges
- CSV format auto-detection (First/Last vs Name columns)
