"""
auto_monitor.py — automatic monitoring engine for HK stocks.

Pipeline for each poll cycle:
    1. fetch_history(symbol)            -> OHLC DataFrame
    2. ta_engine.compute_indicators()   -> indicators
    3. ta_engine.derive_reference_levels() -> short-term high/low reference
    4. news_scraper.fetch_news()        -> news snippets
    5. optional supabase_sink.log()     -> persist to Supabase

Output is a structured dict (reference data ONLY). No buy/sell decision,
no recommendation is ever produced or implied.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, asdict
from typing import Any, Dict, Optional

from data_fetcher import fetch_history
from ta_engine import compute_indicators, derive_reference_levels
from news_scraper import NewsScraper

# --------------------------------------------------------------------------
# Optional Supabase sink (disabled unless env vars are present).
# Keeping it import-safe so the module runs without Supabase installed.
# --------------------------------------------------------------------------
def _supabase_available() -> bool:
    try:
        from supabase import create_client  # type: ignore
        import os

        return bool(os.getenv("SUPABASE_URL") and os.getenv("SUPABASE_SERVICE_ROLE_KEY"))
    except Exception:
        return False


class SupabaseSink:
    """Minimal writer into a `stock_monitor_log` table. Best-effort."""

    def __init__(self) -> None:
        import os
        from supabase import create_client

        self.client = create_client(
            os.environ["SUPABASE_URL"],
            os.environ["SUPABASE_SERVICE_ROLE_KEY"],
        )

    def log_cycle(self, symbol: str, result: Dict[str, Any], chart_url: Optional[str] = None) -> None:
        row = {
            "symbol": symbol,
            "snapshot": json.dumps(result, default=str),
            "chart_url": chart_url,
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        try:
            self.client.table("stock_monitor_log").insert(row).execute()
        except Exception as exc:
            print(f"[supabase] log insert failed: {exc}")


@dataclass
class MonitorCycle:
    symbol: str
    ts: str
    status: str
    reference: Dict[str, Any]
    news: list
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class AutoMonitor:
    def __init__(self, poll_seconds: int = 300, news_limit: int = 5,
                 all_news: bool = False) -> None:
        self.poll_seconds = poll_seconds
        self.news_limit = news_limit if all_news else 0
        self.scraper = NewsScraper()
        # Optional persistence
        self.sink = SupabaseSink() if _supabase_available() else None
        if self.sink is None:
            print("[auto_monitor] Supabase sink disabled (env vars missing or lib absent)")

    def run_once(self, symbol: str) -> MonitorCycle:
        """Run a single monitoring pass and return a structured snapshot."""
        ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        try:
            hist = fetch_history(symbol)
            ta = compute_indicators(hist)
            ref = derive_reference_levels(ta)

            news: list = []
            if self.news_limit > 0:
                news = self.scraper.fetch_news(symbol, limit=self.news_limit)

            cycle = MonitorCycle(
                symbol=symbol, ts=ts, status="ok",
                reference=ref, news=news,
            )
            self._persist(symbol, cycle, None)
            return cycle
        except Exception as exc:
            cycle = MonitorCycle(
                symbol=symbol, ts=ts, status="error",
                reference={}, news=[], error=str(exc),
            )
            return cycle

    def _persist(self, symbol: str, cycle: MonitorCycle, chart_url: Optional[str]) -> None:
        if self.sink is not None:
            self.sink.log_cycle(symbol, cycle.to_dict(), chart_url)

    def run_loop(self, symbols, cycles: int = 1) -> None:
        """
        Polling loop. `cycles=-1` runs forever (use ONLY outside serverless).
        Between polls it sleeps self.poll_seconds.
        """
        count = 0
        while cycles == -1 or count < cycles:
            for sym in symbols:
                result = self.run_once(sym)
                print(json.dumps(result.to_dict(), ensure_ascii=False, default=str, indent=2))
            count += 1
            if cycles == -1 or count < cycles:
                time.sleep(self.poll_seconds)


# ---------------------------------------------------------------------------
# Quick self-test: `python auto_monitor.py 09868`
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import sys

    sym = sys.argv[1] if len(sys.argv) > 1 else "09868"
    monitor = AutoMonitor(news_limit=3)
    cycle = monitor.run_once(sym)
    print(json.dumps(cycle.to_dict(), ensure_ascii=False, default=str, indent=2))
