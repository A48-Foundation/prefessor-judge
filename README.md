# Prefessor Judge 🎓⚖️

A tournament judge preference sheet generator for the A48 debate program. Built as a Discord bot ("Prefessor Judge") that automates the process of ranking judges for upcoming tournaments.

## Overview

Prefessor Judge has three components:

1. **Absolute Ranking Database** — Takes CSV input of judges and rankings from past tournaments, stores absolute scores in a Notion database.
2. **Pref Calculator** — Given a list of judges for an upcoming tournament and tier quotas, algorithmically assigns optimal tier rankings (1–5, Strike, Conflict) that satisfy round/judge count requirements.
3. **Discord Bot UI** — Users interact with Prefessor Judge through Discord: upload a CSV, score unknown judges with Tabroom paradigm data, review/edit scores, set quotas, and receive a filled pref sheet.

## Features

### Interactive Discord Bot
- **Rich embeds** — All messages use Discord embeds with color-coded status indicators
- **Button-based scoring** — Score judges 1–7 with a single click instead of typing numbers
- **Navigation controls** — Previous / Next / Skip buttons to move between judges
- **Judge comparison** — Side-by-side paradigm comparison using the 🔍 Compare button:
  - Select any judge from a dropdown
  - View both judges' paradigm philosophy, school, rounds, and existing scores in parallel embeds
  - Make more informed scoring decisions based on Tabroom data
- **Review & Edit** — After scoring all judges, see a summary and change any score before proceeding
- **Quota mode buttons** — Choose between round count and judge count quotas with a button press

### Tabroom Integration
- Authenticates with a Tabroom.com account to fetch judge paradigm data
- Searches judges by name and scrapes their philosophy/judging approach
- Pre-fetches paradigms for all unmatched judges when a CSV is uploaded
- In-memory cache (1-hour TTL) prevents redundant scraping
- Paradigm text is displayed directly in Discord embeds with "View full paradigm" links

### Tier Assignment Algorithm
- Maps absolute scores (1–7) to natural tiers (1–5, Strike, Conflict)
- Adjusts assignments to satisfy min/max quota constraints per tier
- Supports both **round count** and **judge count** quota modes
- Handles boundary judges (scores ending in .5) and tier-5 stickiness
- Post-stabilization swap pass to keep low-quality judges in appropriate tiers

## Project Structure

```
prefessor-judge/
├── pref-calculator/
│   ├── bot.py                 # Discord bot with interactive UI
│   ├── main.py                # CLI version (standalone)
│   ├── csv_parser.py          # Parse tournament judge CSV files
│   ├── csv_writer.py          # Write output CSV with tier assignments
│   ├── name_matcher.py        # Fuzzy match CSV names to Notion database
│   ├── notion_reader.py       # Fetch absolute scores from Notion
│   ├── score_prompter.py      # CLI score prompting for unknown judges
│   ├── tier_assigner.py       # Core tier assignment algorithm
│   ├── tabroom_scraper.py     # Tabroom.com paradigm scraper
│   ├── tabroom_cache.py       # In-memory cache for paradigm data
│   ├── requirements.txt       # Python dependencies
│   └── generate_test_data.py  # Test data generator
├── run_bot.ps1                # PowerShell launcher for the bot
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
python bot.py
```

Or use the PowerShell launcher:

```powershell
.\run_bot.ps1
```

### Running the CLI Version

```bash
cd pref-calculator
python main.py path/to/tournament.csv
```

## Discord Bot Usage

1. **Start a session** — Mention the bot: `@Prefessor Judge do prefs`
2. **Upload CSV** — Attach a tournament judge CSV file (columns: `Name, School, Rounds, Your Rating` or `First, Last, School, Online, Rounds, Rating`)
3. **Score unknown judges** — For judges not found in the Notion database:
   - View the judge's info and Tabroom paradigm in an embed
   - Click a score button (1–7) or use navigation buttons
   - Use **🔍 Compare** to view two judges side-by-side
   - Use **◀ Previous** to go back and change a score
4. **Review scores** — See a summary of all scored judges; use the dropdown to edit any score
5. **Set quotas** — Choose quota mode (rounds or judges), then enter min/max for each tier
6. **Get results** — Receive a tier assignment report and the filled CSV file

Type `cancel` at any time to abort the workflow.

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
