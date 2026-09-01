"""
ml_helper.py — minimal scikit-learn boilerplate for signal feature processing.

Goal: build feature rows from indicator data so you can later train a
classifier on LABELED data. It does NOT embed any buy/sell logic and ships
with no trained model — it only provides:
    - feature engineering (returns, SMA ratios, BB position, RSI, volatility)
    - train/test split helper
    - a stub for a (future) model pipeline

The `RSI` here uses TA-Lib; guard is included so it degrades gracefully if
TA-Lib isn't importable yet.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

try:
    import talib
    _HAS_TALIB = True
except Exception:  # pragma: no cover
    _HAS_TALIB = False
    talib = None

from sklearn.model_selection import train_test_split  # type: ignore


def engineer_features(ta: pd.DataFrame) -> pd.DataFrame:
    """
    Build numeric feature columns from a ta_engine indicator DataFrame.

    Returns a copy of `ta` with extra ML-ready columns (all NaN-safe).
    """
    out = ta.copy()

    close = out["close"].astype(float)

    # Price returns
    out["ret_1"] = close.pct_change(1)
    out["ret_5"] = close.pct_change(5)

    # SMA ratios (structure features)
    out["sma19_over_sma50"] = out["sma_mid"] / out["sma_long"].replace(0, np.nan)

    # Bollinger Band position (0..1 normalized; NaN-safe)
    span = (out["bb_upper"] - out["bb_lower"]).replace(0, np.nan)
    out["bb_position"] = (close - out["bb_lower"]) / span

    # Volatility (rolling std of 1-day returns)
    out["vol_10"] = out["ret_1"].rolling(10).std()

    # RSI (TA-Lib, 14-period) — optional
    if _HAS_TALIB:
        out["rsi_14"] = talib.RSI(close.values, timeperiod=14)
    else:
        out["rsi_14"] = np.nan

    return out


def make_train_test(features: pd.DataFrame, target: pd.Series | None,
                    test_size: float = 0.2, random_state: int = 42):
    """
    Split engineered features (+ optional target) into train/test.

    If `target` is None, only X is returned for unsupervised / inference use.
    """
    X = features.dropna().reset_index(drop=True)
    if target is None:
        return X, None, None, None
    # align target to the same (post-dropna) index by position
    y = target.iloc[X.index].reset_index(drop=True) if len(target) == len(features) else None

    if y is None or y.isna().all():
        return X, None, None, None
    return train_test_split(X, y, test_size=test_size, random_state=random_state, shuffle=False)


def stub_pipeline() -> None:
    """
    Placeholder for your future model (RandomForest / LogisticRegression).
    Deliberately empty — no trained model is embedded in this boilerplate.
    """
    print("[ml_helper] No model shipped. Train your own on labeled data.")


# ---------------------------------------------------------------------------
# Quick self-test: `python ml_helper.py`
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    from ta_engine import compute_indicators
    from data_fetcher import fetch_history

    hist = fetch_history("09868")
    ta = compute_indicators(hist)
    feats = engineer_features(ta)
    print("Engineered features (tail):")
    print(feats.tail(3).round(4).to_string())
    stub_pipeline()
