"""brevity data sources.

Two interfaces:
  - FundamentalsSource: profile + quote + ratios + historicals  (Fundamentals page)
  - OptionsSource: expirations + option chain + spot           (Gamma Exposure page)

Adapters:
  - EdgarSource (free, no key — just an email in User-Agent)
  - FMPSource (free 250/day, email signup)
  - PolygonSource (paid options data, email signup)
  - TradierSource (free options data, requires brokerage account / KYC)
  - MergedSource (composes EDGAR + FMP for the Fundamentals page)
"""
from __future__ import annotations

from .base import (
    CompanyProfile,
    FinancialPeriod,
    FundamentalsBundle,
    FundamentalsSource,
    KeyMetricsTTM,
    OptionChain,
    OptionExpiration,
    OptionsSource,
    PricePoint,
    Quote,
)
from .alphavantage import AlphaVantageSource
from .edgar import EdgarSource
from .finnhub import FinnhubSource
from .fmp import FMPSource
from .merged import MergedSource
from .polygon import PolygonSource
from .tradier import TradierSource
from .twelvedata import TwelveDataSource


def get_fundamentals_source(
    edgar_email: str | None = None,
    fmp_key: str | None = None,
    finnhub_key: str | None = None,
    twelvedata_key: str | None = None,
    alphavantage_key: str | None = None,
) -> MergedSource:
    """Return the default fundamentals source: EDGAR + FMP + Finnhub + TD + AV.

    Priority chain (per-field): FMP → Finnhub → Twelve Data → Alpha Vantage → EDGAR-TTM.
    """
    return MergedSource(
        edgar=EdgarSource(contact_email=edgar_email),
        fmp=FMPSource(api_key=fmp_key),
        finnhub=FinnhubSource(api_key=finnhub_key),
        twelvedata=TwelveDataSource(api_key=twelvedata_key),
        alphavantage=AlphaVantageSource(api_key=alphavantage_key),
    )


def get_options_source(
    polygon_key: str | None = None,
    tradier_token: str | None = None,
    tradier_env: str | None = None,
    *,
    preferred: str | None = None,
) -> OptionsSource | None:
    """Return the first available options source.

    Preference order (when `preferred` is None):
        Polygon → Tradier → None

    Polygon is preferred when available because its signup is email-only
    (no KYC, no brokerage application), making it the friendliest path for
    most users. Tradier is free but requires a brokerage account.

    Set `preferred` to "polygon" or "tradier" to force a specific source.
    """
    polygon = PolygonSource(api_key=polygon_key)
    tradier = TradierSource(token=tradier_token, environment=tradier_env)

    if preferred == "polygon":
        return polygon if polygon.available else None
    if preferred == "tradier":
        return tradier if tradier.available else None

    if polygon.available:
        return polygon
    if tradier.available:
        return tradier
    return None


def list_options_source_status(
    polygon_key: str | None = None,
    tradier_token: str | None = None,
) -> list[dict]:
    """For UI status display — which options sources are configured."""
    return [
        {
            "name": "Polygon",
            "configured": bool((polygon_key or "").strip()),
            "signup": "https://polygon.io/dashboard/signup",
            "tier": "Options Starter $29/mo (email only, no KYC)",
        },
        {
            "name": "Tradier",
            "configured": bool((tradier_token or "").strip()),
            "signup": "https://tradier.com",
            "tier": "Free market-data (requires brokerage account / KYC)",
        },
        {
            "name": "Interactive Brokers",
            "configured": False,  # No REST adapter yet
            "signup": "https://www.interactivebrokers.com",
            "tier": "Free options data via TWS/Gateway — adapter not yet implemented",
        },
    ]


__all__ = [
    "CompanyProfile",
    "FinancialPeriod",
    "FundamentalsBundle",
    "FundamentalsSource",
    "KeyMetricsTTM",
    "OptionChain",
    "OptionExpiration",
    "OptionsSource",
    "PricePoint",
    "Quote",
    "AlphaVantageSource",
    "EdgarSource",
    "FinnhubSource",
    "FMPSource",
    "MergedSource",
    "PolygonSource",
    "TradierSource",
    "TwelveDataSource",
    "get_fundamentals_source",
    "get_options_source",
    "list_options_source_status",
]
