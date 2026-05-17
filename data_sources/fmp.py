"""Financial Modeling Prep adapter — uses the /stable/ API.

In brevity, FMP fills in what EDGAR doesn't provide:
  - Current quote (price, change, market cap, today's volume)
  - Company profile (logo, sector, industry, website, CEO)
  - Current TTM ratios (P/E, P/S, P/B, EV/EBITDA, ROE, ROIC, margins…)
  - Next earnings date
  - Daily price history (FMP free returns up to 5y)

Historical quarterly/annual financials come from EDGAR (deeper + free), so
this adapter does NOT pull income/cash-flow/balance-sheet statements.

Free tier: 250 req/day, signup at https://site.financialmodelingprep.com/.
With 24h caching on profile/ratios and 5min on quote, easily fits the limit.
"""
from __future__ import annotations

import os
from datetime import date, timedelta
from typing import Any

import requests

from . import cache
from .base import CompanyProfile, KeyMetricsTTM, PricePoint, Quote

BASE = "https://financialmodelingprep.com/stable"
TIMEOUT = 12

TTL_QUOTE = 300              # 5 min
TTL_PROFILE = 24 * 3600      # 24 h
TTL_RATIOS = 24 * 3600       # 24 h
TTL_PRICE_HISTORY = 6 * 3600


def _f(x: Any) -> float | None:
    if x is None or x == "":
        return None
    try:
        v = float(x)
        if v != v:  # NaN
            return None
        return v
    except (TypeError, ValueError):
        return None


class FMPSource:
    name = "fmp"

    def __init__(self, api_key: str | None = None):
        self.api_key = (api_key or os.getenv("FMP_API_KEY", "")).strip()

    @property
    def available(self) -> bool:
        return bool(self.api_key)

    # ─── HTTP ────────────────────────────────────────────────────────────

    def _get(self, path: str, params: dict | None = None, ttl: int = TTL_PROFILE) -> Any:
        params = dict(params or {})
        params["apikey"] = self.api_key

        cache_key = f"fmp__{path}__" + "&".join(
            f"{k}={v}" for k, v in sorted(params.items()) if k != "apikey"
        )
        hit = cache.get(cache_key, ttl)
        if hit is not None:
            return hit
        try:
            r = requests.get(f"{BASE}/{path}", params=params, timeout=TIMEOUT)
            if r.status_code == 402:
                # Per-ticker paywall (newer IPOs, smaller caps, ADRs).
                # Silent — let the merged source decide whether to surface it.
                return None
            r.raise_for_status()
            data = r.json()
        except (requests.RequestException, ValueError):
            return None
        cache.put(cache_key, data)
        return data

    # ─── Profile ─────────────────────────────────────────────────────────

    def get_profile(self, ticker: str) -> CompanyProfile:
        data = self._get("profile", {"symbol": ticker}, ttl=TTL_PROFILE)
        if not isinstance(data, list) or not data:
            return CompanyProfile(ticker=ticker)
        d = data[0]
        return CompanyProfile(
            ticker=ticker,
            name=d.get("companyName") or "",
            exchange=d.get("exchange") or d.get("exchangeFullName"),
            sector=d.get("sector"),
            industry=d.get("industry"),
            website=d.get("website"),
            image=d.get("image"),
            description=d.get("description"),
            country=d.get("country"),
            ceo=d.get("ceo"),
            employees=int(d["fullTimeEmployees"]) if d.get("fullTimeEmployees") else None,
        )

    # ─── Quote ───────────────────────────────────────────────────────────

    def get_quote(self, ticker: str) -> Quote:
        q = Quote(ticker=ticker)

        data = self._get("quote", {"symbol": ticker}, ttl=TTL_QUOTE)
        if isinstance(data, list) and data:
            d = data[0]
            q.price = _f(d.get("price")) or 0.0
            q.change = _f(d.get("change")) or 0.0
            q.change_pct = _f(d.get("changePercentage")) or 0.0
            q.market_cap = _f(d.get("marketCap"))
            q.week52_high = _f(d.get("yearHigh"))
            q.week52_low = _f(d.get("yearLow"))
            q.avg_volume = _f(d.get("volume"))

        # Shares outstanding from profile (quote stable doesn't return it)
        prof = self._get("profile", {"symbol": ticker}, ttl=TTL_PROFILE)
        if isinstance(prof, list) and prof:
            mc = _f(prof[0].get("marketCap"))
            price = _f(prof[0].get("price"))
            if mc and price and price > 0:
                q.shares_outstanding = mc / price

        # Next earnings — filter the earnings endpoint for upcoming events.
        # Free tier rejects `limit`, so omit it.
        cal = self._get("earnings", {"symbol": ticker}, ttl=TTL_PROFILE)
        if isinstance(cal, list) and cal:
            today = date.today().isoformat()
            future = [
                e for e in cal
                if e.get("date", "") >= today and e.get("epsActual") is None
            ]
            future.sort(key=lambda e: e.get("date", ""))
            if future:
                q.next_earnings_date = future[0].get("date")

        return q

    # ─── TTM Ratios ──────────────────────────────────────────────────────

    def get_metrics_ttm(self, ticker: str, *, market_cap: float | None = None) -> KeyMetricsTTM:
        """Current trailing-twelve-month ratios. None on FMP free-tier paywall."""
        m = KeyMetricsTTM()

        km = self._get("key-metrics-ttm", {"symbol": ticker}, ttl=TTL_RATIOS)
        if isinstance(km, list) and km:
            d = km[0]
            m.earnings_yield = _f(d.get("earningsYieldTTM"))
            m.ev_to_ebitda = _f(d.get("evToEBITDATTM"))
            m.ev_to_sales = _f(d.get("evToSalesTTM"))
            m.fcf_yield = _f(d.get("freeCashFlowYieldTTM"))
            m.roe = _f(d.get("returnOnEquityTTM"))
            m.roic = _f(d.get("returnOnInvestedCapitalTTM"))

        ratios = self._get("ratios-ttm", {"symbol": ticker}, ttl=TTL_RATIOS)
        if isinstance(ratios, list) and ratios:
            d = ratios[0]
            m.pe = _f(d.get("priceToEarningsRatioTTM"))
            m.peg = _f(d.get("priceToEarningsGrowthRatioTTM"))
            m.forward_peg = _f(d.get("forwardPriceToEarningsGrowthRatioTTM"))
            m.price_to_sales = _f(d.get("priceToSalesRatioTTM"))
            m.price_to_book = _f(d.get("priceToBookRatioTTM"))
            m.price_to_cash_flow = _f(d.get("priceToOperatingCashFlowRatioTTM"))
            m.price_to_free_cash_flow = _f(d.get("priceToFreeCashFlowRatioTTM"))
            m.profit_margin = _f(d.get("netProfitMarginTTM"))
            m.operating_margin = _f(d.get("operatingProfitMarginTTM"))
            m.debt_to_equity = _f(d.get("debtToEquityRatioTTM"))
            if m.earnings_yield is None and m.pe:
                m.earnings_yield = 1.0 / m.pe

        # Revenue growth CAGR (annual)
        fg = self._get("financial-growth", {"symbol": ticker, "period": "annual", "limit": 1})
        if isinstance(fg, list) and fg:
            d = fg[0]
            m.revenue_growth_3y = _f(d.get("threeYRevenueGrowthPerShare"))
            m.revenue_growth_5y = _f(d.get("fiveYRevenueGrowthPerShare"))
            m.revenue_growth_10y = _f(d.get("tenYRevenueGrowthPerShare"))

        return m

    # ─── Price history ───────────────────────────────────────────────────

    def get_prices(self, ticker: str, days: int = 1825) -> list[PricePoint]:
        start = (date.today() - timedelta(days=days)).isoformat()
        data = self._get(
            "historical-price-eod/light",
            {"symbol": ticker, "from": start},
            ttl=TTL_PRICE_HISTORY,
        )
        if not isinstance(data, list):
            return []
        out = [
            PricePoint(date=r["date"], close=_f(r.get("price")) or 0.0)
            for r in data if r.get("date") and _f(r.get("price"))
        ]
        out.sort(key=lambda p: p.date)
        return out
