"""
pages/margin.py — Portfolio margin tool.

Two modes driven by st.session_state["view"]:

  Guided  — A true sequential wizard. One step at a time, completed steps
             collapse to a summary bar, a progress stepper shows where you are.
             Each step fills the screen with only what you need right now.

  Expert  — A single dense page: all four sections visible simultaneously,
             detail tables open, no explanations, full P&L grid.
"""
from datetime import date
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import cpm_engine as cpm
import ui
from ui import money, hint, PETROL, AMBER, LOSS, GAIN, INK, SLATE
from occ_reference import OCCReference

st.set_page_config(
    page_title="Portfolio margin — Clearinghouse Risk Lab",
    page_icon=":material/account_balance:",
    layout="wide",
    initial_sidebar_state="expanded",
)
ui.inject_css()
ui.register_plotly_template()
PCOLS = cpm.PCOLS
XL = ui.labels(cpm.POINT_LABELS)


@st.cache_resource
def load_reference():
    return OCCReference("reference")


@st.cache_data
def load_sample():
    return cpm.read_pmc_file("sample_positions.csv"), pd.read_csv("market_data.csv")


ref = load_reference()
MODEL_NAMES = {
    "Bjerksund-Stensland 2002":           "Bjerksund-Stensland",
    "Binomial CRR (American, 300 steps)":  "Binomial tree",
    "Black-Scholes (European)":            "Black-Scholes (European)",
}

# ── initialise wizard state ──────────────────────────────────────────────────
if "wizard_step" not in st.session_state:
    st.session_state["wizard_step"] = 1
if "wizard_acct" not in st.session_state:
    st.session_state["wizard_acct"] = None

# ======================================================================= SIDEBAR
with st.sidebar:
    st.markdown(
        '<div class="brand">Clearinghouse Risk Lab</div>'
        '<div class="brand-sub">Portfolio margin tool</div>',
        unsafe_allow_html=True,
    )
    mode = st.segmented_control(
        "View", ["Guided", "Expert"], default="Guided",
        help="Guided walks you through one step at a time — designed for a new margin clerk. "
             "Expert shows everything at once — for a head of risk who knows what they want.",
    )
    guided = (mode or "Guided") == "Guided"

    # In Guided view, only show settings relevant to the current step.
    # Expert always shows everything.
    if not guided or st.session_state["wizard_step"] >= 2:
        st.divider()
        st.markdown("**Valuation settings**", help="Apply to this tool only.")
        val_date = st.date_input("Valuation date", date.today(),
                                 help="Time to expiry is measured from this date.")
        r = st.number_input("Risk-free rate (%)", value=4.00, step=0.25, format="%.2f",
                            help="Short-term Treasury yield is typical.") / 100
        am_model = st.selectbox("Model for American options", list(MODEL_NAMES),
                                format_func=MODEL_NAMES.get,
                                help="Bjerksund-Stensland is fast; binomial tree is slower "
                                     "and slightly more accurate.")
        st.divider()
        st.markdown("**Stress test**", help="Not part of the regulatory calculation.")
        vol_pts = st.slider("Extra vol in a selloff", 0, 20, 0, 1, format="%d pts",
                            help="Asks: what if volatility spikes in a selloff? "
                                 "Adds implied vol as the market falls.")
        vol_bump = vol_pts / 100
        if vol_pts:
            st.badge(f"Stress on: +{vol_pts} vol pts", icon=":material/bolt:", color="orange")
    else:
        val_date = date.today(); r = 0.04; am_model = "Bjerksund-Stensland 2002"; vol_bump = 0.0

    st.divider()
    st.caption(f"OCC reference files dated {ref.as_of}. Sample market data is illustrative.")


# ── shared data loading ──────────────────────────────────────────────────────
sample_pos, sample_mkt = load_sample()


def run_engine(positions, market, vol_bump=0.0):
    """Run CPM and cache the result in session state."""
    return cpm.run_cpm(positions, market, ref,
                       r=r, model=am_model, today=val_date, vol_up_on_down=vol_bump)


def go_to(step: int):
    st.session_state["wizard_step"] = step
    st.rerun()


# ============================================================================
# EXPERT VIEW — dense, everything visible, no wizard
# ============================================================================
if not guided:
    st.markdown("## Portfolio margin")

    # ── Load ────────────────────────────────────────────────────────────────
    up = st.file_uploader("Position file (OCC PMC CSV)", type=["csv"])
    positions = sample_pos
    if up:
        try:
            positions = cpm.read_pmc_file(up)
            if positions.empty: raise ValueError
        except Exception:
            st.error(f"{up.name} couldn't be read. Showing the sample book instead.")
            positions = sample_pos

    e_hdr, e_reset = st.columns([6, 1], vertical_alignment="center")
    e_hdr.caption("Edit positions and market data below, or upload a different file above.")
    if e_reset.button("Reset to sample", key="ex_reset",
                      help="Discard all edits and restore the original sample book."):
        st.toast("Sample book restored.", icon=":material/undo:")
        st.rerun()
    c1, c2 = st.columns(2)
    with c1.expander("Edit positions (optional)", icon=":material/edit:"):
        st.caption("Double-click a cell to change · Negative quantity = short · Press Esc to cancel")
        positions = st.data_editor(positions, num_rows="dynamic", width="stretch", key="e_pos")
    with c2.expander("Edit market data (optional)", icon=":material/tune:"):
        st.caption("Every symbol in the position table needs a row here.")
        mkt_df = st.data_editor(sample_mkt, num_rows="dynamic", width="stretch", key="e_mkt")
    market = mkt_df.dropna(subset=["symbol"]).set_index("symbol")

    positions = positions[positions["symbol"].fillna("").astype(str).str.strip() != ""]
    need = sorted({p.symbol for p in positions.itertuples()
                   if ref.lookup(p.symbol,
                                 p.sec_type if isinstance(p.sec_type, str) else "S",
                                 p.acct_type if isinstance(p.acct_type, str) and p.acct_type else "C").eligible})
    missing = [s for s in need if s not in market.index]
    if missing:
        missing_list = ", ".join(missing)
        st.error(
            f"Missing market data for: **{missing_list}**. "
            "**To fix:** expand **Edit market data** above and add a row for each symbol "
            "with its price, ATM vol, skew and dividend yield.",
            icon=":material/error:",
        )
        st.stop()

    res = run_engine(positions, market, vol_bump)
    det = res["detail"]
    if det.empty:
        st.info("No eligible positions. Edit the position table above.")
        st.stop()

    if len(res["excluded"]):
        st.warning("Excluded (ineligible for account type): " +
                   "; ".join(f"{x.account} {x.description}" for x in res["excluded"].itertuples()))

    # ── Accounts ────────────────────────────────────────────────────────────
    st.markdown("### Accounts")
    accts = res["accounts"].copy()
    fin_all = res["final"]
    accts["type"] = accts.acct_type.map(ui.ACCOUNT_TYPES)
    accts["binds"] = (accts.account
                      .map(fin_all.sort_values("requirement").groupby("account")["binding"].last())
                      .str.replace("-", ui.MINUS))
    accts = accts.sort_values("excess").reset_index(drop=True)
    view = accts[["account", "type", "requirement", "nav", "excess", "binds"]]
    sel = st.dataframe(
        ui.money_table(view, ["requirement", "nav", "excess"]),
        hide_index=True, width="stretch", on_select="rerun",
        selection_mode="single-row", key="e_acct",
        selection_default={"selection": {"rows": [0]}},
        column_config={
            "account": "Account", "type": "Type",
            "requirement": "Requirement", "nav": "Net liquidation value",
            "excess": "Pos. value vs. requirement", "binds": "Largest charge set by",
        },
    )
    rows = sel.selection.rows if sel and sel.selection else []
    acct = view.iloc[rows[0]]["account"] if rows else view.iloc[0]["account"]
    selected_display = view.iloc[rows[0]]["account"] if rows else view.iloc[0]["account"]
    st.caption(
        f"Showing **account {selected_display}** · "
        "Click the checkbox at the left of any row to switch accounts · "
        "Pos. value vs. requirement excludes cash and other collateral"
    )
    a = accts[accts.account == acct].iloc[0]
    is_cust = a["acct_type"] == "C"
    req_label = "Margin requirement" if is_cust else "Risk-based haircut"

    # ── Verdict ─────────────────────────────────────────────────────────────
    st.markdown(f"### Account {acct}")
    k = st.columns(4)
    k[0].metric(req_label, money(a["requirement"]), border=True)
    k[1].metric("Net liquidation value", money(a["nav"]), border=True)
    k[2].metric("Pos. value vs. requirement", money(a["excess"]), border=True)
    k[3].metric("Saved by offsets", money(a["offset_benefit"]), border=True)
    st.caption(f"{ui.ACCOUNT_TYPES[a['acct_type']]} ranges · OCC minimums only.")

    da = det[det.account == acct]
    pgx = res["product_groups"]; pgx = pgx[pgx.account == acct]
    pos_alone = np.maximum(np.clip(-da[PCOLS].min(axis=1), 0, None), da["minimum"]).sum()
    cg_alone  = a["no_offsets"]; pg_alone = pgx["requirement_alone"].sum(); req = a["requirement"]
    steps_ = [("Every position on its own", pos_alone, "absolute", ""),
              ("Class group netting", cg_alone - pos_alone, "relative", ""),
              ("Product group offsets", pg_alone - cg_alone, "relative", ""),
              ("Portfolio group offsets", req - pg_alone, "relative", ""),
              (req_label, req, "total", "")]
    br = go.Figure(go.Waterfall(
        orientation="h", y=[s[0] for s in steps_], x=[s[1] for s in steps_],
        measure=[s[2] for s in steps_], customdata=[s[3] for s in steps_],
        text=[money(s[1], signed=s[2] == "relative") for s in steps_], textposition="outside",
        decreasing=dict(marker=dict(color=GAIN)), increasing=dict(marker=dict(color=LOSS)),
        totals=dict(marker=dict(color=PETROL)), connector=dict(line=dict(color="#9AA59C", width=1)),
        hovertemplate="<b>%{y}: %{text}</b><extra></extra>"))
    br.update_layout(title="Requirement bridge", height=300,
                     yaxis=dict(autorange="reversed", gridcolor="rgba(0,0,0,0)"),
                     xaxis=dict(title="Dollars", tickformat="$~s",
                                range=[0, max(pos_alone, cg_alone, pg_alone, req) * 1.18]),
                     showlegend=False, margin=dict(l=10, r=20, t=48, b=10))
    st.plotly_chart(br, width="stretch")

    # ── Drivers ─────────────────────────────────────────────────────────────
    st.markdown("### What drives it")
    fin = fin_all[fin_all.account == acct]
    groups = fin["group"].tolist()
    grp = groups[0] if len(groups) == 1 else (
        st.segmented_control("Group", groups, default=groups[0]) or groups[0])
    row = fin[fin.group == grp].iloc[0]
    pg_list = [p.strip() for p in str(row["product_groups"]).split(",")]
    st.caption(f"Path: {row['path']} · Binding: {row['binding'].replace('-', ui.MINUS).lower()}")

    t1, t2, t3, t4 = st.tabs(["Risk array", "Positions", "Offset detail", "All positions"])

    def _comps(pg_list, cgs, da):
        if len(pg_list) > 1:
            return [(f"PG {c.product_group} {ref.product_group_name(c.product_group).title()[:20]}",
                     [getattr(c, p) for p in PCOLS]) for c in pgx[pgx.product_group.isin(pg_list)].itertuples()]
        elif len(cgs) > 1:
            return [(f"{c.class_group} {str(c.class_group_name).title()[:24]}",
                     [getattr(c, p) for p in PCOLS]) for c in cgs.itertuples()]
        else:
            dd = da[da.product_group.isin(pg_list)].copy()
            dd["sz"] = dd[PCOLS].abs().max(axis=1)
            return [(x.description, [getattr(x, p) for p in PCOLS])
                    for x in dd.sort_values("sz", ascending=False).head(6).itertuples()]

    with t1:
        cgs = res["class_groups"]; cgs = cgs[(cgs.account == acct) & (cgs.product_group.isin(pg_list))]
        fig = go.Figure()
        net = [row[c] for c in PCOLS]
        fig.add_trace(go.Bar(x=XL, y=net, name="Net after offsets",
                             marker=dict(color=[LOSS if v < 0 else GAIN for v in net]), opacity=0.28))
        for name, ys in _comps(pg_list, cgs, da):
            fig.add_trace(go.Scatter(x=XL, y=ys, mode="lines+markers", name=name))
        if row["worst_point"] is not None and not pd.isna(row["worst_point"]):
            w = int(row["worst_point"])
            fig.add_vrect(x0=w-.45, x1=w+.45, fillcolor=AMBER, opacity=0.14, line_width=0)
        fig.add_hline(y=0, line_width=1, line_color="#9AA59C")
        fig.update_xaxes(type="category", title="Price scenario")
        fig.update_layout(title="P&L in each scenario", yaxis=dict(title="P/L", tickformat="$~s"), height=420)
        st.plotly_chart(fig, width="stretch")
    with t2:
        tc = cpm.top_contributors(res, acct, grp, n=10)
        st.dataframe(ui.money_table(tc, ["pnl_at_binding_point"], int_cols=["qty"]),
                     hide_index=True, width="stretch",
                     column_config={"description": "Position", "class_group": "CG",
                                    "qty": "Qty", "pnl_at_binding_point": "P&L worst case"})
    with t3:
        cgx = res["class_groups"]; cgx = cgx[cgx.account == acct]
        st.markdown("**Class groups (100% netting)**")
        st.dataframe(ui.money_table(cgx[["class_group","class_group_name","product_group","risk","minimum","standalone_req"]],
                                    ["risk","minimum","standalone_req"]), hide_index=True, width="stretch")
        st.markdown("**Product groups**")
        st.dataframe(ui.money_table(pgx[["product_group","product_group_name","offset_pct","gross_loss","offset_credit","requirement_alone"]],
                                    ["gross_loss","offset_credit","requirement_alone"], ["offset_pct"]), hide_index=True, width="stretch")
        ps = res["portfolio_steps"]; ps = ps[ps.account == acct]
        if len(ps):
            st.markdown("**Portfolio groups**")
            st.dataframe(ui.money_table(ps.drop(columns="account"),
                                        ["requirement_before","requirement_after","saving"],["offset_pct"]),
                         hide_index=True, width="stretch")
    with t4:
        cols = (["description","qty","class_group","product_group","mmaf","range",
                 "multiplier","theo_price","market_value","minimum","notes"] + PCOLS)
        st.dataframe(ui.money_table(da[cols], ["market_value","minimum"]+PCOLS,
                                    int_cols=["qty","multiplier"], dec={"theo_price":4,"mmaf":2}),
                     hide_index=True, width="stretch",
                     column_config={p: l for p, l in zip(PCOLS, XL)})

    st.divider()
    d1, d2 = st.columns(2)
    d1.download_button(
        "Download full results (CSV)", det.to_csv(index=False), "margin_results.csv",
        icon=":material/download:", width="stretch",
        help="Every position with its class group, product group, and P&L in all 10 scenarios.",
    )
    d2.download_button(
        "Export for OCC's calculator", cpm.to_pmc_csv(positions), "positions_pmc.csv",
        icon=":material/upload_file:", width="stretch",
        help="The same book in OCC's upload format. Upload to OCC's own tool to cross-check.",
    )
    st.stop()


# ============================================================================
# GUIDED VIEW — sequential wizard
# ============================================================================
step = st.session_state["wizard_step"]
ui.wizard_stepper(step)

# ── State: carry positions and results across steps ─────────────────────────
# We store the computed result in session_state so Steps 2-4 don't re-upload.
if "positions" not in st.session_state:
    st.session_state["positions"] = sample_pos.copy()
if "market" not in st.session_state:
    st.session_state["market"] = sample_mkt.copy()
if "res" not in st.session_state:
    st.session_state["res"] = None


def _ensure_result():
    if st.session_state["res"] is None:
        pos = st.session_state["positions"]
        mkt = st.session_state["market"].dropna(subset=["symbol"]).set_index("symbol")
        st.session_state["res"] = run_engine(pos, mkt, vol_bump)
    return st.session_state["res"]


def _invalidate():
    st.session_state["res"] = None


# ──────────────────────────────────────────────────────────────────────────────
# STEP 1 — Load positions
# Two visual states:
#   A) "file_chosen" not set → big two-path choice screen
#   B) "file_chosen" set     → green status banner + secondary controls + big CTA
# ──────────────────────────────────────────────────────────────────────────────
if step == 1:
    file_chosen = st.session_state.get("file_chosen", False)  # True once user picks a path

    # ── STATE A: no choice yet ────────────────────────────────────────────────
    if not file_chosen:
        ui.wizard_card(
            "How do you want to start?",
            "Pick one of the two options below. You can always switch later.",
        )

        # Two large, clearly differentiated choice cards
        col_sample, col_upload = st.columns(2, gap="large")

        with col_sample:
            st.html(
                '<div class="s1-path primary">'
                '<div class="path-icon">\U0001f4cb</div>'
                '<div class="path-title">Use the sample book</div>'
                '<div class="path-sub">4 accounts — index spreads, single stocks, a basket '
                'and a market maker. Ready immediately. Best if you\'re exploring the tool '
                'for the first time.</div>'
                '</div>'
            )
            if st.button("Use sample book →", type="primary", use_container_width=True,
                         key="pick_sample",
                         help="Loads 20 positions across 4 accounts. Nothing to upload."):
                st.session_state["positions"] = sample_pos.copy()
                st.session_state["market"]    = sample_mkt.copy()
                st.session_state["file_source"] = "Sample book (20 positions, 4 accounts)"
                st.session_state["file_chosen"] = True
                _invalidate()
                st.rerun()

        with col_upload:
            st.html(
                '<div class="s1-path">'
                '<div class="path-icon">\U0001f4c2</div>'
                '<div class="path-title">Upload your own file</div>'
                '<div class="path-sub">A CSV in OCC\'s Portfolio Margin Calculator format. '
                'Download the sample file to use as a template if you don\'t have one yet.</div>'
                '</div>'
            )
            up = st.file_uploader("Position file (OCC PMC CSV)", type=["csv"],
                                  label_visibility="collapsed",
                                  help="Export from OCC's Portfolio Margin Calculator, "
                                       "or build a CSV in OCC's format.")
            if up:
                try:
                    loaded = cpm.read_pmc_file(up)
                    if loaded.empty:
                        raise ValueError("no rows")
                    st.session_state["positions"]   = loaded
                    st.session_state["market"]      = sample_mkt.copy()
                    st.session_state["file_source"] = f"{up.name} ({len(loaded)} positions)"
                    st.session_state["file_chosen"] = True
                    _invalidate()
                    st.rerun()
                except Exception:
                    st.error(
                        f"**{up.name}** couldn't be read as an OCC position file. "
                        "Make sure it's a CSV with position rows starting with 346. "
                        "Download the sample file to see the correct format.",
                        icon=":material/error:",
                    )
            with st.container():
                c1, c2 = st.columns(2)
                with open("sample_positions.csv", "rb") as f:
                    c1.download_button("Download sample file", f, "sample_positions.csv",
                                       icon=":material/download:", use_container_width=True,
                                       help="Use as a template in Excel.")
                with c2.popover("What's in the file?", icon=":material/help:",
                                use_container_width=True):
                    st.markdown(
                        "One row per position:\n\n"
                        "- **Account ID** · **Account type** (C customer, F firm, M market maker)\n"
                        "- **Symbol** · **Security type** (S stock, O option, F future)\n"
                        "- **Put/call** · **Expiry** (YYYYMMDD) · **Strike** (options only)\n"
                        "- **Long/short** (L or S) · **Quantity** (negative = short)\n\n"
                        "Open the sample file to see the full format."
                    )

    # ── STATE B: file is loaded ───────────────────────────────────────────────
    else:
        source  = st.session_state.get("file_source", "Sample book")
        pos     = st.session_state["positions"]
        pos     = pos[pos["symbol"].fillna("").astype(str).str.strip() != ""]
        n_pos   = len(pos)
        n_acct  = pos["account"].nunique() if "account" in pos.columns else "?"

        # Prominent green loaded banner — the dominant visual element
        ui.loaded_banner(source, n_pos, n_acct)

        # Secondary: change source or reset, clearly labeled as optional
        with st.expander("⚙ Options: switch file, edit, or reset", expanded=False):
            st.caption("You don't need to open this. Everything is already set up above.")

            # Switch source
            st.markdown("**Switch to a different source**")
            sw1, sw2 = st.columns([1, 1], gap="medium")
            with sw1:
                if st.button("← Use the sample book instead", use_container_width=True,
                             key="switch_sample",
                             help="Replaces your current book with the sample."):
                    st.session_state["positions"]   = sample_pos.copy()
                    st.session_state["market"]      = sample_mkt.copy()
                    st.session_state["file_source"] = "Sample book (20 positions, 4 accounts)"
                    _invalidate()
                    st.rerun()
            with sw2:
                up2 = st.file_uploader("Upload a different file", type=["csv"],
                                       label_visibility="collapsed",
                                       key="up2",
                                       help="Replaces the currently loaded book.")
                if up2:
                    try:
                        loaded2 = cpm.read_pmc_file(up2)
                        if loaded2.empty:
                            raise ValueError
                        st.session_state["positions"]   = loaded2
                        st.session_state["market"]      = sample_mkt.copy()
                        st.session_state["file_source"] = f"{up2.name} ({len(loaded2)} positions)"
                        _invalidate()
                        st.rerun()
                    except Exception:
                        st.error(f"Couldn't read {up2.name}. Check the format.",
                                 icon=":material/error:")

            st.divider()
            st.markdown("**Edit the loaded book**")
            st.caption("Double-click a cell to change it · Negative quantity = short · "
                       "Press Esc to cancel an edit")
            edited = st.data_editor(
                st.session_state["positions"], num_rows="dynamic",
                width="stretch", key="g_pos",
                column_config={
                    "acct_type": st.column_config.SelectboxColumn("Account type",
                                 options=["C","F","M"], help="C customer, F firm, M market maker"),
                    "sec_type":  st.column_config.SelectboxColumn("Security",
                                 options=["S","O","I","F","W"],
                                 help="S stock/ETF, O option, I option on future, F future"),
                    "put_call":  st.column_config.SelectboxColumn("P/C", options=["P","C",""]),
                    "expiry":    st.column_config.DateColumn("Expiry"),
                    "strike":    st.column_config.NumberColumn("Strike", format="%.2f"),
                    "qty":       st.column_config.NumberColumn("Quantity", format="%d",
                                 help="Negative = short"),
                },
            )
            if not edited.equals(st.session_state["positions"]):
                st.session_state["positions"] = edited
                _invalidate()

            mkt_edited = st.data_editor(
                st.session_state["market"], num_rows="dynamic",
                width="stretch", key="g_mkt",
                column_config={
                    "spot":      st.column_config.NumberColumn("Price", format="%.2f"),
                    "atm_vol":   st.column_config.NumberColumn("ATM vol",
                                 help="Implied volatility as a decimal: 0.20 = 20%"),
                    "skew":      st.column_config.NumberColumn("Skew",
                                 help="Vol added per 10% drop in strike"),
                    "div_yield": st.column_config.NumberColumn("Div. yield", format="%.3f"),
                },
            )
            if not mkt_edited.equals(st.session_state["market"]):
                st.session_state["market"] = mkt_edited
                _invalidate()

            st.divider()
            if st.button("↩ Reset everything to the sample book", key="reset_pos",
                         help="Restores the original sample book and market data."):
                st.session_state["positions"]   = sample_pos.copy()
                st.session_state["market"]      = sample_mkt.copy()
                st.session_state["file_source"] = "Sample book (20 positions, 4 accounts)"
                _invalidate()
                st.toast("Reset to sample book.", icon=":material/undo:")
                st.rerun()

        # Validate
        mkt = st.session_state["market"].dropna(subset=["symbol"]).set_index("symbol")
        need = sorted({p.symbol for p in pos.itertuples()
                       if ref.lookup(p.symbol,
                                     p.sec_type if isinstance(p.sec_type, str) else "S",
                                     p.acct_type if isinstance(p.acct_type, str) and p.acct_type else "C").eligible})
        missing = [s for s in need if s not in mkt.index]
        if missing:
            st.error(
                f"Missing market data for: **{', '.join(missing)}**. "
                "Open the Options section above and add rows to the market data table.",
                icon=":material/error:",
            )

        # THE CTA — visually dominant, nothing competing with it
        st.markdown('<div class="wiz-cta"></div>', unsafe_allow_html=True)
        disabled = bool(missing)
        if st.button(
            "Calculate margin →" if not disabled else "Fix missing data first",
            type="primary", disabled=disabled,
            use_container_width=True,
            help="Runs OCC's TIMS methodology across all accounts in the book.",
        ):
            st.session_state["positions"] = pos
            _invalidate()
            go_to(2)


# ──────────────────────────────────────────────────────────────────────────────
# STEP 2 — Accounts at a glance
# ──────────────────────────────────────────────────────────────────────────────
elif step == 2:
    # Completed step 1 bar
    pos = st.session_state["positions"]
    n_pos = len(pos[pos["symbol"].fillna("").astype(str).str.strip() != ""])
    if ui.done_bar("Load positions", f"{n_pos} positions loaded", 1, "back1",
                   back_label="← Change book"):
        go_to(1)

    res = _ensure_result()
    det = res["detail"]
    if det.empty:
        st.warning("No eligible positions to calculate. Go back and check the book.", icon=":material/warning:")
        if st.button("← Back to Load positions"):
            go_to(1)
        st.stop()

    if len(res["excluded"]):
        st.warning(
            "Some positions were excluded because OCC's file doesn't allow them in their account type: "
            + "; ".join(f"{x.account} — {x.description}" for x in res["excluded"].itertuples())
            + ". To fix: remove those rows or change the account type to F or M.",
            icon=":material/block:",
        )

    ui.wizard_card(
        "Check each account",
        "Click the checkbox at the left of any row to select it, then press 'Review' below. "
        "Sorted by largest position-value gap first.",
    )

    accts = res["accounts"].copy()
    fin_all = res["final"]
    accts["type"]  = accts.acct_type.map(ui.ACCOUNT_TYPES)
    accts["binds"] = (accts.account
                      .map(fin_all.sort_values("requirement").groupby("account")["binding"].last())
                      .str.replace("-", ui.MINUS))
    accts = accts.sort_values("excess").reset_index(drop=True)
    view  = accts[["account", "type", "requirement", "nav", "excess", "binds"]]

    sel = st.dataframe(
        ui.money_table(view, ["requirement", "nav", "excess"]),
        hide_index=True, width="stretch",
        on_select="rerun", selection_mode="single-row", key="g_acct",
        selection_default={"selection": {"rows": [0]}},
        column_config={
            "account": "Account", "type": "Type",
            "requirement": st.column_config.Column("Requirement",
                                                   help=ui.GLOSSARY["Margin requirement"]),
            "nav": st.column_config.Column("Net liquidation value",
                                           help=ui.GLOSSARY["Net liquidation value (NAV)"]),
            "excess": st.column_config.Column("Position value vs. requirement",
                                              help="Does not include cash or other collateral. "
                                                   "A sizing indicator, not a confirmed call."),
            "binds": st.column_config.Column("Largest charge set by",
                                             help=ui.GLOSSARY["Binding point"]),
        },
    )

    rows  = sel.selection.rows if sel and sel.selection else []
    acct  = view.iloc[rows[0]]["account"] if rows else view.iloc[0]["account"]
    st.caption(
        f"Showing account **{acct}** · {len(accts)} accounts total. "
        "Position value vs. requirement excludes cash and other collateral."
    )

    a = accts[accts.account == acct].iloc[0]
    gap_txt = money(-a["excess"]) if a["excess"] < 0 else f"+{money(a['excess'])}"
    is_cust = a["acct_type"] == "C"
    req_label = "margin requirement" if is_cust else "risk-based haircut"
    tip = (f"Position value is {gap_txt} vs. the {req_label}. "
           "Cash and other collateral aren't included here.")

    st.markdown('<div class="wiz-cta"></div>', unsafe_allow_html=True)
    col_btn, col_back, col_hint = st.columns([2, 1, 4], vertical_alignment="center")
    with col_btn:
        if st.button(f"Review account {acct} →", type="primary", use_container_width=True,
                     help=f"See the full requirement and offset breakdown for account {acct}."):
            st.session_state["wizard_acct"] = acct
            go_to(3)
    with col_back:
        if st.button("← Change book", use_container_width=True, key="s2_back",
                     help="Go back to load a different file or edit positions."):
            go_to(1)
    with col_hint:
        st.caption(f"Account **{acct}** selected · {tip}")


# ──────────────────────────────────────────────────────────────────────────────
# STEP 3 — Verdict: the four numbers + requirement bridge
# ──────────────────────────────────────────────────────────────────────────────
elif step == 3:
    res  = _ensure_result()
    det  = res["detail"]
    acct = st.session_state.get("wizard_acct") or res["accounts"].sort_values("excess").iloc[0]["account"]
    accts = res["accounts"].copy()
    accts["type"] = accts.acct_type.map(ui.ACCOUNT_TYPES)
    accts = accts.sort_values("excess").reset_index(drop=True)
    a = accts[accts.account == acct].iloc[0]
    is_cust = a["acct_type"] == "C"
    req_label = "Margin requirement" if is_cust else "Risk-based haircut"

    # Completed step bars
    pos = st.session_state["positions"]
    n_pos = len(pos[pos["symbol"].fillna("").astype(str).str.strip() != ""])
    if ui.done_bar("Load positions", f"{n_pos} positions", 1, "back1b",
                   back_label="← Change book"):
        go_to(1)
    if ui.done_bar("Check accounts", f"{len(accts)} accounts", 2, "back2b",
                   back_label="← Change account"):
        go_to(2)

    ui.wizard_card(
        f"Account {acct}: the verdict",
        "Here's the requirement, how position value compares to it, "
        "and how much OCC's offset rules saved.",
    )

    # Badge
    if a["excess"] < 0:
        st.badge(
            f"Position value {money(a['excess'])} vs. requirement (excl. cash & collateral)",
            icon=":material/info:", color="blue",
        )
    else:
        st.badge(
            f"Position value {money(a['excess'], signed=True)} vs. requirement (excl. cash & collateral)",
            icon=":material/info:", color="blue",
        )

    # Four numbers — large, clean, with inline question-mark tooltips
    k = st.columns(4)
    k[0].metric(req_label, money(a["requirement"]), border=True,
                help=ui.GLOSSARY["Margin requirement"] if is_cust else ui.GLOSSARY.get("Risk-based haircut",""))
    k[1].metric("Net liquidation value", money(a["nav"]), border=True,
                help=ui.GLOSSARY["Net liquidation value (NAV)"])
    k[2].metric("Position value vs. requirement", money(a["excess"]), border=True,
                help="Position value minus requirement. Cash and other collateral not included.")
    k[3].metric("Saved by offsets", money(a["offset_benefit"]), border=True,
                help="How much lower the requirement is than if every class group stood alone.")
    st.caption(f"{ui.ACCOUNT_TYPES[a['acct_type']]} ranges and minimums. "
               "These are OCC's minimums; your firm's house requirements may be higher.")

    # Requirement bridge — the centrepiece of the verdict step
    da   = det[det.account == acct]
    pgx  = res["product_groups"]; pgx = pgx[pgx.account == acct]
    pos_alone = np.maximum(np.clip(-da[PCOLS].min(axis=1), 0, None), da["minimum"]).sum()
    cg_alone  = a["no_offsets"]
    pg_alone  = pgx["requirement_alone"].sum()
    req  = a["requirement"]
    steps_ = [
        ("Every position on its own",  pos_alone,             "absolute",
         "What you'd pay if nothing could offset anything"),
        ("Class group netting",        cg_alone - pos_alone,  "relative",
         "Saved: same underlying nets at 100% (e.g. SPX against SPY)"),
        ("Product group offsets",      pg_alone - cg_alone,   "relative",
         "Saved: related underlyings offset at OCC's percentage"),
        ("Portfolio group offsets",    req - pg_alone,        "relative",
         "Saved: groups of product groups offset at OCC's BBIDX/USIDX percentage"),
        (req_label,                    req,                   "total",
         "What the account must hold"),
    ]
    br = go.Figure(go.Waterfall(
        orientation="h", y=[s[0] for s in steps_], x=[s[1] for s in steps_],
        measure=[s[2] for s in steps_], customdata=[s[3] for s in steps_],
        text=[money(s[1], signed=s[2]=="relative") for s in steps_], textposition="outside",
        decreasing=dict(marker=dict(color=GAIN)), increasing=dict(marker=dict(color=LOSS)),
        totals=dict(marker=dict(color=PETROL)), connector=dict(line=dict(color="#9AA59C", width=1)),
        hovertemplate="<b>%{y}: %{text}</b><br><i>%{customdata}</i><extra></extra>"))
    br.update_layout(
        title="Requirement bridge — hover each bar to see what it means",
        height=330,
        yaxis=dict(autorange="reversed", gridcolor="rgba(0,0,0,0)"),
        xaxis=dict(title="Dollars", tickformat="$~s",
                   range=[0, max(pos_alone, cg_alone, pg_alone, req) * 1.18]),
        showlegend=False, margin=dict(l=10, r=20, t=56, b=10))
    st.plotly_chart(br, width="stretch")
    st.caption("Green bars are savings from hedges. "
               "Read top to bottom: the bridge shows how each offset layer reduces the requirement.")

    # Next-step hint
    fin    = res["final"]; fin = fin[fin.account == acct]
    top_g  = fin.sort_values("requirement").iloc[-1]
    cgs_a  = res["class_groups"]
    cgs_a  = cgs_a[(cgs_a.account == acct)
                   & cgs_a.product_group.isin([p.strip() for p in str(top_g["product_groups"]).split(",")])]
    if top_g["worst_point"] is not None and not pd.isna(top_g["worst_point"]):
        cg_loss = cgs_a[PCOLS[int(top_g["worst_point"])]]
    else:
        cg_loss = cgs_a[PCOLS].min(axis=1)
    worst_cg = cgs_a.loc[cg_loss.idxmin()]
    ui.next_step(
        f"the largest net loss comes from <b>{str(worst_cg['class_group_name']).title()}</b> "
        f"(class group {worst_cg['class_group']}, {money(min(cg_loss.min(), 0))}). "
        "Click below to see exactly which positions drive it and run what-ifs.",
        guided=True,
    )

    st.markdown('<div class="wiz-cta"></div>', unsafe_allow_html=True)
    c1, c2 = st.columns([2, 5], vertical_alignment="center")
    with c1:
        if st.button("See what drives it →", type="primary", use_container_width=True,
                     help="Drill into the risk array and which positions cause the loss."):
            go_to(4)
    with c2:
        st.caption(
            "Not the right account? Use **← Change account** above. "
            "Want to test a hedge? Use **← Change book** above, edit a quantity, "
            "and calculate again — you'll land back here."
        )


# ──────────────────────────────────────────────────────────────────────────────
# STEP 4 — Find what drives it
# ──────────────────────────────────────────────────────────────────────────────
elif step == 4:
    res  = _ensure_result()
    det  = res["detail"]
    acct = st.session_state.get("wizard_acct") or res["accounts"].sort_values("excess").iloc[0]["account"]
    accts = res["accounts"].copy()
    accts["type"] = accts.acct_type.map(ui.ACCOUNT_TYPES)
    accts = accts.sort_values("excess").reset_index(drop=True)
    a  = accts[accts.account == acct].iloc[0]
    is_cust  = a["acct_type"] == "C"
    req_label = "Margin requirement" if is_cust else "Risk-based haircut"

    # Completed step bars
    pos = st.session_state["positions"]
    n_pos = len(pos[pos["symbol"].fillna("").astype(str).str.strip() != ""])
    if ui.done_bar("Load positions", f"{n_pos} positions", 1, "back1c",
                   back_label="← Change book"):
        go_to(1)
    if ui.done_bar("Check accounts", f"{len(accts)} accounts", 2, "back2c",
                   back_label="← Change account"):
        go_to(2)
    if ui.done_bar(f"Account {acct} verdict",
                   f"{req_label.lower()} {money(a['requirement'])}", 3, "back3c",
                   back_label="← Back to verdict"):
        go_to(3)

    ui.wizard_card(
        f"What drives account {acct}'s requirement",
        "The risk array shows which price scenario hurts most. "
        "'Positions behind the worst case' shows who's responsible. "
        "'Offset detail' shows the full cascade math.",
    )

    da   = det[det.account == acct]
    pgx  = res["product_groups"]; pgx = pgx[pgx.account == acct]
    fin  = res["final"]; fin = fin[fin.account == acct]
    groups = fin["group"].tolist()
    grp  = groups[0] if len(groups) == 1 else (
        st.segmented_control("Group", groups, default=groups[0],
                             help="Groups that can't offset each other are charged separately.") or groups[0])
    row  = fin[fin.group == grp].iloc[0]
    pg_list = [p.strip() for p in str(row["product_groups"]).split(",")]

    if len(groups) > 1:
        st.caption(f"Offset path: {row['path']} · "
                   f"Binding: {row['binding'].replace('-', ui.MINUS).lower()}")

    t_arr, t_why, t_off = st.tabs([
        "📊 Risk array",
        "🎯 Positions behind the worst case",
        "🔢 Offset detail",
    ])

    with t_arr:
        cgs = res["class_groups"]
        cgs = cgs[(cgs.account == acct) & (cgs.product_group.isin(pg_list))]
        fig = go.Figure()
        net = [row[c] for c in PCOLS]
        fig.add_trace(go.Bar(x=XL, y=net, name="Net after offsets",
                             marker=dict(color=[LOSS if v < 0 else GAIN for v in net]),
                             opacity=0.28, hovertemplate="Net: %{y:$,.0f}<extra></extra>"))
        if len(pg_list) > 1:
            comps = [(f"PG {c.product_group} {ref.product_group_name(c.product_group).title()[:20]}",
                      [getattr(c, p) for p in PCOLS],
                      ref.range_for(c.product_group, a["acct_type"]))
                     for c in pgx[pgx.product_group.isin(pg_list)].itertuples()]
        elif len(cgs) > 1:
            comps = [(f"{c.class_group} {str(c.class_group_name).title()[:24]}",
                      [getattr(c, p) for p in PCOLS],
                      ref.range_for(c.product_group, a["acct_type"]))
                     for c in cgs.itertuples()]
        else:
            dd = da[da.product_group.isin(pg_list)].copy()
            dd["sz"] = dd[PCOLS].abs().max(axis=1)
            comps = [(x.description, [getattr(x, p) for p in PCOLS],
                      ref.range_for(x.product_group, a["acct_type"]))
                     for x in dd.sort_values("sz", ascending=False).head(6).itertuples()]
        for name, ys, rng in comps:
            lo, hi = rng
            mv = [f"{m:+.1%}".replace("-", ui.MINUS) for m in cpm.valuation_points(lo, hi)]
            fig.add_trace(go.Scatter(x=XL, y=ys, mode="lines+markers", name=name,
                                     customdata=mv,
                                     hovertemplate=name + ": %{y:$,.0f} at %{customdata}<extra></extra>"))
        if row["worst_point"] is not None and not pd.isna(row["worst_point"]):
            w = int(row["worst_point"])
            fig.add_vrect(x0=w-.45, x1=w+.45, fillcolor=AMBER, opacity=0.14, line_width=0)
            fig.add_annotation(x=XL[w], y=0.0, yref="paper", yanchor="bottom",
                               text="<b>Worst case</b>", showarrow=False,
                               font=dict(color="#8A5A12", size=12),
                               bgcolor="rgba(246,247,245,0.85)")
        fig.add_hline(y=0, line_width=1, line_color="#9AA59C")
        fig.update_xaxes(type="category", title="Price scenario (−5 = largest decline, +5 = largest rally)")
        fig.update_layout(title="Profit and loss in each of OCC's 10 price scenarios",
                          yaxis=dict(title="Profit / loss", tickformat="$~s"), height=460)
        st.plotly_chart(fig, width="stretch")
        st.caption("Hover a point to see the actual market move behind it. "
                   "The amber column is the worst case — that loss becomes the requirement "
                   "unless the per-contract minimum is higher.")
        if not row["binding"].startswith("Point"):
            st.info(f"Set by **{row['binding'].lower()}**: "
                    f"requirement {money(row['requirement'])} "
                    f"(worst loss {money(row['risk'])}, minimum {money(row['minimum'])}).",
                    icon=":material/info:")

    with t_why:
        tc = cpm.top_contributors(res, acct, grp, n=10)
        st.dataframe(
            ui.money_table(tc, ["pnl_at_binding_point"], int_cols=["qty"]),
            hide_index=True, width="stretch",
            column_config={
                "description": "Position",
                "class_group": st.column_config.Column("Class group",
                               help=ui.GLOSSARY["Class group"]),
                "qty": st.column_config.Column("Quantity", help="Negative = short"),
                "pnl_at_binding_point": st.column_config.Column("P&L in the worst case",
                               help="This position's profit or loss in the amber scenario"),
            },
        )
        st.caption(
            "Positions in the same class group net fully — a large loss can be cancelled "
            "by a gain in the same group. The real drivers are large losses with no partner."
        )
        st.info("💡 To test a hedge: go back to Step 1, edit a quantity, and recalculate. "
                "You'll see exactly how the requirement changes.", icon=":material/tips_and_updates:")

    with t_off:
        cgx = res["class_groups"]; cgx = cgx[cgx.account == acct]
        st.markdown("**Class groups — 100% netting within each underlying**")
        st.dataframe(
            ui.money_table(cgx[["class_group","class_group_name","product_group",
                                 "risk","minimum","standalone_req"]],
                           ["risk","minimum","standalone_req"]),
            hide_index=True, width="stretch",
            column_config={
                "class_group": st.column_config.Column("Class group", help=ui.GLOSSARY["Class group"]),
                "class_group_name": "Name", "product_group": "Product group",
                "risk": st.column_config.Column("Worst loss",
                        help="Largest net loss across all 10 scenarios"),
                "minimum": st.column_config.Column("Minimum", help=ui.GLOSSARY["Minimum charge"]),
                "standalone_req": st.column_config.Column("Requirement alone",
                        help="The larger of worst loss and minimum, before any further offsets"),
            },
        )
        st.markdown("**Product groups — offsets at OCC's file percentage**")
        st.dataframe(
            ui.money_table(pgx[["product_group","product_group_name","offset_pct",
                                 "gross_loss","offset_credit","requirement_alone","portfolio_groups"]],
                           ["gross_loss","offset_credit","requirement_alone"], ["offset_pct"]),
            hide_index=True, width="stretch",
            column_config={
                "product_group": st.column_config.Column("Product group",
                                  help=ui.GLOSSARY["Product group"]),
                "product_group_name": "Name",
                "offset_pct": st.column_config.Column("Offset",
                               help="Share of one group's gain allowed to offset another's loss"),
                "gross_loss": "Gross loss",
                "offset_credit": st.column_config.Column("Offset credit",
                                  help="Gains credited against losses in the worst scenario"),
                "requirement_alone": "Requirement",
                "portfolio_groups": "Portfolio groups",
            },
        )
        ps = res["portfolio_steps"]; ps = ps[ps.account == acct]
        st.markdown("**Portfolio groups — BBIDX (85%) applied first, then USIDX (50%)**")
        if len(ps):
            st.dataframe(
                ui.money_table(ps.drop(columns="account"),
                               ["requirement_before","requirement_after","saving"], ["offset_pct"]),
                hide_index=True, width="stretch",
                column_config={
                    "portfolio_group": st.column_config.Column("Portfolio group",
                                       help=ui.GLOSSARY["Portfolio group"]),
                    "offset_pct": "Offset", "inputs": "Product groups combined",
                    "requirement_before": "Before", "requirement_after": "After", "saving": "Saved",
                },
            )
        else:
            st.caption("None apply: fewer than two product groups in any portfolio group.")

    st.divider()
    c1, c2, c3 = st.columns([2, 2, 3], vertical_alignment="center")
    with c1:
        if st.button("← Different account", use_container_width=True, key="s4_acct",
                     help="Go back to the accounts table and choose a different account."):
            go_to(2)
    with c2:
        det_a = det[det.account == acct]
        st.download_button("Download results (CSV)", det_a.to_csv(index=False),
                           f"margin_{acct}.csv", icon=":material/download:",
                           use_container_width=True,
                           help=f"Account {acct}: every position with its P&L in all 10 scenarios.")
    with c3:
        st.markdown(
            ":material/restart_alt: [Start over — go back to Step 1](#)",
            help="Returns to Load positions. Your position file and edits are preserved.",
        )
        if st.button("↩ Start over from Step 1", key="s4_restart",
                     help="Returns to Load positions. All your data is preserved — "
                          "nothing is deleted. You can re-run with a different file or edits."):
            go_to(1)
