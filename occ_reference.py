"""
occ_reference.py — Loads OCC's nightly RBH/CPM reference files and answers
"how is this product treated?" for the margin engine.

Files (drop tomorrow's versions into reference/ and everything updates):
  RBHCPMIncludedProductsReport.csv  symbol + product type -> class group,
                                    product group, multiplier, MMAF,
                                    minimum charge per contract, eligibility
  RBHCPMClassGroupsReport.csv       class group -> product group, basket
                                    parameters, eligibility
  RBHCPMProductGroupsReport.csv     product group -> offset %, valuation
                                    ranges for CPM, RBH firm, RBH market maker
  RBHCPMPortfolioGroupsReport.csv   portfolio groups (BBIDX 85%, USIDX 50%)
                                    and their member product groups
  RBHEnhancedReturnsETFsReport.csv  leveraged / inverse ETFs and their MMAF
                                    (used as a cross-check of the products file)

Account types follow the PMC file's Interval Distinction ID:
  C = customer (CPM), F = broker-dealer / firm (RBH), M = market maker (RBH)
"""
from dataclasses import dataclass, field
from pathlib import Path
import glob
import pandas as pd

# PMC security type code -> OCC product type
SEC_TO_PTYPE = {"S": "EQUI", "O": "OPTN", "I": "OPTN", "F": "FUTU",
                "W": "WARR", "X": "CURR"}

# Defaults for a symbol OCC doesn't list. OCC FAQ #9: an exchange-listed
# stock not on the files "should use a 15% haircut with no offsets".
DEFAULT_PG = "999"
DEFAULT_MIN_OPTION = {"C": 37.50, "F": 25.00, "M": 25.00}


def _num(x, default=0.0):
    try:
        return float(str(x).replace(",", "").strip())
    except (TypeError, ValueError):
        return default


def _find(folder, stem):
    hits = sorted(glob.glob(str(Path(folder) / f"{stem}*.csv")))
    if not hits:
        raise FileNotFoundError(f"{stem}*.csv not found in {folder}")
    return hits[-1]


def _strip_footer(df, key):
    """OCC files end with a 'Last Update' row; drop it and return its date."""
    mask = df[key].astype(str).str.strip().str.startswith("Last Update")
    as_of = None
    if mask.any():
        row = df[mask].iloc[0].astype(str).tolist()
        as_of = next((v for v in row[1:] if "/" in v), None)
    return df[~mask].copy(), as_of


@dataclass
class Treatment:
    """Everything the engine needs to know about one position's product."""
    symbol: str
    ptype: str
    found: bool
    description: str
    class_group: str
    product_group: str
    multiplier: float
    mmaf: float                      # market move adjustment factor
    min_charge: float                # per contract, for this account type
    eligible: bool                   # for this account type
    is_etf: bool = False
    notes: list = field(default_factory=list)


class OCCReference:
    def __init__(self, folder="reference"):
        f = folder
        ip = pd.read_csv(_find(f, "RBHCPMIncludedProductsReport"), dtype=str,
                         keep_default_na=False)
        ip.columns = [c.strip() for c in ip.columns]
        ip, self.as_of = _strip_footer(ip, "Symbol")
        for c in ip.columns:
            ip[c] = ip[c].str.strip()
        self.products = ip

        cg = pd.read_csv(_find(f, "RBHCPMClassGroupsReport"), dtype=str,
                         keep_default_na=False)
        cg.columns = [c.strip() for c in cg.columns]
        cg, _ = _strip_footer(cg, "Class Group")
        for c in cg.columns:
            cg[c] = cg[c].str.strip()
        self.class_groups = cg.set_index("Class Group")
        self.baskets = cg[cg["Basket ID"] != ""].set_index("Basket ID")

        pg = pd.read_csv(_find(f, "RBHCPMProductGroupsReport"), dtype=str,
                         keep_default_na=False)
        pg.columns = [c.strip() for c in pg.columns]
        pg, _ = _strip_footer(pg, "Product Group")
        pg["Product Group"] = pg["Product Group"].str.strip()
        self.product_groups = pg.set_index("Product Group")

        pf = pd.read_csv(_find(f, "RBHCPMPortfolioGroupsReport"), dtype=str,
                         keep_default_na=False)
        pf.columns = [c.strip() for c in pf.columns]
        pf, _ = _strip_footer(pf, "Portfolio Group")
        pf = pf[pf["Product Group"].str.strip() != ""]
        # Highest offset first: OCC FAQ #10 — BBIDX (85%) is netted before
        # its result flows into USIDX (50%).
        groups = {}
        for _, r in pf.iterrows():
            g = groups.setdefault(r["Portfolio Group"].strip(),
                                  {"offset": _num(r["Portfolio Group Offset %"]) / 100,
                                   "product_groups": []})
            groups[r["Portfolio Group"].strip()]["product_groups"].append(r["Product Group"].strip())
        self.portfolio_groups = dict(sorted(groups.items(), key=lambda kv: -kv[1]["offset"]))

        er = pd.read_csv(_find(f, "RBHEnhancedReturnsETFsReport"), dtype=str,
                         skiprows=1, keep_default_na=False)
        er.columns = [c.strip() for c in er.columns]
        er = er[~er["Symbol"].str.strip().str.startswith("Last Update")]
        er["Symbol"] = er["Symbol"].str.strip()
        self.enhanced = er.set_index("Symbol")

        self._futures_classes = set(ip.loc[ip["Product Type"] == "FUTU", "Class Group"])

    # ------------------------------------------------------------------
    def range_for(self, product_group, acct_type="C"):
        """(down, up) as signed fractions, e.g. (-0.08, 0.06) for PG 9 / CPM."""
        cols = {"C": ("CPM % Down", "CPM % Up"),
                "F": ("RBH Firm % Down", "RBH Firm % Up"),
                "M": ("RBH Market Maker % Down", "RBH Market Maker % Up")}[acct_type]
        row = self.product_groups.loc[product_group] if product_group in self.product_groups.index \
            else self.product_groups.loc[DEFAULT_PG]
        return -_num(row[cols[0]]) / 100, _num(row[cols[1]]) / 100

    def product_group_offset(self, product_group):
        if product_group not in self.product_groups.index:
            return 0.0
        return _num(self.product_groups.loc[product_group, "Product Group Offset %"]) / 100

    def product_group_name(self, product_group):
        if product_group in self.product_groups.index:
            return self.product_groups.loc[product_group, "Product Group Description"]
        return "UNLISTED"

    def class_group_name(self, cg):
        if cg in self.class_groups.index:
            return self.class_groups.loc[cg, "Class Group Description"]
        return cg

    def basket(self, basket_id):
        """Basket parameters, or None if the ID isn't on OCC's file."""
        if basket_id in self.baskets.index:
            b = self.baskets.loc[basket_id]
            return {"class_group": b["Class Group"],
                    "offset": _num(b["Basket Offset %"]) / 100,
                    "min_charge_pct": _num(b["Basket Minimum Charge %"]) / 100,
                    "min_index_cap_pct": _num(b["Basket Minimum % of Index Capitalization"]) / 100}
        return None

    # ------------------------------------------------------------------
    def lookup(self, symbol, sec_type, acct_type="C"):
        """Resolve one position's treatment. Handles symbol collisions such
        as ES (CME E-mini S&P vs. Eversource Energy) by security type: an
        option on a future ('I') takes the row whose class group lists
        futures; a plain option ('O') takes the other."""
        symbol = symbol.strip().upper()
        ptype = SEC_TO_PTYPE.get(sec_type, "EQUI")
        rows = self.products[(self.products["Symbol"] == symbol) &
                             (self.products["Product Type"] == ptype)]
        notes = []
        if len(rows) > 1:
            fut = rows["Class Group"].isin(self._futures_classes)
            pick = rows[fut] if sec_type in ("I", "F") and fut.any() else rows[~fut]
            rows = pick if len(pick) else rows
            if len(rows) > 1:
                notes.append(f"{symbol} matches {len(rows)} OCC rows; used the first")
        is_option = sec_type in ("O", "I", "W")
        if rows.empty:
            notes.append("Not on OCC's file: default 15% range, no offsets (OCC FAQ #9)")
            return Treatment(symbol, ptype, False, symbol, symbol, DEFAULT_PG,
                             100.0 if is_option else 1.0, 1.0,
                             DEFAULT_MIN_OPTION[acct_type] if is_option else 0.0,
                             True, notes=notes)
        r = rows.iloc[0]
        elig_col = "Product CPM Eligible" if acct_type == "C" else "Product RBH Eligible"
        min_col = "CPM Minimum Charge Per Contract" if acct_type == "C" else "RBH Minimum Charge Per Contract"
        mmaf = _num(r["Market Move Adjustment Factor"], 1.0)
        if symbol in self.enhanced.index:
            er_mmaf = _num(self.enhanced.loc[symbol, "MMAF"] if not isinstance(
                self.enhanced.loc[symbol], pd.DataFrame) else self.enhanced.loc[symbol].iloc[0]["MMAF"], mmaf)
            if abs(er_mmaf - mmaf) > 1e-9:
                notes.append(f"MMAF differs between files ({mmaf} vs {er_mmaf}); used products file")
        if mmaf != 1.0:
            notes.append(f"Leveraged/inverse product: moves {mmaf:+g}x the class group")
        return Treatment(
            symbol=symbol, ptype=ptype, found=True, description=r["Description"],
            class_group=r["Class Group"], product_group=r["Product Group"],
            multiplier=_num(r["Contract Multiplier"], 1.0), mmaf=mmaf,
            min_charge=_num(r[min_col], 0.0), eligible=(r[elig_col] == "Yes"),
            is_etf=(r["ETF"] == "Yes"), notes=notes)

    def portfolio_groups_for(self, product_group):
        return [n for n, g in self.portfolio_groups.items() if product_group in g["product_groups"]]
