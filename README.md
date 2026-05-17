# Brevity

A free, legal, self-hosted stock-analytics dashboard built on **SEC EDGAR**, **Financial Modeling Prep**, **Finnhub**, **Twelve Data**, and (optionally) **Polygon / Tradier** for options data. No scraping, no TOS-gray sources — every data feed is an official API with explicit free-tier permission or US government public data.

## Two pages

| Page | What it shows | Required keys |
|---|---|---|
| **Fundamentals** | Company header, TTM ratios (P/E, P/S, P/B, EV/EBITDA, ROE, ROIC, margins), 15–25 years of quarterly + annual financials, 5-year price history, expand-to-modal data tables | EDGAR contact email + FMP API key (both free) |
| **Gamma Exposure** (optional) | Dealer GEX by strike, gamma flip, call/put walls, regime classification, 8 expiration-filter presets | One of: Polygon, Tradier, or IBKR (see below) |

## Why brevity exists

Most "free stock dashboard" projects scrape Yahoo Finance and break when Yahoo changes its endpoints — and arguably violate Yahoo's TOS. brevity was built to be:

- **Free** for the core (Fundamentals page) with email-only signups
- **Deeper** than most paid dashboards for historicals — SEC EDGAR has 15–25 years of quarterly data for major US filers, vs ~5 periods on most free APIs
- **Legal** — every source has explicit commercial-use permission on its free/paid tier, or is US government public data
- **BYOK** — your API keys live in your `.env`, the app runs locally, your data stays on your machine

## Requirements

- **Python 3.9 or newer** (3.10+ recommended)
- macOS, Linux, or Windows
- A modern browser

Dependencies (installed by `pip install -r requirements.txt`):
`streamlit`, `plotly`, `pandas`, `numpy`, `requests`, `python-dotenv`.

## Quick start

```bash
# 1. Clone
git clone https://github.com/<you>/brevity.git
cd brevity

# 2. Virtual environment (recommended)
python3 -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate

# 3. Install
pip install -r requirements.txt

# 4. Configure your keys
cp .env.example .env
# Open .env in a text editor and fill in keys (see "Data sources" below)

# 5. Run
streamlit run app.py
```

The app opens at <http://localhost:8501>. Stop it with `Ctrl+C`.

## Data sources

### Required for Fundamentals (free, email-only)

| Source | What it provides | Signup | Cost |
|---|---|---|---|
| **SEC EDGAR** | 15–25y of quarterly + annual financials for any US public company | No signup — just put any contact email in `.env` | Free, no rate limit (10 req/sec fair-use ceiling) |
| **Financial Modeling Prep** | Current quote, company profile (logo, sector), TTM ratios, 5y daily price history | Email signup at <https://site.financialmodelingprep.com/developer/docs> | Free 250 req/day |
| **Finnhub** *(recommended)* | Fills FMP-paywalled tickers (recent IPOs like CRWV, smaller caps). Forward P/E pre-computed. ~50-field comprehensive ratios. | Email signup at <https://finnhub.io/register> | Free 60 req/min |
| **Alpha Vantage** *(optional)* | Analyst consensus price target (Finnhub gates this on premium) | Email signup at <https://www.alphavantage.co/support/#api-key> | Free 25 req/day (5/min) |

**Recommended setup** is EDGAR + FMP + **Finnhub** — that combo populates everything except analyst price target. EDGAR + FMP alone leaves Forward P/E and the per-ticker-paywalled fields (CRWV-style) empty. Add Alpha Vantage only if you want the analyst price target row in the header.

**Priority chain per field**: FMP → Finnhub → Alpha Vantage → EDGAR-derived TTM. Each source fills whatever the one above it left None, so adding more keys can only help.

### Optional — pick one for Gamma Exposure

The Gamma Exposure page needs an options-chain provider. Each has different tradeoffs:

| Provider | Cost | Signup difficulty | Notes |
|---|---|---|---|
| **Polygon.io** | $29/mo Options Starter | **Easy** — email only, no KYC, no SSN, no brokerage account | Recommended for most users. Full chains, greeks, real-time. |
| **Tradier** | Free market-data | **Hard** — requires brokerage account application (SSN, US address, KYC). Public form gates to US citizen / permanent resident. | Best value if you can get through KYC. H1B holders should email support@tradier.com directly. |
| **Interactive Brokers** | Free (~$4.50/mo for OPRA options data) | **Medium** — brokerage account, but IBKR accepts H1B and most international users without issue | IBKR's API uses TWS/Gateway running locally. **brevity does not yet ship an IBKR adapter** — contributions welcome. |

If none of these are configured, the Gamma Exposure page displays a clear "configure a provider" panel with links — the Fundamentals page is unaffected.

### Putting it in `.env`

```
EDGAR_CONTACT_EMAIL=your.name@example.com
FMP_API_KEY=your-fmp-key-here

# Recommended — fills FMP-paywalled tickers + Forward P/E
FINNHUB_API_KEY=

# Optional — only needed for analyst price target row
ALPHAVANTAGE_API_KEY=

# Optional — pick one for the Gamma Exposure page
POLYGON_API_KEY=
TRADIER_TOKEN=
TRADIER_ENV=sandbox
```

You can also paste keys into the sidebar inside the app, but `.env` is more convenient for repeated runs. **The `.env` file is gitignored** — your keys never get committed.

## Platform notes

### macOS
- Python 3.9 ships with macOS but may show a harmless `NotOpenSSLWarning` from urllib3. To silence it: install Python via Homebrew (`brew install python@3.11`) or pyenv.
- For faster file watching: `pip install watchdog`.

### Linux
```bash
sudo apt update
sudo apt install python3 python3-venv python3-pip
```

### Windows
- Install Python from <https://www.python.org/downloads/> (check "Add to PATH").
- Activate the venv with `venv\Scripts\activate`.
- If `streamlit` isn't recognized after install, restart your terminal.

## Privacy and security

- **Your tickers never leave your machine** unless you fetch data — and even then, only the ticker symbol goes to the data provider. No portfolio data is uploaded anywhere.
- **`.env` is gitignored** by default. Your API keys never get committed.
- **Cached API responses** live in `~/.cache/brevity/`, outside the project directory. They contain only the data the API returned, never your keys.
- **No telemetry** of any kind. brevity makes one outbound request per data fetch, directly to the configured provider.

If you accidentally commit a key, rotate it immediately — every provider lets you regenerate from their dashboard in under a minute.

## Project structure

```
brevity/
├── app.py                       # Streamlit entry point + sidebar + page router
├── fundamentals_ui.py           # Fundamentals page
├── gex_ui.py                    # Gamma Exposure page
├── gamma_exposure.py            # GEX math (Black-Scholes fallback + greeks aggregation)
├── data_sources/
│   ├── base.py                  # Protocols + dataclasses
│   ├── cache.py                 # Disk cache at ~/.cache/brevity/
│   ├── edgar.py                 # SEC EDGAR adapter (15-25y historicals)
│   ├── fmp.py                   # FMP adapter (quote, profile, ratios, prices)
│   ├── merged.py                # Composes EDGAR + FMP for the Fundamentals page
│   ├── polygon.py               # Polygon options adapter
│   └── tradier.py               # Tradier options adapter
├── requirements.txt
├── .env.example                 # Copy to .env and fill in
└── .gitignore
```

## What brevity intentionally doesn't do

- **No scraping** of Yahoo Finance, Stockanalysis.com, macrotrends, TradingView, etc. — all use TOS-gray paths.
- **No yfinance** — the library is widely used but technically violates Yahoo's TOS. brevity keeps signup-free legality by using SEC EDGAR + FMP free tier instead.
- **No AI features** — those add cost and lock-in. If you want AI risk analysis, check the sister project `market-pulse`.
- **No portfolio tracking** — by design. brevity is a research tool, not a positions tracker.

## Troubleshooting

**"No data for TICKER" on the Fundamentals page**
EDGAR only covers US public companies that file 10-K / 10-Q in USD. Foreign private issuers (NBIS, etc.) often file 20-F in their home currency and aren't fully covered. FMP's free tier paywalls newer IPOs and smaller-cap names. Try a different ticker, or upgrade to FMP Starter for broader coverage.

**Fundamentals chart shows fewer periods than expected**
Free-tier coverage depth depends on how long the company has been filing — recent IPOs only have data going back to their first 10-Q. For SP500-level names you should see 15+ years of quarterly data.

**Gamma Exposure page shows "No options-data provider configured"**
That's expected if you haven't added a Polygon, Tradier, or IBKR key. The Fundamentals page is unaffected. To enable GEX, sign up for one of the three providers in the **Optional (Gamma Exposure)** sidebar section.

**"Legacy Endpoint" error from FMP**
FMP retired their `/api/v3/` endpoints on Aug 31, 2025 for new keys. brevity uses the new `/stable/` API — make sure you're on the latest code.

**Streamlit's port 8501 is in use**
Either close the other Streamlit app or run with `streamlit run app.py --server.port=8502`.

**SPX options not showing**
Free providers don't cover SPX cash-settled options. Use `SPY` (the ETF) instead — strike levels divide by ~10.

## Contributing

This is a personal project shared as-is. The `data_sources/` abstraction makes it easy to add new providers:

- Implement `FundamentalsSource` from `data_sources/base.py` for company data
- Implement `OptionsSource` from `data_sources/base.py` for option chains

PRs welcome — especially for an Interactive Brokers adapter (TWS/Gateway integration), an EODHD adapter, or a Schwab adapter.

## License

MIT. Not financial advice.
