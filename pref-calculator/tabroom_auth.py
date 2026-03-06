"""Reusable Tabroom.com authentication client.

Provides an authenticated ``httpx.Client`` session that can be shared
across multiple Tabroom scrapers (paradigm, results, entries, etc.).
"""
import os
import re
import httpx
from bs4 import BeautifulSoup
from dotenv import load_dotenv

load_dotenv()

# ── Tabroom authentication endpoints ────────────────────────────────────────
BASE_URL = "https://www.tabroom.com"                        # Root URL for all Tabroom requests
LOGIN_PAGE = f"{BASE_URL}/user/login/login.mhtml"           # GET this page to obtain the login form (salt/sha tokens)
LOGIN_POST = f"{BASE_URL}/user/login/login_save.mhtml"      # POST credentials here to authenticate


class TabroomAuth:
    """Manages an authenticated HTTP session with Tabroom.com.

    Creates a persistent ``httpx.Client`` with cookie storage so that a
    single ``login()`` call is sufficient for all subsequent requests
    made through the same client.  Other scrapers can obtain the
    authenticated client via the ``client`` property and reuse it freely.
    """

    # ── Initialisation ──────────────────────────────────────────────────────
    def __init__(self):
        """Create an unauthenticated HTTP client with sensible defaults."""
        self._client = httpx.Client(
            follow_redirects=True,
            timeout=30.0,
            headers={"User-Agent": "PrefessorJudge/1.0"},
        )
        self._logged_in = False

    # ── Authentication ──────────────────────────────────────────────────────
    def login(self) -> bool:
        """Authenticate with Tabroom using credentials from environment.

        Reads ``TABROOM_EMAIL`` and ``TABROOM_PASSWORD`` from the
        environment.  The login form on Tabroom may include hidden
        ``salt`` and ``sha`` fields; these are forwarded automatically.
        On success the session cookies are stored in ``self._client``
        for subsequent requests.

        Returns:
            True if login succeeded, False otherwise.
        """
        email = os.environ.get("TABROOM_EMAIL", "")
        password = os.environ.get("TABROOM_PASSWORD", "")
        if not email or not password:
            print("[TabroomAuth] TABROOM_EMAIL or TABROOM_PASSWORD not set; skipping login.")
            return False

        # Fetch the login page first so we can extract any hidden CSRF-like
        # tokens ("salt" and "sha" fields) required by the form.
        resp = self._client.get(LOGIN_PAGE)
        soup = BeautifulSoup(resp.text, "html.parser")
        form = soup.find("form", {"name": "login"})
        if not form:
            print("[TabroomAuth] Could not find login form on Tabroom.")
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

        # Heuristic #1: if the response no longer contains a "Login" link or
        # we were redirected to the dashboard, the login succeeded.
        if "Login" not in login_resp.text or "dashboard" in login_resp.url.path.lower():
            self._logged_in = True
            print("[TabroomAuth] Logged in to Tabroom successfully.")
            return True

        # Heuristic #2: a visible logout link means we are authenticated.
        check_soup = BeautifulSoup(login_resp.text, "html.parser")
        if check_soup.find("a", href=re.compile(r"/user/login/logout")):
            self._logged_in = True
            print("[TabroomAuth] Logged in to Tabroom successfully.")
            return True

        print("[TabroomAuth] Tabroom login may have failed. Requests may be limited.")
        self._logged_in = False
        return False

    # ── Public accessors ────────────────────────────────────────────────────
    @property
    def is_logged_in(self) -> bool:
        """Whether the client currently holds a valid Tabroom session."""
        return self._logged_in

    @property
    def client(self) -> httpx.Client:
        """Return the underlying ``httpx.Client`` (authenticated or not).

        Other scrapers should use this client for their HTTP requests so
        they benefit from the stored session cookies.
        """
        return self._client

    # ── Cleanup ─────────────────────────────────────────────────────────────
    def close(self):
        """Close the underlying HTTP client and release its resources."""
        self._client.close()
