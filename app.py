"""
app.py — Streamlit front-end for hk-stock-monitor.

Converts the backend-first Flask prototype into an interactive Streamlit
dashboard. Flow per symbol:

    fetch data -> TA compute -> chart PNG -> JSON report
    -> (optional) persist snapshot + chart to Supabase `stock_monitor_log`

Run locally:
    streamlit run app.py

Deploy:
    Streamlit Community Cloud (auto-deploy from GitHub repo).

Secrets:
    Set SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY under
    `.streamlit/secrets.toml` (local) or the Streamlit Cloud Secrets UI.
    They are optional: the app runs fully without Supabase.
"""

from __future__ import annotations

import json
import os

import matplotlib

matplotlib.use("Agg")  # server-safe, must precede pyplot

import pandas as pd
import streamlit as st

# Ensure `core/` package is importable regardless of CWD.
_HERE = os.path.dirname(os.path.abspath(__file__))
import sys

sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.join(_HERE, "core"))

from data_fetcher import fetch_history  # noqa: E402
from ta_engine import compute_indicators, derive_reference_levels  # noqa: E402
from chart import render_chart  # noqa: E402
from news_scraper import NewsScraper  # noqa: E402
from supabase_store import store_snapshot, is_supabase_ready  # noqa: E402


# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="HK Stock Monitor",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)


def load_sidebar_state() -> str:
    """Return a default symbol; sidebar is rendered by the main flow."""
    # Allow a symbol to be passed e.g. via query param seeding.
    return (st.query_params.get("symbol") or "09868")


# ---------------------------------------------------------------------------
# Core pipeline
# ---------------------------------------------------------------------------
def build_report(symbol: str) -> dict:
    """Reuse the backend pipeline: fetch -> TA -> reference -> news."""
    hist = fetch_history(symbol)
    ta = compute_indicators(hist)
    ref = derive_reference_levels(ta)

    news = []
    try:
        news = NewsScraper().fetch_news(symbol, limit=3)
    except Exception:
        news = []  # news is best-effort only

    report = {
        "symbol": symbol.strip(),
        "reference": ref,
        "news": news,
        "note": "Reference data only. No investment recommendation is provided.",
    }
    return hist, ta, ref, news, report


# ---------------------------------------------------------------------------
# Reference-levels rendering helpers
# ---------------------------------------------------------------------------
def render_reference_table(ref: dict) -> None:
    """Display the structured reference-level dict as a readable table."""
    if not ref:
        st.info("No reference data available.")
        return

    # Flatten top-level scalars + named levels.
    rows = []
    for key, val in ref.items():
        if isinstance(val, dict):
            for k2, v2 in val.items():
                rows.append((f"{key} / {k2}", v2))
        else:
            rows.append((key, val))

    df = pd.DataFrame(rows, columns=["Metric", "Value"])
    st.dataframe(df, use_container_width=True, hide_index=True)


# ---------------------------------------------------------------------------
# Supabase persistence
# ---------------------------------------------------------------------------
def persist_to_supabase(symbol: str, report: dict, chart_png: bytes) -> bool:
    """Write report snapshot + chart to Supabase `stock_monitor_log`."""
    if not is_supabase_ready():
        st.caption("⚠️ Supabase not configured — snapshot not saved.")
        return False
    try:
        # chart stored in Supabase Storage (bucket: stock-charts), URL saved here.
        chart_url = store_snapshot(symbol, report, chart_png)
        st.success(f"✅ Snapshot saved to Supabase (chart: {chart_url or 'n/a'})")
        return True
    except Exception as exc:
        st.warning(f"⚠️ Could not save to Supabase: {exc}")
        return False


# ---------------------------------------------------------------------------
# Main UI
# ---------------------------------------------------------------------------
STOCK_CODES = ["09868", "06082", "0700", "9988", "0700", "0005"]

with st.sidebar:
    st.title("📈 HK Stock Monitor")
    st.caption("Technical-analysis reference dashboard (no investment advice).")

    symbol = st.text_input("HK stock code", value=load_sidebar_state()).strip()
    st.caption("e.g. 09868, 06082, 0700, 9988 (leading zeros optional)")

    if st.button("🔍 Run analysis", type="primary", use_container_width=True):
        st.session_state["run"] = True

    st.divider()
    save_db = st.checkbox("Save snapshot to Supabase", value=True)
    st.caption("Optionally persist each run's report + chart to `stock_monitor_log`.")

    st.divider()
    st.caption(
        "Data: Stooq / Yahoo (free).  Values are for **reference only** — "
        "no buy/sell recommendation."
    )


if not symbol:
    st.info("Enter a HK stock code in the sidebar to begin.")
    st.stop()

# Trigger on button press OR first symbol set.
run_requested = st.session_state.get("run", False)
if not run_requested:
    # Show a gentle "ready" state instead of auto-fetching on every rerun.
    st.info(f"Ready. Click **Run analysis** for `{symbol}`.")
    st.stop()

with st.spinner(f"Fetching & analysing {symbol}..."):
    try:
        hist, ta, ref, news, report = build_report(symbol)
    except Exception as exc:
        st.error(f"Analysis failed: {exc}")
        st.caption(
            "Network/source may be rate-limited. Try again in a moment, "
            "or check the symbol format."
        )
        st.stop()

st.title(f"📈 {report['symbol']}")

# --- Metrics row ---
if ref:
    cols = st.columns(4)
    cols[0].metric("Last Close", f"{ref.get('last_close', '--')}")
    cols[1].metric("SMA-2", f"{ref.get('sma_short', '--')}")
    cols[2].metric("SMA-19", f"{ref.get('sma_mid', '--')}")
    cols[3].metric("SMA-50", f"{ref.get('sma_long', '--')}")

    # Signal tone
    if "trend" in ref:
        st.caption(f"Trend: **{ref.get('trend')}**")

# --- Chart ---
chart_png = render_chart(ta, report["symbol"])
st.image(chart_png, use_container_width=True, caption=f"{report['symbol']} — chart")

# --- Reference table ---
with st.expander("📊 Reference levels", expanded=True):
    render_reference_table(ref)

# --- News ---
with st.expander("📰 News snippets"):
    if news:
        for item in news:
            title = item.get("title", "—")
            link = item.get("link", "")
            st.markdown(f"- {title}")
            if link:
                st.caption(f"  {link}")
    else:
        st.caption("No news available (best-effort).")

st.caption("---")
st.caption(report.get("note", ""))

# --- Persist (optional) ---
if save_db:
    persist_to_supabase(report["symbol"], report, chart_png)
