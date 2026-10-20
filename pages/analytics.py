"""
pages/analytics.py — Analytics workbench.

Completely separate from the Portfolio margin tool.
  - Option pricing  (Black-Scholes, Bjerksund-Stensland, Binomial tree, Binary)
  - Greeks          (first and second order, formula vs. finite-difference check)
  - Volatility      (smile construction, implied distribution, skew/kurtosis)
  - Reference       (OCC product lookup, glossary)

Inputs are independent. Nothing here affects the margin calculation.
"""
from datetime import date
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import pricing as pr
import ui
from ui import money, hint, PETROL, AMBER, INK, SLATE
from occ_reference import OCCReference

st.set_page_config(
    page_title="Analytics workbench — Clearinghouse Risk Lab",
    page_icon=":material/analytics:",
    layout="wide",
    initial_sidebar_state="expanded",
)
ui.inject_css()
ui.register_plotly_template()


@st.cache_resource
def load_reference():
    return OCCReference("reference")


ref = load_reference()

# ======================================================================= SIDEBAR
with st.sidebar:
    st.markdown(
        '<div class="brand">Clearinghouse Risk Lab</div>'
        '<div class="brand-sub">Analytics workbench</div>',
        unsafe_allow_html=True,
    )
    st.caption(
        "Independent of the Portfolio margin tool. "
        "Inputs here have no effect on any margin calculation.",
    )
    mode = st.segmented_control(
        "View", ["Guided", "Expert"], default="Guided",
        help="Guided adds explanations. Expert shows the same content with detail sections open.",
    )
    guided = (mode or "Guided") == "Guided"
    st.divider()
    st.markdown("**Valuation**", help="Shared across Option pricing, Greeks and Volatility.")
    val_date = st.date_input("Valuation date", date.today(),
                             help="Time to expiry is measured from this date.")
    r = st.number_input("Risk-free rate (%)", value=4.00, step=0.25, format="%.2f",
                        help="Annual rate used to discount option values. "
                             "A short-term Treasury yield is typical.") / 100
    st.divider()
    st.caption(f"OCC RBH/CPM reference files dated {ref.as_of}.")

# ======================================================================= PAGE HEADER
st.markdown("## Analytics workbench")
hint(
    "Standalone pricing and volatility tools. Set up an option on the Option pricing tab "
    "and the Greeks tab updates automatically. None of these inputs affect the Portfolio margin tool.",
    guided,
)

tab_p, tab_g, tab_v, tab_r = st.tabs([
    ":material/function: Option pricing",
    ":material/show_chart: Greeks",
    ":material/ssid_chart: Volatility",
    ":material/menu_book: Reference",
])

# ======================================================================= PRICING
with tab_p:
    st.markdown("### Option pricing")

    # ── Inputs + live results in one connected panel ──────────────────────────
    with st.container(border=True):
        # Row 1: inputs
        row1 = st.columns([1, 1, 1, 1, 1, 1.4])
        S = row1[0].number_input("Underlying price", value=100.0, min_value=0.01,
                                 help="Today's price of the stock, index or future")
        K = row1[1].number_input("Strike", value=100.0, min_value=0.01,
                                 help="The price the option lets you buy (call) or sell (put) at")
        days = row1[2].number_input("Days to expiry", value=180, min_value=1,
                                    help="Calendar days until the option expires")
        vol = row1[3].number_input("Volatility (%)", value=25.0, min_value=1.0, step=1.0,
                                   help="Implied volatility: the market's expected annual price swing. "
                                        "25 means 25%.") / 100
        q = row1[4].number_input("Dividend yield (%)", value=3.0, min_value=0.0, step=0.25,
                                 help="Annual dividend as a % of price. "
                                      "Dividends make early exercise of calls more likely.") / 100
        with row1[5]:
            cp_lbl = st.segmented_control("Type", ["Put", "Call"], default="Put",
                                          help="A put gains when price falls; a call gains when it rises.")
            is_fut = st.toggle("Option on a future", help="Uses Black-76: carry b = 0.")

        cp_lbl = cp_lbl or "Put"
        T = days / 365
        b = 0.0 if is_fut else r - q
        cp = 1 if cp_lbl == "Call" else -1

        euro   = pr.bsm(S, K, T, r, b, vol, cp)
        bs02   = pr.bjerksund_stensland_2002(S, K, T, r, b, vol, cp)
        crr    = pr.crr_binomial(S, K, T, r, b, vol, cp, steps=2000)
        binary = pr.binary_cash_or_nothing(S, K, T, r, b, vol, cp)

        st.divider()

        # Row 2: results — four model values + early-exercise, all in one row
        res_cols = st.columns([1, 1, 1, 1, 0.8])
        res_cols[0].metric("Black-Scholes (European)", f"{euro:.4f}",
                           f"{euro - crr:+.4f} vs. tree",
                           delta_color="off", delta_arrow="off", border=False,
                           help="Exact for European options. A lower bound for American.")
        res_cols[1].metric("Bjerksund-Stensland", f"{bs02:.4f}",
                           f"{bs02 - crr:+.4f} vs. tree",
                           delta_color="off", delta_arrow="off", border=False,
                           help="Fast approximation for American options. Should sit just below the tree.")
        res_cols[2].metric("Binomial tree (American)", f"{crr:.4f}",
                           "benchmark · 2,000 steps",
                           delta_color="off", delta_arrow="off", border=False,
                           help="Most accurate American price. 2,000 steps is the benchmark.")
        res_cols[3].metric(f"Binary {cp_lbl.lower()} · $1 payout", f"{binary:.4f}",
                           f"{binary * np.exp(r * T):.1%} risk-neutral probability",
                           delta_color="off", delta_arrow="off", border=False,
                           help="Pays $1 if in the money at expiry. Value equals the probability, discounted.")
        res_cols[4].metric("Early-exercise premium", f"{crr - euro:.4f}",
                           "American − European",
                           delta_color="off", delta_arrow="off", border=False,
                           help="What the right to exercise early is worth. Zero for European options.")

    # ── Charts + expander: side by side ──────────────────────────────────────
    left, right = st.columns(2)
    with left:
        steps_n = np.arange(10, 301, 5)
        conv = [pr.crr_binomial(S, K, T, r, b, vol, cp, int(n), american=False) for n in steps_n]
        f = go.Figure([
            go.Scatter(x=steps_n, y=conv, name="Binomial (European)", line=dict(color=PETROL)),
            go.Scatter(x=steps_n, y=[euro] * len(steps_n), name="Black-Scholes",
                       line=dict(color=AMBER, dash="dash")),
        ])
        f.update_layout(title="Tree converges to Black-Scholes", height=340,
                        xaxis_title="Steps in the tree", yaxis_title="Option value")
        st.plotly_chart(f, width="stretch")

        with st.expander("How the models differ", icon=":material/help:", expanded=False):
            st.markdown(
                "- **Black-Scholes** is exact for European options (exercise only at expiry).\n"
                "- **Binomial tree** checks at every step whether early exercise pays. "
                "The benchmark for American options.\n"
                "- **Bjerksund-Stensland** approximates the American value in microseconds. "
                "It's a lower bound — expect it slightly below the tree.\n"
                "- **Binary** pays $1 if in the money; its value is the discounted probability."
            )

    with right:
        spots    = np.linspace(0.6 * K, 1.4 * K, 41)
        prem_b   = [pr.crr_binomial(s, K, T, r, b, vol, cp, 400) - pr.bsm(s, K, T, r, b, vol, cp) for s in spots]
        prem_bs  = [pr.bjerksund_stensland_2002(s, K, T, r, b, vol, cp) - pr.bsm(s, K, T, r, b, vol, cp) for s in spots]
        f2 = go.Figure([
            go.Scatter(x=spots, y=prem_b,  name="Binomial tree",       line=dict(color=PETROL)),
            go.Scatter(x=spots, y=prem_bs, name="Bjerksund-Stensland", line=dict(color=AMBER)),
        ])
        f2.update_layout(title="Early-exercise premium by underlying price", height=340,
                         xaxis_title="Underlying price", yaxis_title="American − European")
        st.plotly_chart(f2, width="stretch")

        hint("The premium peaks deep in-the-money, where early exercise captures intrinsic value "
             "before dividends are paid, and fades to zero out-of-the-money.", guided)

# ======================================================================= GREEKS
# Correct order of derivative classification:
# First order:  Delta, Vega, Theta, Rho
# Second order: Gamma (∂²V/∂S²), Vanna (∂²V/∂S∂σ), Volga (∂²V/∂σ²),
#               Charm (∂²V/∂S∂t), Speed (∂³V/∂S³ — actually third, shown here by convention)
#
# Gamma is the second derivative of value w.r.t. the underlying price.
# It conventionally appears directly below Delta in Greek tables.
with tab_g:
    st.markdown("### Greeks")
    hint(
        f"Sensitivities for a {days}-day {K:g} {cp_lbl.lower()} "
        f"on an underlying at {S:g}, {vol:.0%} vol.",
        guided,
    )

    g = pr.bsm_greeks(S, K, T, r, b, vol, cp)

    # Order: Delta, Gamma, then remaining first-order, then remaining second-order
    # Gamma is 2nd-order but conventionally listed with/after Delta
    greek_order = ["Delta", "Gamma", "Vega", "Theta", "Rho",
                   "Vanna", "Volga", "Charm", "Speed"]
    meaning = {
        "Delta":  ("per $1 move",      "Value change for a $1 move in the underlying"),
        "Gamma":  ("per $1 move",      "How fast delta changes — the second derivative of value w.r.t. price"),
        "Vega":   ("per vol point",    "Value change for a 1-point rise in volatility"),
        "Theta":  ("per day",          "Value lost to one day passing"),
        "Rho":    ("per 1% rate",      "Value change for a 1% rise in rates"),
        "Vanna":  ("delta per vol pt", "How delta shifts when volatility changes (∂²V/∂S∂σ)"),
        "Volga":  ("vega per vol pt",  "How vega shifts when volatility changes (∂²V/∂σ²)"),
        "Charm":  ("delta per day",    "How delta drifts as time passes (∂²V/∂S∂t)"),
        "Speed":  ("gamma per $1",     "How gamma changes with the underlying price"),
    }
    # Delta is 1st order; Gamma is 2nd order but listed first by convention
    order_label = {
        "Delta": "1st order",
        "Gamma": "2nd order",
        "Vega":  "1st order",
        "Theta": "1st order",
        "Rho":   "1st order",
        "Vanna": "2nd order",
        "Volga": "2nd order",
        "Charm": "2nd order",
        "Speed": "2nd order",
    }
    scale = {
        "Vega": 0.01, "Theta": 1/365, "Rho": 0.01,
        "Vanna": 0.01, "Volga": 0.0001, "Charm": -1/365,
    }
    gt = pd.DataFrame({
        "Greek": greek_order,
        "Order": [order_label[k] for k in greek_order],
        "Value": [g[k] * scale.get(k, 1) for k in greek_order],
        "Units": [meaning[k][0] for k in greek_order],
        "What it tells you": [meaning[k][1] for k in greek_order],
    })

    # ── Table left, chart right — same vertical position ─────────────────────
    tbl_col, chart_col = st.columns([2, 3])

    with tbl_col:
        show_gt = gt if guided else gt.drop(columns="What it tells you")
        st.dataframe(
            ui.money_table(show_gt, dec={"Value": 5}),
            hide_index=True, width="stretch", row_height=36,
            column_config={
                "Greek": st.column_config.Column(width="small"),
                "Order": st.column_config.Column(width="small"),
                "Value": st.column_config.Column(width="small"),
                "Units": st.column_config.Column(width="medium"),
                "What it tells you": st.column_config.Column(width="large"),
            },
        )
        with st.expander("Check: formulas vs. finite differences",
                         icon=":material/fact_check:", expanded=not guided):
            fd = pr.fd_greeks("Black-Scholes (European)", S, K, T, r, b, vol, cp)
            st.dataframe(
                pd.DataFrame({
                    "Greek":             list(fd),
                    "Formula":           [g[k] for k in fd],
                    "Finite difference": list(fd.values()),
                    "Diff":              [abs(g[k] - fd[k]) for k in fd],
                }),
                hide_index=True, width="stretch",
                column_config={
                    "Formula":           st.column_config.NumberColumn(format="%.6f"),
                    "Finite difference": st.column_config.NumberColumn(format="%.6f"),
                    "Diff":              st.column_config.NumberColumn(format="%.2e"),
                },
            )
            st.caption("Sub-basis-point differences confirm the formulas are correct.")

    with chart_col:
        which = st.segmented_control("Plot", greek_order, default="Gamma")
        which = which or "Gamma"
        spots = np.linspace(0.7 * K, 1.3 * K, 121)
        f3 = go.Figure()
        for d_ in sorted({7, 30, 90, int(days)}):
            f3.add_trace(go.Scatter(
                x=spots, name=f"{d_}d",
                y=[pr.bsm_greeks(s, K, d_/365, r, b, vol, cp)[which] * scale.get(which, 1)
                   for s in spots],
            ))
        f3.add_vline(x=K, line_width=1, line_dash="dot", line_color=SLATE)
        f3.update_layout(
            title=f"{which} across underlying prices — by time to expiry",
            height=460,
            xaxis_title="Underlying price",
            yaxis_title=f"{which} ({meaning[which][0]})",
        )
        st.plotly_chart(f3, width="stretch")
        hint("Dotted line = strike. Short-dated gamma peaks sharply at the strike — "
             "why short-dated options are hardest to margin.", guided)

# ======================================================================= VOLATILITY
with tab_v:
    st.markdown("### Volatility: skew and kurtosis")
    hint("Shape a volatility smile and see the price distribution it implies. "
         "A steeper skew fattens the left tail; more curvature fattens both tails.", guided)

    # ── Inputs ───────────────────────────────────────────────────────────────
    with st.container(border=True):
        c = st.columns([1.2, 1, 1.4, 1.4, 1.4])
        F0  = c[0].number_input("Forward price", value=100.0, key="vf",
                                help="Expected price at expiry from today's price, rates and dividends")
        Tv  = c[1].number_input("Days to expiry", value=30, min_value=5, key="vt") / 365
        atm = c[2].slider("ATM volatility (%)", 5, 80, 20, 1,
                          help="Implied volatility for at-the-money strikes") / 100
        sk  = c[3].slider("Skew", -0.60, 0.20, -0.25, 0.01,
                          help="Vol change per unit of log-moneyness. "
                               "Negative = downside strikes cost more.")
        cv  = c[4].slider("Curvature", 0.0, 2.0, 0.5, 0.05,
                          help="How much volatility rises on both wings.")

    # ── Compute ───────────────────────────────────────────────────────────────
    Ks   = np.linspace(F0 * 0.55, F0 * 1.45, 721)
    kk   = np.log(Ks / F0)
    sig  = np.maximum(atm + sk * kk + cv * kk**2, 0.01)
    cls  = np.array([pr.bsm(F0, K_, Tv, r, 0.0, s_, 1) for K_, s_ in zip(Ks, sig)])
    dK   = Ks[1] - Ks[0]
    dens = np.clip(np.exp(r * Tv) * np.gradient(np.gradient(cls, dK), dK), 0, None)
    dens /= np.trapezoid(dens, Ks)
    flat = np.array([pr.bsm(F0, K_, Tv, r, 0.0, atm, 1) for K_ in Ks])
    ln_d = np.clip(np.exp(r * Tv) * np.gradient(np.gradient(flat, dK), dK), 0, None)
    ln_d /= np.trapezoid(ln_d, Ks)

    def moments(p):
        x   = np.log(Ks / F0)
        mu  = np.trapezoid(x * p, Ks)
        var = np.trapezoid((x - mu)**2 * p, Ks)
        return (round(np.trapezoid((x - mu)**3 * p, Ks) / var**1.5, 3) + 0.0,
                round(np.trapezoid((x - mu)**4 * p, Ks) / var**2 - 3, 3) + 0.0)

    s_sk, s_ku = moments(dens)

    # ── Headline stats: full-width, tinted ────────────────────────────────────
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Implied skewness", f"{s_sk:.3f}", f"{s_sk:+.3f} vs. lognormal",
              delta_color="off", delta_arrow="off", border=True,
              help="Negative = fatter left (crash) tail than Black-Scholes assumes.")
    m2.metric("Implied excess kurtosis", f"{s_ku:.3f}", f"{s_ku:+.3f} vs. lognormal",
              delta_color="off", delta_arrow="off", border=True,
              help="Positive = fatter tails on both sides than Black-Scholes assumes.")
    m3.metric("ATM vol", f"{atm:.1%}", f"smile: {sig.min():.1%}–{sig.max():.1%} range",
              delta_color="off", delta_arrow="off", border=True,
              help="At-the-money implied volatility set above.")
    m4.metric("Skew steepness", f"{sk:+.2f}", "vol/unit log-moneyness",
              delta_color="off", delta_arrow="off", border=True,
              help="How steeply the smile tilts. −0.25 is a typical equity skew.")

    # ── Charts: smile left, distribution right ────────────────────────────────
    left, right = st.columns(2)
    with left:
        f4 = go.Figure([
            go.Scatter(x=Ks, y=sig * 100, name="Smile",             line=dict(color=PETROL)),
            go.Scatter(x=Ks, y=[atm * 100] * len(Ks), name="Flat (Black-Scholes)",
                       line=dict(color=SLATE, dash="dash")),
        ])
        f4.update_layout(title="Implied volatility smile", height=400,
                         xaxis_title="Strike",
                         yaxis=dict(title="Implied volatility (%)", ticksuffix="%"))
        st.plotly_chart(f4, width="stretch")

    with right:
        log_hdr, log_toggle = st.columns([3, 1], vertical_alignment="center")
        log_hdr.markdown("**Risk-neutral price distribution at expiry**")
        log_on = log_toggle.toggle("Log scale", value=True,
                                   help="Log scale shows the tails. Always use it to compare crash risk.")
        f5 = go.Figure([
            go.Scatter(x=Ks, y=dens, name="Implied by smile", line=dict(color=PETROL)),
            go.Scatter(x=Ks, y=ln_d, name="Lognormal (flat vol)", line=dict(color=SLATE, dash="dash")),
        ])
        f5.update_layout(height=370,
                         xaxis_title="Price at expiry",
                         yaxis_title="Probability density",
                         margin=dict(t=8))
        if log_on:
            f5.update_yaxes(type="log", range=[-5, np.log10(max(dens.max(), ln_d.max()) * 1.5)])
        st.plotly_chart(f5, width="stretch")

    hint("Breeden-Litzenberger: the risk-neutral density is the second derivative of call "
         "prices with respect to strike. A fatter left tail means short puts can lose more "
         "in a crash than a flat-vol scenario grid suggests — the argument for the stress test.",
         guided)

# ======================================================================= REFERENCE
with tab_r:
    st.markdown("### Reference")
    left, right = st.columns([1.15, 1])
    with left:
        st.markdown("#### Look up how OCC treats a product")
        with st.container(border=True):
            q_ = st.columns(3)
            sym     = q_[0].text_input("Symbol", "TQQQ",
                                       help="Any ticker. Press Enter to look it up.").strip().upper()
            st_code = q_[1].selectbox("Security type", ["S","O","I","F","W"],
                                      format_func={"S":"Stock or ETF","O":"Option",
                                                   "I":"Option on future","F":"Future","W":"Warrant"}.get)
            at_code = q_[2].selectbox("Account type", ["C","F","M"],
                                      format_func=ui.ACCOUNT_TYPES.get)
            t      = ref.lookup(sym, st_code, at_code)
            lo, hi = ref.range_for(t.product_group, at_code)
            if not t.found:
                st.badge("Not on OCC's file — default treatment", icon=":material/help:", color="orange")
            elif not t.eligible:
                st.badge(f"Not eligible for {ui.ACCOUNT_TYPES[at_code]} accounts",
                         icon=":material/block:", color="red")
            else:
                st.badge(f"Eligible for {ui.ACCOUNT_TYPES[at_code]} accounts",
                         icon=":material/check_circle:", color="green")
            info = {
                "Description":        t.description,
                "Class group":        f"{t.class_group}, {ref.class_group_name(t.class_group).title()}",
                "Product group":      f"{t.product_group}, {ref.product_group_name(t.product_group).title()}",
                "Product group offset": f"{ref.product_group_offset(t.product_group):.0%}",
                "Portfolio groups":   ", ".join(f"{g_} ({ref.portfolio_groups[g_]['offset']:.0%})"
                                                for g_ in ref.portfolio_groups_for(t.product_group)) or "None",
                "Price moves":        f"{lo:+.1%} to {hi:+.1%}",
                "Leverage factor (MMAF)": f"{t.mmaf:+g}" + (
                    f", so moves are {lo*t.mmaf:+.1%} to {hi*t.mmaf:+.1%}" if t.mmaf != 1 else ""),
                "Contract multiplier": f"{t.multiplier:,g}",
                "Minimum charge":     ("None (shares)" if st_code == "S"
                                       else f"${t.min_charge:,.2f}" if t.min_charge >= 0.01
                                       else f"${t.min_charge:g}"),
            }
            if t.class_group in ref.class_groups.index and ref.class_groups.loc[t.class_group, "Basket ID"]:
                bk = ref.basket(ref.class_groups.loc[t.class_group, "Basket ID"])
                info["Basket code"] = (f"{ref.class_groups.loc[t.class_group, 'Basket ID']}: "
                                       f"{bk['offset']:.0%} offset, {bk['min_charge_pct']:.1%} minimum charge")
            for n_ in t.notes:
                info.setdefault("Note", n_)
            st.dataframe(pd.DataFrame(info.items(), columns=["Setting", "Value"]),
                         hide_index=True, width="stretch")
        st.markdown("#### How OCC builds a requirement")
        st.markdown(
            "1. Look up each position: groups, multiplier, leverage factor, minimum charge, "
            "and whether the account type may hold it.\n"
            "2. Reprice at 10 price moves set by its product group.\n"
            "3. Net everything in the same class group at 100%.\n"
            "4. Offset across class groups at the product group's percentage.\n"
            "5. Offset across product groups at the portfolio group's percentage, BBIDX before USIDX.\n"
            "6. Take the worst net loss, or the sum of minimum charges if that is higher.")
        st.caption(f"Source: OCC RBH/CPM reference files dated {ref.as_of}, and OCC's RBH/CPM FAQ (Feb 2022).")
    with right:
        st.markdown("#### Glossary")
        for term, text in ui.GLOSSARY.items():
            with st.expander(term):
                st.write(text)
