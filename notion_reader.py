"""Fetch all judge absolute scores from the Notion database."""
from dotenv import load_dotenv
import os
import httpx


def fetch_notion_judges():
    """Return dict of {name: score} for all judges in Notion. Score may be None."""
    load_dotenv()
    api_key = os.environ["NOTION_API_KEY"]
    db_id = os.environ["NOTION_DATABASE_ID"]
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Notion-Version": "2022-06-28",
        "Content-Type": "application/json",
    }

    all_rows = []
    cursor = None
    while True:
        body = {"page_size": 100}
        if cursor:
            body["start_cursor"] = cursor
        resp = httpx.post(
            f"https://api.notion.com/v1/databases/{db_id}/query",
            headers=headers,
            json=body,
            timeout=30.0,
        )
        resp.raise_for_status()
        data = resp.json()
        all_rows.extend(data.get("results", []))
        if not data.get("has_more"):
            break
        cursor = data.get("next_cursor")

    judges = {}
    for page in all_rows:
        props = page["properties"]
        name_parts = props["Name"]["title"]
        if not name_parts:
            continue
        name = name_parts[0]["plain_text"].strip()
        score = props["Prefs"]["number"]
        judges[name] = score

    return judges
