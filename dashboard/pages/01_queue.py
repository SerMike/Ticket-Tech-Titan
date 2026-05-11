"""01_queue.py — Ticket queue page.

The analyst's main workflow view: a filterable table of every ticket
joined with its AI evaluation and ban record. Filters live in the
sidebar so the table itself has maximum horizontal room. Selecting a
ticket below the table opens an expander whose detail body is built
out in Step 5 of planning/phase-3-checklist.md.
"""

import pandas as pd
import streamlit as st

import db

# AI categories the evaluator can assign, plus a synthetic "Not yet evaluated"
# bucket so analysts can explicitly include/exclude tickets without an
# evaluation row. Mirrors evaluation.evaluator.VALID_CATEGORIES.
_AI_CATEGORIES = [
    "Auto-Deny",
    "Likely Legitimate",
    "Admitted to Cheating",
    "Templated/Bot Appeal",
    "Needs Review",
]
_UNEVALUATED_LABEL = "Not yet evaluated"

# Dark-theme friendly colors for the ai_category cell. These use saturated
# fills plus explicit text color so the queue stays readable in Streamlit's
# dark preview.
_CATEGORY_COLORS = {
    "Auto-Deny": ("#7f1d1d", "#fee2e2"),
    "Likely Legitimate": ("#14532d", "#dcfce7"),
    "Needs Review": ("#713f12", "#fef3c7"),
    "Admitted to Cheating": ("#581c87", "#f3e8ff"),
    "Templated/Bot Appeal": ("#374151", "#f3f4f6"),
}

_VISIBLE_COLUMNS = [
    "ticket_id",
    "user_name",
    "ticket_issue_category",
    "ai_category",
    "confidence_score",
    "admitted_cheating",
    "admitted_exploit",
    "status",
    "created_at",
]


st.set_page_config(
    page_title="Queue — Ticket Tech Titan",
    layout="wide",
    page_icon="🎮",
)

with st.sidebar:
    st.title("Ticket Tech Titan")
    st.caption("AI-powered ban appeal review")
    st.divider()

st.title("Ticket queue")


# ---------------------------------------------------------------------------
# Load
# ---------------------------------------------------------------------------

rows = db.get_all_tickets()
df = pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Filters (sidebar)
# ---------------------------------------------------------------------------

with st.sidebar:
    st.subheader("Filters")
    st.markdown(
        """
        <style>
        section[data-testid="stSidebar"] div[data-testid="stMultiSelect"]
        div[data-baseweb="select"] {
            min-height: 188px !important;
            height: auto !important;
            align-items: flex-start !important;
        }

        section[data-testid="stSidebar"] div[data-testid="stMultiSelect"]
        div[data-baseweb="select"] > div {
            min-height: 188px !important;
            align-content: flex-start !important;
            align-items: flex-start !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    selected_categories = st.multiselect(
        "AI category",
        options=_AI_CATEGORIES + [_UNEVALUATED_LABEL],
        default=_AI_CATEGORIES + [_UNEVALUATED_LABEL],
    )

    selected_statuses = st.multiselect(
        "Status",
        options=list(db.ALLOWED_STATUSES),
        default=list(db.ALLOWED_STATUSES),
    )

    confidence_range = st.slider(
        "Confidence score",
        min_value=0.0,
        max_value=1.0,
        value=(0.0, 1.0),
        step=0.05,
        help=(
            "Filters evaluated tickets to this confidence band. Tickets "
            "without an evaluation are controlled by the AI category filter."
        ),
    )

    admitted_only = st.checkbox("Show admitted cheating only", value=False)


# ---------------------------------------------------------------------------
# Apply filters
# ---------------------------------------------------------------------------

filtered = df.copy()

# AI category — treat NULL ai_category as the synthetic "Not yet evaluated"
# option so it can be toggled alongside the real categories.
category_mask = filtered["ai_category"].isin(selected_categories)
if _UNEVALUATED_LABEL in selected_categories:
    category_mask = category_mask | filtered["ai_category"].isna()
filtered = filtered[category_mask]

# Status
filtered = filtered[filtered["status"].isin(selected_statuses)]

# Confidence — only constrain rows that actually have a score so
# unevaluated tickets aren't silently dropped by a narrowed slider.
low, high = confidence_range
confidence_mask = filtered["confidence_score"].isna() | (
    filtered["confidence_score"].astype(float).between(low, high)
)
filtered = filtered[confidence_mask]

# Admitted cheating
if admitted_only:
    filtered = filtered[filtered["admitted_cheating"] == True]  # noqa: E712


# ---------------------------------------------------------------------------
# Table
# ---------------------------------------------------------------------------

if filtered.empty:
    st.info("No tickets match the current filters.")
else:
    display = filtered[_VISIBLE_COLUMNS].reset_index(drop=True)

    def _checkmark(value) -> str:
        if pd.isna(value):
            return ""
        return "☑" if bool(value) else "☐"

    display["admitted_cheating"] = display["admitted_cheating"].map(_checkmark)
    display["admitted_exploit"] = display["admitted_exploit"].map(_checkmark)

    def _color_category(val):
        colors = _CATEGORY_COLORS.get(val)
        if not colors:
            return ""
        background, foreground = colors
        return (
            f"background-color: {background}; "
            f"color: {foreground}; "
            "font-weight: 700;"
        )

    def _style_admission(val):
        if val == "☑":
            return "color: #60a5fa; font-weight: 900; text-align: center;"
        return "color: #6b7280; font-weight: 700; text-align: center;"

    styled = (
        display.style
        .map(_color_category, subset=["ai_category"])
        .map(_style_admission, subset=["admitted_cheating", "admitted_exploit"])
        .set_properties(
            subset=["admitted_cheating", "admitted_exploit"],
            **{"text-align": "center"},
        )
    )

    st.caption(f"Showing {len(display)} of {len(df)} tickets.")
    st.dataframe(
        styled,
        width="stretch",
        hide_index=True,
        column_config={
            "ticket_id": st.column_config.TextColumn("Ticket ID"),
            "user_name": st.column_config.TextColumn("Player"),
            "ticket_issue_category": st.column_config.TextColumn("User category"),
            "ai_category": st.column_config.TextColumn("AI category"),
            "confidence_score": st.column_config.ProgressColumn(
                "Confidence",
                min_value=0.0,
                max_value=1.0,
                format="%.2f",
            ),
            "admitted_cheating": st.column_config.TextColumn(
                "Adm. cheat",
                alignment="center",
            ),
            "admitted_exploit": st.column_config.TextColumn(
                "Adm. exploit",
                alignment="center",
            ),
            "status": st.column_config.TextColumn("Status"),
            "created_at": st.column_config.DatetimeColumn(
                "Submitted", format="YYYY-MM-DD HH:mm"
            ),
        },
    )


# ---------------------------------------------------------------------------
# Ticket detail view
# ---------------------------------------------------------------------------

# Streamlit color shortcodes used when rendering the AI category badge.
# Keys must match evaluation.evaluator.VALID_CATEGORIES.
_CATEGORY_BADGE_COLOR = {
    "Auto-Deny": "red",
    "Likely Legitimate": "green",
    "Needs Review": "orange",
    "Admitted to Cheating": "violet",
    "Templated/Bot Appeal": "gray",
}


def _admission_indicator(value) -> str:
    """Render a boolean admission flag as an analyst-friendly glyph."""
    if value is True:
        return "✅ Yes"
    if value is False:
        return "❌ No"
    return "— Not evaluated"


def _render_detail(detail: dict) -> None:
    """Render the full ticket detail inside the caller's container.

    Layout (matches Step 5 of planning/phase-3-checklist.md):
      - Left column: raw appeal + status selectbox
      - Right column: ban record (or wrongful-ban warning)
      - Bottom: AI evaluation block with summary and expandable reasoning
    """
    ticket_id = detail["ticket_id"]
    left, right = st.columns(2)

    # -- Left: raw appeal ---------------------------------------------------
    with left:
        st.subheader("Appeal")
        st.markdown(
            f"**Player:** {detail['user_name']}  \n"
            f"**User ID:** `{detail['user_id']}`  \n"
            f"**Ticket ID:** `{ticket_id}`  \n"
            f"**Submitted:** {detail['created_at'].strftime('%Y-%m-%d %H:%M')}"
        )
        st.caption(f"User-submitted category: **{detail['ticket_issue_category']}**")
        st.markdown(f"#### {detail['ticket_title']}")
        st.write(detail["ticket_body"])

        st.divider()
        st.markdown("**Status**")
        current_status = detail["status"]
        new_status = st.selectbox(
            "Status",
            options=list(db.ALLOWED_STATUSES),
            index=list(db.ALLOWED_STATUSES).index(current_status),
            key=f"status_{ticket_id}",
            label_visibility="collapsed",
        )
        if new_status != current_status:
            try:
                db.update_ticket_status(ticket_id, new_status)
                st.toast(
                    f"Ticket {ticket_id}: {current_status} → {new_status}",
                    icon="✅",
                )
                st.rerun()
            except ValueError as e:
                st.error(str(e))

    # -- Right: ban record --------------------------------------------------
    with right:
        st.subheader("Ban record")
        if detail["ban_reason"] is None:
            st.warning("⚠️ No ban record — potential wrongful ban")
        else:
            st.markdown(
                f"**Reason:** {detail['ban_reason']}  \n"
                f"**Detection:** {detail['detection_method']}  \n"
                f"**Duration:** {detail['ban_duration']}  \n"
                f"**Ban date:** {detail['ban_date']}"
            )

    # -- Bottom: AI evaluation ---------------------------------------------
    st.divider()
    st.subheader("AI evaluation")

    if detail["ai_category"] is None:
        st.info("Not yet evaluated. Run the evaluation pipeline to populate.")
        return

    category = detail["ai_category"]
    badge_color = _CATEGORY_BADGE_COLOR.get(category, "blue")
    confidence = float(detail["confidence_score"]) if detail["confidence_score"] is not None else 0.0

    cat_col, conf_col, adm_col = st.columns([2, 2, 3])
    with cat_col:
        st.markdown("**Category**")
        st.markdown(f":{badge_color}[**{category}**]")
    with conf_col:
        st.markdown("**Confidence**")
        st.progress(confidence, text=f"{confidence:.0%}")
    with adm_col:
        st.markdown(
            f"**Admitted cheating:** {_admission_indicator(detail['admitted_cheating'])}  \n"
            f"**Admitted exploit:** {_admission_indicator(detail['admitted_exploit'])}"
        )

    evaluation = db.get_ai_evaluation(ticket_id)
    if evaluation is None:
        # Shouldn't happen — ai_category is non-null but the eval row vanished.
        st.warning("AI evaluation row could not be loaded.")
        return

    st.markdown("**Summary**")
    with st.container(border=True):
        st.write(evaluation["ai_summary"])

    with st.expander("Show full reasoning"):
        st.write(evaluation["ai_reasoning"])


st.divider()
st.subheader("Inspect a ticket")

ticket_ids = filtered["ticket_id"].tolist() if not filtered.empty else []
selected_id = st.selectbox(
    "Choose a ticket from the filtered list",
    options=ticket_ids,
    index=0 if ticket_ids else None,
    placeholder="No tickets match the current filters",
    disabled=not ticket_ids,
)

if selected_id:
    detail = db.get_ticket_detail(selected_id)
    if detail is None:
        st.warning(f"Ticket {selected_id} no longer exists.")
    else:
        with st.expander(f"Ticket {selected_id}", expanded=True):
            _render_detail(detail)
