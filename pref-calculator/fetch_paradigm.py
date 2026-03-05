"""Fetch a judge's paradigm from Tabroom and write it to a text file."""
import sys
from tabroom_scraper import TabroomScraper


def main():
    name = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else "Neo Cai"
    print(f"Fetching paradigm for: {name}")

    scraper = TabroomScraper()
    scraper.login()
    result = scraper.fetch_paradigm_by_name(name)

    if not result:
        print("No paradigm found.")
        return

    out_file = f"paradigm_{name.replace(' ', '_')}.txt"
    with open(out_file, "w", encoding="utf-8") as f:
        f.write(f"Judge: {result.get('name', '?')}\n")
        f.write(f"School: {result.get('school', '?')}\n")
        f.write(f"URL: {result.get('paradigm_url', '?')}\n")
        f.write("=" * 60 + "\n")
        f.write(result.get("philosophy", "NO PARADIGM"))

    phil_len = len(result.get("philosophy", ""))
    print(f"Wrote {out_file} ({phil_len} chars)")


if __name__ == "__main__":
    main()
