"""
ui.py — the app's design system ("clearing ledger").

Palette
  INK     #1B2A3A  text
  PAPER   #F6F7F5  page background
  SURFACE #FFFFFF  content surfaces
  RULE    #D5DAD3  borders and gridlines
  PETROL  #0E5A6B  actions, brand, primary series
  AMBER   #B7791F  the binding (worst-case) point
  LOSS    #B4361E  losses (always paired with a minus sign / down marker)
  GAIN    #1F6F4A  gains (always paired with a plus sign / up marker)

Type: IBM Plex Sans (body) and IBM Plex Sans Condensed (headings, headline
figures), bundled in static/fonts and wired up in .streamlit/config.toml.
Every number uses tabular figures so columns of dollars line up.
"""
import plotly.graph_objects as go
import plotly.io as pio
import streamlit as st

INK, PAPER, SURFACE, RULE = "#1B2A3A", "#F6F7F5", "#FFFFFF", "#D5DAD3"
PETROL, AMBER, LOSS, GAIN, SLATE = "#0E5A6B", "#B7791F", "#B4361E", "#1F6F4A", "#5B6B7A"
SERIES = [PETROL, AMBER, "#6B3F69", SLATE, "#5E8F6E", "#9C4A3A", "#3E7CA6"]
FONT = "Plex, 'IBM Plex Sans', 'Segoe UI', Helvetica, Arial, sans-serif"
MINUS = "\u2212"   # a true minus sign, not a hyphen

ACCOUNT_TYPES = {"C": "Customer (CPM)", "F": "Firm (RBH)", "M": "Market maker (RBH)"}


def inject_css():
    st.markdown(f"""
<style>
  html, body, [class*="st-"], .stMarkdown, .stDataFrame {{ font-variant-numeric: tabular-nums; }}
  .block-container {{ padding-top: 2.2rem; max-width: 1320px; }}
  h1, h2, h3 {{ letter-spacing: -0.01em; color: {INK}; }}
  /* Step headings in Guided view: the number is a real sequence marker */
  .step {{ display: flex; align-items: baseline; gap: .65rem; margin: 1.6rem 0 .2rem; }}
  .step .n {{ font-family: PlexCond, {FONT}; font-weight: 600; color: {PAPER};
             background: {PETROL}; border-radius: 4px; padding: 0 .45rem; font-size: .95rem; }}
  .step .t {{ font-family: PlexCond, {FONT}; font-weight: 600; font-size: 1.25rem; color: {INK}; }}
  /* ---- Step 1 two-state design ----------------------------------- */
  /* State A: no file loaded — big explicit choice */
  .s1-choice {{ display: flex; gap: 1rem; margin: .5rem 0 1.2rem; }}
  .s1-path {{
    flex: 1; border-radius: 8px; padding: 1.4rem 1.6rem; cursor: pointer;
    border: 2px solid {RULE}; background: {SURFACE};
    transition: border-color .15s, box-shadow .15s; }}
  .s1-path.primary {{
    border-color: {PETROL}; background: #EDF4F3; }}
  .s1-path .path-icon {{ font-size: 1.8rem; margin-bottom: .5rem; }}
  .s1-path .path-title {{
    font-family: PlexCond, {FONT}; font-weight: 600; font-size: 1.1rem;
    color: {INK}; margin-bottom: .3rem; }}
  .s1-path .path-sub {{
    font-size: .88rem; color: #4A5A68; line-height: 1.5; }}
  /* State B: file loaded — prominent status banner */
  .s1-loaded {{
    display: flex; align-items: center; gap: 1rem;
    padding: 1rem 1.4rem; border-radius: 8px;
    background: #EDF4F3; border: 2px solid {PETROL};
    margin-bottom: 1rem; }}
  .s1-loaded-icon {{ font-size: 1.5rem; flex-shrink: 0; color: {PETROL}; }}
  .s1-loaded-body {{ flex: 1; }}
  .s1-loaded-title {{
    font-weight: 600; font-size: 1.05rem; color: {INK}; margin-bottom: .15rem; }}
  .s1-loaded-sub {{ font-size: .9rem; color: #2A5A2A; }}
  .s1-loaded-change {{
    font-size: .82rem; color: {PETROL}; text-decoration: underline;
    text-underline-offset: 2px; cursor: pointer; white-space: nowrap; }}
  /* ---- Guided-view wizard ----------------------------------------- */
  /* Progress stepper */
  .wiz-stepper {{ display: flex; align-items: center; gap: 0;
                 padding: 1rem 0 1.6rem; }}
  .wiz-step {{ display: flex; flex-direction: column; align-items: center;
               flex: 1; position: relative; cursor: pointer; }}
  .wiz-step:not(:last-child)::after {{
    content: ''; position: absolute; top: 14px; left: 50%; width: 100%;
    height: 2px; background: {RULE}; z-index: 0; }}
  .wiz-step.done:not(:last-child)::after {{ background: {PETROL}; opacity: .5; }}
  .wiz-circle {{
    width: 28px; height: 28px; border-radius: 50%; display: flex;
    align-items: center; justify-content: center; font-size: .8rem;
    font-weight: 600; position: relative; z-index: 1;
    border: 2px solid {RULE}; background: white; color: #8A9A8A; }}
  .wiz-step.active .wiz-circle {{
    border-color: {PETROL}; background: {PETROL}; color: white; }}
  .wiz-step.done .wiz-circle {{
    border-color: {PETROL}; background: white; color: {PETROL}; }}
  .wiz-label {{
    font-size: .73rem; font-weight: 500; margin-top: .3rem;
    color: #8A9A8A; text-align: center; max-width: 80px; line-height: 1.3; }}
  .wiz-step.active .wiz-label {{ color: {PETROL}; font-weight: 600; }}
  .wiz-step.done  .wiz-label {{ color: #3A5A3A; }}
  /* Active step card */
  .wiz-card {{
    border-left: 3px solid {PETROL}; padding: 1.4rem 1.6rem 1.6rem;
    background: {SURFACE}; border-radius: 0 8px 8px 0;
    box-shadow: 0 1px 4px rgba(0,0,0,.06); margin-bottom: 1rem; }}
  .wiz-card-title {{
    font-family: PlexCond, {FONT}; font-weight: 600; font-size: 1.3rem;
    color: {INK}; margin: 0 0 .25rem; }}
  .wiz-card-sub {{
    font-size: .92rem; color: #4A5A68; margin: 0 0 1.1rem; max-width: 76ch;
    line-height: 1.5; }}
  /* Completed step summary bar */
  .wiz-done-bar {{
    display: flex; align-items: center; gap: .75rem;
    padding: .55rem .9rem; background: #EEF3ED;
    border-radius: 6px; margin-bottom: .5rem; cursor: pointer;
    border: 1px solid #D5E0D2; }}
  .wiz-done-icon {{ color: {PETROL}; font-size: 1rem; flex-shrink: 0; }}
  .wiz-done-title {{ font-weight: 600; font-size: .9rem; color: {INK}; }}
  .wiz-done-summary {{ font-size: .88rem; color: #4A5A68; margin-left: .25rem; }}
  .wiz-done-edit {{ font-size: .8rem; color: {PETROL}; margin-left: auto;
                    text-decoration: underline; text-underline-offset: 2px; }}
  /* Large action button */
  .wiz-cta {{ margin-top: 1.1rem; }}
  .hint {{ color: #4A5A68; font-size: .93rem; max-width: 72ch; margin: .1rem 0 .6rem; line-height: 1.5; }}
  .brand {{ font-family: PlexCond, {FONT}; font-weight: 600; font-size: 1.35rem; color: {PETROL};
           line-height: 1.15; margin-bottom: .1rem; }}
  .brand-sub {{ color: #4A5A68; font-size: .85rem; margin-bottom: .4rem; }}
  [data-testid="stMetricValue"] {{ font-family: PlexCond, {FONT}; font-weight: 600; }}
  [data-testid="stMetricLabel"] p {{ font-size: .88rem; color: #3A4A5A; }}
  .stTabs [data-baseweb="tab"] p {{ font-weight: 500; font-size: .98rem; }}
  /* "Next step" guidance: a quiet left rule, not a card */
  .next {{ border-left: 3px solid {PETROL}; background: #E7EFEE; padding: .55rem .85rem;
          border-radius: 0 4px 4px 0; margin: .5rem 0 .9rem; max-width: 80ch;
          font-size: .94rem; line-height: 1.5; color: {INK}; }}
  .next b {{ color: {PETROL}; font-weight: 600; }}
  .next.alert {{ border-left-color: {LOSS}; background: #F6E9E5; }}
  .next.alert b {{ color: {LOSS}; }}
  :focus-visible {{ outline: 2px solid {AMBER} !important; outline-offset: 2px; }}
  @media (prefers-reduced-motion: reduce) {{ * {{ transition: none !important; animation: none !important; }} }}
</style>""", unsafe_allow_html=True)


def register_plotly_template():
    t = go.layout.Template()
    t.layout = go.Layout(
        font=dict(family=FONT, size=13, color=INK),
        title=dict(font=dict(family="PlexCond, " + FONT, size=16, color=INK), x=0, xanchor="left"),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        colorway=SERIES,
        xaxis=dict(gridcolor="#E4E8E2", linecolor=RULE, zerolinecolor=RULE, ticks="outside",
                   tickcolor=RULE, title=dict(font=dict(size=12, color="#4A5A68"))),
        yaxis=dict(gridcolor="#E4E8E2", linecolor=RULE, zerolinecolor="#9AA59C",
                   title=dict(font=dict(size=12, color="#4A5A68"))),
        legend=dict(orientation="h", yanchor="bottom", y=1.0, xanchor="right", x=1, font=dict(size=12)),
        hoverlabel=dict(font=dict(family=FONT, size=12), bgcolor=SURFACE, bordercolor=RULE),
        margin=dict(l=10, r=10, t=64, b=10),
    )
    pio.templates["ledger"] = t
    pio.templates.default = "ledger"


def money(x, signed=False):
    """$46,988 · −$45,745 (true minus sign) · +$1,243 when signed."""
    if x is None:
        return "—"
    if round(x) == 0:
        return "$0"
    s = f"${abs(x):,.0f}"
    if x < 0:
        return MINUS + s
    return ("+" + s) if signed and x > 0 else s


def step(n, title, hint=None, guided=True):
    """A numbered step heading in Guided view; a plain subheading in Expert."""
    if guided:
        st.markdown(f'<div class="step"><span class="n">{n}</span><span class="t">{title}</span></div>',
                    unsafe_allow_html=True)
        if hint:
            st.markdown(f'<div class="hint">{hint}</div>', unsafe_allow_html=True)
    else:
        st.markdown(f"#### {title}")



def next_step(text, guided=True, alert=False, label="Next step"):
    """Tell a novice what to do now. Shown in Guided view only."""
    if guided:
        cls = "next alert" if alert else "next"
        st.markdown(f'<div class="{cls}"><b>{label}:</b> {text}</div>', unsafe_allow_html=True)


WIZARD_STEPS = [
    ("1", "Load",     "Load positions"),
    ("2", "Accounts", "Check accounts"),
    ("3", "Verdict",  "Review account"),
    ("4", "Drivers",  "Find what drives it"),
]


def loaded_banner(source: str, n_pos: int, n_acct: int):
    """Green status banner shown when a file (or sample) is loaded. State B."""
    st.html(
        '<div class="s1-loaded">'
        '<span class="s1-loaded-icon">✔️</span>'
        '<div class="s1-loaded-body">'
        f'<div class="s1-loaded-title">{source}</div>'
        f'<div class="s1-loaded-sub">{n_pos} positions across {n_acct} accounts — ready to calculate</div>'
        '</div></div>'
    )


def wizard_stepper(current: int):
    """Horizontal progress stepper for the guided wizard. current is 1-based."""
    parts = []
    for idx, (num, short, _) in enumerate(WIZARD_STEPS):
        s = idx + 1
        cls = "wiz-step done" if s < current else ("wiz-step active" if s == current else "wiz-step")
        circle = "✓" if s < current else num
        div = (
            f'<div class="{cls}">'
            f'<div class="wiz-circle">{circle}</div>'
            f'<div class="wiz-label">{short}</div></div>'
        )
        parts.append(div)
    st.html('<div class="wiz-stepper">' + "".join(parts) + '</div>')


def wizard_card(title: str, subtitle: str):
    """Open a styled active-step card. Follow with content, then close with st.container."""
    st.html(
        f'<div class="wiz-card">'        f'<div class="wiz-card-title">{title}</div>'        f'<div class="wiz-card-sub">{subtitle}</div></div>'
    )


def done_bar(title: str, summary: str, step: int, key: str, back_label: str = "← Change"):
    """Collapsed summary for a completed step. Returns True if the user clicks back."""
    c1, c2 = st.columns([10, 1], vertical_alignment="center")
    with c1:
        st.html(
            '<div class="wiz-done-bar">'
            '<span class="wiz-done-icon">✓</span>'
            f'<span class="wiz-done-title">{title}</span>'
            f'<span class="wiz-done-summary">{summary}</span>'
            '<span class="wiz-done-edit">change ↗</span></div>'
        )
    with c2:
        return st.button(back_label, key=key, help=f"Go back and change {title.lower()}")


def hint(text, guided=True):
    if guided:
        st.markdown(f'<div class="hint">{text}</div>', unsafe_allow_html=True)


GLOSSARY = {
    "Margin requirement": "The collateral the account must hold so it can absorb the worst loss "
                          "across OCC's price scenarios. Shown as a positive dollar amount.",
    "Risk-based haircut": "For firm (F) and market-maker (M) accounts: the capital charge under the SEC "
                          "net capital rule, computed with OCC's RBH ranges and minimums. If the account's "
                          "value is below it, the shortfall is a charge against capital, not a customer call.",
    "Net liquidation value (NAV)": "What the positions are worth today at theoretical prices. "
                                   "Futures carry no value here because they settle daily.",
    "Excess or deficit": "NAV minus the requirement (OCC RBH/CPM FAQ #12). For a customer account a "
                         "deficit is a margin call: the customer must deposit that amount. For a firm or "
                         "market-maker account it is a haircut shortfall.",
    "Valuation points": "OCC revalues every position at 10 price moves, five down (−5 … −1) and five "
                        "up (+1 … +5). The size of the moves depends on the product group: "
                        "−8%/+6% for large-cap indexes, ±15% for single stocks.",
    "Binding point": "The valuation point with the largest net loss. It sets the requirement, "
                     "unless the per-contract minimum is larger.",
    "Class group": "Products on the same underlying (SPX, SPY and XSP are all S&P 500). Gains and "
                   "losses net fully: 100%.",
    "Product group": "Closely related class groups, such as the S&P 500 and the Dow. Gains in one "
                     "offset losses in another at the group's percentage (90% for large-cap indexes, "
                     "0% for single stocks).",
    "Portfolio group": "Related product groups that get a further, smaller offset. BBIDX (85%) is "
                       "applied first, then USIDX (50%) across Nasdaq, large, mid and small caps.",
    "Market move adjustment factor (MMAF)": "How much a leveraged or inverse product moves per 1% "
                                            "move in its class group. TQQQ is +3, SQQQ is −3.",
    "Minimum charge": "A floor per contract from OCC's file (usually $37.50, $3.75 for some ETF "
                      "options). The requirement is never lower than the sum of these.",
    "Basket": "A group of stocks a customer designates as replicating an index. With a valid OCC "
              "basket code, the stocks join the index's class group at a 95% offset.",
    "CPM / RBH": "Customer portfolio margin (CPM) applies to customer accounts. Risk-based haircuts "
                 "(RBH) apply to firm and market-maker accounts, with their own ranges and minimums.",
}


def money_table(df, money_cols=(), pct_cols=(), int_cols=(), dec=None):
    """Format a table for display: whole dollars with a true minus sign,
    percentages, integers. Raw values stay underneath for sorting."""
    fmt = {c: money for c in money_cols if c in df}
    fmt.update({c: (lambda v: f"{v:.0%}") for c in pct_cols if c in df})
    fmt.update({c: (lambda v: f"{v:,.0f}".replace("-", MINUS)) for c in int_cols if c in df})
    for c, d in (dec or {}).items():
        if c in df:
            fmt[c] = (lambda v, d=d: f"{v:,.{d}f}".replace("-", MINUS))
    return df.style.format(fmt, na_rep="")


def labels(points):
    return [p.replace("-", MINUS) for p in points]
