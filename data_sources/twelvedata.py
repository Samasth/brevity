"""Twelve Data adapter — primarily a price-history fallback for paywalled tickers.

What TD's free tier covers (validated by live probe):
  - /quote          ✓ free — any US-listed ticker, real-time price + 52wk range
  - /time_series    ✓ free — daily OHLCV. Returns up to ~1500 trading days
                              (5+ years for established tickers; "all available"
                              for recent IPOs like CRWV)
  - /statistics     ⚠ per-ticker paywalled — works for major caps (AAPL),
                              returns 403 for recent IPOs / smaller caps (CRWV).
                              We try it and let 403 fall through gracefully.

The big win is /time_series — 1500 day window beats Alpha Vantage's free
100-day compact limit, so paywalled-by-FMP tickers like CRWV get a longer
price chart.

Rate limits: 800 req/day, 8 req/min.

Docs: https://twelvedata.com/docs
Signup: https://twelvedata.com/account
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import requests

from . import cache
from .base import PricePoint

BASE = "https://api.twelvedata.com"
TIMEOUT = 20

TTL_QUOTE = 5 * 60
TTL_STATS = 12 * 3600
TTL_PRICES = 6 * 3600


@dataclass
class TDOverview:
    """Subset of TD /statistics fields. Often None for paywalled tickers."""
    market_cap: float | None = None
    enterprise_value: float | None = None
    trailing_pe: float | None = None
    forward_pe: float | None = None
    peg: float | None = None
    price_to_sales_ttm: float | None = None
    price_to_book: float | None = None
    ev_to_revenue: float | None = None
    ev_to_ebitda: float | None = None
    # Financials
    profit_margin: float | None = None
    operating_margin: float | None = None
    gross_margin: float | None = None
    roe: float | None = None
    roa: float | None = None
    revenue_ttm: float | None = None
    gross_profit_ttm: float | None = None
    ebitda: float | None = None
    eps_ttm: float | None = None
    net_income_ttm: float | None = None
    # Quarterly growth (decimal, e.g. 0.166 = 16.6%)
    quarterly_revenue_growth: float | None = None
    quarterly_earnings_growth: float | None = None
    # Balance sheet
    total_cash: float | None = None
    total_debt: float | None = None
    debt_to_equity: float | None = None
    book_value_per_share: float | None = None


@dataclass
class TDQuote:
    price: float | None = None
    change: float | None = None
    change_pct: float | None = None
    avg_volume: float | None = None
    week52_high: float | None = None
    week52_low: float | None = None


def _f(x: Any) -> float | None:
    if x is None or x == "":
        return None
    try:
        v = float(x)
        if v != v:
            return None
        return v
    except (TypeError, ValueError):
        return None


class TwelveDataSource:
    name = "twelvedata"

    def __init__(self, api_key: str | None = None):
        self.api_key = (api_key or os.getenv("TWELVEDATA_API_KEY", "")).strip()

    @property
    def available(self) -> bool:
        return bool(self.api_key)

    # ─── HTTP ────────────────────────────────────────────────────────────

    def _get(self, path: str, params: dict, ttl: int) -> dict | None:
        if not self.available:
            return None
        params = {**params, "apikey": self.api_key}
        cache_key = f"td__{path}__" + "&".join(
            f"{k}={v}" for k, v in sorted(params.items()) if k != "apikey"
        )
        hit = cache.get(cache_key, ttl)
        if hit is not None:
            return hit
        try:
            r = requests.get(f"{BASE}/{path}", params=params, timeout=TIMEOUT)
            if r.status_code != 200:
                return None
            data = r.json()
        except (requests.RequestException, ValueError):
            return None
        if not isinstance(data, dict):
            return None
        # TD signals errors via {"code": ..., "message": "..."}
        if data.get("code") and data.get("status") in ("error",) + (
            None,) and "message" in data:
            # Don't cache errors — try again next time
            if data.get("code") in (400, 403, 404, 429):
                return None
        cache.put(cache_key, data)
        return data

    # ─── Quote ───────────────────────────────────────────────────────────

    def get_quote(self, ticker: str) -> TDQuote | None:
        ticker = ticker.upper().strip()
        if not ticker:
            return None
        d = self._get("quote", {"symbol": ticker}, TTL_QUOTE)
        if not d or "close" not in d:
            return None
        week52 = d.get("fifty_two_week") or {}
        return TDQuote(
            price=_f(d.get("close")),
            change=_f(d.get("change")),
            change_pct=_f(d.get("percent_change")),
            avg_volume=_f(d.get("average_volume")),
            week52_high=_f(week52.get("high")),
            week52_low=_f(week52.get("low")),
        )

    # ─── /statistics (per-ticker paywalled for many) ────────────────────

    def get_overview(self, ticker: str) -> TDOverview | None:
        ticker = ticker.upper().strip()
        if not ticker:
            return None
        d = self._get("statistics", {"symbol": ticker}, TTL_STATS)
        if not d:
            return None
        stats = d.get("statistics")
        if not isinstance(stats, dict):
            return None
        v = stats.get("valuations_metrics") or {}
        f = stats.get("financials") or {}
        inc = f.get("income_statement") or {}
        bs = f.get("balance_sheet") or {}
        return TDOverview(
            market_cap=_f(v.get("market_capitalization")),
            enterprise_value=_f(v.get("enterprise_value")),
            trailing_pe=_f(v.get("trailing_pe")),
            forward_pe=_f(v.get("forward_pe")),
            peg=_f(v.get("peg_ratio")),
            price_to_sales_ttm=_f(v.get("price_to_sales_ttm")),
            price_to_book=_f(v.get("price_to_book_mrq")),
            ev_to_revenue=_f(v.get("enterprise_to_revenue")),
            ev_to_ebitda=_f(v.get("enterprise_to_ebitda")),
            profit_margin=_f(f.get("profit_margin")),
            operating_margin=_f(f.get("operating_margin")),
            gross_margin=_f(f.get("gross_margin")),
            roe=_f(f.get("return_on_equity_ttm")),
            roa=_f(f.get("return_on_assets_ttm")),
            revenue_ttm=_f(inc.get("revenue_ttm")),
            gross_profit_ttm=_f(inc.get("gross_profit_ttm")),
            ebitda=_f(inc.get("ebitda")),
            eps_ttm=_f(inc.get("diluted_eps_ttm")),
            net_income_ttm=_f(inc.get("net_income_to_common_ttm")),
            quarterly_revenue_growth=_f(inc.get("quarterly_revenue_growth")),
            quarterly_earnings_growth=_f(inc.get("quarterly_earnings_growth_yoy")),
            total_cash=_f(bs.get("total_cash_mrq")),
            total_debt=_f(bs.get("total_debt_mrq")),
            debt_to_equity=_f(bs.get("total_debt_to_equity_mrq")),
            book_value_per_share=_f(bs.get("book_value_per_share_mrq")),
        )

    # ─── Price history ───────────────────────────────────────────────────

    def get_prices(self, ticker: str, *, outputsize: int = 1500) -> list[PricePoint]:
        """Daily OHLC. outputsize=1500 returns up to 5+ years of trading days
        on free tier (or all available for recent IPOs)."""
        ticker = ticker.upper().strip()
        if not ticker:
            return []
        d = self._get(
            "time_series",
            {"symbol": ticker, "interval": "1day", "outputsize": str(outputsize)},
            TTL_PRICES,
        )
        if not d or "values" not in d:
            return []
        out: list[PricePoint] = []
        for row in d["values"]:
            if not isinstance(row, dict):
                continue
            dt = row.get("datetime")
            close = _f(row.get("close"))
            if dt and close is not None:
                out.append(PricePoint(date=dt, close=close))
        out.sort(key=lambda p: p.date)
        return out
