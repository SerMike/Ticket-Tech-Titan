"""app.py — Streamlit entry point for the Ticket Tech Titan dashboard.

Run with:
    streamlit run dashboard/app.py

The landing page shows a three-metric summary strip (open queue depth,
today's auto-denies, AI-flagged "Needs Review" backlog) so an analyst
knows what's on their plate before clicking into a page. Streamlit
auto-discovers files in ``pages/`` and renders them as sidebar nav
below the app header.
"""

import streamlit as st

import db

st.set_page_config(
    page_title="Ticket Tech Titan",
    layout="wide",
    page_icon="🎮",
)

with st.sidebar:
    st.title("Ticket Tech Titan")
    st.caption("AI-powered ban appeal review")
    st.divider()

st.title("Dashboard")
st.write(
    "Overview of the ticket queue and recent AI activity. "
    "Use the sidebar to open the queue or the analytics page."
)

stats = db.get_summary_stats()
col_open, col_denied, col_review = st.columns(3)
col_open.metric("Open tickets", stats["open_count"])
col_denied.metric("Auto-denied today", stats["auto_denied_today"])
col_review.metric("Needs review", stats["needs_review"])
