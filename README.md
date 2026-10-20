# Clearinghouse Risk Lab

A customer portfolio margin (CPM) engine with option pricing, Greeks and
volatility analytics, built in Python and Streamlit.

## Run it

1. Install Python 3.11+ from python.org. On Windows, tick "Add to PATH".
2. Open a terminal in this folder.
3. Install the libraries: `pip install -r requirements.txt`
4. Run the validation checks: `python tests.py` (all 22 should pass).
5. Launch the app: `streamlit run app.py` (it opens in your browser).

To host it publicly:
1. Push the folder to a GitHub repository.
2. Deploy it free at share.streamlit.io.

## Files

| File | What it does |
|---|---|
| `pricing.py` | The pricing models: Black-Scholes-Merton (with cost of carry), Black-76, Bjerksund-Stensland 2002, CRR binomial, cash-or-nothing binary, analytic first- and second-order Greeks, finite-difference Greeks, and an implied-vol solver. |
| `occ_reference.py` | Loads OCC's nightly RBH/CPM files from `reference/` and resolves each product's class group, product group, portfolio groups, range, multiplier, MMAF, minimum charge and eligibility, for customer (C), firm (F) and market-maker (M) accounts. |
| `reference/` | OCC's RBH/CPM files (as of 10/16/2026). Drop newer files in with the same names to update. |
| `cpm_engine.py` | The margin engine. It reads OCC PMC position files and builds the requirement through OCC's hierarchy: class group (100% netting, plus 95% basket offsets), then product group (file offset %), then portfolio group (BBIDX 85% first, then USIDX 50%). It applies MMAF scaling for leveraged and inverse products and excludes ineligible products, reporting them. |
| `app.py` | The dashboard: Margin, Option pricing, Greeks, Volatility and Reference tabs, with a Guided view (numbered steps, plain-English explanations) and an Expert view (dense, detail tables open). |
| `ui.py` | The design system: palette, type, chart template, money formatting, glossary. |
| `.streamlit/config.toml`, `static/fonts/` | Theme settings and the bundled IBM Plex fonts (SIL Open Font License), so the look works offline. |
| `tests.py` | Validation evidence: put-call parity, Bjerksund-Stensland vs. a 3,000-step tree, Greeks vs. finite differences, rule ranges, minimums, offsets, and the file round trip. |
| `sample_positions.csv` | A sample book in OCC's upload format. |
| `market_data.csv` | Illustrative market data and product mappings. Not live data. |

## How it improves on OCC's calculator

- **One screen.** You see the requirement, NAV, standalone total and offset benefit together, instead of five tabs of raw numbers.
- **It explains itself.** It names the binding constraint (a point, or the minimum), shows a gross loss → offset credit → requirement waterfall, and lists the positions driving the loss.
- **It charts the risk array**, by class group and net.
- **What-ifs.** You can edit positions and market data in place.
- **Uses your own model.** It prices with your chosen model, with editable vol and skew, and has an optional vol-stress overlay that OCC's tool doesn't offer.
- **Same file formats.** It exports in OCC's upload format, so results can be cross-checked against OCC's calculator.

## Learning path (read the code in this order)

1. `pricing.py`, sections 1–2: `bsm`, then `crr_binomial`. These map directly to math you already know.
2. `tests.py`: short, readable, and shows how each piece is called.
3. `cpm_engine.py`: `valuation_points` → `position_value` → `run_cpm`.
4. `app.py`: Streamlit is read top to bottom; each `st.` call draws one element.

Exercise: add a sixth Greek (e.g. "color") to `bsm_greeks`, then add a test for it.

## Known limitations (state these in interviews; it builds credibility)

- **It doesn't use OCC's theoretical prices.** Every setting comes from OCC's files, but positions are repriced with my own models and editable vols, so results differ from OCC's calculator by the pricing difference. Reconciling the two on the same book is the next validation step.
- **Simplified baskets.** A basket is treated as tracking its index 1:1 at the basket offset. Checking that the basket meets the minimum share of index capitalization is left to the user, as OCC's own calculator does (FAQ #7).
- **Not modeled:** concentration add-ons and house requirements; currency and debt class-group specifics; ADR-specific treatment.
- **Simple smile.** The vol smile is a parametric approximation, not a fitted surface.
- **One pricing caveat:** discrete dividends are approximated with a continuous yield.

## Validation note

Several published transcriptions of the Bjerksund-Stensland (2002) formula print
the strike K where the boundary I1 belongs, in two of the first-period phi terms.
Implemented as printed, the model overprices American calls by about 30%. This
was caught by benchmarking against a 3,000-step binomial tree, then fixed and
locked in with a regression test (`tests.py`, check 2).
