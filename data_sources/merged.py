"""MergedSource — composes EDGAR + FMP + Finnhub + Twelve Data + AV.

Five-layer fallback so the page degrades gracefully:

    FMP (primary)              — clean quote + ratios for well-covered tickers
    Finnhub (preferred)        — 60/min. Comprehensive ratios + forwardPE
                                 pre-computed. Covers recent IPOs.
    Twelve Data (fallback)     — Mainly used for longer price history on
                                 FMP-paywalled tickers (up to 1500 days vs
                                 AV's 100-day cap). /statistics is per-ticker
                                 paywalled on free; we use it where it works.
    Alpha Vantage (fallback)   — Only source for analyst price target on
                                 free tier. Rate-limited (5/min), used sparingly.
    EDGAR-computed TTM (last)  — sum/snapshot of latest 4 EDGAR quarters.

EDGAR is always primary for historical financial statements (deeper than any
free alternative).
"""
from __future__ import annotations

from bisect import bisect_right

from .alphavantage import AlphaVantageSource, AVOverview, AVQuote
from .base import (
    CompanyProfile,
    FinancialPeriod,
    FundamentalsBundle,
    KeyMetricsTTM,
    PricePoint,
    Quote,
)
from .edgar import EdgarSource
from .finnhub import FHOverview, FHQuote, FinnhubSource
from .fmp import FMPSource
from .twelvedata import TDOverview, TDQuote, TwelveDataSource


def _first(*vals):
    """First non-None value; helper for priority chains."""
    for v in vals:
        if v is not None:
            return v
    return None


class MergedSource:
    name = "merged"

    def __init__(
        self,
        edgar: EdgarSource | None = None,
        fmp: FMPSource | None = None,
        finnhub: FinnhubSource | None = None,
        twelvedata: TwelveDataSource | None = None,
        alphavantage: AlphaVantageSource | None = None,
    ):
        self.edgar = edgar or EdgarSource()
        self.fmp = fmp or FMPSource()
        self.finnhub = finnhub or FinnhubSource()
        self.twelvedata = twelvedata or TwelveDataSource()
        self.alphavantage = alphavantage or AlphaVantageSource()

    @property
    def available(self) -> bool:
        return self.edgar.available or self.fmp.available

    @property
    def status(self) -> dict[str, bool]:
        return {
            "edgar": self.edgar.available,
            "fmp": self.fmp.available,
            "finnhub": self.finnhub.available,
            "twelvedata": self.twelvedata.available,
            "alphavantage": self.alphavantage.available,
        }

    # ─── Bundle ──────────────────────────────────────────────────────────

    def get_bundle(self, ticker: str) -> FundamentalsBundle | None:
        ticker = ticker.upper().strip()
        if not ticker:
            return None

        # ── Layer 1: pull from each source independently ──
        edgar_bundle = (
            self.edgar.get_bundle(ticker) if self.edgar.available else None
        )

        fmp_profile = None
        fmp_quote = None
        fmp_metrics = None
        fmp_prices: list[PricePoint] = []
        if self.fmp.available:
            fmp_profile = self.fmp.get_profile(ticker)
            fmp_quote = self.fmp.get_quote(ticker)
            fmp_metrics = self.fmp.get_metrics_ttm(
                ticker, market_cap=fmp_quote.market_cap if fmp_quote else None,
            )
            fmp_prices = self.fmp.get_prices(ticker)

        fh_overview: FHOverview | None = None
        fh_quote: FHQuote | None = None
        fh_next_earnings: str | None = None
        fh_forward_eps: float | None = None
        if self.finnhub.available:
            fh_overview = self.finnhub.get_overview(ticker)
            fh_quote = self.finnhub.get_quote(ticker)
            fh_next_earnings = self.finnhub.get_next_earnings_date(ticker)
            fh_forward_eps = self.finnhub.get_forward_eps_annual(ticker)

        td_overview: TDOverview | None = None
        td_quote: TDQuote | None = None
        if self.twelvedata.available:
            td_overview = self.twelvedata.get_overview(ticker)  # may be None (paywalled)
            td_quote = self.twelvedata.get_quote(ticker)

        av_overview: AVOverview | None = None
        av_quote: AVQuote | None = None
        if self.alphavantage.available:
            av_overview = self.alphavantage.get_overview(ticker)

        # Did FMP serve this ticker? If quote.price is 0 and metrics are
        # mostly empty, FMP paywalled it. Finnhub usually fills the gap;
        # only fall back to AV's GLOBAL_QUOTE if neither has a price.
        fmp_paywalled = (
            fmp_quote is not None
            and fmp_quote.price == 0
            and (fmp_metrics is None or fmp_metrics.pe is None)
        )
        fh_has_price = fh_quote is not None and (fh_quote.price or 0) > 0
        if fmp_paywalled and not fh_has_price and self.alphavantage.available:
            av_quote = self.alphavantage.get_global_quote(ticker)

        # ── Layer 2: detect total miss and bail ──
        edgar_has = edgar_bundle is not None and (edgar_bundle.quarterly or edgar_bundle.annual)
        fmp_has = fmp_quote is not None and (fmp_quote.price > 0 or (fmp_profile and fmp_profile.name))
        fh_has = fh_overview is not None or fh_has_price
        td_has = td_overview is not None or (td_quote is not None and td_quote.price)
        av_has = av_overview is not None or av_quote is not None
        if not (edgar_has or fmp_has or fh_has or td_has or av_has):
            return None

        # ── Layer 3: compose ──
        profile = self._merge_profile(
            edgar_bundle.profile if edgar_bundle else CompanyProfile(ticker=ticker),
            fmp_profile,
            fh_overview,
            av_overview,
        )
        quote = self._merge_quote(
            ticker, fmp_quote, fh_overview, fh_quote,
            td_overview, td_quote, av_overview, av_quote,
        )
        # Finnhub's earnings calendar fills next_earnings_date when FMP didn't
        if not quote.next_earnings_date and fh_next_earnings:
            quote.next_earnings_date = fh_next_earnings

        metrics = self._merge_metrics(
            fmp_metrics, fh_overview, td_overview, av_overview, edgar_bundle,
            quote_price=quote.price,
            market_cap=quote.market_cap,
            fh_forward_eps=fh_forward_eps,
        )

        quarterly = edgar_bundle.quarterly if edgar_bundle else []
        annual = edgar_bundle.annual if edgar_bundle else []

        # Price history priority:
        #   FMP (1255 daily, 5y for covered tickers)
        # → Twelve Data (up to 1500 days, all-available for recent IPOs)
        # → Alpha Vantage (100 days only on free tier)
        prices = fmp_prices
        if not prices and self.twelvedata.available:
            prices = self.twelvedata.get_prices(ticker)
        if not prices and self.alphavantage.available:
            prices = self.alphavantage.get_daily_prices(ticker)

        if prices:
            self._compute_ratios(quarterly, prices, cadence="Q")
            self._compute_ratios(annual, prices, cadence="FY")

        # Track which sources actually contributed data (for the UI footer)
        sources: list[str] = []
        if edgar_has:
            sources.append("edgar")
        if fmp_has:
            sources.append("fmp")
        if self.finnhub.available and fh_has:
            sources.append("finnhub")
        if self.twelvedata.available and td_has:
            sources.append("twelvedata")
        if self.alphavantage.available and (av_overview is not None or av_quote is not None):
            sources.append("alphavantage")

        return FundamentalsBundle(
            profile=profile,
            quote=quote,
            metrics_ttm=metrics,
            quarterly=quarterly,
            annual=annual,
            price_history=prices,
            sources=sources,
        )

    # ─── Profile merge ───────────────────────────────────────────────────

    @staticmethod
    def _merge_profile(
        edgar_p: CompanyProfile,
        fmp_p: CompanyProfile | None,
        fh: FHOverview | None,
        av: AVOverview | None,
    ) -> CompanyProfile:
        """Priority: FMP → Finnhub → AV → EDGAR. Each fills any field above
        it left None."""
        p = CompanyProfile(ticker=edgar_p.ticker, cik=edgar_p.cik)
        if fmp_p:
            p.name = fmp_p.name or p.name
            p.exchange = fmp_p.exchange
            p.sector = fmp_p.sector
            p.industry = fmp_p.industry
            p.website = fmp_p.website
            p.image = fmp_p.image
            p.description = fmp_p.description
            p.country = fmp_p.country
            p.ceo = fmp_p.ceo
            p.employees = fmp_p.employees
        if fh:
            p.name = p.name or fh.name
            p.exchange = p.exchange or fh.exchange
            p.sector = p.sector or fh.sector
            p.industry = p.industry or fh.industry
            p.country = p.country or fh.country
            p.website = p.website or fh.website
            p.image = p.image or fh.image
        if av:
            p.name = p.name or av.name
            p.exchange = p.exchange or av.exchange
            p.sector = p.sector or av.sector
            p.industry = p.industry or av.industry
            p.country = p.country or av.country
            p.description = p.description or av.description
        p.name = p.name or edgar_p.name
        return p

    # ─── Quote merge ─────────────────────────────────────────────────────

    @staticmethod
    def _merge_quote(
        ticker: str,
        fmp_q: Quote | None,
        fh_o: FHOverview | None,
        fh_q: FHQuote | None,
        td_o: TDOverview | None,
        td_q: TDQuote | None,
        av_o: AVOverview | None,
        av_q: AVQuote | None,
    ) -> Quote:
        q = fmp_q or Quote(ticker=ticker)

        # Price + change: prefer Finnhub (real-time), then TD, then AV
        if q.price == 0 and fh_q is not None and fh_q.price:
            q.price = fh_q.price
            q.change = fh_q.change or 0.0
            q.change_pct = fh_q.change_pct or 0.0
        if q.price == 0 and td_q is not None and td_q.price:
            q.price = td_q.price
            q.change = td_q.change or 0.0
            q.change_pct = td_q.change_pct or 0.0
        if q.price == 0 and av_q is not None and av_q.price:
            q.price = av_q.price
            q.change = av_q.change or 0.0
            q.change_pct = av_q.change_pct or 0.0
        # Last resort: market_cap / shares
        if q.price == 0:
            for src in (fh_o, td_o, av_o):
                if src and src.market_cap and getattr(src, "shares_outstanding", None):
                    q.price = src.market_cap / src.shares_outstanding
                    break

        # Quote-state fields: FMP → FH → TD → AV
        q.market_cap = q.market_cap or _first(
            fh_o.market_cap if fh_o else None,
            td_o.market_cap if td_o else None,
            av_o.market_cap if av_o else None,
        )
        q.shares_outstanding = q.shares_outstanding or _first(
            fh_o.shares_outstanding if fh_o else None,
            av_o.shares_outstanding if av_o else None,
        )
        q.week52_high = q.week52_high or _first(
            fh_o.week52_high if fh_o else None,
            td_q.week52_high if td_q else None,
            av_o.week52_high if av_o else None,
        )
        q.week52_low = q.week52_low or _first(
            fh_o.week52_low if fh_o else None,
            td_q.week52_low if td_q else None,
            av_o.week52_low if av_o else None,
        )
        q.avg_volume = q.avg_volume or _first(
            td_q.avg_volume if td_q else None,
        )
        # Analyst target only from AV (Finnhub gates it on premium)
        q.analyst_target_price = q.analyst_target_price or (
            av_o.analyst_target_price if av_o else None
        )

        return q

    # ─── Metrics merge ───────────────────────────────────────────────────

    @staticmethod
    def _merge_metrics(
        fmp_m: KeyMetricsTTM | None,
        fh_o: FHOverview | None,
        td_o: TDOverview | None,
        av_o: AVOverview | None,
        edgar_bundle: FundamentalsBundle | None,
        *,
        quote_price: float,
        market_cap: float | None,
        fh_forward_eps: float | None = None,
    ) -> KeyMetricsTTM:
        m = fmp_m or KeyMetricsTTM()

        def fh(attr):
            return getattr(fh_o, attr, None) if fh_o else None

        def td(attr):
            return getattr(td_o, attr, None) if td_o else None

        def av(attr):
            return getattr(av_o, attr, None) if av_o else None

        # Layer 2: Finnhub > Twelve Data > Alpha Vantage fill remaining gaps
        m.pe = _first(m.pe, fh("trailing_pe"), td("trailing_pe"), av("trailing_pe"))
        m.forward_pe = _first(m.forward_pe, fh("forward_pe"), td("forward_pe"), av("forward_pe"))
        m.peg = _first(m.peg, fh("peg"), td("peg"), av("peg"))
        m.price_to_sales = _first(
            m.price_to_sales, fh("price_to_sales_ttm"),
            td("price_to_sales_ttm"), av("price_to_sales_ttm"),
        )
        m.price_to_book = _first(
            m.price_to_book, fh("price_to_book"), td("price_to_book"), av("price_to_book"),
        )
        m.price_to_cash_flow = _first(m.price_to_cash_flow, fh("price_to_cash_flow"))
        m.price_to_free_cash_flow = _first(
            m.price_to_free_cash_flow, fh("price_to_free_cash_flow"),
        )
        # EV ratios — Finnhub doesn't expose these on free tier; TD has them
        m.ev_to_ebitda = _first(m.ev_to_ebitda, td("ev_to_ebitda"), av("ev_to_ebitda"))
        m.ev_to_sales = _first(m.ev_to_sales, td("ev_to_revenue"), av("ev_to_revenue"))
        m.profit_margin = _first(
            m.profit_margin, fh("profit_margin"), td("profit_margin"), av("profit_margin"),
        )
        m.operating_margin = _first(
            m.operating_margin, fh("operating_margin"),
            td("operating_margin"), av("operating_margin"),
        )
        m.roe = _first(m.roe, fh("roe"), td("roe"), av("roe"))
        m.roic = _first(m.roic, fh("roic"))
        m.debt_to_equity = _first(m.debt_to_equity, fh("debt_to_equity"), td("debt_to_equity"))
        m.revenue_ttm = _first(m.revenue_ttm, td("revenue_ttm"), av("revenue_ttm"))
        m.net_income = _first(m.net_income, td("net_income_ttm"))
        if m.net_debt is None and td_o and td_o.total_debt is not None and td_o.total_cash is not None:
            m.net_debt = td_o.total_debt - td_o.total_cash

        # Revenue CAGR from EDGAR annual data. We OVERRIDE FMP's values here
        # because FMP's `*RevenueGrowthPerShare` fields are "per-share growth
        # over N years" (affected by buybacks), not CAGR. For AAPL with 35%
        # share-count reduction, FMP returns 174% for 10y — the per-share total
        # growth — instead of the true ~6% CAGR. The Growth section is labeled
        # "CAGR" in the UI, so EDGAR's clean math wins when annual data exists.
        if edgar_bundle and edgar_bundle.annual:
            annual_with_rev = [
                a for a in sorted(edgar_bundle.annual, key=lambda x: x.date)
                if a.revenue and a.revenue > 0
            ]
            if len(annual_with_rev) >= 2:
                latest = annual_with_rev[-1]
                def cagr_n(years: int) -> float | None:
                    if len(annual_with_rev) < years + 1:
                        return None
                    base = annual_with_rev[-(years + 1)]
                    if not base.revenue or base.revenue <= 0:
                        return None
                    return (latest.revenue / base.revenue) ** (1 / years) - 1
                # Override FMP's per-share value with true CAGR when computable
                cagr3 = cagr_n(3)
                cagr5 = cagr_n(5)
                cagr10 = cagr_n(10)
                if cagr3 is not None:
                    m.revenue_growth_3y = cagr3
                if cagr5 is not None:
                    m.revenue_growth_5y = cagr5
                if cagr10 is not None:
                    m.revenue_growth_10y = cagr10

        # Layer 3: derive remaining gaps from EDGAR quarterly (last 4) + balance sheet
        if edgar_bundle and edgar_bundle.quarterly:
            recent = edgar_bundle.quarterly[-4:]

            def ttm_sum(attr: str) -> float | None:
                """Sum non-None values across recent 4 quarters.

                Strict version (all 4 present) is the ideal. But early-stage
                tickers (recent IPOs like CRWV) can have gaps in EDGAR — we
                accept ≥3 of 4 quarters and return the partial sum rather than
                None, since "almost a year" is more useful than missing data.
                """
                vals = [getattr(p, attr) for p in recent
                        if getattr(p, attr) is not None]
                if len(vals) < 3:
                    return None
                return sum(vals)

            if m.revenue_ttm is None:
                m.revenue_ttm = ttm_sum("revenue")
            if m.net_income is None:
                m.net_income = ttm_sum("net_income")
            if m.free_cash_flow is None:
                m.free_cash_flow = ttm_sum("free_cash_flow")

            # Margins from EDGAR if AV didn't supply
            if m.profit_margin is None and m.revenue_ttm and m.net_income is not None:
                m.profit_margin = m.net_income / m.revenue_ttm

            # P/E and P/S from current price + EDGAR TTM if not set yet
            last_q = recent[-1] if recent else None
            if last_q is not None:
                if m.pe is None and quote_price:
                    ttm_eps = ttm_sum("eps")
                    if ttm_eps:  # truthy: non-zero and non-None
                        m.pe = quote_price / ttm_eps
                if m.price_to_sales is None and market_cap and m.revenue_ttm:
                    m.price_to_sales = market_cap / m.revenue_ttm
                if m.fcf_yield is None and m.free_cash_flow and market_cap:
                    m.fcf_yield = m.free_cash_flow / market_cap
                if m.price_to_free_cash_flow is None and market_cap and m.free_cash_flow:
                    # P/FCF: positive only — negative FCF makes the ratio meaningless
                    if m.free_cash_flow > 0:
                        m.price_to_free_cash_flow = market_cap / m.free_cash_flow
                if m.net_debt is None and last_q.cash is not None and last_q.debt is not None:
                    m.net_debt = last_q.debt - last_q.cash

        # Forward P/E derivation from Finnhub earnings-calendar EPS estimates.
        # Useful when /stock/metric's `forwardPE` is None (unprofitable tickers
        # like CRWV) — gives the same mathematically-computable Forward P/E
        # that AlphaScope shows.
        if m.forward_pe is None and quote_price and fh_forward_eps:
            m.forward_pe = quote_price / fh_forward_eps

        # Forward PEG: forward P/E divided by expected earnings growth rate.
        # Only meaningful when growth is positive (negative or zero growth
        # makes PEG nonsense). We try eps_growth_ttm first (Finnhub), then
        # fall back to revenue growth (rougher but available more often).
        if m.forward_peg is None and m.forward_pe is not None and m.forward_pe > 0:
            growth = None
            if fh_o and fh_o.eps_growth_ttm and fh_o.eps_growth_ttm > 0:
                growth = fh_o.eps_growth_ttm
            elif m.revenue_growth_3y and m.revenue_growth_3y > 0:
                growth = m.revenue_growth_3y
            if growth:
                # PEG convention: P/E / (growth% as integer)
                # e.g., P/E 30, growth 15% → PEG = 30 / 15 = 2.0
                m.forward_peg = m.forward_pe / (growth * 100)

        # Earnings yield = 1 / P/E. Computed last so it captures EDGAR-derived
        # P/E values too (e.g. CRWV's negative P/E from a negative TTM EPS).
        if m.earnings_yield is None and m.pe not in (None, 0):
            m.earnings_yield = 1.0 / m.pe

        return m

    # ─── Historical P/E and P/S (per-period) ────────────────────────────

    @staticmethod
    def _compute_ratios(
        periods: list[FinancialPeriod],
        prices: list[PricePoint],
        *,
        cadence: str,
    ) -> None:
        """In-place: compute pe and ps for each period using price history."""
        if not periods or not prices:
            return

        price_dates = [p.date for p in prices]
        price_values = [p.close for p in prices]

        def price_at_or_before(date_str: str) -> float | None:
            idx = bisect_right(price_dates, date_str) - 1
            if 0 <= idx < len(price_values):
                return price_values[idx]
            return None

        ordered = sorted(periods, key=lambda x: x.date)

        for i, p in enumerate(ordered):
            price = price_at_or_before(p.date)
            if price is None:
                continue

            if cadence == "FY":
                eps = p.eps
                revenue = p.revenue
                shares = p.weighted_shares
            else:
                if i < 3:
                    continue
                window = ordered[i - 3:i + 1]
                if any(rp.eps is None for rp in window):
                    eps = None
                else:
                    eps = sum(rp.eps for rp in window)
                if any(rp.revenue is None for rp in window):
                    revenue = None
                else:
                    revenue = sum(rp.revenue for rp in window)
                shares = p.weighted_shares

            if eps:
                p.pe = price / eps
            if revenue and shares:
                p.ps = (price * shares) / revenue
