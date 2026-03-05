"""Prefessor Judge - Discord Bot.

A Discord bot that runs the pref sheet generator through chat.
Flow: user uploads CSV → bot asks quota mode → bot asks tier quotas →
bot asks for unknown judge scores → bot outputs filled CSV.
"""
import os
import sys
import io
import asyncio
import tempfile
import urllib.parse
import discord
from discord import ui
from dotenv import load_dotenv

# Add pref-calculator to path so we can import modules
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "pref-calculator"))
from csv_parser import parse_tournament_csv
from notion_reader import fetch_notion_judges
from name_matcher import match_judges
from tier_assigner import assign_tiers, format_report
from csv_writer import write_output_csv

load_dotenv()

intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)

# Per-channel session state
sessions = {}


class PrefSession:
    """Tracks the state of a prefs workflow in a channel."""
    def __init__(self, channel_id, user_id):
        self.channel_id = channel_id
        self.user_id = user_id
        self.state = "awaiting_csv"
        self.csv_judges = None
        self.matched = None
        self.unmatched = None
        self.prompted_scores = []
        self.skipped_judges = []
        self.current_unmatched_idx = 0
        self.all_judges = None
        self.quota_mode = None
        self.quotas = {}
        self.current_tier = 1
        self.notion_judges = None


def parse_quota_input(text):
    """Parse a quota string like '6,-' or '-,3' or '5,10' into a dict."""
    text = text.strip()
    if not text or text == "skip" or text == "-":
        return None
    parts = text.split(",")
    q = {}
    if len(parts) >= 1 and parts[0].strip() not in ("-", ""):
        q["min"] = int(parts[0].strip())
    if len(parts) >= 2 and parts[1].strip() not in ("-", ""):
        q["max"] = int(parts[1].strip())
    return q if q else None


def tabroom_paradigm_url(name):
    """Build a Tabroom paradigm search URL from a judge name (Last, First)."""
    if ", " in name:
        last, first = name.split(", ", 1)
    else:
        parts = name.split()
        first = parts[0] if parts else ""
        last = " ".join(parts[1:]) if len(parts) > 1 else ""
    params = urllib.parse.urlencode({"search_first": first.strip(), "search_last": last.strip()})
    return f"https://www.tabroom.com/index/paradigm.mhtml?{params}"


@client.event
async def on_ready():
    print(f"Prefessor Judge is online as {client.user}", flush=True)


@client.event
async def on_message(message):
    if message.author == client.user:
        return

    # Debug: log all messages
    print(f"[MSG] #{message.channel}: {message.author}: {message.content[:100]}")
    print(f"  Mentions bot: {client.user.mentioned_in(message)}")

    channel_id = message.channel.id
    session = sessions.get(channel_id)

    # Check if user is starting a new prefs workflow
    if client.user.mentioned_in(message) and not session:
        content = message.content.lower()
        print(f"  Content check: {content}")
        if "pref" in content or "judge" in content or "rank" in content or "tournament" in content or "hello" in content or "hi" in content:
            sessions[channel_id] = PrefSession(channel_id, message.author.id)
            await message.channel.send(
                "📋 **Prefessor Judge** here! Let's do prefs.\n\n"
                "Upload the tournament judge CSV file (columns: `Name, School, Rounds, Your Rating`)."
            )
            return
        else:
            await message.channel.send(
                "👋 I'm **Prefessor Judge**! Mention me and say something like "
                "\"do prefs\" to start a prefs workflow."
            )
            return

    # If no active session, ignore
    if not session:
        return

    # Only respond to the user who started the session
    if message.author.id != session.user_id:
        return

    # Cancel command
    if message.content.strip().lower() == "cancel":
        del sessions[channel_id]
        await message.channel.send("❌ Prefs workflow cancelled.")
        return

    # State machine
    try:
        await handle_state(message, session)
    except Exception as e:
        await message.channel.send(f"⚠️ Error: {e}")
        del sessions[channel_id]


async def handle_state(message, session):
    channel = message.channel

    # --- STATE: Awaiting CSV upload ---
    if session.state == "awaiting_csv":
        if not message.attachments:
            await channel.send("Please upload a CSV file to continue.")
            return

        attachment = message.attachments[0]
        if not attachment.filename.endswith(".csv"):
            await channel.send("That doesn't look like a CSV file. Please upload a `.csv` file.")
            return

        # Download and parse CSV
        csv_bytes = await attachment.read()
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".csv", mode="wb")
        tmp.write(csv_bytes)
        tmp.close()

        try:
            session.csv_judges = parse_tournament_csv(tmp.name)
        finally:
            os.unlink(tmp.name)

        await channel.send(f"✅ Loaded **{len(session.csv_judges)}** judges from `{attachment.filename}`.")

        # Fetch Notion data
        await channel.send("🔍 Fetching absolute scores from Notion...")
        session.notion_judges = fetch_notion_judges()
        await channel.send(f"📊 Found **{len(session.notion_judges)}** judges in the database.")

        # Match names
        session.matched, session.unmatched = match_judges(session.csv_judges, session.notion_judges)
        await channel.send(
            f"🔗 **Matched:** {len(session.matched)} judges\n"
            f"❓ **Unmatched:** {len(session.unmatched)} judges"
        )

        # If there are unmatched judges, offer choice: rate them or skip
        if session.unmatched:
            session.state = "awaiting_unmatched_choice"
            await channel.send(
                f"❓ **{len(session.unmatched)}** judge(s) not found in the database.\n"
                f"**1.** Rate each judge manually\n"
                f"**2.** Skip — leave their ratings empty in the output\n\n"
                f"Enter **1** or **2**:"
            )
        else:
            session.state = "awaiting_quota_mode"
            await ask_quota_mode(channel)

    # --- STATE: Awaiting choice for unmatched judges ---
    elif session.state == "awaiting_unmatched_choice":
        text = message.content.strip()
        if text == "1" or "rate" in text.lower() or "manual" in text.lower():
            session.state = "prompting_scores"
            session.current_unmatched_idx = 0
            judge = session.unmatched[0]
            url = tabroom_paradigm_url(judge["name"])
            await channel.send(
                f"Enter a score from **1-7** (0.5 increments) for each.\n"
                f"6 = Strike, 7 = Conflict (same school)\n\n"
                f"**{judge['name']}** ({judge['school']})\n"
                f"📖 [View Paradigm on Tabroom]({url})"
            )
        elif text == "2" or "skip" in text.lower():
            session.skipped_judges = list(session.unmatched)
            await channel.send(f"⏭️ Skipping {len(session.unmatched)} unmatched judge(s) — they'll have empty ratings.")
            session.state = "awaiting_quota_mode"
            await ask_quota_mode(channel)
        else:
            await channel.send("Please enter **1** (rate manually) or **2** (skip):")

    # --- STATE: Prompting for unknown judge scores ---
    elif session.state == "prompting_scores":
        try:
            score = float(message.content.strip())
            if score < 1 or score > 7:
                await channel.send("Score must be between **1** and **7** (7=conflict). Try again:")
                return
            score = round(score * 2) / 2  # snap to 0.5
        except ValueError:
            await channel.send("Please enter a number (e.g., `3` or `3.5`):")
            return

        judge = session.unmatched[session.current_unmatched_idx]
        session.prompted_scores.append((judge, score))
        session.current_unmatched_idx += 1

        if session.current_unmatched_idx < len(session.unmatched):
            next_judge = session.unmatched[session.current_unmatched_idx]
            url = tabroom_paradigm_url(next_judge["name"])
            await channel.send(
                f"**{next_judge['name']}** ({next_judge['school']})\n"
                f"📖 [View Paradigm on Tabroom]({url})"
            )
        else:
            await channel.send("✅ All judge scores entered!")
            session.state = "awaiting_quota_mode"
            await ask_quota_mode(channel)

    # --- STATE: Awaiting quota mode ---
    elif session.state == "awaiting_quota_mode":
        text = message.content.strip()
        if text == "1" or "round" in text.lower():
            session.quota_mode = "rounds"
        elif text == "2" or "judge" in text.lower():
            session.quota_mode = "judges"
        else:
            await channel.send("Please enter **1** (round count) or **2** (judge count):")
            return

        unit = "judges" if session.quota_mode == "judges" else "rounds"
        session.state = "awaiting_quotas"
        session.current_tier = 1
        await channel.send(
            f"📝 Enter {unit} quotas for each tier.\n"
            f"Format: `min,max` (use `-` for no limit, `skip` to skip)\n\n"
            f"**Tier 1** [min,max]:"
        )

    # --- STATE: Awaiting tier quotas ---
    elif session.state == "awaiting_quotas":
        text = message.content.strip()
        try:
            quota = parse_quota_input(text)
            if quota:
                session.quotas[session.current_tier] = quota
        except ValueError:
            await channel.send("Invalid format. Use: `min,max` (e.g., `6,-` or `-,3` or `5,10`):")
            return

        session.current_tier += 1
        if session.current_tier <= 6:
            label = "S (strike)" if session.current_tier == 6 else str(session.current_tier)
            await channel.send(f"**Tier {label}** [min,max]:")
        else:
            # All quotas collected — run the algorithm
            await run_assignment(channel, session)

    # --- STATE: Done ---
    elif session.state == "done":
        if client.user.mentioned_in(message):
            del sessions[channel.id]
            await channel.send("Starting a new session! Upload a tournament CSV to begin.")
            sessions[channel.id] = PrefSession(channel.id, message.author.id)
            sessions[channel.id].state = "awaiting_csv"


async def ask_quota_mode(channel):
    await channel.send(
        "⚖️ How does this tournament measure tier quotas?\n"
        "**1.** Round count (total available rounds per tier)\n"
        "**2.** Judge count (number of judges per tier)\n\n"
        "Enter **1** or **2**:"
    )


async def run_assignment(channel, session):
    await channel.send("⚙️ Assigning tiers...")

    # Build unified judge list (matched + manually scored)
    all_judges = []
    for csv_judge, notion_name, score in session.matched:
        all_judges.append({
            "name": csv_judge["name"],
            "school": csv_judge["school"],
            "rounds": csv_judge["rounds"],
            "score": score if score is not None else 4.0,
            "notion_name": notion_name,
        })
    for csv_judge, score in session.prompted_scores:
        all_judges.append({
            "name": csv_judge["name"],
            "school": csv_judge["school"],
            "rounds": csv_judge["rounds"],
            "score": score,
            "notion_name": None,
        })

    # Run assignment on judges with scores
    assigned, report = assign_tiers(all_judges, session.quotas, session.quota_mode)

    # Collect skipped judges (empty rating)
    skipped = getattr(session, "skipped_judges", [])

    # Send report
    report_text = format_report(report)
    await channel.send(f"```\nTIER ASSIGNMENT REPORT\n{'='*50}\n{report_text}\n```")
    if skipped:
        await channel.send(f"ℹ️ **{len(skipped)}** judge(s) left with empty ratings.")

    # Check for unmet quotas
    unmet = [t for t in range(1, 7) if t in report and isinstance(report[t], dict) and not report[t].get("met", True)]
    if unmet:
        labels = ["S" if t == 6 else str(t) for t in unmet]
        await channel.send(f"⚠️ Warning: Quotas unmet for tier(s): {', '.join(labels)}")

    # Write output CSV to memory and send as attachment
    assigned.sort(key=lambda j: (j["tier"], j["score"]))
    output = io.StringIO()
    import csv
    writer = csv.writer(output)
    writer.writerow(["First", "Last", "School", "Rounds", "Rating"])
    for judge in assigned:
        tier = judge["tier"]
        rating = "C" if tier == 7 else ("S" if tier == 6 else str(tier))
        name = judge["name"]
        if ", " in name:
            last, first = name.split(", ", 1)
        else:
            parts = name.split()
            first = parts[0] if parts else ""
            last = " ".join(parts[1:]) if len(parts) > 1 else ""
        writer.writerow([first, last, judge["school"], judge["rounds"], rating])
    # Append skipped judges with empty rating
    for judge in skipped:
        name = judge["name"]
        if ", " in name:
            last, first = name.split(", ", 1)
        else:
            parts = name.split()
            first = parts[0] if parts else ""
            last = " ".join(parts[1:]) if len(parts) > 1 else ""
        writer.writerow([first, last, judge["school"], judge["rounds"], ""])

    output.seek(0)
    file = discord.File(io.BytesIO(output.getvalue().encode("utf-8")), filename="prefs_output.csv")
    await channel.send("✅ **Prefs complete!** Here's the output:", file=file)

    # Clean up session
    session.state = "done"
    del sessions[channel.id]


if __name__ == "__main__":
    token = os.environ.get("DISCORD_BOT_TOKEN")
    if not token:
        print("Error: DISCORD_BOT_TOKEN not set in .env")
        sys.exit(1)
    client.run(token)
