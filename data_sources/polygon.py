"""Polygon.io adapter — options chains for the Gamma Exposure page.

Polygon offers an email-only signup (no brokerage account, no SSN, no KYC).
Their options data requires a paid plan — Options Starter is $29/mo as of
this writing and gives unlimited API calls + greeks + open interest.

Docs: https://polygon.io/docs/options
Signup: https://polygon.io/dashboard/signup
"""
from __future__ import annotations

import os
from typing import Any

import pandas as pd
import requests

from . import cache
from .base import OptionChain, OptionExpiration

BASE = "https://api.polygon.io"
TIMEOUT = 15

TTL_EXPIRATIONS = 6 * 3600
TTL_CHAIN = 60
TTL_QUOTE = 60


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


class PolygonSource:
    name = "polygon"

    def __init__(self, api_key: str | None = None):
        self.api_key = (api_key or os.getenv("POLYGON_API_KEY", "")).strip()

    @property
    def available(self) -> bool:
        return bool(self.api_key)

    @property
    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}"}

    # ─── HTTP ────────────────────────────────────────────────────────────

    def _get(self, path: str, params: dict | None = None, ttl: int = TTL_CHAIN) -> Any:
        if not self.available:
            return None
        params = dict(params or {})

        cache_key = f"polygon__{path}__" + "&".join(
            f"{k}={v}" for k, v in sorted(params.items())
        )
        hit = cache.get(cache_key, ttl)
        if hit is not None:
            return hit

        url = path if path.startswith("http") else f"{BASE}{path}"
        try:
            r = requests.get(url, params=params, headers=self._headers, timeout=TIMEOUT)
            if r.status_code != 200:
                return None
            data = r.json()
        except (requests.RequestException, ValueError):
            return None
        cache.put(cache_key, data)
        return data

    def _paginate(self, path: str, params: dict, ttl: int) -> list[dict]:
        """Walk Polygon's `next_url` pagination links and return all results."""
        all_results: list[dict] = []
        data = self._get(path, params, ttl=ttl)
        while data and isinstance(data.get("results"), list):
            all_results.extend(data["results"])
            next_url = data.get("next_url")
            if not next_url:
                break
            # next_url already contains the cursor; just append apiKey
            sep = "&" if "?" in next_url else "?"
            data = self._get(
                f"{next_url}{sep}apiKey={self.api_key}",
                params=None,
                ttl=ttl,
            )
            # safety cap — should never exceed a few pages per ticker
            if len(all_results) > 5000:
                break
        return all_results

    # ─── Expirations ─────────────────────────────────────────────────────

    def get_expirations(self, ticker: str) -> list[OptionExpiration]:
        """List unexpired option-contract expirations for `ticker`."""
        results = self._paginate(
            "/v3/reference/options/contracts",
            {
                "underlying_ticker": ticker.upper(),
                "expired": "false",
                "limit": 1000,
            },
            ttl=TTL_EXPIRATIONS,
        )
        # Each contract has expiration_date — dedupe
        unique = sorted({
            r.get("expiration_date") for r in results if r.get("expiration_date")
        })
        return [OptionExpiration(date=d) for d in unique]

    # ─── Spot quote ──────────────────────────────────────────────────────

    def get_spot(self, ticker: str) -> float | None:
        # The previous-day close is the simplest free endpoint; for delayed/
        # real-time during market hours, Polygon's snapshot is also fine.
        data = self._get(
            f"/v2/aggs/ticker/{ticker.upper()}/prev",
            {"adjusted": "true"},
            ttl=TTL_QUOTE,
        )
        if isinstance(data, dict) and data.get("results"):
            r0 = data["results"][0]
            return _f(r0.get("c"))  # close
        return None

    # ─── Option chain ────────────────────────────────────────────────────

    def get_chain(self, ticker: str, expiration: str) -> OptionChain | None:
        ticker = ticker.upper()
        results = self._paginate(
            f"/v3/snapshot/options/{ticker}",
            {
                "expiration_date": expiration,
                "limit": 250,
            },
            ttl=TTL_CHAIN,
        )
        if not results:
            return None

        # Pull spot from the underlying_asset field in the first row
        spot = None
        for r in results:
            ua = r.get("underlying_asset")
            if isinstance(ua, dict):
                spot = _f(ua.get("price"))
                if spot:
                    break
        if spot is None:
            spot = self.get_spot(ticker)
        if spot is None:
            return None

        records = []
        for r in results:
            details = r.get("details") or {}
            greeks = r.get("greeks") or {}
            last_quote = r.get("last_quote") or {}
            records.append({
                "strike": _f(details.get("strike_price")),
                "side": details.get("contract_type"),  # "call" / "put"
                "open_interest": int(r.get("open_interest") or 0),
                "volume": int((r.get("day") or {}).get("volume") or 0),
                "implied_volatility": _f(r.get("implied_volatility")),
                "delta": _f(greeks.get("delta")),
                "gamma": _f(greeks.get("gamma")),
                "bid": _f(last_quote.get("bid")),
                "ask": _f(last_quote.get("ask")),
            })

        df = pd.DataFrame(records)
        df = df[df["strike"].notna() & df["side"].isin(["call", "put"])]
        return OptionChain(
            ticker=ticker,
            expiration=expiration,
            spot=spot,
            df=df,
        )
