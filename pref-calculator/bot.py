"""Prefessor Judge - Discord Bot.

A Discord bot that runs the pref sheet generator through chat.
Interactive UI with buttons, embeds, judge comparison, and review/edit.

Flow: user uploads CSV → bot matches judges → interactive scoring with
compare feature → review & edit → quota mode → tier quotas → output CSV.
"""
import csv as csv_mod
import io
import os
import sys
import tempfile
import urllib.parse

import discord
from discord import ui
from dotenv import load_dotenv

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "pref-calculator"))
from csv_parser import parse_tournament_csv
from notion_reader import fetch_notion_judges
from name_matcher import match_judges
from tier_assigner import assign_tiers, format_report
from csv_writer import write_output_csv
from tabroom_scraper import TabroomScraper
from tabroom_cache import TabroomCache

load_dotenv()

intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)

# Shared Tabroom scraper and cache (initialized on ready)
tabroom_scraper: TabroomScraper | None = None
tabroom_cache = TabroomCache()

# Per-channel session state
sessions: dict[int, "PrefSession"] = {}

EMBED_COLOR = 0x5865F2  # Discord blurple
WARN_COLOR = 0xFEE75C
SUCCESS_COLOR = 0x57F287
ERROR_COLOR = 0xED4245


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def tabroom_paradigm_url(name: str) -> str:
    """Build a Tabroom paradigm search URL from a judge name."""
    if ", " in name:
        last, first = name.split(", ", 1)
    else:
        parts = name.split()
        first = parts[0] if parts else ""
        last = " ".join(parts[1:]) if len(parts) > 1 else ""
    params = urllib.parse.urlencode({"search_first": first.strip(), "search_last": last.strip()})
    return f"https://www.tabroom.com/index/paradigm.mhtml?{params}"


def truncate(text: str, limit: int = 500) -> str:
    if not text:
        return "*No paradigm available*"
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0] + "…"


def parse_quota_input(text: str) -> dict | None:
    text = text.strip()
    if not text or text == "skip" or text == "-":
        return None
    parts = text.split(",")
    q: dict[str, int] = {}
    if len(parts) >= 1 and parts[0].strip() not in ("-", ""):
        q["min"] = int(parts[0].strip())
    if len(parts) >= 2 and parts[1].strip() not in ("-", ""):
        q["max"] = int(parts[1].strip())
    return q if q else None


def build_judge_embed(judge: dict, paradigm: dict | None, *, score: float | None = None,
                      index: int | None = None, total: int | None = None) -> discord.Embed:
    """Build a rich embed card for a single judge."""
    title = judge["name"]
    if index is not None and total is not None:
        title = f"Judge {index}/{total} — {judge['name']}"

    embed = discord.Embed(title=title, color=EMBED_COLOR)
    embed.add_field(name="🏫 School", value=judge.get("school") or "Unknown", inline=True)
    embed.add_field(name="🔄 Rounds", value=str(judge.get("rounds", "?")), inline=True)

    if score is not None:
        label = {6: "Strike", 7: "Conflict"}.get(int(score), str(score))
        embed.add_field(name="⭐ Score", value=label, inline=True)

    url = tabroom_paradigm_url(judge["name"])
    if paradigm and paradigm.get("philosophy"):
        embed.add_field(name="📖 Paradigm", value=truncate(paradigm["philosophy"]), inline=False)
    embed.add_field(name="🔗 Tabroom", value=f"[View full paradigm]({url})", inline=False)

    if index is not None and total is not None:
        embed.set_footer(text=f"Progress: {index}/{total}")
    return embed


def split_name(name: str) -> tuple[str, str]:
    """Split 'Last, First' or 'First Last' into (first, last)."""
    if ", " in name:
        last, first = name.split(", ", 1)
        return first.strip(), last.strip()
    parts = name.split()
    first = parts[0] if parts else ""
    last = " ".join(parts[1:]) if len(parts) > 1 else ""
    return first, last


# ---------------------------------------------------------------------------
# Session
# ---------------------------------------------------------------------------

class PrefSession:
    """Tracks the state of a prefs workflow in a channel."""

    def __init__(self, channel_id: int, user_id: int):
        self.channel_id = channel_id
        self.user_id = user_id
        self.state = "awaiting_csv"
        self.csv_judges: list[dict] = []
        self.matched: list[tuple] = []
        self.unmatched: list[dict] = []
        # scores_map: judge_name -> score  (for unmatched judges)
        self.scores_map: dict[str, float] = {}
        self.current_idx: int = 0
        self.quota_mode: str | None = None
        self.quotas: dict[int, dict] = {}
        self.current_tier: int = 1
        self.notion_judges: dict = {}
        # Paradigm cache references per judge name
        self.paradigms: dict[str, dict | None] = {}


# ---------------------------------------------------------------------------
# Interactive Views
# ---------------------------------------------------------------------------

class ScoreButton(ui.Button):
    """A single score button (1-7)."""

    def __init__(self, score: float, label: str, style: discord.ButtonStyle):
        super().__init__(label=label, style=style, custom_id=f"score_{score}")
        self.score = score

    async def callback(self, interaction: discord.Interaction):
        view: ScoringView = self.view  # type: ignore
        session = sessions.get(interaction.channel_id)
        if not session or interaction.user.id != session.user_id:
            await interaction.response.send_message("Not your session.", ephemeral=True)
            return

        judge = session.unmatched[session.current_idx]
        session.scores_map[judge["name"]] = self.score
        session.current_idx += 1

        if session.current_idx < len(session.unmatched):
            await view.show_judge(interaction)
        else:
            await view.finish_scoring(interaction)


class ScoringView(ui.View):
    """Interactive scoring panel for unknown judges."""

    def __init__(self, session: PrefSession):
        super().__init__(timeout=600)
        self.session = session
        self._add_score_buttons()

    def _add_score_buttons(self):
        styles = {
            1: discord.ButtonStyle.success,
            2: discord.ButtonStyle.success,
            3: discord.ButtonStyle.primary,
            4: discord.ButtonStyle.primary,
            5: discord.ButtonStyle.secondary,
            6: discord.ButtonStyle.danger,
            7: discord.ButtonStyle.danger,
        }
        labels = {1: "1", 2: "2", 3: "3", 4: "4", 5: "5", 6: "6 Strike", 7: "7 Conflict"}
        for s in range(1, 8):
            self.add_item(ScoreButton(float(s), labels[s], styles[s]))

    @ui.button(label="◀ Previous", style=discord.ButtonStyle.secondary, row=2)
    async def prev_button(self, interaction: discord.Interaction, button: ui.Button):
        session = self.session
        if session.current_idx > 0:
            session.current_idx -= 1
        await self.show_judge(interaction)

    @ui.button(label="⏭ Skip (4.0)", style=discord.ButtonStyle.secondary, row=2)
    async def skip_button(self, interaction: discord.Interaction, button: ui.Button):
        session = self.session
        judge = session.unmatched[session.current_idx]
        session.scores_map[judge["name"]] = 4.0
        session.current_idx += 1
        if session.current_idx < len(session.unmatched):
            await self.show_judge(interaction)
        else:
            await self.finish_scoring(interaction)

    @ui.button(label="🔍 Compare", style=discord.ButtonStyle.primary, row=2)
    async def compare_button(self, interaction: discord.Interaction, button: ui.Button):
        session = self.session
        current_judge = session.unmatched[session.current_idx]
        all_names = [j["name"] for j in session.csv_judges if j["name"] != current_judge["name"]]
        # Discord select max 25 options
        options = [discord.SelectOption(label=n[:100], value=n[:100]) for n in all_names[:25]]
        if not options:
            await interaction.response.send_message("No other judges to compare.", ephemeral=True)
            return
        view = CompareSelectView(session, current_judge, options, parent_view=self)
        await interaction.response.send_message("Pick a judge to compare with:", view=view, ephemeral=True)

    async def show_judge(self, interaction: discord.Interaction):
        """Display the current judge card."""
        session = self.session
        judge = session.unmatched[session.current_idx]
        idx = session.current_idx + 1
        total = len(session.unmatched)
        existing_score = session.scores_map.get(judge["name"])

        # Fetch paradigm (cached)
        paradigm = session.paradigms.get(judge["name"])
        if paradigm is None and tabroom_scraper:
            paradigm = tabroom_cache.get_or_fetch(judge["name"], tabroom_scraper)
            session.paradigms[judge["name"]] = paradigm

        embed = build_judge_embed(judge, paradigm, score=existing_score, index=idx, total=total)
        if existing_score is not None:
            embed.set_footer(text=f"Progress: {idx}/{total} • Previously scored: {existing_score}")

        await interaction.response.edit_message(embed=embed, view=self)

    async def finish_scoring(self, interaction: discord.Interaction):
        """Transition to review step after all judges scored."""
        self.stop()
        session = self.session
        session.state = "reviewing"
        review_view = ReviewView(session)
        embed = review_view.build_summary_embed()
        await interaction.response.edit_message(
            embed=embed, view=review_view,
        )


class CompareSelectView(ui.View):
    """Dropdown to pick a judge for side-by-side comparison."""

    def __init__(self, session: PrefSession, current_judge: dict,
                 options: list[discord.SelectOption], parent_view: ScoringView):
        super().__init__(timeout=120)
        self.session = session
        self.current_judge = current_judge
        self.parent_view = parent_view
        select = ui.Select(placeholder="Select a judge to compare…", options=options,
                           custom_id="compare_select")
        select.callback = self.on_select
        self.add_item(select)

    async def on_select(self, interaction: discord.Interaction):
        selected_name = interaction.data["values"][0]  # type: ignore
        # Find the judge dict
        other = next((j for j in self.session.csv_judges if j["name"] == selected_name), None)
        if not other:
            await interaction.response.send_message("Judge not found.", ephemeral=True)
            return

        # Fetch paradigms for both
        p1 = self.session.paradigms.get(self.current_judge["name"])
        if p1 is None and tabroom_scraper:
            p1 = tabroom_cache.get_or_fetch(self.current_judge["name"], tabroom_scraper)
            self.session.paradigms[self.current_judge["name"]] = p1

        p2 = self.session.paradigms.get(other["name"])
        if p2 is None and tabroom_scraper:
            p2 = tabroom_cache.get_or_fetch(other["name"], tabroom_scraper)
            self.session.paradigms[other["name"]] = p2

        score1 = self.session.scores_map.get(self.current_judge["name"])
        score2 = self.session.scores_map.get(other["name"])

        # Find scores from matched judges (Notion) if not in scores_map
        if score2 is None:
            for csv_j, _, s in self.session.matched:
                if csv_j["name"] == other["name"]:
                    score2 = s
                    break

        embed1 = build_judge_embed(self.current_judge, p1, score=score1)
        embed1.title = f"🅰️ {self.current_judge['name']}"
        embed1.color = 0x5865F2

        embed2 = build_judge_embed(other, p2, score=score2)
        embed2.title = f"🅱️ {other['name']}"
        embed2.color = 0xEB459E

        back_view = BackToScoringView(self.parent_view)
        await interaction.response.edit_message(
            content="**Side-by-side comparison:**",
            embeds=[embed1, embed2],
            view=back_view,
        )


class BackToScoringView(ui.View):
    """Simple view with a 'Back' button to return to scoring."""

    def __init__(self, parent_view: ScoringView):
        super().__init__(timeout=120)
        self.parent_view = parent_view

    @ui.button(label="◀ Back to Scoring", style=discord.ButtonStyle.primary)
    async def back(self, interaction: discord.Interaction, button: ui.Button):
        session = self.parent_view.session
        judge = session.unmatched[session.current_idx]
        paradigm = session.paradigms.get(judge["name"])
        idx = session.current_idx + 1
        total = len(session.unmatched)
        embed = build_judge_embed(judge, paradigm, score=session.scores_map.get(judge["name"]),
                                  index=idx, total=total)
        await interaction.response.edit_message(content=None, embeds=[embed], view=self.parent_view)


# ---------------------------------------------------------------------------
# Review View
# ---------------------------------------------------------------------------

class ReviewEditSelect(ui.Select):
    """Dropdown to pick a judge to re-score during review."""

    def __init__(self, session: PrefSession):
        self.session = session
        options = []
        for j in session.unmatched:
            score = session.scores_map.get(j["name"], 4.0)
            label = f"{j['name']} — Score: {score}"
            options.append(discord.SelectOption(label=label[:100], value=j["name"][:100]))
        super().__init__(placeholder="Select a judge to re-score…",
                         options=options[:25], custom_id="review_select")

    async def callback(self, interaction: discord.Interaction):
        selected = interaction.data["values"][0]  # type: ignore
        judge = next((j for j in self.session.unmatched if j["name"] == selected), None)
        if not judge:
            await interaction.response.send_message("Judge not found.", ephemeral=True)
            return
        # Show re-score modal
        modal = ReScoreModal(self.session, judge)
        await interaction.response.send_modal(modal)


class ReScoreModal(ui.Modal, title="Re-score Judge"):
    """Modal popup to enter a new score for a judge."""
    score_input = ui.TextInput(label="Score (1-7, 0.5 increments)", placeholder="e.g. 3 or 3.5",
                               max_length=4, required=True)

    def __init__(self, session: PrefSession, judge: dict):
        super().__init__()
        self.session = session
        self.judge = judge
        current = session.scores_map.get(judge["name"], 4.0)
        self.score_input.default = str(current)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            score = float(self.score_input.value.strip())
            if score < 1 or score > 7:
                await interaction.response.send_message("Score must be 1-7.", ephemeral=True)
                return
            score = round(score * 2) / 2
        except ValueError:
            await interaction.response.send_message("Invalid number.", ephemeral=True)
            return

        self.session.scores_map[self.judge["name"]] = score
        # Refresh the review summary
        view: ReviewView = self.session._review_view  # type: ignore
        embed = view.build_summary_embed()
        await interaction.response.edit_message(embed=embed, view=view)


class ReviewView(ui.View):
    """Summary of all scored judges with option to edit before proceeding."""

    def __init__(self, session: PrefSession):
        super().__init__(timeout=600)
        self.session = session
        session._review_view = self  # back-reference for modal refresh
        if session.unmatched:
            self.add_item(ReviewEditSelect(session))

    def build_summary_embed(self) -> discord.Embed:
        embed = discord.Embed(title="📋 Score Review", color=SUCCESS_COLOR,
                              description="Review your scores. Use the dropdown to change any score, "
                                          "then press **Confirm & Continue**.")
        lines = []
        for j in self.session.unmatched:
            score = self.session.scores_map.get(j["name"], 4.0)
            label = {6.0: "Strike", 7.0: "Conflict"}.get(score, str(score))
            lines.append(f"• **{j['name']}** ({j['school']}) — {label}")
        embed.add_field(name="Scored Judges", value="\n".join(lines) or "None", inline=False)
        return embed

    @ui.button(label="✅ Confirm & Continue", style=discord.ButtonStyle.success, row=2)
    async def confirm(self, interaction: discord.Interaction, button: ui.Button):
        self.stop()
        session = self.session
        session.state = "awaiting_quota_mode"
        embed = discord.Embed(
            title="⚖️ Quota Mode",
            description="How does this tournament measure tier quotas?",
            color=EMBED_COLOR,
        )
        embed.add_field(name="Option 1", value="Round count (total available rounds per tier)", inline=False)
        embed.add_field(name="Option 2", value="Judge count (number of judges per tier)", inline=False)
        view = QuotaModeView(session)
        await interaction.response.edit_message(embed=embed, view=view)


# ---------------------------------------------------------------------------
# Quota Views
# ---------------------------------------------------------------------------

class QuotaModeView(ui.View):
    """Two buttons for selecting quota mode."""

    def __init__(self, session: PrefSession):
        super().__init__(timeout=300)
        self.session = session

    @ui.button(label="1️⃣ Round Count", style=discord.ButtonStyle.primary)
    async def rounds(self, interaction: discord.Interaction, button: ui.Button):
        self.session.quota_mode = "rounds"
        self.stop()
        await self._ask_quotas(interaction)

    @ui.button(label="2️⃣ Judge Count", style=discord.ButtonStyle.primary)
    async def judges(self, interaction: discord.Interaction, button: ui.Button):
        self.session.quota_mode = "judges"
        self.stop()
        await self._ask_quotas(interaction)

    async def _ask_quotas(self, interaction: discord.Interaction):
        session = self.session
        session.state = "awaiting_quotas"
        session.current_tier = 1
        unit = "judges" if session.quota_mode == "judges" else "rounds"
        embed = discord.Embed(
            title="📝 Tier Quotas",
            description=f"Enter **{unit}** quotas for each tier.\n"
                        f"Format: `min,max` (use `-` for no limit, `skip` to skip)\n\n"
                        f"Respond with the quota for **Tier 1**:",
            color=EMBED_COLOR,
        )
        embed.set_footer(text="Example: 6,- means min 6, no max")
        await interaction.response.edit_message(embed=embed, view=None)


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------

@client.event
async def on_ready():
    global tabroom_scraper
    print(f"Prefessor Judge is online as {client.user}", flush=True)
    # Initialize Tabroom scraper
    tabroom_scraper = TabroomScraper()
    tabroom_scraper.login()


@client.event
async def on_message(message: discord.Message):
    if message.author == client.user:
        return

    channel_id = message.channel.id
    session = sessions.get(channel_id)

    # Start new workflow
    if client.user.mentioned_in(message) and not session:
        content = message.content.lower()
        if any(kw in content for kw in ("pref", "judge", "rank", "tournament", "hello", "hi")):
            sessions[channel_id] = PrefSession(channel_id, message.author.id)
            embed = discord.Embed(
                title="📋 Prefessor Judge",
                description="Let's do prefs! Upload the tournament judge CSV file.\n\n"
                            "Expected columns: `Name, School, Rounds, Your Rating`\n"
                            "(or `First, Last, School, Online, Rounds, Rating`)",
                color=EMBED_COLOR,
            )
            embed.set_footer(text="Type 'cancel' at any time to abort.")
            await message.channel.send(embed=embed)
            return
        else:
            embed = discord.Embed(
                title="👋 Prefessor Judge",
                description='Mention me and say something like **"do prefs"** to start!',
                color=EMBED_COLOR,
            )
            await message.channel.send(embed=embed)
            return

    if not session:
        return
    if message.author.id != session.user_id:
        return

    # Cancel
    if message.content.strip().lower() == "cancel":
        del sessions[channel_id]
        embed = discord.Embed(title="❌ Cancelled", description="Prefs workflow cancelled.",
                              color=ERROR_COLOR)
        await message.channel.send(embed=embed)
        return

    try:
        await handle_state(message, session)
    except Exception as e:
        await message.channel.send(f"⚠️ Error: {e}")
        import traceback; traceback.print_exc()
        sessions.pop(channel_id, None)


# ---------------------------------------------------------------------------
# State Machine
# ---------------------------------------------------------------------------

async def handle_state(message: discord.Message, session: PrefSession):
    channel = message.channel

    # --- Awaiting CSV ---
    if session.state == "awaiting_csv":
        if not message.attachments:
            await channel.send(embed=discord.Embed(
                description="Please upload a CSV file to continue.",
                color=WARN_COLOR))
            return

        attachment = message.attachments[0]
        if not attachment.filename.endswith(".csv"):
            await channel.send(embed=discord.Embed(
                description="That doesn't look like a CSV. Please upload a `.csv` file.",
                color=ERROR_COLOR))
            return

        csv_bytes = await attachment.read()
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".csv", mode="wb")
        tmp.write(csv_bytes)
        tmp.close()
        try:
            session.csv_judges = parse_tournament_csv(tmp.name)
        finally:
            os.unlink(tmp.name)

        # Fetch Notion data
        status_msg = await channel.send(embed=discord.Embed(
            description=f"✅ Loaded **{len(session.csv_judges)}** judges from `{attachment.filename}`.\n"
                        "🔍 Fetching absolute scores from Notion…",
            color=EMBED_COLOR))

        session.notion_judges = fetch_notion_judges()
        session.matched, session.unmatched = match_judges(session.csv_judges, session.notion_judges)

        summary = discord.Embed(title="📊 Match Results", color=EMBED_COLOR)
        summary.add_field(name="✅ Matched", value=str(len(session.matched)), inline=True)
        summary.add_field(name="❓ Unmatched", value=str(len(session.unmatched)), inline=True)
        summary.add_field(name="📚 Notion DB", value=str(len(session.notion_judges)), inline=True)
        await channel.send(embed=summary)

        if session.unmatched:
            session.state = "prompting_scores"
            session.current_idx = 0

            # Pre-fetch paradigms in background for all unmatched judges
            if tabroom_scraper:
                loading = await channel.send(embed=discord.Embed(
                    description="🌐 Fetching Tabroom paradigms for unmatched judges…",
                    color=EMBED_COLOR))
                for j in session.unmatched:
                    p = tabroom_cache.get_or_fetch(j["name"], tabroom_scraper)
                    session.paradigms[j["name"]] = p
                await loading.delete()

            # Show first judge with interactive scoring
            judge = session.unmatched[0]
            paradigm = session.paradigms.get(judge["name"])
            embed = build_judge_embed(judge, paradigm, index=1, total=len(session.unmatched))
            view = ScoringView(session)
            intro = discord.Embed(
                title="🎯 Score Unknown Judges",
                description=f"**{len(session.unmatched)}** judges need scores.\n"
                            "Use the buttons below to score each judge (1-7).\n"
                            "• **1** = Best  • **5** = Worst  • **6** = Strike  • **7** = Conflict\n"
                            "• Use **Compare** to view two judges side-by-side\n"
                            "• Use **Previous** to go back and change a score",
                color=EMBED_COLOR,
            )
            await channel.send(embed=intro)
            await channel.send(embed=embed, view=view)
        else:
            session.state = "awaiting_quota_mode"
            await send_quota_mode_prompt(channel, session)

    # --- Awaiting quota text input ---
    elif session.state == "awaiting_quotas":
        text = message.content.strip()
        try:
            quota = parse_quota_input(text)
            if quota:
                session.quotas[session.current_tier] = quota
        except ValueError:
            await channel.send(embed=discord.Embed(
                description="Invalid format. Use: `min,max` (e.g., `6,-` or `-,3` or `5,10`)",
                color=ERROR_COLOR))
            return

        session.current_tier += 1
        if session.current_tier <= 6:
            label = "S (strike)" if session.current_tier == 6 else str(session.current_tier)
            embed = discord.Embed(
                description=f"**Tier {label}** [min,max]:",
                color=EMBED_COLOR,
            )
            await channel.send(embed=embed)
        else:
            await run_assignment(channel, session)

    # --- Done state —
    elif session.state == "done":
        if client.user.mentioned_in(message):
            sessions.pop(channel.id, None)
            sessions[channel.id] = PrefSession(channel.id, message.author.id)
            embed = discord.Embed(
                title="📋 Prefessor Judge — New Session",
                description="Upload a tournament CSV to begin.",
                color=EMBED_COLOR,
            )
            await channel.send(embed=embed)


async def send_quota_mode_prompt(channel, session: PrefSession):
    """Send quota mode selection as interactive buttons."""
    embed = discord.Embed(
        title="⚖️ Quota Mode",
        description="How does this tournament measure tier quotas?",
        color=EMBED_COLOR,
    )
    embed.add_field(name="Option 1", value="Round count (total available rounds per tier)", inline=False)
    embed.add_field(name="Option 2", value="Judge count (number of judges per tier)", inline=False)
    view = QuotaModeView(session)
    await channel.send(embed=embed, view=view)


async def run_assignment(channel, session: PrefSession):
    await channel.send(embed=discord.Embed(description="⚙️ Assigning tiers…", color=EMBED_COLOR))

    all_judges = []
    for csv_judge, notion_name, score in session.matched:
        all_judges.append({
            "name": csv_judge["name"],
            "school": csv_judge["school"],
            "rounds": csv_judge["rounds"],
            "score": score if score is not None else 4.0,
            "notion_name": notion_name,
        })
    for judge in session.unmatched:
        score = session.scores_map.get(judge["name"], 4.0)
        all_judges.append({
            "name": judge["name"],
            "school": judge["school"],
            "rounds": judge["rounds"],
            "score": score,
            "notion_name": None,
        })

    assigned, report = assign_tiers(all_judges, session.quotas, session.quota_mode)

    report_text = format_report(report)
    report_embed = discord.Embed(title="📊 Tier Assignment Report", color=EMBED_COLOR,
                                 description=f"```\n{report_text}\n```")

    unmet = [t for t in range(1, 7)
             if t in report and isinstance(report[t], dict) and not report[t].get("met", True)]
    if unmet:
        labels = ["S" if t == 6 else str(t) for t in unmet]
        report_embed.add_field(name="⚠️ Unmet Quotas",
                               value=f"Tier(s): {', '.join(labels)}", inline=False)
    await channel.send(embed=report_embed)

    # Build output CSV
    assigned.sort(key=lambda j: (j["tier"], j["score"]))
    output = io.StringIO()
    writer = csv_mod.writer(output)
    writer.writerow(["First", "Last", "School", "Rounds", "Rating"])
    for judge in assigned:
        tier = judge["tier"]
        rating = "C" if tier == 7 else ("S" if tier == 6 else str(tier))
        first, last = split_name(judge["name"])
        writer.writerow([first, last, judge["school"], judge["rounds"], rating])

    output.seek(0)
    file = discord.File(io.BytesIO(output.getvalue().encode("utf-8")), filename="prefs_output.csv")

    done_embed = discord.Embed(title="✅ Prefs Complete!", color=SUCCESS_COLOR,
                               description="Here's your filled pref sheet.")
    await channel.send(embed=done_embed, file=file)

    session.state = "done"
    sessions.pop(channel.id, None)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    token = os.environ.get("DISCORD_BOT_TOKEN")
    if not token:
        print("Error: DISCORD_BOT_TOKEN not set in .env")
        sys.exit(1)
    client.run(token)
