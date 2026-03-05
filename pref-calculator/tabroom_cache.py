"""In-memory cache for Tabroom paradigm data.

Avoids re-scraping the same judge within a session. Entries expire after TTL.
"""
import time


DEFAULT_TTL = 3600  # 1 hour


class TabroomCache:
    """Simple in-memory cache keyed by normalized judge name."""

    def __init__(self, ttl: int = DEFAULT_TTL):
        self._cache: dict[str, tuple[dict, float]] = {}
        self._ttl = ttl

    @staticmethod
    def _normalize_key(name: str) -> str:
        return name.strip().lower()

    def get(self, name: str) -> dict | None:
        """Return cached paradigm data or None if missing/expired."""
        key = self._normalize_key(name)
        entry = self._cache.get(key)
        if entry is None:
            return None
        data, ts = entry
        if time.time() - ts > self._ttl:
            del self._cache[key]
            return None
        return data

    def put(self, name: str, data: dict):
        """Store paradigm data for a judge."""
        key = self._normalize_key(name)
        self._cache[key] = (data, time.time())

    def get_or_fetch(self, name: str, scraper) -> dict | None:
        """Return cached data or fetch from Tabroom and cache the result.

        Args:
            name: Judge name in any format accepted by scraper.
            scraper: TabroomScraper instance with fetch_paradigm_by_name method.
        """
        cached = self.get(name)
        if cached is not None:
            return cached

        data = scraper.fetch_paradigm_by_name(name)
        if data:
            self.put(name, data)
        return data

    def clear(self):
        """Clear all cached entries."""
        self._cache.clear()

    def __len__(self):
        return len(self._cache)

    def __bool__(self):
        return True
