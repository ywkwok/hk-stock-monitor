"""
chart.py — server-safe matplotlib chart rendering (Agg backend).

All figure creation goes through this module so the dashboard / monitor
never pops a GUI window. Draws:
    - price line
    - Bollinger Bands (upper / middle / lower)
    - SMA-2 / SMA-19 / SMA-50 overlays

Output image is written to a bytes buffer (PNG) for web delivery.
"""

from __future__ import annotations

import io

import matplotlib

# MUST be set before pyplot import: non-interactive, server/Vercel safe.
matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402
from matplotlib import font_manager  # noqa: E402
import pandas as pd  # noqa: E402


# --- CJK font support (so Chinese titles/labels render on Linux/Vercel) ---
_CJK_CANDIDATES = [
    "Noto Sans CJK SC", "Noto Serif CJK SC", "Noto Sans CJK TC",
    "WenQuanYi Zen Hei", "PingFang HK", "Heiti TC", "Arial Unicode MS",
]
_configured = False


def _setup_fonts() -> None:
    """Register the first available CJK font, if any (best-effort)."""
    global _configured
    if _configured:
        return
    available = {f.name for f in font_manager.fontManager.ttflist}
    for name in _CJK_CANDIDATES:
        if name in available:
            plt.rcParams["font.sans-serif"] = [name] + list(plt.rcParams["font.sans-serif"])
            plt.rcParams["axes.unicode_minus"] = False
            break
    _configured = True


def render_chart(ta: pd.DataFrame, symbol: str) -> bytes:
    """
    Render a PNG chart bytes from a ta_engine indicator DataFrame.

    Returns raw PNG bytes (ready to write to disk or send as HTTP response).
    """
    _setup_fonts()
    fig, ax = plt.subplots(figsize=(11, 6), dpi=110)

    ax.plot(ta.index, ta["close"], label="Close", color="#1f77b4", lw=1.6)
    ax.plot(ta.index, ta["bb_upper"], label="BB Upper", color="#d62728", lw=1.0, ls="--")
    ax.plot(ta.index, ta["bb_middle"], label="BB Middle", color="#9467bd", lw=1.0, ls="-.")
    ax.plot(ta.index, ta["bb_lower"], label="BB Lower", color="#2ca02c", lw=1.0, ls="--")
    ax.plot(ta.index, ta["sma_short"], label="SMA-2", color="#ff7f0e", lw=1.0)
    ax.plot(ta.index, ta["sma_mid"], label="SMA-19", color="#000000", lw=1.0)
    ax.plot(ta.index, ta["sma_long"], label="SMA-50", color="#7f7f7f", lw=1.4)

    ax.set_title(f"{symbol} — Price / Bollinger Bands / SMA overlay")
    ax.set_xlabel("Date")
    ax.set_ylabel("Price")
    ax.legend(loc="best", fontsize=8)
    ax.grid(True, alpha=0.3)

    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png")
    plt.close(fig)  # free memory
    buf.seek(0)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Quick self-test: `python chart.py`
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import numpy as np
    from ta_engine import compute_indicators

    n = 90
    rng = np.random.default_rng(7)
    idx = pd.date_range(end="2026-08-28", periods=n, freq="D")
    close = 40 + np.cumsum(rng.normal(0, 0.2, n))
    demo = pd.DataFrame({"open": close - 0.1, "high": close + 0.3,
                         "low": close - 0.3, "close": close,
                         "volume": rng.integers(1, 30, n) * 1_000_000}, index=idx)
    ta = compute_indicators(demo)
    png = render_chart(ta, "DEMO")
    with open("demo_chart.png", "wb") as fh:
        fh.write(png)
    print(f"Wrote demo_chart.png ({len(png)} bytes)")
