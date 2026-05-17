"""Provider-agnostic data model + interface for fundamentals + options sources.

Each source implements `FundamentalsSource` (for the Fundamentals page) and/or
`OptionsSource` (for the Gamma Exposure page) and returns these shared shapes.
The UI never imports a source directly — it goes through `data_sources.get_*()`.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

import pandas as pd


# ─── Fundamentals ────────────────────────────────────────────────────────────

@dataclass
class CompanyProfile:
    ticker: str
    name: str = ""
    cik: str | None = None
    exchange: str | None = None
    sector: str | None = None
    industry: str | None = None
    website: str | None = None
    image: str | None = None
    description: str | None = None
    country: str | None = None
    ceo: str | None = None
    employees: int | None = None


@dataclass
class Quote:
    ticker: str
    price: float = 0.0
    change: float = 0.0
    change_pct: float = 0.0
    after_hours_price: float | None = None
    market_cap: float | None = None
    shares_outstanding: float | None = None
    week52_high: float | None = None
    week52_low: float | None = None
    next_earnings_date: str | None = None
    avg_volume: float | None = None
    analyst_target_price: float | None = None  # from Alpha Vantage analyst consensus


@dataclass
class KeyMetricsTTM:
    """Trailing-twelve-month ratios. Any field may be None if unsupplied."""
    pe: float | None = None
    forward_pe: float | None = None
    peg: float | None = None
    forward_peg: float | None = None
    earnings_yield: float | None = None
    price_to_sales: float | None = None
    price_to_cash_flow: float | None = None
    price_to_free_cash_flow: float | None = None
    fcf_yield: float | None = None
    price_to_book: float | None = None
    ev_to_ebitda: float | None = None
    ev_to_sales: float | None = None
    profit_margin: float | None = None
    operating_margin: float | None = None
    roe: float | None = None
    roic: float | None = None
    debt_to_equity: float | None = None
    revenue_growth_3y: float | None = None
    revenue_growth_5y: float | None = None
    revenue_growth_10y: float | None = None
    free_cash_flow: float | None = None
    net_income: float | None = None
    net_debt: float | None = None
    revenue_ttm: float | None = None


@dataclass
class FinancialPeriod:
    """One reporting period (quarter or year)."""
    date: str  # YYYY-MM-DD, period end
    period: str = "Q"  # "Q" or "FY"
    fiscal_year: int | None = None
    revenue: float | None = None
    gross_profit: float | None = None
    gross_margin: float | None = None  # 0..1
    ebitda: float | None = None
    operating_income: float | None = None
    net_income: float | None = None
    eps: float | None = None
    cash_from_ops: float | None = None
    capex: float | None = None
    free_cash_flow: float | None = None
    cash: float | None = None
    debt: float | None = None
    weighted_shares: float | None = None  # diluted, weighted-average over the period
    pe: float | None = None  # computed: price_at_end / TTM_EPS
    ps: float | None = None  # computed: (price × shares) / TTM_revenue


@dataclass
class PricePoint:
    date: str  # YYYY-MM-DD
    close: float


@dataclass
class FundamentalsBundle:
    """Everything the Fundamentals page needs for one ticker."""
    profile: CompanyProfile
    quote: Quote
    metrics_ttm: KeyMetricsTTM
    quarterly: list[FinancialPeriod] = field(default_factory=list)
    annual: list[FinancialPeriod] = field(default_factory=list)
    price_history: list[PricePoint] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)  # which providers contributed


@runtime_checkable
class FundamentalsSource(Protocol):
    name: str

    @property
    def available(self) -> bool: ...

    def get_bundle(self, ticker: str) -> FundamentalsBundle | None: ...


# ─── Options (for Gamma Exposure) ────────────────────────────────────────────

@dataclass
class OptionExpiration:
    date: str  # YYYY-MM-DD


@dataclass
class OptionChain:
    """Combined call + put chain for one (ticker, expiry).

    `df` columns required for GEX: strike, side ("call"|"put"), open_interest,
    volume, implied_volatility, bid, ask.
    """
    ticker: str
    expiration: str
    spot: float
    df: pd.DataFrame


@runtime_checkable
class OptionsSource(Protocol):
    name: str

    @property
    def available(self) -> bool: ...

    def get_expirations(self, ticker: str) -> list[OptionExpiration]: ...

    def get_chain(self, ticker: str, expiration: str) -> OptionChain | None: ...

    def get_spot(self, ticker: str) -> float | None: ...
