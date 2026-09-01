"""
ta_engine.py — technical analysis core for HK stocks (TA-Lib with pandas fallback).

Hard-coded indicator parameters (per project spec):
    - SMA-2, SMA-19, SMA-50
    - Bollinger Bands (20-period, 2.0 std dev — TA-Lib BBANDS defaults)

Backend strategy (IMPORTANT for portability):
    - If TA-Lib is importable -> use TA-Lib (fast; requires the C library).
    - Otherwise -> pure-pandas fallback (SMA / Bollinger computed with pandas).
    This makes the engine run on ANY machine even without the TA-Lib C library
    (e.g. a Mac with broken Homebrew, Windows without the DLL, Vercel serverless).

Input : pandas DataFrame with columns [open, high, low, close, volume]
Output: pandas DataFrame of computed indicators + short-term high/low
        reference levels derived from the latest Bollinger envelope.

NOTE: This module only COMPUTES indicators and reference levels.
It NEVER outputs a buy/sell recommendation. All outputs are reference data.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

# ---- Backend detection: try TA-Lib, else fall back to pandas -------------
try:
    import talib

    HAS_TALIB = True
    ENGINE = "TA-Lib"
except Exception:  # pragma: no cover - C library missing on some machines
    talib = None
    HAS_TALIB = False
    ENGINE = "pandas (fallback)"

# Expose a public flag so callers can log which engine is in use.
__all__ = [
    "HAS_TALIB",
    "ENGINE",
    "compute_indicators",
    "derive_reference_levels",
    "SMA_SHORT_WINDOW",
    "SMA_MID_WINDOW",
    "SMA_LONG_WINDOW",
    "BB_PERIOD",
    "BB_NB_DEVUP",
    "BB_NB_DEVdn",
]

# ---- Hard-coded parameters (do not change via config) ----
SMA_SHORT_WINDOW = 2
SMA_MID_WINDOW = 19
SMA_LONG_WINDOW = 50
BB_PERIOD = 20
BB_NB_DEVUP = 2.0
BB_NB_DEVdn = 2.0
BB_MATYPE = 0  # 0 = simple moving average (only relevant to TA-Lib path)


def _require_close(df: pd.DataFrame) -> pd.Series:
    """Return the close series, validating the DataFrame."""
    if "close" not in df.columns:
        raise KeyError("DataFrame must contain a 'close' column")
    close = pd.to_numeric(df["close"], errors="coerce")
    if close.isna().all():
        raise ValueError("'close' column has no valid numeric values")
    return close


# ---------------------------------------------------------------------------
# Backend implementations
# ---------------------------------------------------------------------------
def _sma_talib(close: np.ndarray, period: int) -> np.ndarray:
    return np.asarray(talib.SMA(close, timeperiod=period), dtype=float)


def _sma_pandas(close: pd.Series, period: int) -> np.ndarray:
    return close.rolling(window=period, min_periods=period).mean().to_numpy(dtype=float)


def _bbands_talib(close: np.ndarray) -> tuple:
    upper, middle, lower = talib.BBANDS(
        close,
        timeperiod=BB_PERIOD,
        nbdevup=BB_NB_DEVUP,
        nbdevdn=BB_NB_DEVdn,
        matype=BB_MATYPE,
    )
    return (
        np.asarray(upper, dtype=float),
        np.asarray(middle, dtype=float),
        np.asarray(lower, dtype=float),
    )


def _bbands_pandas(close: pd.Series) -> tuple:
    middle = close.rolling(window=BB_PERIOD, min_periods=BB_PERIOD).mean()
    std = close.rolling(window=BB_PERIOD, min_periods=BB_PERIOD).std(ddof=0)
    upper = middle + (BB_NB_DEVUP * std)
    lower = middle - (BB_NB_DEVdn * std)
    return (
        upper.to_numpy(dtype=float),
        middle.to_numpy(dtype=float),
        lower.to_numpy(dtype=float),
    )


def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """
    Compute SMA-2 / SMA-19 / SMA-50 and Bollinger Bands on `df`.

    Uses TA-Lib when available, otherwise a pure-pandas fallback.
    Produces IDENTICAL column layout regardless of backend.

    Returns a new DataFrame aligned to the input index.
    """
    close = _require_close(df)

    if HAS_TALIB:
        close_arr = close.to_numpy(dtype=float)
        sma_short = _sma_talib(close_arr, SMA_SHORT_WINDOW)
        sma_mid = _sma_talib(close_arr, SMA_MID_WINDOW)
        sma_long = _sma_talib(close_arr, SMA_LONG_WINDOW)
        bb_upper, bb_middle, bb_lower = _bbands_talib(close_arr)
    else:
        sma_short = _sma_pandas(close, SMA_SHORT_WINDOW)
        sma_mid = _sma_pandas(close, SMA_MID_WINDOW)
        sma_long = _sma_pandas(close, SMA_LONG_WINDOW)
        bb_upper, bb_middle, bb_lower = _bbands_pandas(close)

    out = pd.DataFrame(index=df.index)
    # Preserve the original 'date' column (if any) so reference levels can
    # report the actual trading date even when the index is a plain RangeIndex.
    if "date" in df.columns:
        out["date"] = df["date"].values
    out["close"] = close.to_numpy(dtype=float)
    out["sma_short"] = sma_short
    out["sma_mid"] = sma_mid
    out["sma_long"] = sma_long
    out["bb_upper"] = bb_upper
    out["bb_middle"] = bb_middle
    out["bb_lower"] = bb_lower
    return out


def derive_reference_levels(ta: pd.DataFrame) -> dict:
    """
    Derive short-term high/low reference levels from the latest Bollinger
    envelope + moving-average structure.

    Returns a dict of reference values only (NO trading decision).
    """
    if ta.empty:
        return {"error": "No indicator data available"}

    last = ta.iloc[-1]
    # Resolve the label of the last row: prefer a real 'date' column if present
    # (fetch_history returns a RangeIndex with a 'date' column); otherwise use
    # a DatetimeIndex, else the last integer position.
    if "date" in ta.columns:
        raw = last["date"]
        date_label = str(pd.to_datetime(raw).date())
    else:
        idx_last = ta.index[-1]
        date_label = str(idx_last.date()) if hasattr(idx_last, "date") else str(idx_last)
    ref = {
        "date": date_label,
        "engine": ENGINE,
        "last_close": round(float(last["close"]), 3),
        "sma_short": round(float(last["sma_short"]), 3) if np.isfinite(last["sma_short"]) else None,
        "sma_mid": round(float(last["sma_mid"]), 3) if np.isfinite(last["sma_mid"]) else None,
        "sma_long": round(float(last["sma_long"]), 3) if np.isfinite(last["sma_long"]) else None,
        "bb_upper": round(float(last["bb_upper"]), 3) if np.isfinite(last["bb_upper"]) else None,
        "bb_middle": round(float(last["bb_middle"]), 3) if np.isfinite(last["bb_middle"]) else None,
        "bb_lower": round(float(last["bb_lower"]), 3) if np.isfinite(last["bb_lower"]) else None,
        # Simple structured bracket (reference zone, not a trade signal)
        "short_term_high_reference": (
            round(float(last["bb_upper"]), 3) if np.isfinite(last["bb_upper"]) else None
        ),
        "short_term_low_reference": (
            round(float(last["bb_lower"]), 3) if np.isfinite(last["bb_lower"]) else None
        ),
        "structure_note": _structure_note(last),
    }
    return ref


def _structure_note(last: pd.Series) -> str:
    """Describe the latest SMA cross structure (factual, not advice)."""
    sma = last["sma_short"]
    lma = last["sma_long"]
    if not (np.isfinite(sma) and np.isfinite(lma)):
        return "insufficient history for SMA structure (need >51 candles)"
    if sma > lma:
        return "short-MA above long-MA (uptrend tilt observed)"
    if sma < lma:
        return "short-MA below long-MA (downtrend tilt observed)"
    return "short-MA ~ long-MA (no clear tilt)"


# ---------------------------------------------------------------------------
# Quick self-test: `python ta_engine.py`
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import datetime as _dt

    print(f"Engine in use: {ENGINE} (HAS_TALIB={HAS_TALIB})")

    _n = 90
    _idx = pd.date_range(end=_dt.date.today(), periods=_n, freq="D")
    rng = np.random.default_rng(42)
    _close = 50 + np.cumsum(rng.normal(0, 0.3, _n))
    _demo = pd.DataFrame(
        {
            "date": _idx.date,
            "open": _close - 0.1,
            "high": _close + 0.3,
            "low": _close - 0.3,
            "close": _close,
            "volume": rng.integers(1_000_000, 30_000_000, _n),
        },
        index=_idx,
    )

    _ta = compute_indicators(_demo)
    print("Computed indicators tail:")
    print(_ta.tail(5).round(3).to_string())
    print("\nReference levels (reference only):")
    print(repr(derive_reference_levels(_ta)))
