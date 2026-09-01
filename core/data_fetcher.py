"""
data_fetcher.py — historical OHLC price data for HK stocks.

Sources (free, public):
    1. Stooq CSV endpoint (best-effort, no key required):
       https://stooq.com/q/d/l/?s=<code>.HK&i=d
    2. Yahoo Finance chart API (public, no key for basic quotes):
       https://query1.finance.yahoo.com/v8/finance/chart/<code>.HK

Both are free tiers — they may rate-limit or change without notice.
No private/paid financial API is used.

Output : pandas DataFrame with columns [open, high, low, close, volume]
         indexed by date (ascending). Raises on failure.
"""

from __future__ import annotations

import io
from typing import List, Optional

import pandas as pd
import requests

# 5-digit numeric HK codes, or 4-digit codes (e.g. "09868", "06082", "0700").
# Convert to Yahoo/Stooq style: strip leading zeros, append ".HK".
def normalize_symbol(code: str) -> str:
    code = code.strip().lstrip("0") or "0"
    return f"{code}.HK"


# Stooq CSV (simple, no auth). Free but occasionally rate-limited.
def fetch_stooq(code: str) -> pd.DataFrame:
    sym = normalize_symbol(code)
    url = f"https://stooq.com/q/d/l/?s={sym}&i=d"
    resp = requests.get(url, timeout=15)
    resp.raise_for_status()
    df = pd.read_csv(io.StringIO(resp.text))
    df["Date"] = pd.to_datetime(df["Date"])
    df = df.sort_values("Date").reset_index(drop=True)
    df = df.rename(columns={"Date": "date", "Open": "open", "High": "high",
                            "Low": "low", "Close": "close", "Volume": "volume"})
    df = df.dropna(subset=["open", "high", "low", "close"]).reset_index(drop=True)
    df["volume"] = df["volume"].fillna(0)
    return df


# Yahoo Finance chart API (public JSON, no auth for basic range).
def fetch_yahoo(code: str, lookback_days: int = 365) -> pd.DataFrame:
    sym = normalize_symbol(code)
    url = (
        "https://query1.finance.yahoo.com/v8/finance/chart/"
        f"{sym}?range={lookback_days}d&interval=1d"
    )
    headers = {"User-Agent": "Mozilla/5.0 (hk-stock-monitor research)"}
    resp = requests.get(url, headers=headers, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    result = data["chart"]["result"][0]
    ts = result["timestamp"]
    q = result["indicators"]["quote"][0]
    rows = []
    for i, t in enumerate(ts):
        o = q["open"][i]
        h = q["high"][i]
        l = q["low"][i]
        c = q["close"][i]
        if None in (o, h, l, c):
            continue
        rows.append({
            "date": pd.Timestamp(t, unit="s").normalize(),
            "open": o, "high": h, "low": l, "close": c,
            "volume": q["volume"][i] if q["volume"][i] is not None else 0.0,
        })
    df = pd.DataFrame(rows)
    df = df.drop_duplicates(subset="date").sort_values("date").reset_index(drop=True)
    return df


def fetch_history(code: str, lookback: int = 120, sources: Optional[List[str]] = None) -> pd.DataFrame:
    """
    Fetch historical OHLC for a HK stock code.

    Tries sources in order until one succeeds:
        default: ["yahoo", "stooq"]  (Yahoo gives ~1yr, enough for SMA-50)
    Raises RuntimeError if all sources fail.
    """
    sources = sources or ["yahoo", "stooq"]
    errors = []
    for src in sources:
        try:
            if src == "yahoo":
                df = fetch_yahoo(code, lookback_days=max(lookback * 3, 365))
            elif src == "stooq":
                df = fetch_stooq(code)
            else:
                continue
            if df is not None and len(df) >= 2:
                df["symbol"] = code.strip()
                return df.tail(lookback).reset_index(drop=True)
        except Exception as exc:
            errors.append(f"{src}: {exc}")
    raise RuntimeError(f"All data sources failed for {code}: {'; '.join(errors)}")


# ---------------------------------------------------------------------------
# Quick self-test: `python data_fetcher.py 09868`
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import sys

    sym = sys.argv[1] if len(sys.argv) > 1 else "09868"
    hist = fetch_history(sym)
    print(f"Fetched {len(hist)} rows for {sym}")
    print(hist.tail(5).to_string())
