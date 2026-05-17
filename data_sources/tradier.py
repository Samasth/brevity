"""Tradier adapter — options chains for the Gamma Exposure page.

Tradier offers a free market-data account (no brokerage funding required)
with full options chain access. Set TRADIER_TOKEN in .env. The sandbox
endpoint returns delayed quotes; production returns real-time.

Docs: https://documentation.tradier.com/brokerage-api/
"""
from __future__ import annotations

import os
from typing import Any

import pandas as pd
import requests

from . import cache
from .base import OptionChain, OptionExpiration

PROD_BASE = "https://api.tradier.com/v1"
SANDBOX_BASE = "https://sandbox.tradier.com/v1"

TIMEOUT = 12

TTL_EXPIRATIONS = 6 * 3600   # 6 h
TTL_CHAIN = 60               # 1 min
TTL_QUOTE = 30               # 30 s


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


class TradierSource:
    name = "tradier"

    def __init__(self, token: str | None = None, environment: str | None = None):
        self.token = (token or os.getenv("TRADIER_TOKEN", "")).strip()
        env = (environment or os.getenv("TRADIER_ENV", "sandbox")).strip().lower()
        self.base = PROD_BASE if env == "production" else SANDBOX_BASE
        self.environment = "production" if env == "production" else "sandbox"

    @property
    def available(self) -> bool:
        return bool(self.token)

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/json",
        }

    # ─── HTTP ────────────────────────────────────────────────────────────

    def _get(self, path: str, params: dict | None = None, ttl: int = TTL_CHAIN) -> Any:
        if not self.available:
            return None
        params = dict(params or {})
        cache_key = (
            f"tradier_{self.environment}__{path}__"
            + "&".join(f"{k}={v}" for k, v in sorted(params.items()))
        )
        hit = cache.get(cache_key, ttl)
        if hit is not None:
            return hit
        try:
            r = requests.get(
                f"{self.base}/{path}",
                params=params,
                headers=self._headers,
                timeout=TIMEOUT,
            )
            if r.status_code != 200:
                return None
            data = r.json()
        except (requests.RequestException, ValueError):
            return None
        cache.put(cache_key, data)
        return data

    # ─── Expirations ─────────────────────────────────────────────────────

    def get_expirations(self, ticker: str) -> list[OptionExpiration]:
        data = self._get(
            "markets/options/expirations",
            {"symbol": ticker.upper(), "includeAllRoots": "true", "strikes": "false"},
            ttl=TTL_EXPIRATIONS,
        )
        if not isinstance(data, dict):
            return []
        exp = data.get("expirations")
        if not isinstance(exp, dict):
            return []
        dates = exp.get("date") or []
        if isinstance(dates, str):
            dates = [dates]
        return [OptionExpiration(date=d) for d in dates if d]

    # ─── Spot quote ──────────────────────────────────────────────────────

    def get_spot(self, ticker: str) -> float | None:
        data = self._get(
            "markets/quotes",
            {"symbols": ticker.upper(), "greeks": "false"},
            ttl=TTL_QUOTE,
        )
        if not isinstance(data, dict):
            return None
        q = data.get("quotes", {}).get("quote")
        if isinstance(q, list):
            q = q[0] if q else None
        if not isinstance(q, dict):
            return None
        return _f(q.get("last")) or _f(q.get("close"))

    # ─── Option chain ────────────────────────────────────────────────────

    def get_chain(self, ticker: str, expiration: str) -> OptionChain | None:
        spot = self.get_spot(ticker)
        if spot is None:
            return None

        data = self._get(
            "markets/options/chains",
            {"symbol": ticker.upper(), "expiration": expiration, "greeks": "true"},
            ttl=TTL_CHAIN,
        )
        if not isinstance(data, dict):
            return None
        options = data.get("options")
        if not isinstance(options, dict):
            return None
        rows = options.get("option") or []
        if isinstance(rows, dict):
            rows = [rows]
        if not rows:
            return None

        records = []
        for r in rows:
            if not isinstance(r, dict):
                continue
            greeks = r.get("greeks") or {}
            records.append({
                "strike": _f(r.get("strike")),
                "side": r.get("option_type"),  # "call" or "put"
                "open_interest": int(r.get("open_interest") or 0),
                "volume": int(r.get("volume") or 0),
                "implied_volatility": _f(greeks.get("smv_vol")) or _f(greeks.get("mid_iv")),
                "delta": _f(greeks.get("delta")),
                "gamma": _f(greeks.get("gamma")),
                "bid": _f(r.get("bid")),
                "ask": _f(r.get("ask")),
            })
        df = pd.DataFrame(records)
        df = df[df["strike"].notna() & df["side"].isin(["call", "put"])]
        return OptionChain(
            ticker=ticker.upper(),
            expiration=expiration,
            spot=spot,
            df=df,
        )
