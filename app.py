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

from data_fetcher import fetch_history, resolve_stock_name  # noqa: E402
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

    # Display name comes first from the data-source metadata (Yahoo shortName).
    # If the price came from Stooq (Yahoo rate-limited/fallback) there is no
    # metadata, so resolve the short name independently (best-effort; fallback
    # to "" -> caller shows just the code).
    stock_name = hist.attrs.get("stock_name") or ""
    if not stock_name:
        try:
            stock_name = resolve_stock_name(symbol)
        except Exception:
            stock_name = ""

    news = []
    try:
        news = NewsScraper().fetch_news(symbol, limit=3)
    except Exception:
        news = []  # news is best-effort only

    report = {
        "symbol": symbol.strip(),
        "name": stock_name.strip() if isinstance(stock_name, str) else "",
        "reference": ref,
        "news": news,
        "note": "Reference data only. No investment recommendation is provided.",
    }
    return hist, ta, ref, news, report


# ---------------------------------------------------------------------------
# Reference-levels rendering helpers
# ---------------------------------------------------------------------------
def _format_value(v):
    """Coerce a reference value into a single safe, displayable type.

    The Value column may hold floats, None, or free-text notes (engine name,
    structure description, date string).  Mixing numeric floats and text in one
    column produces an object dtype, which newer pyarrow rejects when Streamlit
    serialises the table (ArrowTypeError).  Coercing every cell to str keeps
    the whole column uniform and Arrow-safe.
    """
    if v is None:
        return "--"
    # bool is a subclass of int; keep it as text too for uniformity
    if isinstance(v, bool):
        return str(v)
    if isinstance(v, (int, float)):
        # 3 dp like the rounding applied upstream; trim trailing zeros
        num = round(float(v), 3)
        return f"{num:g}"
    return str(v)


def _pretty_metric(key: str) -> str:
    """Turn technical-level keys into clearer, human-friendly display labels."""
    pretty = {
        # Bollinger Bands labels (Bollinger is the band context of bb_*).
        "bb_upper": "Bollinger Upper",
        "bb_middle": "Bollinger Middle",
        "bb_lower": "Bollinger Lower",
        "short_term_high_reference": "Short-term High Reference",
        "short_term_low_reference": "Short-term Low Reference",
        "structure_note": "Structure Note",
        "last_close": "Last Close",
        # SMA windows: sma_short/mid/long map to SMA-2 / SMA-19 / SMA-50.
        "sma_short": "SMA-2",
        "sma_mid": "SMA-19",
        "sma_long": "SMA-50",
    }
    if key in pretty:
        return pretty[key]
    # Generic fallback: bb_xxx -> Bollinger xxx; else underscore -> space + title case.
    if key.startswith("bb_"):
        return "Bollinger " + key[3:].replace("_", " ").title()
    return key.replace("_", " ").title()


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
                rows.append((f"{_pretty_metric(key)} / {_pretty_metric(k2)}", _format_value(v2)))
        else:
            rows.append((_pretty_metric(key), _format_value(val)))

    df = pd.DataFrame(rows, columns=["Metric", "Value"])
    st.dataframe(df, width="stretch", hide_index=True)


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

    # Show the last-analysed stock name (short name) once a run has completed.
    _last = st.session_state.get("last_report")
    if _last:
        _sym = _last.get("symbol", "")
        _name = _last.get("name", "")
        st.caption(f"**{_sym}**" + (f" · {_name}" if _name else ""))

    symbol = st.text_input("HK stock code", value=load_sidebar_state()).strip()
    st.caption("e.g. 09868, 06082, 0700, 9988 (leading zeros optional)")

    if st.button("🔍 Run analysis", type="primary", width="stretch"):
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

# Remember the latest report so the sidebar can show the short name on rerun.
st.session_state["last_report"] = report

sym = report["symbol"]
name = (report.get("name") or "").strip()
title = f"📈 {sym}" + (f" · {name}" if name else "")
st.title(title)

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
st.image(chart_png, width="stretch", caption=title)

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
