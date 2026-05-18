<h2 align="center">
  <img width="28%" alt="Brevity logo" src="https://raw.githubusercontent.com/Samasth/brevity/main/assets/logo.svg"><br/>
  Stock Analytics, Distilled<br/>
  <sub>15–25 years of free fundamentals · 5 data sources merged · 100% TOS-clean</sub>
</h2>

<div align="center">

  <a href="LICENSE"><img alt="License" src="https://img.shields.io/badge/license-MIT-blue?style=flat-square"></a>
  <a href="#requirements"><img alt="Python" src="https://img.shields.io/badge/python-3.9%2B-3776AB?logo=python&logoColor=white&style=flat-square"></a>
  <a href="#data-sources"><img alt="Data" src="https://img.shields.io/badge/data-free%20%26%20legal-a3e635?style=flat-square"></a>
  <a href="https://streamlit.io/"><img alt="Streamlit" src="https://img.shields.io/badge/built%20with-streamlit-FF4B4B?logo=streamlit&logoColor=white&style=flat-square"></a>

</div>

<div align="center">

[Quick Start](#quick-start) •
[Data Sources](#data-sources) •
[Fundamentals](#fundamentals-page) •
[Gamma Exposure](#gamma-exposure-page) •
[Privacy](#privacy-and-security) •
[Troubleshooting](#troubleshooting)

</div>

Brevity is a self-hosted stock-analytics dashboard built entirely on **official APIs with explicit free-tier or government-public licensing**. No Yahoo scraping, no TOS-gray libraries, no broken endpoints when a third-party tool gets blocked. It merges five data providers (SEC EDGAR + FMP + Finnhub + Twelve Data + Alpha Vantage) into one bundle, with smart fallback so even FMP-paywalled tickers like recent IPOs still populate. For Apple it surfaces **71 quarterly + 19 annual periods of financials back to 2008**, computed P/E and P/S history per period, real analyst targets, and Forward P/E — all from free APIs.

## Quick Start

```bash
git clone https://github.com/Samasth/brevity.git
cd brevity

python3 -m venv venv
source venv/bin/activate                # Windows: venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env
# Open .env in a text editor and fill in two keys:
#   EDGAR_CONTACT_EMAIL=your@email.com   (no signup, just a contact email)
#   FMP_API_KEY=your-fmp-key             (free 250/day at financialmodelingprep.com)

streamlit run app.py
```

Opens at <http://localhost:8501>. First load per ticker takes ~3–6 seconds (downloads SEC EDGAR companyfacts); subsequent loads are instant from disk cache.

For **richer data** (Forward P/E, longer price history, analyst price targets), add three more **email-only** keys to `.env` — all free, no KYC: `FINNHUB_API_KEY`, `TWELVEDATA_API_KEY`, `ALPHAVANTAGE_API_KEY`.

## Main Features

- **15–25 years of historical financials** via SEC EDGAR — deeper than any free alternative for major US filers
- **5-source merged data pipeline** — graceful fallback (FMP → Finnhub → Twelve Data → Alpha Vantage → EDGAR-TTM) so paywalled tickers (CRWV, NBIS, recent IPOs) still populate
- **Computed historical P/E and P/S** — per-period from FMP price history × EDGAR diluted shares × TTM earnings/revenue; works for unprofitable companies too
- **Forward P/E derived from analyst estimates** for tickers where pre-computed values aren't free (annualizes Finnhub's upcoming-earnings EPS estimates)
- **Real revenue CAGR** (not per-share growth) computed from EDGAR annual data — overrides FMP's misleading "per-share" growth values
- **Expand-to-modal charts** with raw data tables for every metric
- **Gamma Exposure page** for options-savvy users (free Tradier or paid Polygon)
- **Zero scraping, zero TOS-gray** — every source is an official API with explicit free-tier permission or US government public data
- **Local-first** — your tickers never leave your machine without an explicit data fetch
- **Disk-cached** — 24h on fundamentals, 5–15 min on quotes — fast reloads, light on rate limits

## Requirements

- **Python 3.9 or newer** (3.10+ recommended)
- macOS, Linux, or Windows
- A modern browser

Dependencies (auto-installed): `streamlit`, `plotly`, `pandas`, `numpy`, `requests`, `python-dotenv`.

## Data Sources

| Source | What it provides | Signup | Free tier | Required? |
|---|---|---|---|---|
| **SEC EDGAR** | 15–25y quarterly + annual financials for any US public co. | No signup — just an email in `User-Agent` | No rate limit (10 req/sec ceiling) | ✓ Required |
| **Financial Modeling Prep** | Current quote, profile (logo, sector), TTM ratios, 5y daily prices | Email only at <https://site.financialmodelingprep.com/developer/docs> | 250 req/day | ✓ Required |
| **Finnhub** | Fills FMP-paywalled tickers. 50+ comprehensive ratios. Forward P/E pre-computed. Earnings calendar. | Email only at <https://finnhub.io/register> | 60 req/min | Recommended |
| **Twelve Data** | Extended price history for paywalled tickers (up to 5y vs AV's 100-day cap) | Email only at <https://twelvedata.com/account> | 800 req/day, 8 req/min | Optional |
| **Alpha Vantage** | Analyst consensus price target (Finnhub gates that on premium) | Email only at <https://www.alphavantage.co/support/#api-key> | 25 req/day | Optional |
| **Tradier** *(Gamma Exposure only)* | Option chains for the GEX page | Free brokerage account (KYC) | Free market-data | Optional |
| **Polygon** *(Gamma Exposure only)* | Option chains for the GEX page | Email only at <https://polygon.io/dashboard/signup> | $29/mo Options Starter (no KYC) | Optional |

EDGAR + FMP alone cover the core Fundamentals page. The other three fill remaining gaps for recent IPOs, unprofitable tickers, and analyst data. **Priority chain per field**: FMP → Finnhub → Twelve Data → Alpha Vantage → EDGAR-derived TTM.

## Fundamentals Page

Per-ticker dashboard with:

- **Header card** — logo, sector, current price + today's change, market cap, shares outstanding, 52-week range, analyst price target with implied upside, next earnings date
- **TTM stats grid** — Earnings-Based Valuation (P/E, Forward P/E, PEG, Forward PEG, Earnings Yield), Revenue & Cash Flow Metrics (P/S, P/CF, P/FCF, FCF Yield), Asset-Based (P/B, D/E), Enterprise Value Multiples (EV/EBITDA, EV/Sales), Profitability (Margin, ROE, ROIC), Growth CAGR (Revenue 3y/5y/10y), Financial Health (FCF, NI, Net Debt)
- **Chart wall** — 14 charts: Stock Price (5Y), Revenue, EBITDA, Gross Profit, Gross Profit Margin, Net Income, Cash from Operations, Free Cash Flow, EPS, CapEx, Cash & Debt, Operating Income, P/E History, P/S History — with Quarterly / Annual toggle
- **Expand-to-modal** — every chart has a ⛶ button that opens a full-size view + raw values data table

## Gamma Exposure Page

Optional second page for options analytics:

- Dealer GEX by strike, gamma flip, call/put walls, regime classification
- 8 expiration filter presets: All, 0DTE, ex-0DTE, This Week, Next 2 Weeks, Next 30 Days, Monthly OPEX, Quarterly OPEX, plus per-date selection
- Black-Scholes gamma fallback when the provider doesn't supply pre-computed greeks
- Works with either Tradier (free, requires brokerage account) or Polygon (paid, email-only signup)

## Privacy and Security

- **Your tickers never leave your machine** unless you explicitly trigger a data fetch — and even then, only the ticker symbol goes to the configured provider. No portfolio data is uploaded anywhere.
- **`.env` is gitignored** — your API keys never get committed.
- **Cached API responses** live in `~/.cache/brevity/`, outside the project directory.
- **No telemetry** of any kind. Brevity makes one outbound request per data fetch, directly to the configured provider.

If you accidentally commit a key, rotate it immediately — every provider lets you regenerate from their dashboard in under a minute.

## Project Structure

```
brevity/
├── app.py                       # Streamlit entry point + sidebar + page router
├── fundamentals_ui.py           # Fundamentals page UI
├── gex_ui.py                    # Gamma Exposure page UI
├── gamma_exposure.py            # GEX math (Black-Scholes fallback + greeks aggregation)
├── data_sources/
│   ├── base.py                  # Protocols + dataclasses
│   ├── cache.py                 # Disk cache at ~/.cache/brevity/
│   ├── edgar.py                 # SEC EDGAR adapter (15–25y historicals)
│   ├── fmp.py                   # FMP adapter (quote, profile, ratios, prices)
│   ├── finnhub.py               # Finnhub adapter (ratios, forward P/E, earnings calendar)
│   ├── twelvedata.py            # Twelve Data adapter (extended price history)
│   ├── alphavantage.py          # Alpha Vantage adapter (analyst target)
│   ├── merged.py                # Composes all five into one FundamentalsBundle
│   ├── polygon.py               # Polygon options adapter (GEX page)
│   └── tradier.py               # Tradier options adapter (GEX page)
├── assets/
│   ├── logo.svg
│   └── banner.svg
├── requirements.txt
├── .env.example
└── .gitignore
```

## What Brevity intentionally does not do

- **No scraping** of Yahoo Finance / Stockanalysis.com / macrotrends / TradingView
- **No yfinance** — widely used but technically violates Yahoo's TOS
- **No portfolio tracking** — by design, this is a research tool
- **No AI features yet** — coming as an optional premium add-on (see roadmap)

## Troubleshooting

**"No data for TICKER" on the Fundamentals page**
EDGAR only covers US public companies that file 10-K / 10-Q in USD. Foreign private issuers (NBIS, etc.) often file 20-F in their home currency. FMP's free tier paywalls newer IPOs and smaller-cap names — adding `FINNHUB_API_KEY` to `.env` usually fills them.

**Charts show fewer periods than expected**
Free-tier coverage depth depends on how long the company has been filing — recent IPOs only have data going back to their first 10-Q. For SP500-level names you should see 15+ years of quarterly data.

**Gamma Exposure page shows "No options-data provider configured"**
Expected if you haven't added a Polygon or Tradier key. The Fundamentals page is unaffected.

**"Legacy Endpoint" error from FMP**
FMP retired their `/api/v3/` endpoints on Aug 31, 2025 for new keys. Brevity uses the new `/stable/` API — make sure you're on the latest code.

**Alpha Vantage shows `—` for analyst target after a few tickers**
AV free tier is 5 req/min. With 24h disk caching this is rare in normal use; if you hit it, wait a minute and refresh.

**Streamlit's port 8501 is in use**
Either close the other app or run with `streamlit run app.py --server.port=8502`.

**SPX options not showing in GEX**
Free providers don't cover SPX cash-settled options. Use `SPY` instead (strikes divide by ~10).

## Contributing

The `data_sources/` abstraction makes it easy to add new providers — just implement `FundamentalsSource` or `OptionsSource` from `data_sources/base.py`.

PRs especially welcome for:
- **Interactive Brokers** adapter (TWS/Gateway integration)
- **EODHD** adapter
- **Schwab API** adapter

## License

MIT — do whatever you want with it. Not financial advice.
