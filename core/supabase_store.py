"""
supabase_store.py — Supabase persistence for hk-stock-monitor.

Stores each analysis snapshot (report JSON + chart PNG) into Supabase:

    table : stock_monitor_log   (see supabase/schema.sql)
    bucket: stock-charts        (created on demand for chart PNGs)

Secrets are read from environment or Streamlit secrets:

    SUPABASE_URL
    SUPABASE_SERVICE_ROLE_KEY    (server-side, KEEP SECRET)

The service-role key bypasses RLS and must NEVER be shipped to the browser.
In Streamlit this module runs server-side, so it is safe to use the
service-role key here.
"""

from __future__ import annotations

import io
import os

try:
    from supabase import create_client, Client

    _HAS_SUPABASE = True
except Exception:  # pragma: no cover - optional dep
    _HAS_SUPABASE = False

try:
    import streamlit as st

    def _secret(key: str) -> str:
        try:
            val = st.secrets.get(key)
        except Exception:
            val = None  # no secrets file configured yet
        if val:
            return str(val).strip()
        return os.getenv(key, "").strip()

except Exception:  # pragma: no cover - non-Streamlit context
    def _secret(key: str) -> str:
        return os.getenv(key, "").strip()


STORAGE_BUCKET = "stock-charts"


def is_supabase_ready() -> bool:
    """True only if supabase lib + URL + service key are present."""
    if not _HAS_SUPABASE:
        return False
    return bool(_secret("SUPABASE_URL")) and bool(_secret("SUPABASE_SERVICE_ROLE_KEY"))


def _client() -> "Client":
    if not is_supabase_ready():
        raise RuntimeError("Supabase not configured (missing URL / service key).")
    return create_client(_secret("SUPABASE_URL"), _secret("SUPABASE_SERVICE_ROLE_KEY"))


def _ensure_storage_bucket(client: "Client") -> None:
    """Create the chart-storage bucket if it does not exist (best-effort)."""
    try:
        client.storage.create_bucket(
            STORAGE_BUCKET, options={"public": True}
        )
    except Exception:
        # Bucket likely already exists; ignore.
        pass


def upload_chart(client: "Client", symbol: str, png: bytes) -> str:
    """Upload chart PNG to Supabase Storage; return public URL (or '' )."""
    _ensure_storage_bucket(client)
    file_name = f"{symbol}-{int(__import__('time').time())}.png"
    client.storage.from_(STORAGE_BUCKET).upload(
        file_name,
        png,
        {"content-type": "image/png"},
    )
    return client.storage.from_(STORAGE_BUCKET).get_public_url(file_name)


def store_snapshot(symbol: str, report: dict, chart_png: bytes) -> str:
    """
    Insert one snapshot row into `stock_monitor_log`.

    Returns the public chart URL (or '' if upload skipped/failed).
    """
    client = _client()

    chart_url = ""
    if chart_png:
        try:
            chart_url = upload_chart(client, symbol, chart_png)
        except Exception:
            chart_url = ""  # chart is optional; still store the report

    row = {
        "symbol": symbol.strip(),
        "snapshot": report,  # jsonb
        "chart_url": chart_url,  # nullable
    }
    client.table("stock_monitor_log").insert(row).execute()
    return chart_url


def fetch_recent(symbol: str, limit: int = 5) -> list:
    """Return the most recent persisted snapshots for a symbol (desc by time)."""
    client = _client()
    res = (
        client.table("stock_monitor_log")
        .select("*")
        .eq("symbol", symbol.strip())
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )
    return res.data or []


if __name__ == "__main__":
    print("Supabase available:", _HAS_SUPABASE)
    print("Ready:", is_supabase_ready())
