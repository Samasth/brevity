"""Gamma Exposure (GEX) — computes dealer gamma positioning by strike.

  - Positive GEX strike: dealers buy dips, sell rips (price magnet)
  - Negative GEX strike: dealers sell dips, buy rips (accelerant)
  - Gamma flip: where net GEX crosses zero — pivot
  - Put wall:  highest put gamma     (support)
  - Call wall: highest call gamma    (resistance)

Data comes through `OptionsSource` (Tradier). Tradier returns pre-computed
greeks (gamma, IV) so we use them directly; Black-Scholes is the fallback
when a row is missing greeks.
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd

from data_sources.base import OptionsSource


# ─── Cache ───────────────────────────────────────────────────────────────────

_cache: dict[str, tuple[float, "GEXResult"]] = {}
CACHE_TTL_SECONDS = 300


# ─── Black-Scholes gamma fallback ───────────────────────────────────────────

def _norm_pdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / math.sqrt(2 * math.pi)


def _bs_gamma(S: float, K: float, T: float, r: float, sigma: float) -> float:
    if T <= 0 or sigma <= 0 or S <= 0 or K <= 0:
        return 0.0
    sqrt_T = math.sqrt(T)
    d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * sqrt_T)
    return _norm_pdf(d1) / (S * sigma * sqrt_T)


# ─── Expiry filters ──────────────────────────────────────────────────────────

EXPIRY_FILTERS = {
    "all":       "All Expirations",
    "0dte":      "0DTE (Today Only)",
    "ex0dte":    "All ex-0DTE",
    "this_week": "This Week",
    "next_2w":   "Next 2 Weeks",
    "next_30d":  "Next 30 Days",
    "monthly":   "Monthly OPEX Only",
    "quarterly": "Quarterly OPEX Only",
}


def get_available_filters(source: OptionsSource, ticker: str) -> dict[str, str]:
    """Return filter keys that have at least one matching expiration for `ticker`."""
    try:
        exps = source.get_expirations(ticker)
    except Exception:
        return {"all": "All Expirations"}
    if not exps:
        return {}
    dates = [e.date for e in exps]

    today = date.today()
    today_str = today.isoformat()
    week_end = today + timedelta(days=(4 - today.weekday()))
    cutoff_2w = today + timedelta(days=14)
    cutoff_30d = today + timedelta(days=30)

    available: dict[str, str] = {"all": f"All Expirations ({len(dates)})"}

    if today_str in dates:
        available["0dte"] = "0DTE (Today Only)"

    ex0 = [d for d in dates if d != today_str]
    if ex0:
        available["ex0dte"] = f"All ex-0DTE ({len(ex0)})"

    tw = [d for d in dates if today <= datetime.strptime(d, "%Y-%m-%d").date() <= week_end]
    if tw:
        available["this_week"] = f"This Week ({len(tw)} exp)"

    n2w = [d for d in dates if datetime.strptime(d, "%Y-%m-%d").date() <= cutoff_2w]
    if n2w:
        available["next_2w"] = f"Next 2 Weeks ({len(n2w)} exp)"

    n30 = [d for d in dates if datetime.strptime(d, "%Y-%m-%d").date() <= cutoff_30d]
    if n30:
        available["next_30d"] = f"Next 30 Days ({len(n30)} exp)"

    monthly = [
        d for d in dates
        if (dt := datetime.strptime(d, "%Y-%m-%d").date()).weekday() == 4
           and 15 <= dt.day <= 21
    ]
    if monthly:
        dates_str = ", ".join(m[5:] for m in monthly[:3])
        suffix = f" +{len(monthly)-3} more" if len(monthly) > 3 else ""
        available["monthly"] = f"Monthly OPEX ({dates_str}{suffix})"

    quarterly = [
        d for d in dates
        if (dt := datetime.strptime(d, "%Y-%m-%d").date()).weekday() == 4
           and 15 <= dt.day <= 21
           and dt.month in (3, 6, 9, 12)
    ]
    if quarterly:
        dates_str = ", ".join(q[5:] for q in quarterly[:3])
        suffix = f" +{len(quarterly)-3} more" if len(quarterly) > 3 else ""
        available["quarterly"] = f"Quarterly OPEX ({dates_str}{suffix})"

    return available


def _filter_expirations(dates: list[str], expiry_filter: str) -> list[str]:
    today = date.today()
    today_str = today.isoformat()

    if expiry_filter == "all":
        return dates
    if expiry_filter == "0dte":
        return [d for d in dates if d == today_str]
    if expiry_filter == "ex0dte":
        return [d for d in dates if d != today_str]
    if expiry_filter == "this_week":
        week_end = today + timedelta(days=(4 - today.weekday()))
        return [d for d in dates if today <= datetime.strptime(d, "%Y-%m-%d").date() <= week_end]
    if expiry_filter == "next_2w":
        cutoff = today + timedelta(days=14)
        return [d for d in dates if datetime.strptime(d, "%Y-%m-%d").date() <= cutoff]
    if expiry_filter == "next_30d":
        cutoff = today + timedelta(days=30)
        return [d for d in dates if datetime.strptime(d, "%Y-%m-%d").date() <= cutoff]
    if expiry_filter == "monthly":
        return [
            d for d in dates
            if (dt := datetime.strptime(d, "%Y-%m-%d").date()).weekday() == 4
               and 15 <= dt.day <= 21
        ]
    if expiry_filter == "quarterly":
        return [
            d for d in dates
            if (dt := datetime.strptime(d, "%Y-%m-%d").date()).weekday() == 4
               and 15 <= dt.day <= 21
               and dt.month in (3, 6, 9, 12)
        ]
    # Specific date
    return [d for d in dates if d == expiry_filter]


# ─── Result type ─────────────────────────────────────────────────────────────

@dataclass
class GEXResult:
    ticker: str
    spot: float
    gex_by_strike: pd.DataFrame  # strike, call_gex, put_gex, net_gex
    total_gex: float
    gamma_flip: float | None
    max_gamma_strike: float
    call_wall: float
    put_wall: float
    key_levels: list[dict]
    regime: str  # "positive" or "negative"


# ─── Calculation ─────────────────────────────────────────────────────────────

def calculate_gex(
    source: OptionsSource,
    ticker: str,
    expiry_filter: str = "all",
    risk_free_rate: float = 0.045,
) -> GEXResult | None:
    """Compute net dealer GEX per strike for `ticker`.

    Args:
        source: An OptionsSource (e.g. TradierSource).
        ticker: Underlying symbol.
        expiry_filter: One of the EXPIRY_FILTERS keys, or a specific YYYY-MM-DD.
        risk_free_rate: For the Black-Scholes gamma fallback.
    """
    ticker = ticker.upper().strip()
    cache_key = f"{ticker}:{source.name}:{expiry_filter}"
    if cache_key in _cache:
        t0, cached = _cache[cache_key]
        if time.time() - t0 < CACHE_TTL_SECONDS:
            return cached

    exps = source.get_expirations(ticker)
    if not exps:
        return None
    dates = [e.date for e in exps]
    dates = _filter_expirations(dates, expiry_filter)
    if not dates:
        return None

    spot = source.get_spot(ticker)
    if spot is None or spot <= 0:
        return None

    today = date.today()
    all_rows = []
    for exp_str in dates:
        try:
            exp_date = datetime.strptime(exp_str, "%Y-%m-%d").date()
        except ValueError:
            continue
        T = max((exp_date - today).days, 1) / 365.0

        chain = source.get_chain(ticker, exp_str)
        if chain is None or chain.df.empty:
            continue

        for _, row in chain.df.iterrows():
            strike = row.get("strike")
            side = row.get("side")
            oi = int(row.get("open_interest") or 0)
            if strike is None or side not in ("call", "put") or oi <= 0:
                continue

            gamma = row.get("gamma")
            iv = row.get("implied_volatility")
            if gamma is None or pd.isna(gamma):
                # Fallback: compute via Black-Scholes
                if iv is None or pd.isna(iv) or iv <= 0:
                    iv = 0.30  # rough default
                gamma = _bs_gamma(spot, strike, T, risk_free_rate, iv)
            if gamma <= 0:
                continue

            # GEX = OI × 100 × gamma × spot × 1%
            # Puts treated as negative (dealers short gamma when short puts)
            gex = oi * 100 * float(gamma) * spot * 0.01
            if side == "put":
                gex = -gex

            all_rows.append({
                "strike": float(strike),
                "side": side,
                "oi": oi,
                "iv": float(iv) if iv is not None and not pd.isna(iv) else None,
                "gamma": float(gamma),
                "gex": gex,
            })

    if not all_rows:
        return None

    raw = pd.DataFrame(all_rows)
    call_gex = raw[raw["side"] == "call"].groupby("strike")["gex"].sum().rename("call_gex")
    put_gex = raw[raw["side"] == "put"].groupby("strike")["gex"].sum().rename("put_gex")
    gex_df = pd.DataFrame({"call_gex": call_gex, "put_gex": put_gex}).fillna(0)
    gex_df["net_gex"] = gex_df["call_gex"] + gex_df["put_gex"]
    gex_df = gex_df.reset_index()

    # Focus around spot (±30%)
    gex_df = gex_df[
        (gex_df["strike"] >= spot * 0.70) & (gex_df["strike"] <= spot * 1.30)
    ].copy()
    if gex_df.empty:
        return None

    total_gex = float(gex_df["net_gex"].sum())
    max_idx = gex_df["net_gex"].abs().idxmax()
    max_gamma_strike = float(gex_df.loc[max_idx, "strike"])
    call_wall_idx = gex_df["call_gex"].idxmax()
    call_wall = float(gex_df.loc[call_wall_idx, "strike"])
    put_wall_idx = gex_df["put_gex"].idxmin()
    put_wall = float(gex_df.loc[put_wall_idx, "strike"])

    # Gamma flip — closest zero-crossing to spot
    sorted_gex = gex_df.sort_values("strike").reset_index(drop=True)
    gamma_flip = None
    nearest_flip_dist = float("inf")
    for i in range(len(sorted_gex) - 1):
        g1, g2 = sorted_gex.iloc[i]["net_gex"], sorted_gex.iloc[i + 1]["net_gex"]
        s1, s2 = sorted_gex.iloc[i]["strike"], sorted_gex.iloc[i + 1]["strike"]
        if g1 * g2 < 0:
            flip = s1 + (s2 - s1) * abs(g1) / (abs(g1) + abs(g2))
            dist = abs(flip - spot)
            if dist < nearest_flip_dist:
                nearest_flip_dist = dist
                gamma_flip = round(float(flip), 2)

    near_spot = gex_df[
        (gex_df["strike"] >= spot * 0.97) & (gex_df["strike"] <= spot * 1.03)
    ]
    spot_gex = near_spot["net_gex"].sum() if not near_spot.empty else total_gex
    regime = "positive" if spot_gex > 0 else "negative"

    key_levels: list[dict] = [
        {"level": spot, "label": "Current Price", "type": "spot"},
        {"level": call_wall, "label": "Call Wall (resistance)", "type": "call_wall",
         "gex": float(gex_df.loc[call_wall_idx, "call_gex"])},
        {"level": put_wall, "label": "Put Wall (support)", "type": "put_wall",
         "gex": float(gex_df.loc[put_wall_idx, "put_gex"])},
    ]
    if gamma_flip is not None:
        key_levels.append({"level": gamma_flip, "label": "Gamma Flip (pivot)",
                           "type": "gamma_flip"})

    top_pos = gex_df.nlargest(3, "net_gex")
    for _, r in top_pos.iterrows():
        if r["strike"] not in (call_wall, put_wall):
            key_levels.append({
                "level": float(r["strike"]),
                "label": "High +GEX (magnet)",
                "type": "positive_gex",
                "gex": float(r["net_gex"]),
            })
    top_neg = gex_df.nsmallest(3, "net_gex")
    for _, r in top_neg.iterrows():
        if r["strike"] not in (call_wall, put_wall):
            key_levels.append({
                "level": float(r["strike"]),
                "label": "High -GEX (accelerant)",
                "type": "negative_gex",
                "gex": float(r["net_gex"]),
            })
    key_levels.sort(key=lambda x: x["level"])

    result = GEXResult(
        ticker=ticker,
        spot=spot,
        gex_by_strike=gex_df,
        total_gex=total_gex,
        gamma_flip=gamma_flip,
        max_gamma_strike=max_gamma_strike,
        call_wall=call_wall,
        put_wall=put_wall,
        key_levels=key_levels,
        regime=regime,
    )
    _cache[cache_key] = (time.time(), result)
    return result
