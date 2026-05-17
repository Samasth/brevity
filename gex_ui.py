"""Gamma Exposure — Streamlit UI.

Renders the dealer GEX profile for a ticker. Powered by Tradier option
chains (free market-data account) — no scraping, fully TOS-clean.
"""
from __future__ import annotations

import streamlit as st
import plotly.graph_objects as go

from data_sources import get_options_source, list_options_source_status
from gamma_exposure import (
    CACHE_TTL_SECONDS,
    EXPIRY_FILTERS,
    _cache,
    calculate_gex,
    get_available_filters,
)


# ─── Style ───────────────────────────────────────────────────────────────────

C = {
    "bg": "#0e1117",
    "card": "#161b22",
    "card_alt": "#1a1f29",
    "border": "#222936",
    "accent": "#a3e635",
    "accent_dim": "rgba(163,230,53,0.18)",
    "green": "#10b981",
    "green_dim": "rgba(16,185,129,0.25)",
    "red": "#ef4444",
    "red_dim": "rgba(239,68,68,0.25)",
    "blue": "#3b82f6",
    "yellow": "#fbbf24",
    "white": "#e6edf3",
    "muted": "#8b949e",
    "grid": "#1f2733",
}


def _regime_badge(regime: str) -> str:
    if regime == "positive":
        return (
            f'<span style="background:#064e3b;color:{C["green"]};padding:4px 12px;'
            f'border-radius:12px;font-weight:600;font-size:14px;">'
            f'POSITIVE GAMMA &mdash; Mean Reverting</span>'
        )
    return (
        f'<span style="background:#450a0a;color:{C["red"]};padding:4px 12px;'
        f'border-radius:12px;font-weight:600;font-size:14px;">'
        f'NEGATIVE GAMMA &mdash; Trending / Volatile</span>'
    )


def _metric_card(label: str, value: str, *, color: str | None = None) -> None:
    color = color or C["white"]
    st.markdown(
        f'<div style="background:{C["card"]};border:1px solid {C["border"]};'
        f'border-radius:8px;padding:12px 16px;text-align:center;">'
        f'<div style="color:{C["muted"]};font-size:11px;text-transform:uppercase;'
        f'letter-spacing:0.05em;">{label}</div>'
        f'<div style="color:{color};font-size:22px;font-weight:700;margin-top:4px;">'
        f'{value}</div></div>',
        unsafe_allow_html=True,
    )


def _render_no_source_screen(polygon_key: str, tradier_token: str) -> None:
    """When no options-data source is configured, lay out the three paths."""
    sources = list_options_source_status(
        polygon_key=polygon_key, tradier_token=tradier_token,
    )

    st.warning(
        "**No options-data provider configured.** Add one of the API keys below "
        "to your `.env` (or the sidebar) to use the Gamma Exposure page."
    )

    cards_html = ""
    for s in sources:
        status_chip = (
            f'<span style="color:{C["green"]};font-size:11px;'
            f'background:rgba(16,185,129,0.15);padding:3px 9px;border-radius:999px;">'
            f'✓ Configured</span>'
            if s["configured"] else
            f'<span style="color:{C["muted"]};font-size:11px;'
            f'background:{C["card_alt"]};padding:3px 9px;border-radius:999px;">'
            f'Not configured</span>'
        )
        cards_html += (
            f'<div style="background:{C["card"]};border:1px solid {C["border"]};'
            f'border-radius:12px;padding:18px 20px;flex:1;min-width:240px;">'
            f'<div style="display:flex;justify-content:space-between;align-items:center;">'
            f'<div style="color:{C["white"]};font-size:16px;font-weight:700;">{s["name"]}</div>'
            f'{status_chip}'
            f'</div>'
            f'<div style="color:{C["muted"]};font-size:13px;margin-top:8px;">{s["tier"]}</div>'
            f'<a href="{s["signup"]}" target="_blank" '
            f'style="color:{C["accent"]};font-size:12px;text-decoration:none;'
            f'display:inline-block;margin-top:10px;">{s["signup"]} ↗</a>'
            f'</div>'
        )

    st.markdown(
        f'<div style="display:flex;gap:14px;flex-wrap:wrap;margin-top:8px;">'
        f'{cards_html}</div>',
        unsafe_allow_html=True,
    )

    st.markdown(
        f'<div style="color:{C["muted"]};font-size:12px;margin-top:18px;line-height:1.6;">'
        f'<b>Which should you pick?</b><br>'
        f'• <b>Polygon</b> ($29/mo) — easiest signup, no SSN/KYC, instant access.<br>'
        f'• <b>Tradier</b> (free) — best value if you can get through their brokerage KYC. '
        f'Their public form requires US citizen / permanent resident status.<br>'
        f'• <b>Interactive Brokers</b> (free, ~$4.50/mo OPRA) — accepts H1B and most '
        f'international users. Requires running TWS/Gateway locally; the brevity '
        f'adapter is not yet built (PRs welcome).'
        f'</div>',
        unsafe_allow_html=True,
    )


# ─── Page ────────────────────────────────────────────────────────────────────

def render(
    polygon_key: str = "",
    tradier_token: str = "",
    tradier_env: str = "sandbox",
) -> None:
    """Render the Gamma Exposure page."""
    st.markdown(
        f'<h1 style="margin-bottom:0;color:{C["white"]};">'
        f'Gamma Exposure '
        f'<span style="color:{C["muted"]};font-size:18px;font-weight:400;">GEX</span></h1>',
        unsafe_allow_html=True,
    )
    st.caption(
        "Dealer gamma positioning by strike — support, resistance, pin levels, "
        "and volatility regime. Optional page; needs an options-data provider."
    )

    source = get_options_source(
        polygon_key=polygon_key,
        tradier_token=tradier_token,
        tradier_env=tradier_env,
    )
    if source is None:
        _render_no_source_screen(polygon_key, tradier_token)
        return

    # Active source badge
    st.markdown(
        f'<div style="display:inline-block;background:{C["accent_dim"]};'
        f'color:{C["accent"]};padding:3px 12px;border-radius:999px;'
        f'font-size:11px;font-weight:600;letter-spacing:0.04em;'
        f'text-transform:uppercase;margin:0 0 12px 0;">'
        f'Source: {source.name}</div>',
        unsafe_allow_html=True,
    )

    # ─── Controls ───────────────────────────────────────────────────────
    col1, col2, col3 = st.columns([1, 2, 1])
    with col1:
        ticker = st.text_input(
            "Ticker", placeholder="SPY",
            key="gex_ticker",
        ).strip().upper()

    expiry_filter = "all"
    with col2:
        if ticker:
            cache_key = f"_gex_filters_{ticker}"
            if cache_key not in st.session_state:
                st.session_state[cache_key] = get_available_filters(source, ticker)
            filters = st.session_state[cache_key]

            try:
                all_dates = [e.date for e in source.get_expirations(ticker)]
            except Exception:
                all_dates = []

            filter_keys = list(filters.keys())
            filter_labels = list(filters.values())
            if all_dates:
                filter_keys.append("__divider__")
                filter_labels.append("── Individual Dates ──")
                for d in all_dates[:20]:
                    filter_keys.append(d)
                    filter_labels.append(f"  {d}")

            if not filter_keys:
                st.selectbox(
                    "Expiration Filter",
                    ["No expirations available"], disabled=True,
                    key="gex_expiry_empty",
                )
            else:
                idx = st.selectbox(
                    "Expiration Filter",
                    range(len(filter_keys)),
                    format_func=lambda i: filter_labels[i],
                    key="gex_expiry_select",
                )
                selected_key = filter_keys[idx]
                if selected_key == "__divider__":
                    selected_key = "all"
                expiry_filter = selected_key
        else:
            st.selectbox("Expiration Filter", ["All Expirations"],
                         disabled=True, key="gex_expiry_disabled")

    with col3:
        zoom_pct = st.slider(
            "Chart Zoom (%)", min_value=5, max_value=30, value=12,
            help="How far from spot price to show on the chart",
            key="gex_zoom",
        )

    if not ticker:
        st.info("Enter a ticker (try **SPY**, **QQQ**, **AAPL**) to load the gamma profile.")
        return

    cache_key = f"{ticker}:{source.name}:{expiry_filter}"
    is_cached = False
    if cache_key in _cache:
        import time as _t
        age = _t.time() - _cache[cache_key][0]
        if age < CACHE_TTL_SECONDS:
            is_cached = True
    btn_label = f"Refresh {ticker} (cached)" if is_cached else f"Calculate GEX for {ticker}"

    if not st.button(btn_label, type="primary", key="gex_calc_btn"):
        st.caption(f"Selected: **{ticker}** · {EXPIRY_FILTERS.get(expiry_filter, expiry_filter)}")
        return

    with st.spinner(f"Pulling option chain(s) for {ticker}…"):
        result = calculate_gex(source, ticker, expiry_filter=expiry_filter)

    if result is None:
        st.error(
            f"No option chain data returned for **{ticker}**. "
            "Index symbols like ^SPX aren't supported — try the corresponding ETF (SPY)."
        )
        return

    _render_result(result, zoom_pct=zoom_pct)


def _render_result(r, zoom_pct: int) -> None:
    # Header row
    h_col1, h_col2 = st.columns([2, 1])
    with h_col1:
        st.markdown(
            f'<div style="display:flex;align-items:center;gap:14px;">'
            f'<div style="font-size:24px;font-weight:700;color:{C["white"]};">{r.ticker}</div>'
            f'<div style="font-size:18px;color:{C["muted"]};">${r.spot:.2f}</div>'
            f'{_regime_badge(r.regime)}'
            f'</div>',
            unsafe_allow_html=True,
        )
    with h_col2:
        st.caption(f"{len(r.gex_by_strike)} strikes analyzed")

    # Metric cards
    m1, m2, m3, m4 = st.columns(4)
    sign = "+" if r.total_gex >= 0 else "−"
    color = C["green"] if r.total_gex >= 0 else C["red"]
    with m1:
        _metric_card("Total Net GEX", f"{sign}{abs(r.total_gex/1e9):.2f}B", color=color)
    with m2:
        _metric_card("Call Wall (R)", f"${r.call_wall:.2f}", color=C["green"])
    with m3:
        _metric_card("Put Wall (S)", f"${r.put_wall:.2f}", color=C["red"])
    with m4:
        flip = f"${r.gamma_flip:.2f}" if r.gamma_flip is not None else "—"
        _metric_card("Gamma Flip", flip, color=C["yellow"])

    # GEX-by-strike chart
    df = r.gex_by_strike.copy()
    df["color"] = df["net_gex"].apply(lambda x: C["green"] if x >= 0 else C["red"])

    lo, hi = r.spot * (1 - zoom_pct / 100), r.spot * (1 + zoom_pct / 100)
    df = df[(df["strike"] >= lo) & (df["strike"] <= hi)]

    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=df["strike"], y=df["net_gex"] / 1e9,
        marker_color=df["color"], marker_line_width=0,
        hovertemplate="Strike $%{x}<br>Net GEX %{y:.2f}B<extra></extra>",
        name="Net GEX",
    ))

    # Annotate key levels
    annotations = []
    for lvl in r.key_levels:
        if not (lo <= lvl["level"] <= hi):
            continue
        if lvl["type"] == "spot":
            color = C["yellow"]; dash = "dot"
        elif lvl["type"] == "call_wall":
            color = C["green"]; dash = "dash"
        elif lvl["type"] == "put_wall":
            color = C["red"]; dash = "dash"
        elif lvl["type"] == "gamma_flip":
            color = C["blue"]; dash = "dashdot"
        else:
            continue
        fig.add_vline(x=lvl["level"], line_color=color, line_dash=dash, line_width=1.5)
        annotations.append(dict(
            x=lvl["level"], y=1.02, yref="paper",
            xref="x", showarrow=False,
            text=lvl["label"], font=dict(size=10, color=color),
        ))

    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color=C["white"], size=11),
        height=500, showlegend=False,
        xaxis=dict(gridcolor=C["grid"], title="Strike",
                   tickprefix="$"),
        yaxis=dict(gridcolor=C["grid"], title="Net GEX ($B per 1% move)",
                   ticksuffix="B", zerolinecolor=C["muted"], zerolinewidth=1),
        annotations=annotations,
        margin=dict(l=10, r=10, t=40, b=10),
        hoverlabel=dict(bgcolor=C["card_alt"], bordercolor=C["border"]),
    )
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

    # Key levels table
    st.markdown(
        f'<div style="color:{C["muted"]};font-size:11px;text-transform:uppercase;'
        f'letter-spacing:0.08em;margin:18px 0 6px 0;">Key Levels</div>',
        unsafe_allow_html=True,
    )
    rows_html = ""
    for lvl in r.key_levels:
        dist_pct = (lvl["level"] - r.spot) / r.spot * 100
        rows_html += (
            f'<div style="display:flex;justify-content:space-between;'
            f'padding:7px 0;border-bottom:1px dashed {C["border"]};font-size:13px;">'
            f'<div style="color:{C["muted"]};">{lvl["label"]}</div>'
            f'<div style="color:{C["white"]};font-weight:600;">'
            f'${lvl["level"]:.2f} <span style="color:{C["muted"]};font-weight:400;">'
            f'({dist_pct:+.2f}%)</span></div></div>'
        )
    st.markdown(
        f'<div style="background:{C["card"]};border:1px solid {C["border"]};'
        f'border-radius:12px;padding:16px 18px;">{rows_html}</div>',
        unsafe_allow_html=True,
    )
