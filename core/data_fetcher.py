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
import time
from typing import List, Optional

import pandas as pd
import requests

# Rotate between Yahoo query hosts to spread load / reduce single-host 429s.
_YAHOO_HOSTS = ["query1.finance.yahoo.com", "query2.finance.yahoo.com"]

# A realistic browser-ish UA helps avoid trivial 429 blocks.
_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
]


def _http_get(url: str, *, timeout: int = 15, **kwargs) -> requests.Response:
    """GET with a realistic UA, retry with backoff on 429/5xx/transport errors."""
    kwargs.setdefault("headers", {})
    kwargs["headers"].setdefault("User-Agent", _USER_AGENTS[0])
    last_exc: Optional[Exception] = None
    for attempt in range(3):
        try:
            resp = requests.get(url, timeout=timeout, **kwargs)
            # Retry transient rate-limit / server errors, then raise.
            if resp.status_code in (429, 500, 502, 503, 504):
                last_exc = RuntimeError(f"HTTP {resp.status_code}")
                time.sleep(1.0 + attempt * 1.5)  # 1s, 2.5s, 4s
                continue
            resp.raise_for_status()
            return resp
        except requests.RequestException as exc:
            last_exc = exc
            time.sleep(1.0 + attempt * 1.0)
    raise last_exc


# HK codes are 4-5 digits, often written with leading zeros (e.g. 09868, 0700, 0005).
# Yahoo/Stooq use a 4-digit zero-padded form + ".HK":
#   09868 -> 9868.HK   0700 -> 0700.HK   0005 -> 0005.HK   9988 -> 9988.HK
def normalize_symbol(code: str) -> str:
    digits = "".join(ch for ch in code.strip() if ch.isdigit())
    if not digits:
        raise ValueError(f"Invalid HK stock code: {code!r}")
    value = int(digits)
    pad = 4 if value <= 9999 else len(digits)
    return f"{value:0{pad}d}.HK"


# Stooq CSV (simple, no auth). Free but occasionally rate-limited.
def fetch_stooq(code: str) -> pd.DataFrame:
    sym = normalize_symbol(code)
    url = f"https://stooq.com/q/d/l/?s={sym}&i=d"
    resp = _http_get(url)
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
    last_exc: Optional[Exception] = None
    for host in _YAHOO_HOSTS:  # try query1 then query2
        url = (
            f"https://{host}/v8/finance/chart/"
            f"{sym}?range={lookback_days}d&interval=1d"
        )
        try:
            resp = _http_get(url)
            data = resp.json()
            result = data["chart"]["result"][0]
            ts = result["timestamp"]
            q = result["indicators"]["quote"][0]
            # meta carries the display name (shortName e.g. "SMIC"); Yahoo provides no Chinese.
            meta = result.get("meta") or {}
            stock_name = (meta.get("shortName") or meta.get("longName") or "").strip()
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
            df.attrs["stock_name"] = stock_name or None
            df = df.drop_duplicates(subset="date").sort_values("date").reset_index(drop=True)
            return df
        except Exception as exc:
            last_exc = exc
            continue  # try next host
    raise last_exc


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
                # Preserve the display name across tail()/reset_index() which may drop attrs.
                name = df.attrs.get("stock_name")
                out = df.tail(lookback).reset_index(drop=True)
                out.attrs["stock_name"] = name
                return out
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
