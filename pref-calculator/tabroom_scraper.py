"""Scrape judge paradigm data from Tabroom.com.

Authenticates with a bot-level Tabroom account, searches for judges,
and fetches paradigm pages (philosophy, record, school).
"""
import os
import re
import httpx
from bs4 import BeautifulSoup
from dotenv import load_dotenv

load_dotenv()

BASE_URL = "https://www.tabroom.com"
LOGIN_PAGE = f"{BASE_URL}/user/login/login.mhtml"
LOGIN_POST = f"{BASE_URL}/user/login/login_save.mhtml"
PARADIGM_SEARCH = f"{BASE_URL}/index/paradigm.mhtml"


class TabroomScraper:
    """Authenticated Tabroom scraper for paradigm data."""

    def __init__(self):
        self._client = httpx.Client(
            follow_redirects=True,
            timeout=30.0,
            headers={"User-Agent": "PrefessorJudge/1.0"},
        )
        self._logged_in = False

    def login(self):
        """Authenticate with Tabroom using credentials from environment."""
        email = os.environ.get("TABROOM_EMAIL", "")
        password = os.environ.get("TABROOM_PASSWORD", "")
        if not email or not password:
            print("[TabroomScraper] TABROOM_EMAIL or TABROOM_PASSWORD not set; skipping login.")
            return False

        # Fetch login page to get salt and sha hidden fields
        resp = self._client.get(LOGIN_PAGE)
        soup = BeautifulSoup(resp.text, "html.parser")
        form = soup.find("form", {"name": "login"})
        if not form:
            print("[TabroomScraper] Could not find login form on Tabroom.")
            return False

        salt_input = form.find("input", {"name": "salt"})
        sha_input = form.find("input", {"name": "sha"})

        payload = {
            "username": email,
            "password": password,
        }
        if salt_input:
            payload["salt"] = salt_input.get("value", "")
        if sha_input:
            payload["sha"] = sha_input.get("value", "")

        login_resp = self._client.post(LOGIN_POST, data=payload)

        # Check if login succeeded by looking for login link absence
        if "Login" not in login_resp.text or "dashboard" in login_resp.url.path.lower():
            self._logged_in = True
            print("[TabroomScraper] Logged in to Tabroom successfully.")
            return True

        # Alternative check: look for the user menu or absence of login form
        check_soup = BeautifulSoup(login_resp.text, "html.parser")
        if check_soup.find("a", href=re.compile(r"/user/login/logout")):
            self._logged_in = True
            print("[TabroomScraper] Logged in to Tabroom successfully.")
            return True

        print("[TabroomScraper] Tabroom login may have failed. Paradigm fetching may be limited.")
        self._logged_in = False
        return False

    @property
    def is_logged_in(self):
        return self._logged_in

    def search_judges(self, first_name: str, last_name: str) -> list[dict]:
        """Search Tabroom for judges matching first/last name.

        Returns list of dicts: [{name, judge_person_id, paradigm_url}, ...]
        """
        params = {"search_first": first_name.strip(), "search_last": last_name.strip()}
        try:
            resp = self._client.get(PARADIGM_SEARCH, params=params)
        except httpx.HTTPError as e:
            print(f"[TabroomScraper] Search error: {e}")
            return []

        soup = BeautifulSoup(resp.text, "html.parser")
        results = []

        # Paradigm search results are links to individual paradigm pages
        # Look for links containing paradigm.mhtml with judge_person_id
        for link in soup.find_all("a", href=re.compile(r"judge_person_id=\d+")):
            href = link.get("href", "")
            match = re.search(r"judge_person_id=(\d+)", href)
            if not match:
                continue
            judge_id = match.group(1)
            name_text = link.get_text(strip=True)
            if not name_text:
                continue
            full_url = href if href.startswith("http") else f"{BASE_URL}{href}"
            results.append({
                "name": name_text,
                "judge_person_id": judge_id,
                "paradigm_url": full_url,
            })

        # Also check if we landed directly on a paradigm page (single result)
        if not results:
            paradigm = self._parse_paradigm_page(soup)
            if paradigm and paradigm.get("name"):
                # Extract judge_person_id from current URL if possible
                url_str = str(resp.url)
                id_match = re.search(r"judge_person_id=(\d+)", url_str)
                paradigm["judge_person_id"] = id_match.group(1) if id_match else ""
                paradigm["paradigm_url"] = url_str
                results.append(paradigm)

        return results

    def fetch_paradigm(self, judge_person_id: str) -> dict | None:
        """Fetch paradigm data for a specific judge.

        Returns dict: {name, school, philosophy, paradigm_url} or None.
        """
        url = f"{PARADIGM_SEARCH}?judge_person_id={judge_person_id}"
        try:
            resp = self._client.get(url)
        except httpx.HTTPError as e:
            print(f"[TabroomScraper] Fetch error for judge {judge_person_id}: {e}")
            return None

        soup = BeautifulSoup(resp.text, "html.parser")
        result = self._parse_paradigm_page(soup)
        if result:
            result["judge_person_id"] = judge_person_id
            result["paradigm_url"] = url
        return result

    def fetch_paradigm_by_name(self, name: str) -> dict | None:
        """Fetch paradigm by hitting the search URL directly.

        Accepts names in "Last, First" or "First Last" format.
        """
        if ", " in name:
            last, first = name.split(", ", 1)
        else:
            parts = name.split()
            first = parts[0] if parts else ""
            last = " ".join(parts[1:]) if len(parts) > 1 else ""

        url = f"{PARADIGM_SEARCH}?search_first={first.strip()}&search_last={last.strip()}"
        try:
            resp = self._client.get(url)
        except httpx.HTTPError as e:
            print(f"[TabroomScraper] Fetch error for {name}: {e}")
            return None

        soup = BeautifulSoup(resp.text, "html.parser")
        result = self._parse_paradigm_page(soup)
        if result:
            result["paradigm_url"] = str(resp.url)
        return result

    def _parse_paradigm_page(self, soup: BeautifulSoup) -> dict | None:
        """Extract paradigm data from a parsed paradigm page."""
        result = {"name": "", "school": "", "philosophy": ""}

        # Judge name — typically in an h4 or h3 or a prominent heading
        for tag in ["h2", "h3", "h4", "h5"]:
            heading = soup.find(tag)
            if heading:
                text = heading.get_text(strip=True)
                if text and len(text) < 100:
                    result["name"] = text
                    break

        # School/affiliation — often near the name
        # Look for text that follows the name or is in a specific class
        affiliation = soup.find(class_=re.compile(r"affil|school|institution", re.I))
        if affiliation:
            result["school"] = affiliation.get_text(strip=True)

        # Paradigm/philosophy text — usually the main body content
        # Look for the paradigm content div/section
        paradigm_div = soup.find(class_=re.compile(r"paradigm|philosophy|ltborderbottom", re.I))
        if paradigm_div:
            result["philosophy"] = paradigm_div.get_text(separator="\n", strip=True)
        else:
            # Fallback: look for the main content area
            main = soup.find(id="content") or soup.find(class_="main")
            if main:
                # Get all text paragraphs
                paragraphs = main.find_all("p")
                if paragraphs:
                    text = "\n".join(p.get_text(strip=True) for p in paragraphs if p.get_text(strip=True))
                    result["philosophy"] = text
                else:
                    # Last resort: get all text from main
                    all_text = main.get_text(separator="\n", strip=True)
                    # Remove common navigation/header text
                    lines = [line.strip() for line in all_text.split("\n") if line.strip()]
                    result["philosophy"] = "\n".join(lines[:30])

        # If no meaningful content extracted, indicate that
        if not result["name"] and not result["philosophy"]:
            return None

        return result

    def close(self):
        """Close the HTTP client."""
        self._client.close()
