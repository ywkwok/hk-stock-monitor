"""
dashboard_app.py — backend-first dashboard entry point (Flask).

Accepts a HK stock code, runs:
    fetch data -> TA compute -> chart PNG -> structured text report
Returns the chart bytes + JSON report via HTTP.

Deployment notes:
    - This file is a LOCAL / dev entry point. For Vercel you do NOT run
      Flask; instead expose a WSGI app (see `app.py` mapping to this
      handler) so Vercel functions can call it request-by-request.
    - Keep Heavy compute (backtest) OUT of the request path.

Run locally:
    python dashboard_app.py
    then open http://127.0.0.1:8000/?symbol=09868
"""

from __future__ import annotations

import io
import json
import os

import matplotlib

matplotlib.use("Agg")  # server-safe

from flask import Flask, Response, jsonify, request, send_file  # type: ignore

from data_fetcher import fetch_history
from ta_engine import compute_indicators, derive_reference_levels
from chart import render_chart
from auto_monitor import AutoMonitor
from news_scraper import NewsScraper

app = Flask(__name__)


def build_report(symbol: str) -> dict:
    """Core pipeline: fetch -> TA -> reference -> news. Returns report dict."""
    hist = fetch_history(symbol)
    ta = compute_indicators(hist)
    ref = derive_reference_levels(ta)

    news = []
    try:
        news = NewsScraper().fetch_news(symbol, limit=3)
    except Exception:
        news = []  # news is best-effort only

    return {
        "symbol": symbol.strip(),
        "reference": ref,
        "news": news,
        "note": "Reference data only. No investment recommendation is provided.",
    }


@app.route("/")
def index():
    symbol = request.args.get("symbol", "").strip()
    if not symbol:
        return (
            jsonify(
                {
                    "usage": "GET /?symbol=09868",
                    "note": "Backend-first prototype. No complex frontend.",
                }
            ),
            200,
        )

    try:
        report = build_report(symbol)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500

    format = request.args.get("format", "json").lower()
    if format == "json":
        return jsonify(report)
    if format == "chart":
        hist = fetch_history(symbol)
        ta = compute_indicators(hist)
        png = render_chart(ta, symbol.strip())
        return Response(png, mimetype="image/png")
    if format == "report":
        txt = json.dumps(report, ensure_ascii=False, indent=2)
        return Response(txt, mimetype="text/plain")

    return jsonify(report)


# ---------------------------------------------------------------------------
# WSGI pointer for Vercel/python serverless (importable, no Flask run needed).
# ---------------------------------------------------------------------------
def vercel_handler(event, context):
    """
    Optional adapter if you deploy via Vercel Python functions + a WSGI shim
    (e.g. `vercel_python` wsgi). In practice, prefer a bare function:
    see README for the recommended Vercel serverless function example.
    """
    query = event.get("queryStringParameters") or {}
    symbol = query.get("symbol", "")
    if not symbol:
        return {"statusCode": 200, "body": json.dumps({"usage": "?symbol=09868"})}
    try:
        report = build_report(symbol)
        return {"statusCode": 200, "body": json.dumps(report, ensure_ascii=False)}
    except Exception as exc:
        return {"statusCode": 500, "body": json.dumps({"error": str(exc)})}


# ---------------------------------------------------------------------------
# Minimal test-run snippet for the whole stack.
# ---------------------------------------------------------------------------
def smoke_test(symbol: str = "09868") -> None:
    """End-to-end check: data -> TA -> chart -> report (no server needed)."""
    hist = fetch_history(symbol)
    ta = compute_indicators(hist)
    ref = derive_reference_levels(ta)
    png = render_chart(ta, symbol)
    report = build_report(symbol)
    assert len(png) > 0, "chart PNG is empty"
    print(f"[smoke] OK — rows={len(hist)}, chart={len(png)}B, close={ref.get('last_close')}")


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "--smoke":
        smoke_test()
        sys.exit(0)

    port = int(os.getenv("PORT", "8000"))
    app.run(host="0.0.0.0", port=port, debug=False)
