"""SEC EDGAR adapter — deep historical fundamentals from US government data.

The SEC publishes XBRL-tagged financial data for every US public company at
data.sec.gov. Coverage: 15-25 years for major filers, no rate limit (10/sec
fair-use ceiling), no API key required.

Fair-use policy asks for a User-Agent with contact info — supplied via the
EDGAR_CONTACT_EMAIL env var.

Docs: https://www.sec.gov/edgar/sec-api-documentation
"""
from __future__ import annotations

import os
import time
from collections import defaultdict
from datetime import date
from typing import Any

import requests

from . import cache
from .base import (
    CompanyProfile,
    FinancialPeriod,
    FundamentalsBundle,
    KeyMetricsTTM,
    Quote,
)

CIK_MAP_URL = "https://www.sec.gov/files/company_tickers.json"
COMPANYFACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"

TTL_CIK_MAP = 7 * 24 * 3600      # 7 days
TTL_COMPANYFACTS = 24 * 3600     # 24 hours

TIMEOUT = 30  # companyfacts can be 5–10 MB

# Concept aliases. For each field, try the (concept, unit, taxonomy) tuples in
# order; the first one with data wins. Different filers and different filing
# eras use different concept names — Apple alone switched its primary revenue
# concept from `Revenues` (2016) → `SalesRevenueNet` → `RevenueFromContract…`.
CONCEPTS: dict[str, list[tuple[str, str, str]]] = {
    "revenue": [
        ("RevenueFromContractWithCustomerExcludingAssessedTax", "USD", "us-gaap"),
        ("Revenues", "USD", "us-gaap"),
        ("SalesRevenueNet", "USD", "us-gaap"),
        ("RevenueFromContractWithCustomerIncludingAssessedTax", "USD", "us-gaap"),
    ],
    "gross_profit": [("GrossProfit", "USD", "us-gaap")],
    "cost_of_revenue": [
        # Used to derive gross_profit when GrossProfit isn't reported
        # (e.g., CRWV reports cost separately but not gross profit directly).
        ("CostOfRevenue", "USD", "us-gaap"),
        ("CostOfGoodsAndServicesSold", "USD", "us-gaap"),
        ("CostOfGoodsSold", "USD", "us-gaap"),
    ],
    "operating_income": [("OperatingIncomeLoss", "USD", "us-gaap")],
    "net_income": [
        ("NetIncomeLoss", "USD", "us-gaap"),
        ("ProfitLoss", "USD", "us-gaap"),
    ],
    "eps": [
        ("EarningsPerShareDiluted", "USD/shares", "us-gaap"),
        ("EarningsPerShareBasic", "USD/shares", "us-gaap"),
    ],
    "cash": [
        ("CashAndCashEquivalentsAtCarryingValue", "USD", "us-gaap"),
        ("Cash", "USD", "us-gaap"),
        ("CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents", "USD", "us-gaap"),
    ],
    "long_term_debt": [
        ("LongTermDebt", "USD", "us-gaap"),
        ("LongTermDebtNoncurrent", "USD", "us-gaap"),
    ],
    "short_term_debt": [
        ("ShortTermBorrowings", "USD", "us-gaap"),
        ("DebtCurrent", "USD", "us-gaap"),
        ("LongTermDebtCurrent", "USD", "us-gaap"),
    ],
    "cash_from_ops": [
        ("NetCashProvidedByUsedInOperatingActivities", "USD", "us-gaap"),
        ("NetCashProvidedByUsedInOperatingActivitiesContinuingOperations", "USD", "us-gaap"),
    ],
    "capex": [
        ("PaymentsToAcquirePropertyPlantAndEquipment", "USD", "us-gaap"),
        ("PaymentsToAcquireProductiveAssets", "USD", "us-gaap"),
    ],
    "depreciation": [
        # Prefer the comprehensive D&A concept (used by AAPL, NVDA in recent filings)
        ("DepreciationDepletionAndAmortization", "USD", "us-gaap"),
        ("DepreciationAndAmortization", "USD", "us-gaap"),
        ("Depreciation", "USD", "us-gaap"),
    ],
    # Diluted weighted-average shares for the period. Used to compute historical
    # P/S = (price × shares) / revenue. NOT a flow concept — the value is the
    # weighted average over the reporting period, not a sum that can be
    # YTD-derived. We treat it like a balance-sheet field downstream.
    "weighted_shares": [
        ("WeightedAverageNumberOfDilutedSharesOutstanding", "shares", "us-gaap"),
        ("WeightedAverageNumberOfSharesOutstandingBasic", "shares", "us-gaap"),
    ],
    # NOTE: CommonStockSharesOutstanding intentionally not included. It's a
    # point-in-time concept reported at filing/cover dates (e.g., 2026-04-17)
    # rather than quarter-ends, which would create phantom period buckets.
    # FMP's profile endpoint gives us the current share count for the header.
}

# Income-statement / cash-flow concepts have `start`–`end` ranges. Balance
# sheet items are point-in-time (`end` only).
FLOW_FIELDS = {
    "revenue", "gross_profit", "cost_of_revenue", "operating_income",
    "net_income", "eps", "cash_from_ops", "capex", "depreciation",
}

# Concepts that have start–end ranges (like flow) but the value is a weighted
# average over the period, not a sum. We need fp/duration filtering but must
# NOT do YTD subtraction.
PERIOD_AVERAGE_FIELDS = {"weighted_shares"}


# ─── Source ──────────────────────────────────────────────────────────────────

class EdgarSource:
    name = "edgar"

    def __init__(self, contact_email: str | None = None):
        self.contact_email = (
            contact_email if contact_email is not None
            else os.getenv("EDGAR_CONTACT_EMAIL", "")
        ).strip()
        self._ticker_to_cik: dict[str, str] | None = None
        self._last_request = 0.0

    @property
    def available(self) -> bool:
        return bool(self.contact_email)

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "User-Agent": f"brevity {self.contact_email}",
            "Accept": "application/json",
        }

    # ─── HTTP with self-throttle + cache ────────────────────────────────

    def _get_json(self, url: str, cache_key: str, ttl: int) -> Any:
        hit = cache.get(cache_key, ttl)
        if hit is not None:
            return hit

        # SEC fair-use: ≤10 req/sec. We pace at ~6/sec to stay polite.
        elapsed = time.time() - self._last_request
        if elapsed < 0.15:
            time.sleep(0.15 - elapsed)

        try:
            r = requests.get(url, headers=self._headers, timeout=TIMEOUT)
            self._last_request = time.time()
            if r.status_code != 200:
                return None
            data = r.json()
        except (requests.RequestException, ValueError):
            return None

        cache.put(cache_key, data)
        return data

    # ─── CIK lookup ─────────────────────────────────────────────────────

    def _load_cik_map(self) -> dict[str, str]:
        if self._ticker_to_cik is not None:
            return self._ticker_to_cik
        raw = self._get_json(CIK_MAP_URL, "edgar_ticker_map", TTL_CIK_MAP)
        if not raw:
            self._ticker_to_cik = {}
            return {}
        mapping = {
            v["ticker"]: str(v["cik_str"]).zfill(10)
            for v in raw.values()
            if v.get("ticker") and v.get("cik_str") is not None
        }
        self._ticker_to_cik = mapping
        return mapping

    def get_cik(self, ticker: str) -> str | None:
        return self._load_cik_map().get(ticker.upper())

    def _fetch_companyfacts(self, cik: str) -> dict | None:
        url = COMPANYFACTS_URL.format(cik=cik)
        return self._get_json(url, f"edgar_cf_{cik}", TTL_COMPANYFACTS)

    # ─── Concept extraction ─────────────────────────────────────────────

    @staticmethod
    def _extract_concept(
        facts: dict,
        aliases: list[tuple[str, str, str]],
    ) -> list[dict]:
        """Merge records from every matching alias.

        Different filers — and the same filer over time — use different concept
        names. AAPL switched from `Revenues` → `RevenueFromContract…` in 2017;
        NVDA still uses `Revenues` for everything. Pulling from all aliases
        avoids missing data when a fixed order doesn't match the filer's choice.
        The downstream `_dedupe_latest_filed` resolves overlaps by `filed` date
        (with first-listed alias winning ties — so we prefer Diluted over Basic
        for EPS, etc.).
        """
        merged: list[dict] = []
        for concept_name, unit, taxonomy in aliases:
            concept = facts.get(taxonomy, {}).get(concept_name)
            if not concept:
                continue
            units = concept.get("units", {}).get(unit)
            if units:
                merged.extend(units)
        return merged

    @staticmethod
    def _days_between(start: str, end: str) -> int | None:
        try:
            return (date.fromisoformat(end) - date.fromisoformat(start)).days
        except ValueError:
            return None

    @classmethod
    def _is_quarterly_range(cls, r: dict) -> bool:
        """Single-quarter range, ≈ 80–100 days."""
        if not r.get("start") or not r.get("end"):
            return False
        d = cls._days_between(r["start"], r["end"])
        return d is not None and 75 <= d <= 100

    @classmethod
    def _is_annual_range(cls, r: dict) -> bool:
        if not r.get("start") or not r.get("end"):
            return False
        d = cls._days_between(r["start"], r["end"])
        return d is not None and 350 <= d <= 380

    @staticmethod
    def _dedupe_latest_filed(records: list[dict]) -> list[dict]:
        """For each (end, fp), keep only the record with the latest `filed`."""
        by_key: dict[tuple[str, str], dict] = {}
        for r in records:
            end = r.get("end")
            fp = r.get("fp") or ""
            if not end:
                continue
            key = (end, fp)
            existing = by_key.get(key)
            if existing is None or (r.get("filed", "") > existing.get("filed", "")):
                by_key[key] = r
        return list(by_key.values())

    # ─── Period assembly ────────────────────────────────────────────────

    @classmethod
    def _normalize_flow_records(cls, records: list[dict],
                                *, subtract_ytd: bool = True) -> list[dict]:
        """Convert any mix of standalone-quarter and YTD records into standalone
        per-period records.

        Some filers (AAPL, NVDA) report cash flow ONLY as YTD aggregates in
        their 10-Qs — a single 6-month value for Q2, 9-month for Q3 — rather
        than the standalone quarter. We detect this by grouping records by
        (fiscal_year, start_date) and computing deltas across the YTD sequence:

            Q1 = 3-month YTD                    (used as-is)
            Q2 = 6-month YTD − 3-month YTD
            Q3 = 9-month YTD − 6-month YTD
            FY = 12-month value                 (used as-is)

        If a group has only one record, we trust the filing's `fp` and `val`.
        """
        grouped: dict[tuple, list[dict]] = defaultdict(list)
        for r in records:
            fy = r.get("fy")
            start = r.get("start")
            end = r.get("end")
            if fy is None or not start or not end:
                continue
            grouped[(fy, start)].append(r)

        # Valid (fp, duration) combinations. The EDGAR `fp` field is the
        # FILING's fiscal period, not the data's — so a 10-K can tag historical
        # quarterly data with fp="FY". We reject records where fp says one
        # thing but the start/end range says another.
        FP_DURATION_BOUNDS = {
            "Q1": (75, 100),
            "Q2": (75, 200),   # standalone (90d) or 6-month YTD (180d)
            "Q3": (75, 290),   # standalone (90d) or 9-month YTD (270d)
            "FY": (350, 380),
        }

        def _fp_consistent(r: dict) -> bool:
            fp = r.get("fp")
            if not fp or fp not in FP_DURATION_BOUNDS:
                return False
            days = cls._days_between(r.get("start"), r.get("end"))
            if days is None:
                return False
            lo, hi = FP_DURATION_BOUNDS[fp]
            return lo <= days <= hi

        derived: list[dict] = []
        for (fy, start), recs in grouped.items():
            # Drop records whose fp doesn't match their duration — e.g., a 10-K
            # tagging a 90-day Q2 with fp="FY".
            recs = [r for r in recs if _fp_consistent(r)]
            if not recs:
                continue

            # Dedupe within the group by end_date, keeping latest filed
            by_end: dict[str, dict] = {}
            for r in recs:
                end = r["end"]
                if end not in by_end or r.get("filed", "") > by_end[end].get("filed", ""):
                    by_end[end] = r
            recs_sorted = sorted(by_end.values(), key=lambda x: x["end"])

            # If only one record shares this (fy, start), it's a standalone
            # period — trust the filing's `fp` and `val`. Filers like AMD/MSFT
            # report cash flow this way (start = quarter_start, not fy_start).
            if len(recs_sorted) == 1:
                derived.append(recs_sorted[0])
                continue

            # Multiple records with the same start: YTD progression. AAPL, NVDA,
            # CRWV report cash flow this way (start = fy_start; ends grow by a
            # quarter each filing).
            ytd = {
                cls._days_between(start, r["end"]): r["val"]
                for r in recs_sorted
                if cls._days_between(start, r["end"]) is not None
                   and r.get("val") is not None
            }

            for r in recs_sorted:
                days = cls._days_between(start, r["end"])
                if days is None:
                    continue
                val = r.get("val")
                if val is None:
                    continue

                # For "weighted average over period" fields (e.g., diluted
                # shares), don't subtract — the reported value is already the
                # average over [start..end]. We just use the duration to assign
                # the right fp.
                if 75 <= days <= 100:
                    fp, new_val = "Q1", val
                elif 170 <= days <= 200:
                    if subtract_ytd:
                        prev = next((ytd[d] for d in ytd if 75 <= d <= 100), 0)
                        fp, new_val = "Q2", val - prev
                    else:
                        fp, new_val = "Q2", val
                elif 260 <= days <= 290:
                    if subtract_ytd:
                        prev = next((ytd[d] for d in ytd if 170 <= d <= 200), 0)
                        fp, new_val = "Q3", val - prev
                    else:
                        fp, new_val = "Q3", val
                elif 350 <= days <= 380:
                    fp, new_val = "FY", val
                else:
                    fp, new_val = r.get("fp"), val

                if not fp:
                    continue

                derived.append({**r, "fp": fp, "val": new_val})

        return derived

    def _build_buckets(self, facts: dict) -> dict[tuple[str, str], dict]:
        """Build {(end_date, fp): {field: value, fiscal_year: N}}."""
        buckets: dict[tuple[str, str], dict] = defaultdict(dict)

        for field, aliases in CONCEPTS.items():
            records = self._extract_concept(facts, aliases)
            if not records:
                continue

            # Flow concepts: derive standalone-quarter values from YTD aggregates.
            # Period-average concepts (shares): same fp/duration handling but
            # no YTD subtraction since the value is already a period average.
            if field in FLOW_FIELDS:
                records = self._normalize_flow_records(records, subtract_ytd=True)
            elif field in PERIOD_AVERAGE_FIELDS:
                records = self._normalize_flow_records(records, subtract_ytd=False)

            records = self._dedupe_latest_filed(records)

            for r in records:
                key = (r["end"], r.get("fp") or "")
                val = r.get("val")
                if val is None:
                    continue
                buckets[key][field] = val
                if r.get("fy") is not None:
                    buckets[key]["fiscal_year"] = r["fy"]

        return buckets

    def _derive_q4(self, buckets: dict[tuple[str, str], dict]) -> None:
        """Compute Q4 for each fiscal year as FY − (Q1 + Q2 + Q3).

        US 10-K filings cover Q4 implicitly, so EDGAR doesn't expose Q4 as a
        standalone record. Without derivation, the quarterly chart shows only
        3 bars per fiscal year.

        We match FY end-dates to their preceding Q1/Q2/Q3 by date arithmetic
        (FY-end − 9/6/3 months ±30 days). The EDGAR `fy` field can't be used
        for grouping because it's the FILING's fiscal year, not the data's.
        """
        from datetime import timedelta

        def parse(s: str) -> date | None:
            try:
                return date.fromisoformat(s)
            except (TypeError, ValueError):
                return None

        # Index buckets by (period, end_date) for quick lookup
        by_period: dict[str, dict[date, dict]] = defaultdict(dict)
        for (end, fp), data in buckets.items():
            d = parse(end)
            if d is not None and fp:
                by_period[fp][d] = data

        def find_nearest(fp: str, target: date, tolerance_days: int = 30):
            """Find the (end_date, data) for `fp` closest to `target`."""
            best: tuple[date, dict] | None = None
            best_diff = tolerance_days + 1
            for d, data in by_period.get(fp, {}).items():
                diff = abs((d - target).days)
                if diff < best_diff:
                    best = (d, data)
                    best_diff = diff
            return best

        for fy_end_str, fy_data in list(by_period.get("FY", {}).items()):
            fy_end_d = fy_end_str  # already a date
            q1 = find_nearest("Q1", fy_end_d - timedelta(days=275))  # ~9 months prior
            q2 = find_nearest("Q2", fy_end_d - timedelta(days=185))  # ~6 months prior
            q3 = find_nearest("Q3", fy_end_d - timedelta(days=95))   # ~3 months prior
            if not (q1 and q2 and q3):
                continue

            q4_data: dict = {"fiscal_year": fy_data.get("fiscal_year")}

            for field in ("revenue", "gross_profit", "cost_of_revenue",
                          "operating_income", "net_income", "eps",
                          "cash_from_ops", "capex", "depreciation"):
                fy_v = fy_data.get(field)
                q_vs = [q1[1].get(field), q2[1].get(field), q3[1].get(field)]
                if fy_v is not None and all(v is not None for v in q_vs):
                    q4_data[field] = fy_v - sum(q_vs)

            # Balance sheet + weighted-shares: snapshot from FY (Q4 weighted
            # shares ≈ FY weighted shares; close enough for charting)
            for field in ("cash", "long_term_debt", "short_term_debt",
                          "weighted_shares"):
                if field in fy_data:
                    q4_data[field] = fy_data[field]

            if q4_data and any(k for k in q4_data if k != "fiscal_year"):
                buckets[(fy_end_d.isoformat(), "Q4")] = q4_data

    # ─── Public API ─────────────────────────────────────────────────────

    def get_bundle(self, ticker: str) -> FundamentalsBundle | None:
        ticker = ticker.upper().strip()
        if not self.available or not ticker:
            return None

        cik = self.get_cik(ticker)
        if not cik:
            return None

        cf = self._fetch_companyfacts(cik)
        if not cf:
            return None

        facts = cf.get("facts", {})
        if not facts:
            return None

        # Skip non-USD filers (foreign private issuers like NBIS report in RUB)
        if not self._has_usd_data(facts):
            return None

        buckets = self._build_buckets(facts)
        self._derive_q4(buckets)

        periods = self._buckets_to_periods(buckets)
        # Drop any bucket with no core financial data — guards against
        # off-quarter-end records (cover-page metadata, etc.) sneaking in.
        periods = [
            p for p in periods
            if p.revenue is not None or p.net_income is not None
        ]
        periods.sort(key=lambda p: p.date)

        quarterly = [p for p in periods if p.period == "Q"]
        annual = [p for p in periods if p.period == "FY"]

        profile = CompanyProfile(
            ticker=ticker,
            name=cf.get("entityName", ""),
            cik=cik,
        )

        return FundamentalsBundle(
            profile=profile,
            quote=Quote(ticker=ticker),         # filled by FMP via merged source
            metrics_ttm=KeyMetricsTTM(),        # filled by FMP via merged source
            quarterly=quarterly,
            annual=annual,
            sources=["edgar"],
        )

    @staticmethod
    def _has_usd_data(facts: dict) -> bool:
        """Confirm this filer reports primary financials in USD."""
        for field in ("revenue", "net_income"):
            for name, unit, tax in CONCEPTS[field]:
                if facts.get(tax, {}).get(name, {}).get("units", {}).get(unit):
                    return True
        return False

    @staticmethod
    def _buckets_to_periods(
        buckets: dict[tuple[str, str], dict],
    ) -> list[FinancialPeriod]:
        out: list[FinancialPeriod] = []
        for (end_date, fp), data in buckets.items():
            if not fp:
                continue

            rev = data.get("revenue")
            gp = data.get("gross_profit")
            cor = data.get("cost_of_revenue")
            opi = data.get("operating_income")
            depr = data.get("depreciation")
            cfo = data.get("cash_from_ops")
            cap = data.get("capex")

            # Derive gross_profit when not directly reported (e.g., CRWV files
            # CostOfRevenue but not GrossProfit).
            if gp is None and rev is not None and cor is not None:
                gp = rev - cor

            gm = (gp / rev) if (rev and gp is not None and rev != 0) else None
            ebitda = (opi + depr) if (opi is not None and depr is not None) else None
            fcf = (cfo - cap) if (cfo is not None and cap is not None) else None

            lt = data.get("long_term_debt")
            st = data.get("short_term_debt")
            total_debt = None
            if lt is not None or st is not None:
                total_debt = (lt or 0) + (st or 0)

            out.append(FinancialPeriod(
                date=end_date,
                period="FY" if fp == "FY" else "Q",
                fiscal_year=data.get("fiscal_year"),
                revenue=rev,
                gross_profit=gp,
                gross_margin=gm,
                ebitda=ebitda,
                operating_income=opi,
                net_income=data.get("net_income"),
                eps=data.get("eps"),
                cash_from_ops=cfo,
                # FMP/yfinance convention: capex shown negative
                capex=-cap if cap is not None else None,
                free_cash_flow=fcf,
                cash=data.get("cash"),
                debt=total_debt,
                weighted_shares=data.get("weighted_shares"),
            ))
        return out
