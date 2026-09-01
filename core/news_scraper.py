"""
news_scraper.py — fetch public market news snippets for a HK stock.

Uses `requests` + `BeautifulSoup4`. Default source is AAStocks' news list
(public page). Be respectful:
    - enforce a small delay between requests (scrape_delay_seconds)
    - keep request volume low
    - scraping may violate the target website's Terms of Service — check
      before aggressive use; prefer the site's official API if available.

Returns a plain list of {title, url, source} dicts. No rendering, no JS.
"""

from __future__ import annotations

import time
from typing import List, Dict

import requests
from bs4 import BeautifulSoup

# --- Config (edit here, or override via env) ---
DEFAULT_BASE = "https://www.aastocks.com"
DEFAULT_NEWS_PATH = "/tc/stocks/news/all-stock-news.aspx"  # example path
REQUEST_TIMEOUT = 10
SCRAPE_DELAY_SECONDS = 1.5
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)


class NewsScraper:
    def __init__(self, session: requests.Session | None = None):
        self.session = session or requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT})

    def fetch_news(
        self,
        symbol: str,
        base_url: str = DEFAULT_BASE,
        path: str = DEFAULT_NEWS_PATH,
        limit: int = 6,
    ) -> List[Dict[str, str]]:
        """
        Fetch and parse news links for `symbol`.

        Returns up to `limit` items: [{"title", "url", "source"}].
        Empty list on any fetch/parse failure (never raises to caller).
        """
        url = base_url + path
        try:
            resp = self.session.get(url, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
        except Exception as exc:  # network / HTTP errors
            print(f"[news_scraper] fetch failed for {symbol}: {exc}")
            return []

        # Polite delay AFTER a successful fetch, before any follow-up.
        time.sleep(SCRAPE_DELAY_SECONDS)

        return self._parse(resp.text, base_url, limit)

    def _parse(self, html: str, base_url: str, limit: int) -> List[Dict[str, str]]:
        soup = BeautifulSoup(html, "html.parser")
        items: List[Dict[str, str]] = []

        # Generic selector: anchor tags whose href contains a news article path.
        # Adjust selectors to the real site structure as needed.
        for a in soup.select("a[href]"):
            href = a.get("href", "")
            if not isinstance(href, str):
                continue
            if "/news/" not in href and "news" not in href.lower():
                continue
            title = a.get_text(strip=True)
            if len(title) < 8:  # skip junk labels
                continue
            full_url = href if href.startswith("http") else base_url + href
            items.append(
                {
                    "title": title[:120],
                    "url": full_url,
                    "source": base_url.replace("https://", "").split("/")[0],
                }
            )
            if len(items) >= limit:
                break
        return items


# ---------------------------------------------------------------------------
# Quick self-test: `python news_scraper.py 09868`
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import sys

    sym = sys.argv[1] if len(sys.argv) > 1 else "09868"
    scraper = NewsScraper()
    news = scraper.fetch_news(sym)
    print(f"News items for {sym}: {len(news)}")
    for item in news:
        print(f"  - {item['title']} | {item['url']}")
    if not news:
        print("  (none returned — site layout may have changed or blocked)")
