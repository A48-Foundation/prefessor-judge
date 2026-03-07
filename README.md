# Prefessor Judge 🎓⚖️

A tournament judge preference sheet generator for the A48 debate program. Built as a Discord bot that automates the process of ranking judges for upcoming tournaments.

Prefessor Judge has three components:

1. **Absolute Ranking Database** — Stores absolute judge scores in a Notion database from past tournaments.
2. **Pref Calculator** — Given a list of judges and tier quotas, algorithmically assigns optimal tier rankings that satisfy round/judge count requirements.
3. **Discord Bot UI** — Interactive Discord interface: upload a CSV, score judges, set quotas, and receive a filled pref sheet.

---

## How to Use

### Quick Start

1. **Start a session** — Mention the bot in Discord: `@Prefessor Judge do prefs`
2. **Upload your CSV** — Attach a tournament judge CSV file
3. **Select rating scale** — Choose the tournament's max rating (1–5, 1–6, 1–7) via buttons
4. **Choose rating source** — "Notion Database" or "From Scratch" (buttons)
5. **Rate unmatched judges** — Choose a method (buttons):
   - **Direct Rating** — Score each judge individually with paradigm info
   - **Pairwise Compare** — Pick the better judge in side-by-side matchups
   - **Skip** — Leave unmatched judges with default ratings
6. **Review scores** — Edit any score using the dropdown before continuing
7. **Set quotas** — Choose quota mode (rounds or judges), then enter min/max per tier
8. **Get results** — Download the filled CSV with tier assignments

Type `cancel` to abort or `resume` to refresh buttons if they stop responding.

### CSV Format

The bot accepts two CSV formats:

**Format A:**
```
First,Last,School,Online,Rounds,Rating
John,Smith,Harvard,Y,4,
Jane,Doe,Yale,N,6,3
```

**Format B:**
```
Name,School,Rounds,Your Rating
John Smith,Harvard,4,
Jane Doe,Yale,6,3
```

The **Rating** column is optional. If a judge already has a rating filled in, it's treated as an anchor — that judge skips manual scoring. If all judges have ratings, the bot jumps directly to quota setup.

Special values in the Rating column:
- **S** — Strike (will not judge our debaters)
- **C** — Conflict (same school as our program)
- **Number** — Score on the tournament's rating scale (e.g., 3 on a 1–5 scale)
- **Max + 1** — Also interpreted as Strike (e.g., 6 on a 1–5 scale)

### Rating Modes

#### Direct Rating
View each judge's Tabroom paradigm and school info, then click a score button (1–N, Strike, or Conflict). Use **Compare** to see two judges side-by-side, or **Previous** to go back and change a score.

#### Pairwise Comparison
An Elo-based system presents judges in pairs — pick the better one. The system uses adaptive Swiss pairing to minimize comparisons (~250 for 85 judges instead of 3,570 round-robin). During comparison you can also:

- **Rate directly** via the dropdown (1–N, Strike, Conflict) — removes the judge from future matchups and improves calibration for remaining judges
- **Strike/Conflict** via buttons — removes the judge immediately
- **Undo** — reverses the last action
- **Done** — finish early with current rankings

### Quota Entry

Quotas define how many rounds (or judges) each tier must contain. Enter space-separated values:

```
Format: min or min,max for each tier
Example: 10,50 10 10 10 5 -,5
         T1    T2 T3 T4 T5 Strike
```

- `10,50` — Tier 1 needs at least 10, at most 50
- `10` — Tier 2 needs at least 10, no maximum
- `-,5` — Strike tier has no minimum, at most 5

### Output

The bot produces a CSV file with columns: `First, Last, School, Rounds, Rating`

| Rating | Meaning |
|--------|---------|
| 1–5    | Tier assignment (1 = best) |
| S      | Strike |
| C      | Conflict |

### MPJ Strategy

The tier assignments are optimized for **Mutually Preferred Judging (MPJ)**:

- **Tier 1 is kept tight** — exactly the quota minimum, concentrating the strongest signal on your best judges
- **Tiers 2–3 are filled generously** — giving the MPJ algorithm flexibility to find good mutual matches
- **Strikes are aggressive** — forcing unwanted judges into other teams' rounds
- **Tier 5 acts as a soft strike** — the 1-5 penalty is so high it almost never places

### Score & Tier Reference

| Internal Score | Tier | Meaning |
|---------------|------|---------|
| 1–1.5 | 1 | Best judges |
| 2–2.5 | 2 | Good judges |
| 3–3.5 | 3 | Average judges |
| 4–4.5 | 4 | Below average |
| 5–5.5 | 5 | Worst judges |
| 6 | S | Strike |
| 7 | C | Conflict |

---

## How to Implement

### Prerequisites
- Python 3.10+
- A Discord bot token ([Discord Developer Portal](https://discord.com/developers/applications))
  - **Message Content** privileged intent must be enabled
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

### Project Structure

```
prefessor-judge/
├── pref-calculator/
│   ├── main.py                 # Discord bot entry point + all UI/state logic
│   ├── csv_parser.py           # Parse tournament judge CSV files
│   ├── csv_writer.py           # Write output CSV with tier assignments
│   ├── name_matcher.py         # Fuzzy match CSV names to Notion database
│   ├── notion_reader.py        # Fetch absolute scores from Notion
│   ├── pairwise_ranker.py      # Elo + adaptive Swiss pairwise ranking
│   ├── tier_assigner.py        # Core tier assignment algorithm
│   ├── judge_scraper.py        # Tabroom.com paradigm scraper
│   ├── tabroom_auth.py         # Tabroom.com authentication client
│   ├── tabroom_cache.py        # In-memory cache for paradigm data
│   ├── README.md               # Algorithm documentation
│   └── requirements.txt        # Python dependencies
├── Procfile                    # Railway deployment
├── railway.toml                # Railway config
├── requirements.txt            # Root requirements
├── run_bot.ps1                 # PowerShell launcher
└── .gitignore
```

### Architecture

The bot runs as a single Discord client (`main.py`, ~1500 lines) that manages per-channel sessions via a state machine:

```
awaiting_csv → awaiting_rating_range → awaiting_source_choice →
awaiting_unmatched_choice → prompting_scores / comparing →
reviewing → awaiting_quota_mode → awaiting_quotas → done
```

All user-facing choice prompts use `discord.ui.View` subclasses with buttons. Button callbacks edit the original message (no duplicate sends). Text input is only used for quota numbers and CSV uploads.

**Score normalization:** All user input scores are normalized to an internal [1.0, 5.0] scale at the input boundary (`_normalize_score()`). Strike = 6.0, Conflict = 7.0 internally. This means `tier_assigner.py` and `pairwise_ranker.py` never need to know about the tournament's rating range.

### Key Modules

| Module | Purpose |
|--------|---------|
| `main.py` | Discord bot, UI views, state machine, session management |
| `pairwise_ranker.py` | Elo-based pairwise ranking with Swiss pairing |
| `tier_assigner.py` | Multi-phase tier assignment algorithm |
| `csv_parser.py` | Auto-detects CSV format, parses judge dicts |
| `name_matcher.py` | Fuzzy matching (threshold ≥ 85, Unicode normalization) |
| `notion_reader.py` | Fetches judge scores from Notion database |
| `judge_scraper.py` | Scrapes Tabroom.com paradigm pages |
| `tabroom_auth.py` | Tabroom.com session authentication |
| `tabroom_cache.py` | In-memory paradigm cache (1-hour TTL) |

See [`pref-calculator/README.md`](pref-calculator/README.md) for detailed algorithm documentation (pairwise ranking, tier assignment, score normalization).

---

## Changelog

### v4 — Configurable Rating Scale & Button UI (2026-03-07)
- **Configurable rating scale** — Choose 1–5, 1–6, 1–7, or custom max; all scores normalized to internal 1–5 scale
- **Pre-filled CSV support** — Existing ratings (numbers, S, C) honored as anchors; fully pre-filled sheets skip to quotas
- **Button-based prompts** — Rating source, unmatched choice, and rating scale all use interactive buttons (no typing)
- **Conflict support everywhere** — Conflict buttons in pairwise, direct rating, dropdowns, and re-score modal
- **Output labels** — CSV output uses `C` for conflict and `S` for strike
- **Scraper refactor** — `tabroom_scraper.py` split into `judge_scraper.py` + `tabroom_auth.py`
- **Message deduplication** — Button callbacks edit original messages instead of sending duplicates

### v3 — Adaptive Pairwise & Guaranteed Quotas (2026-03-05)
- **Rank from scratch** mode — rate all judges fresh without Notion data
- **Pairwise comparison** with Elo + adaptive Swiss pairing (6 rounds, ~250 comparisons for 85 judges)
- **Hybrid rating** — direct rating dropdowns during pairwise comparison
- **Guaranteed tier quotas** — 3-phase algorithm (optimal partition → flexible assignment → greedy fallback)
- **Infeasibility only from strikes** — algorithm shuffles judges between any tiers to meet quotas
- **Improved name matching** — case-insensitive, Unicode stripping, apostrophe normalization
- **No view timeouts** — buttons stay active as long as the bot is running
- **Resume command** — type `resume` to get fresh buttons
- **Railway deployment** — Procfile and railway.toml for cloud hosting

### v2 — Interactive UI & Judge Comparison (2026-03-05)
- Rewrote Discord bot with interactive components (buttons, select menus, modals)
- Added ScoringView, CompareSelectView, ReviewView
- Added Tabroom scraper with paradigm cache (1-hour TTL)
- Rich Discord embeds with consistent color-coded styling

### v1 — Initial Release (2026-03-03 to 2026-03-04)
- Pref calculator with tier assignment algorithm
- Notion database integration for absolute judge scores
- Fuzzy name matching between CSV and Notion
- Discord bot with text-based workflow
- Support for both round count and judge count quota modes
- CSV format auto-detection (First/Last vs Name columns)
