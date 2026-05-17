"""Alpha Vantage adapter — fills FMP free-tier gaps.

Alpha Vantage's free tier is far more permissive than FMP's per-ticker
paywall: tickers like CRWV / NBIS / recent IPOs that FMP 402s come back fine
on AV. So we use AV as a **fallback** for paywalled tickers — for forward
P/E + analyst target on FMP-covered names, but for ALL of quote+ratios+
profile on FMP-paywalled names.

Endpoints used:
  - OVERVIEW       — ~50 fields: ratios, margins, growth, target, market cap
  - GLOBAL_QUOTE   — current price + change (fallback when FMP price = 0)

Docs:   https://www.alphavantage.co/documentation/
Signup: https://www.alphavantage.co/support/#api-key
Free tier: 25 calls/day, 5 calls/minute.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import requests

from . import cache
from .base import PricePoint

BASE = "https://www.alphavantage.co/query"
TIMEOUT = 15
TTL_OVERVIEW = 24 * 3600
TTL_QUOTE = 15 * 60
TTL_DAILY = 12 * 3600


@dataclass
class AVOverview:
    """Subset of Alpha Vantage OVERVIEW fields we actually consume."""
    # Profile
    name: str | None = None
    sector: str | None = None
    industry: str | None = None
    country: str | None = None
    exchange: str | None = None
    description: str | None = None
    # Quote-like
    market_cap: float | None = None
    shares_outstanding: float | None = None
    week52_high: float | None = None
    week52_low: float | None = None
    # Ratios
    forward_pe: float | None = None
    trailing_pe: float | None = None
    peg: float | None = None
    price_to_book: float | None = None
    price_to_sales_ttm: float | None = None
    ev_to_ebitda: float | None = None
    ev_to_revenue: float | None = None
    # Margins / returns
    profit_margin: float | None = None
    operating_margin: float | None = None
    roe: float | None = None
    roa: float | None = None
    # Earnings / cash
    revenue_ttm: float | None = None
    gross_profit_ttm: float | None = None
    eps_ttm: float | None = None
    ebitda: float | None = None
    # Other
    analyst_target_price: float | None = None
    beta: float | None = None
    dividend_yield: float | None = None


@dataclass
class AVQuote:
    price: float | None = None
    change: float | None = None
    change_pct: float | None = None
    volume: int | None = None


def _f(x: Any) -> float | None:
    """AV returns numbers as strings; 'None', '-', '', 'NaN' all mean missing."""
    if x is None:
        return None
    s = str(x).strip()
    if not s or s in ("None", "-", "NaN"):
        return None
    try:
        v = float(s)
        if v != v:
            return None
        return v
    except (TypeError, ValueError):
        return None


def _str(x: Any) -> str | None:
    if x is None:
        return None
    s = str(x).strip()
    if not s or s in ("None", "-"):
        return None
    return s


class AlphaVantageSource:
    name = "alphavantage"

    def __init__(self, api_key: str | None = None):
        self.api_key = (api_key or os.getenv("ALPHAVANTAGE_API_KEY", "")).strip()

    @property
    def available(self) -> bool:
        return bool(self.api_key)

    def _get(self, function: str, params: dict, ttl: int) -> dict | None:
        if not self.available:
            return None
        params = {"function": function, "apikey": self.api_key, **params}
        cache_key = f"av__{function}__" + "&".join(
            f"{k}={v}" for k, v in sorted(params.items()) if k != "apikey"
        )
        data = cache.get(cache_key, ttl)
        if data is None:
            try:
                r = requests.get(BASE, params=params, timeout=TIMEOUT)
                if r.status_code != 200:
                    return None
                data = r.json()
            except (requests.RequestException, ValueError):
                return None
            if not isinstance(data, dict):
                return None
            # Rate-limit / info messages instead of real data — don't cache.
            if "Information" in data or "Note" in data:
                return None
            cache.put(cache_key, data)
        return data

    # ─── OVERVIEW ───────────────────────────────────────────────────────

    def get_overview(self, ticker: str) -> AVOverview | None:
        ticker = ticker.upper().strip()
        if not ticker:
            return None
        data = self._get("OVERVIEW", {"symbol": ticker}, TTL_OVERVIEW)
        if not data or not data.get("Symbol"):
            return None
        return AVOverview(
            name=_str(data.get("Name")),
            sector=_str(data.get("Sector")),
            industry=_str(data.get("Industry")),
            country=_str(data.get("Country")),
            exchange=_str(data.get("Exchange")),
            description=_str(data.get("Description")),
            market_cap=_f(data.get("MarketCapitalization")),
            shares_outstanding=_f(data.get("SharesOutstanding")),
            week52_high=_f(data.get("52WeekHigh")),
            week52_low=_f(data.get("52WeekLow")),
            forward_pe=_f(data.get("ForwardPE")),
            trailing_pe=_f(data.get("TrailingPE") or data.get("PERatio")),
            peg=_f(data.get("PEGRatio")),
            price_to_book=_f(data.get("PriceToBookRatio")),
            price_to_sales_ttm=_f(data.get("PriceToSalesRatioTTM")),
            ev_to_ebitda=_f(data.get("EVToEBITDA")),
            ev_to_revenue=_f(data.get("EVToRevenue")),
            profit_margin=_f(data.get("ProfitMargin")),
            operating_margin=_f(data.get("OperatingMarginTTM")),
            roe=_f(data.get("ReturnOnEquityTTM")),
            roa=_f(data.get("ReturnOnAssetsTTM")),
            revenue_ttm=_f(data.get("RevenueTTM")),
            gross_profit_ttm=_f(data.get("GrossProfitTTM")),
            eps_ttm=_f(data.get("DilutedEPSTTM") or data.get("EPS")),
            ebitda=_f(data.get("EBITDA")),
            analyst_target_price=_f(data.get("AnalystTargetPrice")),
            beta=_f(data.get("Beta")),
            dividend_yield=_f(data.get("DividendYield")),
        )

    # ─── TIME_SERIES_DAILY ──────────────────────────────────────────────

    def get_daily_prices(self, ticker: str) -> list[PricePoint]:
        """Fallback price-history source for FMP-paywalled tickers.

        AV free tier only allows `outputsize=compact` (latest 100 trading days)
        on this endpoint — `outputsize=full` (20+ years) is premium-gated.
        So we get a 5-month chart instead of a 5-year one for paywalled tickers.
        Better than empty.
        """
        ticker = ticker.upper().strip()
        if not ticker:
            return []
        data = self._get(
            "TIME_SERIES_DAILY",
            {"symbol": ticker, "outputsize": "compact"},
            TTL_DAILY,
        )
        if not isinstance(data, dict):
            return []
        series = data.get("Time Series (Daily)")
        if not isinstance(series, dict):
            return []
        out: list[PricePoint] = []
        for d, row in series.items():
            close = _f(row.get("4. close")) if isinstance(row, dict) else None
            if close is not None:
                out.append(PricePoint(date=d, close=close))
        out.sort(key=lambda p: p.date)
        return out

    # ─── GLOBAL_QUOTE ───────────────────────────────────────────────────

    def get_global_quote(self, ticker: str) -> AVQuote | None:
        ticker = ticker.upper().strip()
        if not ticker:
            return None
        data = self._get("GLOBAL_QUOTE", {"symbol": ticker}, TTL_QUOTE)
        if not data:
            return None
        q = data.get("Global Quote") or {}
        if not q:
            return None
        # Alpha Vantage's number-prefixed keys ("05. price", etc.)
        price = _f(q.get("05. price"))
        if price is None:
            return None
        change = _f(q.get("09. change"))
        change_pct_raw = q.get("10. change percent") or ""
        change_pct = _f(str(change_pct_raw).rstrip("%"))
        return AVQuote(
            price=price,
            change=change,
            change_pct=change_pct,
            volume=int(_f(q.get("06. volume")) or 0) or None,
        )
