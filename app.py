"""
app.py — Clearinghouse Risk Lab entry point.

Two completely separate tools, each on its own page:
  Portfolio margin    — OCC TIMS CPM/RBH engine, position analysis
  Analytics workbench — Option pricing, Greeks, Volatility, Reference

Run:  streamlit run app.py
"""
import streamlit as st

margin_page = st.Page(
    "pages/margin.py",
    title="Portfolio margin",
    icon=":material/account_balance:",
    default=True,
)
analytics_page = st.Page(
    "pages/analytics.py",
    title="Analytics workbench",
    icon=":material/analytics:",
)

pg = st.navigation(
    {
        "Portfolio margin tool": [margin_page],
        "Analytics workbench":   [analytics_page],
    },
    position="sidebar",
    expanded=True,
)
pg.run()
