"""Scrape judge paradigm data from Tabroom.com.

Uses ``TabroomAuth`` for session management and provides methods
to search for judges and fetch their paradigm pages (philosophy,
record, school).
"""
import re
import httpx
from bs4 import BeautifulSoup

from tabroom_auth import TabroomAuth

# ── Tabroom paradigm endpoint ───────────────────────────────────────────────
BASE_URL = "https://www.tabroom.com"                        # Root URL for constructing full paradigm links
PARADIGM_SEARCH = f"{BASE_URL}/index/paradigm.mhtml"        # Paradigm search/view endpoint


class TabroomScraper:
    """Paradigm scraper for Tabroom.com.

    Delegates authentication to a ``TabroomAuth`` instance (which can
    optionally be shared with other scrapers).  All HTTP requests are
    issued through the authenticated client exposed by ``TabroomAuth``.
    """

    # ── Initialisation ──────────────────────────────────────────────────────
    def __init__(self, auth: TabroomAuth | None = None):
        """Initialise the scraper.

        Args:
            auth: An existing ``TabroomAuth`` instance.  If *None*, a new
                  one is created internally (call ``login()`` to authenticate).
        """
        self._auth = auth or TabroomAuth()
        self._client = self._auth.client  # Convenience alias for the HTTP client

    # ── Authentication (delegates to TabroomAuth) ───────────────────────────
    def login(self) -> bool:
        """Authenticate with Tabroom via the underlying ``TabroomAuth``.

        Returns:
            True if login succeeded, False otherwise.
        """
        return self._auth.login()

    @property
    def is_logged_in(self) -> bool:
        """Whether the scraper currently holds a valid Tabroom session."""
        return self._auth.is_logged_in

    @property
    def auth(self) -> TabroomAuth:
        """Expose the ``TabroomAuth`` instance for sharing with other scrapers."""
        return self._auth

    # ── Judge search & paradigm fetching ─────────────────────────────────────
    def search_judges(self, first_name: str, last_name: str) -> list[dict]:
        """Search Tabroom for judges matching first/last name.

        Sends a GET request to the paradigm search endpoint with
        ``search_first`` and ``search_last`` query parameters.  The response
        may contain a list of matching judges OR redirect straight to a
        single paradigm page if there is exactly one match.

        Returns:
            A list of dicts, each containing ``name``,
            ``judge_person_id``, and ``paradigm_url``.
        """
        params = {"search_first": first_name.strip(), "search_last": last_name.strip()}
        try:
            resp = self._client.get(PARADIGM_SEARCH, params=params)
        except httpx.HTTPError as e:
            print(f"[TabroomScraper] Search error: {e}")
            return []

        soup = BeautifulSoup(resp.text, "html.parser")
        results = []

        # Paradigm search results are rendered as anchor tags whose hrefs
        # include a ``judge_person_id`` query parameter.  Iterate over all
        # matching links and collect the relevant metadata.
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

        # If no result links were found the server may have redirected us
        # directly to the single matching paradigm page.  Try parsing it.
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
        """Fetch the full paradigm page for a judge identified by their ID.

        Builds the paradigm URL from ``judge_person_id`` and delegates
        HTML parsing to ``_parse_paradigm_page``.

        Returns:
            A dict with ``name``, ``school``, ``philosophy``,
            ``judge_person_id``, and ``paradigm_url``; or *None* if the
            page could not be fetched or contained no useful data.
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
        """Convenience wrapper: search for a judge by full name string.

        Accepts names in ``"Last, First"`` or ``"First Last"`` format,
        splits them into first/last components, then issues a paradigm
        search request identical to ``search_judges``.  If the search
        lands on a paradigm page the data is parsed and returned.

        Returns:
            Parsed paradigm dict or *None*.
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

    # ── Internal HTML parsing helpers ──────────────────────────────────────
    def _parse_paradigm_page(self, soup: BeautifulSoup) -> dict | None:
        """Extract paradigm data from a parsed paradigm page.

        Employs a series of heuristics to locate the judge's name,
        school/affiliation, and philosophy text within the HTML.  The
        Tabroom markup is not perfectly consistent, so multiple fallback
        strategies are tried in order.

        Returns:
            A dict ``{name, school, philosophy}`` or *None* if neither a
            name nor philosophy text could be found.
        """
        result = {"name": "", "school": "", "philosophy": ""}

        # --- Judge name: check prominent heading tags (h2-h5) ---
        for tag in ["h2", "h3", "h4", "h5"]:
            heading = soup.find(tag)
            if heading:
                text = heading.get_text(strip=True)
                if text and len(text) < 100:
                    result["name"] = text
                    break

        # --- School / affiliation: look for a CSS class containing
        #     "affil", "school", or "institution" ---
        affiliation = soup.find(class_=re.compile(r"affil|school|institution", re.I))
        if affiliation:
            result["school"] = affiliation.get_text(strip=True)

        # --- Philosophy / paradigm body text ---
        # Primary: a container whose CSS class matches paradigm-related names.
        paradigm_div = soup.find(class_=re.compile(r"paradigm|philosophy|ltborderbottom", re.I))
        if paradigm_div:
            result["philosophy"] = paradigm_div.get_text(separator="\n", strip=True)
        else:
            # Fallback: grab the #content or .main container and extract
            # either its <p> tags or, as a last resort, raw text.
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

        # If neither name nor philosophy was found the page likely isn't
        # a valid paradigm page — return None to signal the caller.
        if not result["name"] and not result["philosophy"]:
            return None

        return result

    # ── Cleanup ──────────────────────────────────────────────────────────────
    def close(self):
        """Close the underlying HTTP client and release its resources."""
        self._auth.close()
