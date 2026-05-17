"""Company Fundamentals — Streamlit UI.

Backed by EDGAR (15-25y of historical financials) + FMP (current quote,
profile, TTM ratios). All free and TOS-clean.
"""
from __future__ import annotations

from typing import Iterable

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from data_sources import (
    FinancialPeriod,
    FundamentalsBundle,
    get_fundamentals_source,
)
from data_sources import cache as ds_cache


# ─── Style ───────────────────────────────────────────────────────────────────

C = {
    "bg": "#0e1117",
    "card": "#161b22",
    "card_alt": "#1a1f29",
    "border": "#222936",
    "accent": "#a3e635",
    "accent_dim": "rgba(163,230,53,0.18)",
    "blue": "#3b82f6",
    "green": "#10b981",
    "red": "#ef4444",
    "white": "#e6edf3",
    "muted": "#8b949e",
    "grid": "#1f2733",
}

PLOTLY_LAYOUT = dict(
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(0,0,0,0)",
    font=dict(color=C["white"], size=11),
    margin=dict(l=10, r=10, t=10, b=10),
    xaxis=dict(gridcolor=C["grid"], zerolinecolor=C["grid"], showline=False),
    yaxis=dict(gridcolor=C["grid"], zerolinecolor=C["grid"], showline=False),
    hoverlabel=dict(bgcolor=C["card_alt"], bordercolor=C["border"], font_color=C["white"]),
)


def _inject_css() -> None:
    st.markdown(
        f"""
        <style>
        .as-header {{
            background: linear-gradient(135deg, {C['card']} 0%, {C['card_alt']} 100%);
            border: 1px solid {C['border']};
            border-radius: 14px;
            padding: 22px 28px;
            margin-bottom: 18px;
        }}
        .as-title {{
            font-size: 28px; font-weight: 700; color: {C['white']};
            margin: 0; line-height: 1.15;
        }}
        .as-sub {{
            color: {C['muted']}; font-size: 13px; margin-top: 4px;
            letter-spacing: 0.02em;
        }}
        .as-pill {{
            display: inline-block;
            background: {C['accent_dim']}; color: {C['accent']};
            padding: 3px 10px; border-radius: 999px;
            font-size: 11px; font-weight: 600;
            letter-spacing: 0.04em; text-transform: uppercase;
            margin-right: 6px;
        }}
        .as-kv {{
            display: flex; justify-content: space-between;
            padding: 7px 0; border-bottom: 1px dashed {C['border']};
            font-size: 13px;
        }}
        .as-kv:last-child {{ border-bottom: none; }}
        .as-kv-k {{ color: {C['muted']}; }}
        .as-kv-v {{ color: {C['white']}; font-weight: 600; }}
        .as-chip-up {{
            background: rgba(16,185,129,0.18); color: {C['green']};
            padding: 3px 9px; border-radius: 999px;
            font-size: 12px; font-weight: 700;
        }}
        .as-chip-down {{
            background: rgba(239,68,68,0.18); color: {C['red']};
            padding: 3px 9px; border-radius: 999px;
            font-size: 12px; font-weight: 700;
        }}
        .as-section-head {{
            color: {C['muted']}; font-size: 11px;
            text-transform: uppercase; letter-spacing: 0.08em;
            margin: 22px 0 8px 0;
        }}
        .as-stat-card {{
            background: {C['card']};
            border: 1px solid {C['border']};
            border-radius: 12px; padding: 16px 18px;
        }}
        .as-stat-h {{
            color: {C['accent']}; font-size: 12px; font-weight: 700;
            text-transform: uppercase; letter-spacing: 0.06em;
            margin: 0 0 10px 0;
            border-bottom: 1px solid {C['border']}; padding-bottom: 6px;
        }}
        .as-chart-title {{
            color: {C['white']}; font-size: 13px; font-weight: 600;
            text-align: center; padding: 6px 0 4px 0;
        }}
        [data-testid="stVerticalBlockBorderWrapper"] {{
            background: {C['card']};
            border-color: {C['border']} !important;
            border-radius: 12px !important;
        }}
        [data-testid="stButton"] button[kind="secondary"] {{
            min-height: 32px; padding: 2px 8px;
            background: transparent; border: 1px solid {C['border']};
            color: {C['muted']}; font-size: 14px;
        }}
        [data-testid="stButton"] button[kind="secondary"]:hover {{
            color: {C['accent']}; border-color: {C['accent']};
            background: transparent;
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )


# ─── Formatters ──────────────────────────────────────────────────────────────

def _fmt_money(x: float | None, decimals: int = 2) -> str:
    if x is None:
        return "—"
    abs_x = abs(x)
    sign = "-" if x < 0 else ""
    if abs_x >= 1e12:
        return f"{sign}${abs_x/1e12:.{decimals}f}T"
    if abs_x >= 1e9:
        return f"{sign}${abs_x/1e9:.{decimals}f}B"
    if abs_x >= 1e6:
        return f"{sign}${abs_x/1e6:.{decimals}f}M"
    if abs_x >= 1e3:
        return f"{sign}${abs_x/1e3:.{decimals}f}K"
    return f"{sign}${abs_x:.{decimals}f}"


def _fmt_num(x: float | None, decimals: int = 2) -> str:
    if x is None:
        return "—"
    abs_x = abs(x)
    sign = "-" if x < 0 else ""
    if abs_x >= 1e9:
        return f"{sign}{abs_x/1e9:.{decimals}f}B"
    if abs_x >= 1e6:
        return f"{sign}{abs_x/1e6:.{decimals}f}M"
    if abs_x >= 1e3:
        return f"{sign}{abs_x/1e3:.{decimals}f}K"
    return f"{sign}{abs_x:.{decimals}f}"


def _fmt_ratio(x: float | None, decimals: int = 2) -> str:
    return "—" if x is None else f"{x:.{decimals}f}"


def _fmt_pct(x: float | None, decimals: int = 2) -> str:
    return "—" if x is None else f"{x*100:.{decimals}f}%"


# ─── Header ──────────────────────────────────────────────────────────────────

def _render_header(b: FundamentalsBundle) -> None:
    p, q = b.profile, b.quote

    chip = ""
    if q.change_pct:
        cls = "as-chip-up" if q.change >= 0 else "as-chip-down"
        sign = "+" if q.change >= 0 else ""
        chip = f'<span class="{cls}">{sign}${q.change:.2f} ({sign}{q.change_pct:.2f}%)</span>'

    pills = []
    if p.exchange:
        pills.append(f'<span class="as-pill">{p.exchange}</span>')
    if p.sector:
        pills.append(f'<span class="as-pill">{p.sector}</span>')
    if p.cik:
        pills.append(f'<span class="as-pill">CIK {p.cik.lstrip("0")}</span>')

    logo_html = (
        f'<img src="{p.image}" style="width:64px;height:64px;border-radius:10px;'
        f'border:1px solid {C["border"]};background:#fff;padding:4px;" />'
        if p.image else
        f'<div style="width:64px;height:64px;border-radius:10px;'
        f'border:1px solid {C["border"]};background:{C["card_alt"]};'
        f'display:flex;align-items:center;justify-content:center;'
        f'font-size:24px;font-weight:800;color:{C["accent"]};">{p.ticker[:2]}</div>'
    )

    price_block = (
        f'<div style="text-align:right;">'
        f'  <div style="color:{C["muted"]};font-size:11px;text-transform:uppercase;'
        f'        letter-spacing:0.06em;">Last Price</div>'
        f'  <div style="color:{C["white"]};font-size:32px;font-weight:700;line-height:1.1;">'
        f'    ${q.price:.2f}</div>'
        f'  <div style="color:{C["muted"]};font-size:11px;margin-top:2px;">'
        f'    {p.industry or ""}</div>'
        f'</div>'
        if q.price > 0 else ""
    )

    st.markdown(
        f"""
        <div class="as-header">
          <div style="display:flex;align-items:center;gap:18px;">
            {logo_html}
            <div style="flex:1;">
              <div>{''.join(pills)}</div>
              <div class="as-title">{p.name or p.ticker}</div>
              <div class="as-sub">{p.ticker} {chip}</div>
            </div>
            {price_block}
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # KV pair cards
    left, right = st.columns(2)
    with left:
        rows = [
            ("Market Cap", _fmt_money(q.market_cap, 2)),
            ("Revenue (TTM)", _fmt_money(b.metrics_ttm.revenue_ttm, 2)),
            ("Shares Outstanding", _fmt_num(q.shares_outstanding, 2)),
            ("Website",
                f'<a href="{p.website}" target="_blank" '
                f'style="color:{C["accent"]};text-decoration:none;">{p.website or "—"}</a>'
                if p.website else "—"),
        ]
        st.markdown(_kv_card(rows), unsafe_allow_html=True)
    with right:
        # Analyst target with computed upside % when both are available
        if q.analyst_target_price and q.price:
            upside = (q.analyst_target_price - q.price) / q.price * 100
            up_color = C["green"] if upside >= 0 else C["red"]
            analyst_cell = (
                f'${q.analyst_target_price:.2f}  '
                f'<span style="color:{up_color};font-weight:400;font-size:11px;">'
                f'({upside:+.1f}%)</span>'
            )
        elif q.analyst_target_price:
            analyst_cell = f"${q.analyst_target_price:.2f}"
        else:
            analyst_cell = "—"

        rows = [
            ("Current Share Price", f"${q.price:.2f}" if q.price else "—"),
            ("Today's Change",
                f'<span style="color:{C["green"] if q.change >= 0 else C["red"]};">'
                f'${q.change:+.2f}</span>' if q.change else "—"),
            ("52wk Range",
                f"${q.week52_low:.2f} – ${q.week52_high:.2f}"
                if q.week52_low and q.week52_high else "—"),
            ("Analyst Target (12mo)", analyst_cell),
            ("Next Earnings", q.next_earnings_date or "—"),
        ]
        st.markdown(_kv_card(rows), unsafe_allow_html=True)


def _kv_card(rows: Iterable[tuple[str, str]]) -> str:
    body = "".join(
        f'<div class="as-kv"><div class="as-kv-k">{k}</div>'
        f'<div class="as-kv-v">{v}</div></div>'
        for k, v in rows
    )
    return f'<div class="as-stat-card">{body}</div>'


def _stat_card(title: str, rows: Iterable[tuple[str, str]]) -> str:
    body = "".join(
        f'<div class="as-kv"><div class="as-kv-k">{k}</div>'
        f'<div class="as-kv-v">{v}</div></div>'
        for k, v in rows
    )
    return f'<div class="as-stat-card"><div class="as-stat-h">{title}</div>{body}</div>'


# ─── TTM Stats Grid ──────────────────────────────────────────────────────────

def _render_stats(b: FundamentalsBundle) -> None:
    m = b.metrics_ttm
    st.markdown('<div class="as-section-head">Statistics (TTM)</div>', unsafe_allow_html=True)

    c1, c2 = st.columns(2)
    with c1:
        st.markdown(_stat_card("Earnings-Based Valuation", [
            ("Price to Earnings (P/E)", _fmt_ratio(m.pe, 3)),
            ("Forward P/E", _fmt_ratio(m.forward_pe, 3)),
            ("Price/Earnings Growth (PEG)", _fmt_ratio(m.peg, 3)),
            ("Forward PEG", _fmt_ratio(m.forward_peg, 3)),
            ("Earnings Yield",
                _fmt_pct(m.earnings_yield, 2)
                if m.earnings_yield is not None and abs(m.earnings_yield) < 1
                else _fmt_ratio(m.earnings_yield, 3)),
        ]), unsafe_allow_html=True)
    with c2:
        st.markdown(_stat_card("Revenue & Cash Flow Metrics", [
            ("Price to Sales (P/S)", _fmt_ratio(m.price_to_sales, 3)),
            ("Price to Cash Flow (P/CF)", _fmt_ratio(m.price_to_cash_flow, 3)),
            ("Price to FCF (P/FCF)", _fmt_ratio(m.price_to_free_cash_flow, 3)),
            ("Free Cash Flow Yield",
                _fmt_pct(m.fcf_yield, 2)
                if m.fcf_yield is not None and abs(m.fcf_yield) < 1
                else _fmt_ratio(m.fcf_yield, 3)),
        ]), unsafe_allow_html=True)

    c3, c4 = st.columns(2)
    with c3:
        st.markdown(_stat_card("Asset-Based Metrics", [
            ("Price to Book (P/B)", _fmt_ratio(m.price_to_book, 3)),
            ("Debt to Equity", _fmt_ratio(m.debt_to_equity, 3)),
        ]), unsafe_allow_html=True)
    with c4:
        st.markdown(_stat_card("Enterprise Value Multiples", [
            ("EV to EBITDA", _fmt_ratio(m.ev_to_ebitda, 3)),
            ("EV to Sales", _fmt_ratio(m.ev_to_sales, 3)),
        ]), unsafe_allow_html=True)

    c5, c6 = st.columns(2)
    with c5:
        st.markdown(_stat_card("Profitability", [
            ("Profit Margin", _fmt_pct(m.profit_margin)),
            ("Operating Margin", _fmt_pct(m.operating_margin)),
            ("Return on Equity (ROE)", _fmt_pct(m.roe)),
            ("Return on Invested Capital (ROIC)", _fmt_pct(m.roic)),
        ]), unsafe_allow_html=True)
    with c6:
        st.markdown(_stat_card("Growth (CAGR)", [
            ("Revenue 3y", _fmt_pct(m.revenue_growth_3y)),
            ("Revenue 5y", _fmt_pct(m.revenue_growth_5y)),
            ("Revenue 10y", _fmt_pct(m.revenue_growth_10y)),
        ]), unsafe_allow_html=True)

    c7, _ = st.columns(2)
    with c7:
        # Derive these from latest annual EDGAR data when FMP doesn't have them
        fcf = m.free_cash_flow
        ni = m.net_income
        nd = m.net_debt
        if (fcf is None or ni is None or nd is None) and b.annual:
            latest = b.annual[-1]
            if fcf is None:
                fcf = latest.free_cash_flow
            if ni is None:
                ni = latest.net_income
            if nd is None and latest.cash is not None and latest.debt is not None:
                nd = latest.debt - latest.cash
        st.markdown(_stat_card("Financial Health", [
            ("Free Cash Flow", _fmt_money(fcf)),
            ("Net Income", _fmt_money(ni)),
            ("Net Debt", _fmt_money(nd)),
            ("Debt to Equity", _fmt_ratio(m.debt_to_equity, 3)),
        ]), unsafe_allow_html=True)


# ─── Charts ──────────────────────────────────────────────────────────────────

def _bar_chart(periods: list[FinancialPeriod], attr: str, *,
               money: bool = True, pct: bool = False,
               color_signed: bool = True, height: int = 240) -> go.Figure:
    xs, ys = [], []
    for p in periods:
        v = getattr(p, attr)
        if v is None:
            continue
        xs.append(p.date)
        ys.append(v * 100 if pct else v)
    if not ys:
        return _empty_chart(height)
    if color_signed:
        colors = [C["accent"] if y >= 0 else C["red"] for y in ys]
    else:
        colors = [C["blue"]] * len(ys)

    if pct:
        hover = "%{x}<br>%{y:.2f}%<extra></extra>"
    elif money:
        text = [_fmt_money(y, 1) for y in ys]
        hover = "%{x}<br>%{customdata}<extra></extra>"
    else:
        hover = "%{x}<br>%{y:.2f}<extra></extra>"

    fig = go.Figure(go.Bar(
        x=xs, y=ys,
        marker_color=colors,
        marker_line_width=0,
        hovertemplate=hover,
        customdata=text if money and not pct else None,
    ))
    fig.update_layout(**PLOTLY_LAYOUT, height=height, showlegend=False)
    if pct:
        fig.update_yaxes(ticksuffix="%")
    return fig


def _line_chart(periods: list[FinancialPeriod], attr: str, *, height: int = 240) -> go.Figure:
    xs, ys = [], []
    for p in periods:
        v = getattr(p, attr)
        if v is None:
            continue
        xs.append(p.date)
        ys.append(v)
    if not ys:
        return _empty_chart(height)
    fig = go.Figure(go.Scatter(
        x=xs, y=ys, mode="lines+markers",
        line=dict(color=C["accent"], width=2),
        marker=dict(size=5, color=C["accent"]),
        fill="tozeroy",
        fillcolor=C["accent_dim"],
        hovertemplate="%{x}<br>%{y:.3f}<extra></extra>",
    ))
    fig.update_layout(**PLOTLY_LAYOUT, height=height, showlegend=False)
    return fig


def _price_chart(b: FundamentalsBundle, *, height: int = 240) -> go.Figure:
    if not b.price_history:
        return _empty_chart(height)
    xs = [p.date for p in b.price_history]
    ys = [p.close for p in b.price_history]
    fig = go.Figure(go.Scatter(
        x=xs, y=ys, mode="lines",
        line=dict(color=C["accent"], width=1.6),
        fill="tozeroy",
        fillcolor=C["accent_dim"],
        hovertemplate="%{x}<br>$%{y:.2f}<extra></extra>",
    ))
    fig.update_layout(**PLOTLY_LAYOUT, height=height, showlegend=False)
    fig.update_yaxes(tickprefix="$")
    return fig


def _cash_debt_chart(periods: list[FinancialPeriod], *, height: int = 240) -> go.Figure:
    if not periods:
        return _empty_chart(height)
    xs = [p.date for p in periods]
    cash = [p.cash if p.cash is not None else 0 for p in periods]
    debt = [p.debt if p.debt is not None else 0 for p in periods]
    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=xs, y=debt, name="Debt",
        marker_color=C["blue"], marker_line_width=0,
        hovertemplate="%{x}<br>Debt: %{customdata}<extra></extra>",
        customdata=[_fmt_money(v, 1) for v in debt],
    ))
    fig.add_trace(go.Bar(
        x=xs, y=cash, name="Cash",
        marker_color=C["accent"], marker_line_width=0,
        hovertemplate="%{x}<br>Cash: %{customdata}<extra></extra>",
        customdata=[_fmt_money(v, 1) for v in cash],
    ))
    fig.update_layout(
        **PLOTLY_LAYOUT, height=height, barmode="group",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0.5, xanchor="center"),
    )
    return fig


def _empty_chart(height: int = 240) -> go.Figure:
    fig = go.Figure()
    fig.add_annotation(
        text="No data available",
        xref="paper", yref="paper", x=0.5, y=0.5,
        showarrow=False, font=dict(color=C["muted"], size=12),
    )
    fig.update_layout(**PLOTLY_LAYOUT, height=height)
    return fig


# ─── Expand modal ────────────────────────────────────────────────────────────

def _data_table(periods: list[FinancialPeriod], attr: str, *,
                money: bool, pct: bool) -> pd.DataFrame | None:
    rows = []
    for p in periods:
        v = getattr(p, attr)
        if v is None:
            continue
        if pct:
            display = f"{v*100:.2f}%"
        elif money:
            display = _fmt_money(v, 2)
        else:
            display = _fmt_num(v, 3)
        rows.append({"Period": p.date, "Value": display})
    if not rows:
        return None
    df = pd.DataFrame(rows).sort_values("Period", ascending=False).reset_index(drop=True)
    return df


@st.dialog(" ", width="large")
def _chart_modal(title: str, kind: str, *,
                 periods: list[FinancialPeriod] | None = None,
                 attr: str | None = None,
                 money: bool = True,
                 pct: bool = False,
                 color_signed: bool = True,
                 bundle: FundamentalsBundle | None = None,
                 sources: list[str] | None = None) -> None:
    st.markdown(
        f'<h3 style="color:{C["white"]};margin:0 0 12px 0;">{title}</h3>',
        unsafe_allow_html=True,
    )

    if kind == "bar" and periods and attr:
        fig = _bar_chart(periods, attr, money=money, pct=pct,
                         color_signed=color_signed, height=520)
    elif kind == "line" and periods and attr:
        fig = _line_chart(periods, attr, height=520)
    elif kind == "price" and bundle:
        fig = _price_chart(bundle, height=520)
    elif kind == "cash_debt" and periods:
        fig = _cash_debt_chart(periods, height=520)
    else:
        fig = _empty_chart(520)

    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": True})

    st.markdown(
        f'<div style="color:{C["muted"]};font-size:11px;text-transform:uppercase;'
        f'letter-spacing:0.08em;margin:14px 0 6px 0;">Raw Values</div>',
        unsafe_allow_html=True,
    )

    if kind in ("bar", "line") and periods and attr:
        df = _data_table(periods, attr, money=money, pct=pct)
        if df is not None:
            st.dataframe(df, hide_index=True, use_container_width=True)
        else:
            st.caption("No data points available.")
    elif kind == "cash_debt" and periods:
        rows = [{
            "Period": p.date,
            "Cash": _fmt_money(p.cash, 2) if p.cash is not None else "—",
            "Debt": _fmt_money(p.debt, 2) if p.debt is not None else "—",
            "Net Debt": _fmt_money((p.debt or 0) - (p.cash or 0), 2),
        } for p in sorted(periods, key=lambda x: x.date, reverse=True)]
        st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)
    elif kind == "price" and bundle and bundle.price_history:
        ph = bundle.price_history
        st.caption(
            f"{len(ph)} daily price points · "
            f"{ph[0].date} → {ph[-1].date} · "
            f"high ${max(p.close for p in ph):.2f}, low ${min(p.close for p in ph):.2f}"
        )

    src_str = " + ".join(sources or [])
    if kind in ("bar", "line", "cash_debt"):
        note = "Historical financials from SEC EDGAR. Depth limited only by what the company has filed."
    else:
        note = "Daily prices from Financial Modeling Prep (free tier returns 5y)."
    st.caption(f"Source: **{src_str or 'unknown'}** · {note}")


# ─── Chart card ──────────────────────────────────────────────────────────────

def _chart_card(title: str, fig: go.Figure, key: str, *,
                modal: dict | None = None) -> None:
    with st.container(border=True):
        if modal is not None:
            t_col, b_col = st.columns([9, 1])
            with t_col:
                st.markdown(
                    f'<div class="as-chart-title">{title}</div>',
                    unsafe_allow_html=True,
                )
            with b_col:
                if st.button("⛶", key=f"exp_{key}", help="Expand chart"):
                    _chart_modal(title=title, **modal)
        else:
            st.markdown(
                f'<div class="as-chart-title">{title}</div>',
                unsafe_allow_html=True,
            )
        st.plotly_chart(fig, use_container_width=True, key=key,
                        config={"displayModeBar": False})


def _has_values(periods: list[FinancialPeriod], attr: str) -> bool:
    return any(getattr(p, attr) is not None for p in periods)


# ─── Chart wall ──────────────────────────────────────────────────────────────

def _render_charts(b: FundamentalsBundle, periods: list[FinancialPeriod], cadence: str) -> None:
    st.markdown(
        f'<div class="as-section-head">Latest Insights — {cadence}  '
        f'<span style="color:{C["muted"]};text-transform:none;letter-spacing:0;">'
        f'({len(periods)} periods available)</span></div>',
        unsafe_allow_html=True,
    )

    srcs = b.sources

    def bar_modal(attr, *, money=True, pct=False, color_signed=True):
        return dict(kind="bar", periods=periods, attr=attr,
                    money=money, pct=pct, color_signed=color_signed, sources=srcs)

    # Row 1: Price | Revenue | EBITDA
    r1c1, r1c2, r1c3 = st.columns(3)
    with r1c1:
        _chart_card("Stock Price (5Y)", _price_chart(b), key=f"price_{cadence}",
                    modal=dict(kind="price", bundle=b, sources=srcs))
    with r1c2:
        _chart_card("Revenue", _bar_chart(periods, "revenue", color_signed=False),
                    key=f"rev_{cadence}", modal=bar_modal("revenue", color_signed=False))
    with r1c3:
        _chart_card("EBITDA", _bar_chart(periods, "ebitda"),
                    key=f"ebitda_{cadence}", modal=bar_modal("ebitda"))

    # Row 2: Gross Profit | Gross Margin | Net Income
    r2c1, r2c2, r2c3 = st.columns(3)
    with r2c1:
        _chart_card("Gross Profit",
                    _bar_chart(periods, "gross_profit", color_signed=False),
                    key=f"gp_{cadence}",
                    modal=bar_modal("gross_profit", color_signed=False))
    with r2c2:
        _chart_card("Gross Profit Margin",
                    _bar_chart(periods, "gross_margin", money=False, pct=True, color_signed=False),
                    key=f"gpm_{cadence}",
                    modal=bar_modal("gross_margin", money=False, pct=True, color_signed=False))
    with r2c3:
        _chart_card("Net Income", _bar_chart(periods, "net_income"),
                    key=f"ni_{cadence}", modal=bar_modal("net_income"))

    # Row 3: CFO | FCF | EPS
    r3c1, r3c2, r3c3 = st.columns(3)
    with r3c1:
        _chart_card("Cash from Operations", _bar_chart(periods, "cash_from_ops"),
                    key=f"cfo_{cadence}", modal=bar_modal("cash_from_ops"))
    with r3c2:
        _chart_card("Free Cash Flow", _bar_chart(periods, "free_cash_flow"),
                    key=f"fcf_{cadence}", modal=bar_modal("free_cash_flow"))
    with r3c3:
        _chart_card("Earnings Per Share",
                    _bar_chart(periods, "eps", money=False),
                    key=f"eps_{cadence}",
                    modal=bar_modal("eps", money=False))

    # Row 4: Capex | Cash & Debt | Operating Income
    r4c1, r4c2, r4c3 = st.columns(3)
    with r4c1:
        _chart_card("Capital Expenditure", _bar_chart(periods, "capex"),
                    key=f"capex_{cadence}", modal=bar_modal("capex"))
    with r4c2:
        _chart_card("Cash and Debt", _cash_debt_chart(periods),
                    key=f"cd_{cadence}",
                    modal=dict(kind="cash_debt", periods=periods, sources=srcs))
    with r4c3:
        _chart_card("Operating Income",
                    _bar_chart(periods, "operating_income"),
                    key=f"opi_{cadence}",
                    modal=bar_modal("operating_income"))

    # Row 5: P/E History | P/S History (computed from price × shares / earnings).
    # These are derived in MergedSource — quarterly uses TTM (rolling 4 quarters),
    # annual uses direct values.
    pe_label = "Price to Earnings (TTM)" if cadence == "Quarterly" else "Price to Earnings"
    ps_label = "Price to Sales (TTM)" if cadence == "Quarterly" else "Price to Sales"

    r5c1, r5c2, _ = st.columns(3)
    with r5c1:
        _chart_card(pe_label, _line_chart(periods, "pe"),
                    key=f"pe_{cadence}",
                    modal=dict(kind="line", periods=periods, attr="pe",
                               money=False, sources=srcs))
    with r5c2:
        _chart_card(ps_label, _line_chart(periods, "ps"),
                    key=f"ps_{cadence}",
                    modal=dict(kind="line", periods=periods, attr="ps",
                               money=False, sources=srcs))


# ─── Page ────────────────────────────────────────────────────────────────────

def render(edgar_email: str = "", fmp_key: str = "",
           finnhub_key: str = "", twelvedata_key: str = "",
           alphavantage_key: str = "") -> None:
    """Render the Fundamentals page."""
    _inject_css()

    st.markdown(
        f'<h1 style="margin-bottom:0;color:{C["white"]};">'
        f'Company Fundamentals '
        f'<span style="color:{C["muted"]};font-size:18px;font-weight:400;">'
        f'· 15-25 years of free historical data via SEC EDGAR + FMP</span></h1>',
        unsafe_allow_html=True,
    )
    st.caption(
        "Historicals from SEC EDGAR (free, no key — just an email). "
        "Current quote + profile + TTM ratios from FMP free tier (250 req/day). "
        "Cached locally for fast reloads."
    )

    cc1, cc2, cc3 = st.columns([3, 2, 1])
    with cc1:
        ticker = st.text_input(
            "Ticker", placeholder="AAPL, NVDA, GOOGL, TSLA…",
            key="fund_ticker",
        ).strip().upper()
    with cc2:
        cadence = st.radio(
            "Cadence", ["Quarterly", "Annually"],
            horizontal=True, key="fund_cadence",
        )
    with cc3:
        st.write("")
        st.write("")
        if st.button("Clear cache", help="Delete on-disk cached responses"):
            n = ds_cache.clear()
            st.toast(f"Cleared {n} cached responses")

    if not ticker:
        st.info(
            "Enter a US-listed ticker to load fundamentals. "
            "Add `EDGAR_CONTACT_EMAIL` and `FMP_API_KEY` to your `.env` for the best experience."
        )
        _render_source_status(
            edgar_email, fmp_key, finnhub_key, twelvedata_key, alphavantage_key,
        )
        return

    src = get_fundamentals_source(
        edgar_email=edgar_email,
        fmp_key=fmp_key,
        finnhub_key=finnhub_key,
        twelvedata_key=twelvedata_key,
        alphavantage_key=alphavantage_key,
    )
    if not src.available:
        st.error(
            "No data sources configured. Add `EDGAR_CONTACT_EMAIL` (free, no signup) "
            "or `FMP_API_KEY` (free 250/day) to `.env` or the sidebar."
        )
        return

    with st.spinner(f"Fetching {ticker} from EDGAR + FMP…"):
        try:
            bundle = src.get_bundle(ticker)
        except Exception as e:
            st.error(f"Fetch failed: {e}")
            return

    if bundle is None:
        st.warning(
            f"No data for **{ticker}**. "
            "EDGAR covers US public companies that file 10-K/10-Q in USD. "
            "ADRs / foreign filers and tickers not in FMP's free tier may have limited coverage."
        )
        return

    _render_header(bundle)
    _render_stats(bundle)

    periods = bundle.quarterly if cadence == "Quarterly" else bundle.annual
    if not periods:
        st.warning(
            f"No {cadence.lower()} financials available for {ticker}. "
            f"Try the other cadence."
        )
        return

    _render_charts(bundle, periods, cadence)

    # Footer
    parts = []
    if "edgar" in bundle.sources:
        parts.append(f"**EDGAR** ({len(bundle.quarterly)}Q + {len(bundle.annual)}FY)")
    if "fmp" in bundle.sources:
        parts.append(f"**FMP** (quote + {len(bundle.price_history)} prices + ratios)")
    if "finnhub" in bundle.sources:
        parts.append("**Finnhub** (ratios + forward P/E)")
    if "twelvedata" in bundle.sources:
        parts.append("**Twelve Data** (extended price history)")
    if "alphavantage" in bundle.sources:
        parts.append("**Alpha Vantage** (analyst target)")
    st.caption(" · ".join(parts) + " · cached on disk for fast reloads")

    # Honest disclosure of what's missing on free data
    with st.expander("Data source notes", expanded=False):
        forward_status = (
            "**populated**" if "alphavantage" in bundle.sources else
            "**empty** — add an Alpha Vantage API key to populate it"
        )
        st.markdown(
            f"- **Forward P/E** is sourced from Alpha Vantage's free OVERVIEW "
            f"endpoint (analyst consensus). Currently {forward_status}.\n"
            "- **Analyst Target Price** comes from the same Alpha Vantage call.\n"
            "- **P/E and P/S history** are computed from FMP price history × "
            "EDGAR per-period diluted shares × TTM earnings / revenue. "
            "Quarterly view uses TTM (rolling 4 quarters); annual uses direct "
            "annual values.\n"
            "- **Revenue by Segment** is reported in 10-K/10-Q filings as XBRL "
            "**dimensional data** (`ProductOrServiceAxis`, `GeographicalAxis`, "
            "`StatementBusinessSegmentsAxis`). EDGAR's flat `companyfacts` JSON "
            "doesn't expose these directly — extracting them reliably across "
            "filers is a meaningful engineering effort that's deferred to v2."
        )


def _render_source_status(edgar_email: str, fmp_key: str,
                          finnhub_key: str = "",
                          twelvedata_key: str = "",
                          alphavantage_key: str = "") -> None:
    items = []
    items.append(("SEC EDGAR", bool(edgar_email),
                  "Contact email set" if edgar_email else "Set EDGAR_CONTACT_EMAIL"))
    items.append(("FMP", bool(fmp_key),
                  "API key set" if fmp_key else "Add FMP_API_KEY for current quote + ratios"))
    items.append(("Finnhub (recommended)", bool(finnhub_key),
                  "API key set" if finnhub_key
                  else "Add FINNHUB_API_KEY — fills FMP gaps + Forward P/E (60/min)"))
    items.append(("Twelve Data (optional)", bool(twelvedata_key),
                  "API key set" if twelvedata_key
                  else "Add TWELVEDATA_API_KEY for longer price history (800/day)"))
    items.append(("Alpha Vantage (optional)", bool(alphavantage_key),
                  "API key set" if alphavantage_key
                  else "Add ALPHAVANTAGE_API_KEY for analyst price target"))
    rows = "".join(
        f'<div class="as-kv">'
        f'<div class="as-kv-k">{name}</div>'
        f'<div class="as-kv-v" style="color:{C["green"] if ok else C["muted"]};">'
        f'{("✓ " if ok else "○ ") + status}</div>'
        f'</div>'
        for name, ok, status in items
    )
    st.markdown(
        f'<div class="as-stat-card" style="margin-top:18px;">'
        f'<div class="as-stat-h">Data Source Status</div>{rows}</div>',
        unsafe_allow_html=True,
    )
