"""02_analytics.py - Analytics page.

Shows the aggregate AI evaluation and ticket-volume signals that help
analysts understand queue composition and detection outcomes.
"""

from __future__ import annotations

from decimal import Decimal

import pandas as pd
import plotly.express as px
import streamlit as st

import db


st.set_page_config(
    page_title="Analytics - Ticket Tech Titan",
    layout="wide",
    page_icon="🎮",
)

with st.sidebar:
    st.title("Ticket Tech Titan")
    st.caption("AI-powered ban appeal review")
    st.divider()

st.title("Analytics")


_CATEGORY_COLORS = {
    "Auto-Deny": "#D64550",
    "Likely Legitimate": "#2E8B57",
    "Admitted to Cheating": "#D97706",
    "Templated/Bot Appeal": "#6B7280",
    "Needs Review": "#F2C94C",
}


def _to_int(value) -> int:
    """Normalize aggregate counts from psycopg2 into plain ints."""
    if value is None:
        return 0
    if isinstance(value, Decimal):
        return int(value)
    return int(value)


def _pct(numerator: int, denominator: int) -> str:
    if denominator == 0:
        return "0.0%"
    return f"{100.0 * numerator / denominator:.1f}%"


def _category_dataframe(rows: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(rows)
    if df.empty:
        return pd.DataFrame(columns=["ai_category", "count"])
    df["count"] = df["count"].map(_to_int)
    return df


def _detection_dataframe(rows: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(rows)
    if df.empty:
        return pd.DataFrame(columns=["detection_method", "count"])
    df["count"] = df["count"].map(_to_int)
    df["detection_method"] = df["detection_method"].fillna("(no ban record)")
    return df


def _volume_dataframe(rows: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(rows)
    if df.empty:
        return pd.DataFrame(columns=["date", "count"])
    df["date"] = pd.to_datetime(df["date"])
    df["count"] = df["count"].map(_to_int)
    return df


def _render_empty(message: str) -> None:
    st.info(message)


with st.spinner("Loading analytics..."):
    analytics = db.get_analytics_data()

category_df = _category_dataframe(analytics["category_breakdown"])
detection_df = _detection_dataframe(analytics["detection_method_counts"])
volume_df = _volume_dataframe(analytics["volume_over_time"])
admissions = analytics["admission_rates"] or {}

total_evaluated = _to_int(admissions.get("total"))
admitted_cheating = _to_int(admissions.get("admitted_cheating"))
admitted_exploit = _to_int(admissions.get("admitted_exploit"))
total_tickets = int(volume_df["count"].sum()) if not volume_df.empty else 0
not_evaluated = max(total_tickets - total_evaluated, 0)

metric_cols = st.columns(4)
metric_cols[0].metric("Evaluated tickets", total_evaluated)
metric_cols[1].metric("Not evaluated", not_evaluated)
metric_cols[2].metric(
    "Cheating admissions", admitted_cheating, _pct(admitted_cheating, total_evaluated)
)
metric_cols[3].metric(
    "Exploit admissions", admitted_exploit, _pct(admitted_exploit, total_evaluated)
)

st.divider()

left, right = st.columns(2)

with left:
    st.subheader("AI category breakdown")
    if category_df.empty:
        _render_empty("No AI evaluations have been generated yet.")
    else:
        fig = px.bar(
            category_df,
            x="count",
            y="ai_category",
            orientation="h",
            color="ai_category",
            color_discrete_map=_CATEGORY_COLORS,
            text="count",
            labels={"count": "Tickets", "ai_category": "AI category"},
        )
        fig.update_layout(
            showlegend=False,
            margin=dict(l=0, r=20, t=10, b=0),
            yaxis={"categoryorder": "total ascending"},
        )
        fig.update_traces(textposition="outside", cliponaxis=False)
        st.plotly_chart(fig, width="stretch")

with right:
    st.subheader("Admission rates")
    if total_evaluated == 0:
        _render_empty("No evaluated tickets are available for admission metrics.")
    else:
        admission_df = pd.DataFrame(
            [
                {
                    "admission_type": "Admitted cheating",
                    "count": admitted_cheating,
                    "rate": 100.0 * admitted_cheating / total_evaluated,
                },
                {
                    "admission_type": "Admitted exploit",
                    "count": admitted_exploit,
                    "rate": 100.0 * admitted_exploit / total_evaluated,
                },
            ]
        )
        fig = px.bar(
            admission_df,
            x="admission_type",
            y="rate",
            text=admission_df["rate"].map(lambda value: f"{value:.1f}%"),
            labels={"admission_type": "Admission", "rate": "Rate"},
            color="admission_type",
            color_discrete_map={
                "Admitted cheating": "#D97706",
                "Admitted exploit": "#7C3AED",
            },
        )
        fig.update_layout(
            showlegend=False,
            margin=dict(l=0, r=20, t=10, b=0),
            yaxis_range=[0, max(100, admission_df["rate"].max() * 1.2)],
        )
        fig.update_traces(textposition="outside", cliponaxis=False)
        st.plotly_chart(fig, width="stretch")

st.divider()

left, right = st.columns(2)

with left:
    st.subheader("Detection method volume")
    if detection_df.empty:
        _render_empty("No ban records are available for detection-method analytics.")
    else:
        fig = px.bar(
            detection_df,
            x="count",
            y="detection_method",
            orientation="h",
            text="count",
            labels={"count": "Tickets", "detection_method": "Detection method"},
            color="count",
            color_continuous_scale="Tealgrn",
        )
        fig.update_layout(
            showlegend=False,
            coloraxis_showscale=False,
            margin=dict(l=0, r=20, t=10, b=0),
            yaxis={"categoryorder": "total ascending"},
        )
        fig.update_traces(textposition="outside", cliponaxis=False)
        st.plotly_chart(fig, width="stretch")

with right:
    st.subheader("Ticket volume over time")
    if volume_df.empty:
        _render_empty("No tickets have been ingested yet.")
    else:
        fig = px.line(
            volume_df,
            x="date",
            y="count",
            markers=True,
            labels={"date": "Date", "count": "Tickets"},
        )
        fig.update_traces(line_color="#2563EB", marker_color="#2563EB")
        fig.update_layout(margin=dict(l=0, r=20, t=10, b=0))
        st.plotly_chart(fig, width="stretch")

st.divider()
st.subheader("Raw aggregates")

tab_category, tab_detection, tab_volume = st.tabs(
    ["Categories", "Detection methods", "Volume"]
)

with tab_category:
    if category_df.empty:
        _render_empty("No category rows to display.")
    else:
        st.dataframe(category_df, width="stretch", hide_index=True)

with tab_detection:
    if detection_df.empty:
        _render_empty("No detection-method rows to display.")
    else:
        st.dataframe(detection_df, width="stretch", hide_index=True)

with tab_volume:
    if volume_df.empty:
        _render_empty("No volume rows to display.")
    else:
        display_volume = volume_df.copy()
        display_volume["date"] = display_volume["date"].dt.date
        st.dataframe(display_volume, width="stretch", hide_index=True)
