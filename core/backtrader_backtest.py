"""
backtrader_backtest.py — backtrader sample skeleton for HK stock data.

This is a STRATEGY SKELETON: it demonstrates wiring backtrader with a
pandas feed and ONE simple indicator. It contains NO buy/sell logic and
no recommendation. Add your own signal rules (or leave it as a harness).

NOTE (Vercel): backtrader is CPU/IO heavy and runs long on the free tier.
Run backtests as a Worker / external cron, NOT inside a request handler.
"""

from __future__ import annotations

import backtrader as bt  # type: ignore
import pandas as pd

from data_fetcher import fetch_history


class IndicatorOnlyStrategy(bt.Strategy):
    """
    Placeholder strategy: computes a SMA-cross reference but exits flat.
    No orders are ever placed — it is a harness for your own logic.
    """

    params = (("fast", 19), ("slow", 50))

    def __init__(self) -> None:
        self.fast = bt.indicators.SMA(self.data.close, period=self.params.fast)
        self.slow = bt.indicators.SMA(self.data.close, period=self.params.slow)
        # Register a cross indicator (not used for orders here).
        self.cross = bt.indicators.CrossOver(self.fast, self.slow)

    def next(self) -> None:
        # Intentionally empty: no buy/sell orders in this skeleton.
        pass


def df_to_btfeed(df: pd.DataFrame) -> bt.feeds.PandasData:
    """Convert pandas OHLC DataFrame into a backtrader data feed."""
    df = df.copy()
    # Ensure there is a proper datetime index; backtrader requires it.
    if not isinstance(df.index, pd.DatetimeIndex):
        if "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"])
            df = df.set_index("date")
        else:
            raise ValueError("DataFrame needs a 'date' column or DatetimeIndex")
    feed = bt.feeds.PandasData(
        dataname=df,
        datetime=None,  # use index as datetime
        open="open", high="high", low="low", close="close",
        volume="volume", openinterest=-1,
    )
    return feed


def run_backtest(symbol: str, cash: float = 100_000.0) -> None:
    """Run a sample cerebro session and print performance stats."""
    cerebro = bt.Cerebro()
    cerebro.broker.setcash(cash)
    cerebro.addstrategy(IndicatorOnlyStrategy)

    hist = fetch_history(symbol, lookback=250)
    feed = df_to_btfeed(hist)
    cerebro.adddata(feed)

    # Commission model (example placeholder).
    cerebro.broker.setcommission(commission=0.001)

    print(f"Starting Portfolio Value: {cerebro.broker.getvalue():,.2f}")
    cerebro.run()
    print(f"Final Portfolio Value:    {cerebro.broker.getvalue():,.2f}")
    print("(Strategy places no orders — this is a harness skeleton.)")


# ---------------------------------------------------------------------------
# Quick self-test: `python backtrader_backtest.py 09868`
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import sys

    sym = sys.argv[1] if len(sys.argv) > 1 else "09868"
    run_backtest(sym)
