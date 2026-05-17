"""brevity — Streamlit entry point.

Two pages:
  - Fundamentals (SEC EDGAR + FMP)
  - Gamma Exposure (Tradier)
"""
from __future__ import annotations

import os

import streamlit as st
from dotenv import load_dotenv

load_dotenv()

st.set_page_config(
    page_title="brevity",
    page_icon=":material/menu_book:",
    layout="wide",
)


# ─── Sidebar ─────────────────────────────────────────────────────────────────

st.sidebar.title("brevity")
st.sidebar.caption("Free, legal-source-only stock analytics.")

with st.sidebar.expander("Core (Fundamentals)", expanded=True):
    st.caption("Required for the Fundamentals page. All free.")
    edgar_email = st.text_input(
        "EDGAR contact email",
        value=os.getenv("EDGAR_CONTACT_EMAIL", ""),
        help="SEC requires a contact email in the User-Agent header. No signup, no API key.",
    )
    fmp_key = st.text_input(
        "FMP API Key",
        value=os.getenv("FMP_API_KEY", ""),
        type="password",
        help="Free 250 req/day — sign up at financialmodelingprep.com (email only).",
    )
    finnhub_key = st.text_input(
        "Finnhub API Key (recommended)",
        value=os.getenv("FINNHUB_API_KEY", ""),
        type="password",
        help="Fills FMP-paywalled tickers (CRWV, NBIS, recent IPOs). "
             "Adds Forward P/E. Free 60 req/min — finnhub.io (email only).",
    )
    twelvedata_key = st.text_input(
        "Twelve Data API Key (optional)",
        value=os.getenv("TWELVEDATA_API_KEY", ""),
        type="password",
        help="Adds longer price-history fallback (up to 5y for paywalled tickers, "
             "vs AV's 100-day limit). Free 800/day, 8/min — twelvedata.com (email only).",
    )
    alphavantage_key = st.text_input(
        "Alpha Vantage API Key (optional)",
        value=os.getenv("ALPHAVANTAGE_API_KEY", ""),
        type="password",
        help="Only needed for analyst price target (Finnhub gates that on premium). "
             "Free 25 req/day — alphavantage.co (email only).",
    )

with st.sidebar.expander("Optional (Gamma Exposure)", expanded=False):
    st.caption(
        "Pick ONE provider for option chains. Polygon is the easiest "
        "(email signup, paid). Tradier is free but requires KYC."
    )
    polygon_key = st.text_input(
        "Polygon API Key",
        value=os.getenv("POLYGON_API_KEY", ""),
        type="password",
        help="Options Starter $29/mo — polygon.io (email only, no KYC).",
    )
    tradier_token = st.text_input(
        "Tradier Token",
        value=os.getenv("TRADIER_TOKEN", ""),
        type="password",
        help="Free, but signup requires brokerage account + KYC — tradier.com",
    )
    tradier_env = st.selectbox(
        "Tradier environment",
        ["sandbox", "production"],
        index=0 if os.getenv("TRADIER_ENV", "sandbox") == "sandbox" else 1,
        help="Sandbox = 15-min delayed. Production = real-time.",
    )


# ─── Main ────────────────────────────────────────────────────────────────────

page = st.radio(
    "Navigate",
    ["Fundamentals", "Gamma Exposure"],
    horizontal=True,
    label_visibility="collapsed",
)

if page == "Fundamentals":
    import fundamentals_ui
    fundamentals_ui.render(
        edgar_email=edgar_email,
        fmp_key=fmp_key,
        finnhub_key=finnhub_key,
        twelvedata_key=twelvedata_key,
        alphavantage_key=alphavantage_key,
    )
elif page == "Gamma Exposure":
    import gex_ui
    gex_ui.render(
        polygon_key=polygon_key,
        tradier_token=tradier_token,
        tradier_env=tradier_env,
    )
