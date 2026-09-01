# hk-stock-monitor

Hong Kong stock **automatic monitoring & technical-analysis dashboard**.
Input a HK stock code (e.g. `09868`, `06082`) → fetch OHLC history → compute TA-Lib indicators
(SMA-2 / SMA-19 / SMA-50 + Bollinger Bands) → render a matplotlib chart (Agg, server-safe) →
return a structured text report with short-term high/low reference levels and scraped news snippets.

> **Compliance note:** This project outputs **reference data only**. It contains **no buy/sell
> decision logic and no investment recommendation**. All signals are for reference.

---

## 1. Project Overview

| Area | Choice |
|------|--------|
| Language | Python 3.11 |
| Data sources | Stooq CSV + Yahoo Finance chart API (free, no key) |
| News | `requests` + `BeautifulSoup4` (AAStocks public news page) |
| TA engine | `TA-Lib` (SMA-2/19/50, Bollinger 20,2) |
| Charting | `matplotlib` with **Agg** backend (no GUI) |
| Backtest skeleton | `backtrader` (offline / Worker only) |
| ML boilerplate | `scikit-learn` (feature engineering, no shipped model) |
| Web UI | **Streamlit** (`app.py`, primary front-end) |
| Persistence | Supabase (`stock_monitor_log` table + `stock-charts` storage bucket) |
| Hosting | **Streamlit Community Cloud** (auto-deploy from GitHub) |

---

## 2. Folder Tree

```text
hk-stock-monitor/
├── app.py                     # Streamlit front-end (primary UI)
├── api/
│   ├── __init__.py
│   └── dashboard.py            # (optional) Vercel/Flask serverless adapter
├── core/
│   ├── __init__.py
│   ├── ta_engine.py            # TA-Lib indicators + reference levels
│   ├── news_scraper.py         # requests + bs4 news fetch
│   ├── data_fetcher.py         # OHLC history (Stooq / Yahoo)
│   ├── chart.py                # matplotlib Agg chart renderer
│   ├── auto_monitor.py         # auto-monitor polling engine
│   ├── backtrader_backtest.py  # backtrader harness skeleton
│   ├── ml_helper.py            # scikit-learn feature boilerplate
│   ├── dashboard_app.py        # (legacy) Flask entry + build_report()
│   └── supabase_store.py       # Supabase persistence (snapshot + chart)
├── supabase/
│   └── schema.sql              # table + RLS policies
├── .streamlit/
│   └── secrets.toml.example    # Streamlit secrets template (no real values)
├── requirements.txt
├── vercel.json                 # (optional) legacy Vercel config
├── .env.example
├── .gitignore
└── README.md
```

---

## 3. Local Test Steps

```bash
# 1. Create venv & install deps
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 2. TA-Lib is OPTIONAL — the pure-pandas fallback is used if missing.
#    See "TA-Lib installation" below if you want the fast path.

# 3. (Optional) copy the Streamlit secrets template and fill Supabase keys
cp .streamlit/secrets.toml.example .streamlit/secrets.toml

# 4. End-to-end smoke test (no server, no Supabase needed)
python core/dashboard_app.py --smoke   # or the direct pipeline test below

# 5. Run each module standalone
python core/ta_engine.py              # indicator self-test (random data)
python core/data_fetcher.py 09868     # fetch real OHLC
python core/auto_monitor.py 09868     # one monitor cycle (data + news)
python core/backtrader_backtest.py 09868  # backtrader harness
python core/ml_helper.py              # feature engineering demo
python core/supabase_store.py         # prints Supabase readiness (no creds = False)

# 6. Run the Streamlit dashboard (primary UI)
streamlit run app.py                  # http://localhost:8501

# 7. (Legacy) backend-only Flask dashboard
pip install flask && python core/dashboard_app.py   # http://127.0.0.1:8000/?symbol=09868
```

**Smoke output example:**
```text
[smoke] OK — rows=120, chart=45231B, close=27.31
```

---

## 4. TA-Lib Installation (⚠️ important)

`TA-Lib` is a **Python wrapper around a native C library** (`libta-lib`). You must install the C
library first, then the pip wheel:

```bash
# macOS
brew install ta-lib

# Debian / Ubuntu (build from source)
sudo apt-get install build-essential wget
wget http://prdownloads.sourceforge.net/ta-lib/ta-lib-0.4.0-src.tar.gz
tar -xzf ta-lib-0.4.0-src.tar.gz && cd ta-lib && ./configure --prefix=/usr && make && sudo make install

# then
pip install TA-Lib>=0.7.1
```

> **Version note:** use **TA-Lib 0.7.x** (not 0.4.x). Newer releases support
> numpy>=2 and Python 3.12; 0.4.x fails to build against numpy 2 (`PyArray_Descr`
> `subarray` / `NPY_DEFAULT` errors).

If `pip install TA-Lib` fails (or you cannot install the C library — e.g. a Mac with broken
Homebrew, or Windows without the DLL), you now have **this option**:

### ✅ You don't actually need TA-Lib anymore (pure-pandas fallback)

`core/ta_engine.py` now ships with a **pure-pandas fallback** for SMA/Bollinger. It auto-detects:
- If TA-Lib is importable → uses **TA-Lib** (engine reported as `TA-Lib`).
- Otherwise → uses **pandas** (engine reported as `pandas (fallback)`).

The fallback produces **identical values** (verified to 6 decimal places on real data). So you can
skip TA-Lib entirely and just install the rest:

```bash
# Minimal install that runs EVERYTHING except the optional TA-Lib fast-path:
pip install pandas numpy matplotlib requests beautifulsoup4 lxml python-dotenv
pip install backtrader scikit-learn    # optional modules
```

Then `ta_engine` automatically uses the fallback. Check which engine is active:
```python
from ta_engine import ENGINE, HAS_TALIB
print(ENGINE)   # 'TA-Lib' or 'pandas (fallback)'
```

> The reference report also includes an `"engine"` field so you always know which backend ran.

**Other install options if you still want TA-Lib:**
1. Install the C library (above) then retry.
2. Prebuilt wheel: `pip install ta-lib --only-binary :all:` (if one matches your OS/arch).
3. Windows: grab the prebuilt `ta-lib-0.4.0-msvc.zip` DLL from the official site, unzip to
   `C:\ta-lib`, add to PATH, then `pip install TA-Lib`.

---

## 5. Streamlit + Supabase Deployment

### 5.1 Architecture

- **Front-end UI**: `app.py` — a Streamlit app (no Flask / no JS build needed).
- **Persistence**: Supabase `stock_monitor_log` table (`supabase/schema.sql`) + a
  `stock-charts` storage bucket (`core/supabase_store.py` creates it on demand).
- **Hosting**: Streamlit Community Cloud — connects to your GitHub repo and
  auto-deploys on every `main` push.

### 5.2 Required secrets (never commit these)

| Key | Where | Sensitive? |
|-----|-------|------------|
| `SUPABASE_URL` | `.streamlit/secrets.toml` (local) / Streamlit Cloud Secrets | public |
| `SUPABASE_SERVICE_ROLE_KEY` | Streamlit Cloud Secrets (server-side) | **secret — never in git / client** |

> The `service_role` key bypasses RLS. It is only used server-side inside
> `core/supabase_store.py`. Do **not** use the public anon key for writes.

>`/.streamlit/secrets.toml` is gitignored — see `.gitignore`. Template:
>`/.streamlit/secrets.toml.example`.

### 5.3 Local run

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
# optional: fill .streamlit/secrets.toml from the example template
streamlit run app.py
# open http://localhost:8501
```

### 5.4 Deploy to Streamlit Community Cloud

1. Push this repo to **GitHub** (private).
2. Go to **share.streamlit.io** -> **Create app** -> connect the repo.
3. Set **Main file path**: `app.py`.
4. Under **Advanced settings -> Secrets**: paste `SUPABASE_URL` and
   `SUPABASE_SERVICE_ROLE_KEY` (server-side key).
5. Deploy. Every push to `main` auto-redeploys.

### 5.5 Set up Supabase

1. Create a project at [supabase.com](https://supabase.com).
2. In the **SQL Editor**, run `supabase/schema.sql` (creates `stock_monitor_log` + RLS).
3. Create a storage bucket named **`stock-charts`** (Settings -> Storage), or let
   `core/supabase_store.py` create it on first run (requires the bucket creation
   permission on the service-role key).
4. Copy `SUPABASE_URL` + `SUPABASE_SERVICE_ROLE_KEY` into Streamlit Secrets.

### 5.6 Legacy Vercel adapter (optional)

`api/dashboard.py` + `vercel.json` are kept for reference; the primary UI is
Streamlit. To run the backend-only report endpoint on Vercel, follow the old
instructions under `api/dashboard.py` and set the same Supabase env vars there.

---

## 6. GitHub Push Hint

```bash
cd hk-stock-monitor
git init
git add .
git commit -m "feat: HK stock monitor (Streamlit + Supabase)"
git branch -M main
git remote add origin git@github.com:<you>/hk-stock-monitor.git
git push -u origin main
```

> `.gitignore` already excludes `secrets.toml`, `.env*`, `.vercel/`, `__pycache__`, `*.png` — **never commit secrets.**
> After pushing, connect the repo in **Streamlit Community Cloud** → auto-deploys on `main` push.

---

## 7. Compliance & Legal

- **No investment advice:** this project returns computed indicators and reference levels only.
  It does not recommend buy/sell actions.
- **Scraping:** news scraping inserts a polite delay between requests and keeps volume low, but
  **scraping a public website may violate its Terms of Service** — review the target site's ToS and
  prefer official APIs where available.
- **Data sources:** Stooq / Yahoo are free, may be rate-limited or change without notice. No private
  paid financial API is used.
