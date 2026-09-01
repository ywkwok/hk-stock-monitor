"""
api/dashboard.py — Vercel Python serverless function.

Vercel maps `/api/dashboard.py` to a request handler. This thin function
imports the core dashboard logic and returns JSON.

IMPORTANT (Vercel serverless constraints):
    - TA-Lib requires the native C library; the default Vercel Python
      runtime may not have it. See README.md "TA-Lib on Vercel" for
      workarounds (amazonlinux build layer / Docker / worker).
    - matplotlib uses Agg backend (no display).
    - Keep this request-handler LIGHT: no backtests, no long loops.
      Heavy jobs belong in a background Worker / cron.

Runtime config: set `vercel.json` python runtime + memory/timeout limits.
"""

import json
import os

# Ensure the core/ package is importable on the serverless function path.
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, ".."))  # project root
sys.path.insert(0, os.path.join(_HERE, "..", "core"))  # core package

from dashboard_app import build_report  # noqa: E402  (flask app object reused)


def handler(request):
    """Vercel Python function entry (serverless)."""
    # request: a Vercel RequestWrapper-like object.
    # If running under Flask's test client or the WSGI shim, params differ;
    # keep it simple and read from query string when possible.
    symbol = ""
    try:
        params = request.query_params or {}
        symbol = (params.get("symbol") or "").strip()
    except Exception:
        # fallback: inspect args
        try:
            symbol = request.args.get("symbol", "").strip()
        except Exception:
            symbol = ""

    if not symbol:
        return {
            "statusCode": 200,
            "body": json.dumps({"usage": "/api/dashboard?symbol=09868"}),
        }

    try:
        report = build_report(symbol)
        return {"statusCode": 200, "body": json.dumps(report, ensure_ascii=False)}
    except Exception as exc:
        return {"statusCode": 500, "body": json.dumps({"error": str(exc)})}
