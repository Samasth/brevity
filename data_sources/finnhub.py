"""Finnhub adapter — preferred fallback for FMP-paywalled tickers.

Why Finnhub: 60 req/min on the free tier (12× Alpha Vantage's 5/min cap) with
the same or richer coverage of ratios. Email-only signup, no KYC.

Endpoints used (all free tier):
  - /quote                       — current price + today's change
  - /stock/profile2              — name, logo, sector, market cap, shares
  - /stock/metric?metric=all     — ~50 fields incl. forwardPE, forwardPEG,
                                   trailing P/E, P/S, P/B, ROE, all margins,
                                   growth, 52wk range, dividend yield

We deliberately do NOT use /stock/price-target (premium-gated → 403) or
/stock/earnings-estimate (premium-gated → returns HTML). The Alpha Vantage
adapter remains the source for analyst-consensus price target.

Unit quirks:
  - /stock/profile2 returns `marketCapitalization` and `shareOutstanding` in
    MILLIONS. We scale by 1e6.
  - /stock/metric returns margins, returns, growth rates as PERCENTAGES
    (e.g., 27.15 means 27.15%). We divide by 100 to match brevity's
    base.py convention (decimals where applicable).

Docs:   https://finnhub.io/docs/api
Signup: https://finnhub.io/register
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import requests

from . import cache

BASE = "https://finnhub.io/api/v1"
TIMEOUT = 12

TTL_QUOTE = 5 * 60
TTL_PROFILE = 24 * 3600
TTL_METRIC = 6 * 3600
TTL_TARGET = 12 * 3600
TTL_ESTIMATE = 24 * 3600
TTL_CALENDAR = 12 * 3600


@dataclass
class FHOverview:
    """All the fields we extract from Finnhub for the Fundamentals page."""
    # Profile
    name: str | None = None
    sector: str | None = None
    industry: str | None = None
    country: str | None = None
    exchange: str | None = None
    website: str | None = None
    image: str | None = None
    ipo_date: str | None = None
    employees: int | None = None
    # Quote-like / capital structure
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
    price_to_cash_flow: float | None = None
    price_to_free_cash_flow: float | None = None
    ev_to_ebitda: float | None = None
    ev_to_revenue: float | None = None
    # Margins / returns
    profit_margin: float | None = None
    operating_margin: float | None = None
    gross_margin: float | None = None
    roe: float | None = None
    roa: float | None = None
    roic: float | None = None
    debt_to_equity: float | None = None
    # Earnings / cash
    revenue_ttm: float | None = None
    eps_ttm: float | None = None
    # Growth
    revenue_growth_ttm: float | None = None
    eps_growth_ttm: float | None = None
    # Analyst consensus
    analyst_target_price: float | None = None
    n_analysts: int | None = None
    # Other
    beta: float | None = None
    dividend_yield: float | None = None


@dataclass
class FHQuote:
    price: float | None = None
    change: float | None = None
    change_pct: float | None = None


def _f(x: Any) -> float | None:
    if x is None or x == "":
        return None
    try:
        v = float(x)
        if v != v or v == 0:
            return None
        return v
    except (TypeError, ValueError):
        return None


def _str(x: Any) -> str | None:
    if x is None:
        return None
    s = str(x).strip()
    return s or None


class FinnhubSource:
    name = "finnhub"

    def __init__(self, api_key: str | None = None):
        self.api_key = (api_key or os.getenv("FINNHUB_API_KEY", "")).strip()

    @property
    def available(self) -> bool:
        return bool(self.api_key)

    # ─── HTTP ────────────────────────────────────────────────────────────

    def _get(self, path: str, params: dict, ttl: int) -> dict | list | None:
        if not self.available:
            return None
        params = {**params, "token": self.api_key}
        cache_key = f"finnhub__{path}__" + "&".join(
            f"{k}={v}" for k, v in sorted(params.items()) if k != "token"
        )
        hit = cache.get(cache_key, ttl)
        if hit is not None:
            return hit
        try:
            r = requests.get(f"{BASE}{path}", params=params, timeout=TIMEOUT)
            if r.status_code != 200:
                return None
            data = r.json()
        except (requests.RequestException, ValueError):
            return None
        cache.put(cache_key, data)
        return data

    # ─── Sub-fetches ────────────────────────────────────────────────────

    def _fetch_quote(self, ticker: str) -> dict | None:
        d = self._get("/quote", {"symbol": ticker.upper()}, TTL_QUOTE)
        return d if isinstance(d, dict) and d.get("c") else None

    def _fetch_profile(self, ticker: str) -> dict | None:
        d = self._get("/stock/profile2", {"symbol": ticker.upper()}, TTL_PROFILE)
        return d if isinstance(d, dict) and d.get("name") else None

    def _fetch_metric(self, ticker: str) -> dict | None:
        d = self._get(
            "/stock/metric",
            {"symbol": ticker.upper(), "metric": "all"},
            TTL_METRIC,
        )
        if isinstance(d, dict) and isinstance(d.get("metric"), dict):
            return d["metric"]
        return None

    # ─── Public API ─────────────────────────────────────────────────────

    def get_upcoming_earnings(self, ticker: str, months_ahead: int = 13) -> list[dict]:
        """Return list of upcoming earnings events with EPS + revenue estimates.

        Each event: {"date": "YYYY-MM-DD", "epsEstimate": float|None,
                     "revenueEstimate": float|None}
        """
        from datetime import date, timedelta
        frm = date.today().isoformat()
        to = (date.today() + timedelta(days=months_ahead * 31)).isoformat()
        d = self._get(
            "/calendar/earnings",
            {"from": frm, "to": to, "symbol": ticker.upper()},
            TTL_CALENDAR,
        )
        if not isinstance(d, dict):
            return []
        events = d.get("earningsCalendar") or []
        # Sort by date ascending
        events.sort(key=lambda e: e.get("date", ""))
        return events

    def get_next_earnings_date(self, ticker: str) -> str | None:
        events = self.get_upcoming_earnings(ticker, months_ahead=6)
        return events[0].get("date") if events else None

    def get_forward_eps_annual(self, ticker: str) -> float | None:
        """Forward annualized EPS from upcoming analyst estimates.

        Useful for computing Forward P/E when Finnhub's /stock/metric doesn't
        report `forwardPE` (typically unprofitable companies). Strategy:

          - 4+ quarterly estimates: sum the next 4 (clean annualization)
          - 2-3 estimates: sum + scale to 4-quarter year
          - 1 estimate: that single quarter × 4 (rough, but matches what
            AlphaScope and other dashboards show for tickers with only 1
            future earnings event known)
          - 0 estimates: None
        """
        events = self.get_upcoming_earnings(ticker, months_ahead=13)
        estimates = [
            e.get("epsEstimate") for e in events
            if e.get("epsEstimate") is not None
        ]
        if not estimates:
            return None
        usable = estimates[:4]
        total = sum(usable)
        if len(usable) < 4:
            total *= 4 / len(usable)
        return total

    def get_quote(self, ticker: str) -> FHQuote | None:
        q = self._fetch_quote(ticker)
        if not q:
            return None
        return FHQuote(
            price=_f(q.get("c")),
            change=_f(q.get("d")),
            change_pct=_f(q.get("dp")),
        )

    def get_overview(self, ticker: str) -> FHOverview | None:
        """Combine /profile2 + /metric into a single overview.

        Skips /stock/price-target (premium-gated) and /stock/earnings-estimate
        (premium-gated). Forward P/E + PEG come directly from /stock/metric.
        Each sub-fetch is independently disk-cached.
        """
        ticker = ticker.upper().strip()
        if not ticker:
            return None

        profile = self._fetch_profile(ticker)
        metric = self._fetch_metric(ticker)
        if profile is None and metric is None:
            return None

        ov = FHOverview()

        # ── Profile ──────────────────────────────────────────────────
        if profile:
            ov.name = _str(profile.get("name"))
            ov.sector = _str(profile.get("gicsSector") or profile.get("finnhubIndustry"))
            ov.industry = _str(profile.get("finnhubIndustry"))
            ov.country = _str(profile.get("country"))
            ov.exchange = _str(profile.get("exchange"))
            ov.website = _str(profile.get("weburl"))
            ov.image = _str(profile.get("logo"))
            ov.ipo_date = _str(profile.get("ipo"))
            # profile2 returns market cap + shares in MILLIONS
            mc_m = _f(profile.get("marketCapitalization"))
            so_m = _f(profile.get("shareOutstanding"))
            if mc_m:
                ov.market_cap = mc_m * 1e6
            if so_m:
                ov.shares_outstanding = so_m * 1e6

        # ── Metric (~50 fields) ──────────────────────────────────────
        if metric:
            # Helper: Finnhub returns percentages (27.15 means 27.15%) for
            # margins/returns/growth/yield. We divide by 100 so they match
            # brevity's decimal convention in KeyMetricsTTM.
            def pct(key: str) -> float | None:
                v = _f(metric.get(key))
                return v / 100 if v is not None else None

            ov.week52_high = _f(metric.get("52WeekHigh"))
            ov.week52_low = _f(metric.get("52WeekLow"))

            # P/E variants — prefer TTM
            ov.trailing_pe = (
                _f(metric.get("peTTM"))
                or _f(metric.get("peExclExtraTTM"))
                or _f(metric.get("peAnnual"))
            )
            # Forward — pre-computed by Finnhub
            ov.forward_pe = _f(metric.get("forwardPE"))
            ov.peg = _f(metric.get("forwardPEG")) or _f(metric.get("pegTTM"))

            ov.price_to_book = (
                _f(metric.get("pbAnnual")) or _f(metric.get("pbQuarterly"))
            )
            ov.price_to_sales_ttm = (
                _f(metric.get("psTTM")) or _f(metric.get("psAnnual"))
            )
            # Per-share ratios (Finnhub gives price/X PER SHARE — not directly
            # comparable to market-cap based P/CF; we report what we have).
            ov.price_to_cash_flow = _f(metric.get("pcfShareTTM"))
            ov.price_to_free_cash_flow = _f(metric.get("pfcfShareTTM"))

            # Margins (% → decimal)
            ov.gross_margin = pct("grossMarginTTM")
            ov.operating_margin = pct("operatingMarginTTM")
            ov.profit_margin = pct("netProfitMarginTTM")
            # Returns (% → decimal)
            ov.roe = pct("roeTTM")
            ov.roa = pct("roaTTM")
            ov.roic = pct("roiTTM")
            # Debt
            ov.debt_to_equity = (
                _f(metric.get("totalDebt/totalEquityAnnual"))
                or _f(metric.get("longTermDebt/equityAnnual"))
            )
            # Earnings
            ov.eps_ttm = _f(metric.get("epsTTM"))
            # Growth (% → decimal)
            ov.revenue_growth_ttm = pct("revenueGrowthTTMYoy")
            ov.eps_growth_ttm = pct("epsGrowthTTMYoy")
            # Beta + yield
            ov.beta = _f(metric.get("beta"))
            ov.dividend_yield = pct("currentDividendYieldTTM")
            # Market cap from /metric is raw (not million-scaled)
            if ov.market_cap is None:
                ov.market_cap = _f(metric.get("marketCapitalization"))

        return ov
