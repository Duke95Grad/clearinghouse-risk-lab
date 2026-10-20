"""
tests.py — model validation checks. Run with:  python tests.py
A margin model is only as credible as its validation evidence; these are
the checks a reviewer (or regulator) would ask to see first.
"""
from datetime import date
import pandas as pd
import numpy as np
import pricing as pr
import cpm_engine as cpm

def check(name, ok):
    print(("PASS " if ok else "FAIL ") + name)
    return ok

results = []
# 1. Put-call parity for the European model
S, K, T, r, b, v = 100, 95, 0.5, 0.04, 0.01, 0.3
c, p = pr.bsm(S, K, T, r, b, v, 1), pr.bsm(S, K, T, r, b, v, -1)
results.append(check("put-call parity", abs((c - p) - (S*pr.np.exp((b-r)*T) - K*pr.np.exp(-r*T))) < 1e-10))

# 2. Bjerksund-Stensland is a lower bound within 1.5% of a 3,000-step tree
for args in [(42, 40, 0.75, 0.04, -0.04, 0.35, 1), (100, 100, 0.5, 0.1, 0.1, 0.25, -1),
             (90, 100, 1, 0.06, 0.06, 0.3, -1)]:
    a, t = pr.bjerksund_stensland_2002(*args), pr.crr_binomial(*args, steps=3000)
    results.append(check(f"BS2002 vs tree {args}: {a:.4f} vs {t:.4f}", a <= t + 1e-3 and abs(a/t - 1) < 0.015))

# 3. American >= European
results.append(check("American >= European",
    pr.crr_binomial(100, 110, 1, 0.05, 0.05, 0.3, -1) >= pr.bsm(100, 110, 1, 0.05, 0.05, 0.3, -1)))

# 4. Analytic Greeks match finite differences
g = pr.bsm_greeks(100, 100, 0.5, 0.05, 0.03, 0.25, 1)
fd = pr.fd_greeks("Black-Scholes (European)", 100, 100, 0.5, 0.05, 0.03, 0.25, 1)
results.append(check("Greeks analytic = finite difference", all(abs(g[k]-fd[k]) < 1e-4 for k in fd)))

# 5. Implied vol round trip
px = pr.bsm(100, 90, 0.25, 0.04, 0.04, 0.42, -1)
results.append(check("implied vol round trip", abs(pr.implied_vol(px, 100, 90, 0.25, 0.04, 0.04, -1) - 0.42) < 1e-6))

# ---------------- CPM / RBH engine vs. OCC's reference files ----------------
from occ_reference import OCCReference
ref = OCCReference("reference")
mkt = pd.read_csv("market_data.csv").set_index("symbol")
T0 = date(2026, 10, 18)

def one(sym, sec, qty, acct_type="C", **kw):
    row = {"account": "X", "acct_type": acct_type, "symbol": sym, "sec_type": sec,
           "put_call": kw.get("pc", ""), "expiry": kw.get("exp"), "strike": kw.get("k", 0.0),
           "exercise": kw.get("ex", "A"), "qty": qty, "basket_id": kw.get("basket", "")}
    return pd.DataFrame([row])

# 6. Ranges come from the product group file, by account type
results.append(check("PG 9 customer range -8%/+6%", ref.range_for("9", "C") == (-0.08, 0.06)))
results.append(check("PG 9 RBH firm range ±10%", ref.range_for("9", "F") == (-0.10, 0.10)))
results.append(check("PG 999 range ±15%", ref.range_for("999", "C") == (-0.15, 0.15)))

# 7. SPX, SPY and ES share class group 00018 (100% netting)
results.append(check("SPX/SPY/ES in class group 00018",
    {ref.lookup("SPX", "O").class_group, ref.lookup("SPY", "S").class_group,
     ref.lookup("ES", "F", "M").class_group} == {"00018"}))

# 8. ES symbol collision resolved by security type
results.append(check("ES option = Eversource (999); ES fut option = E-mini (00018)",
    ref.lookup("ES", "O").class_group == "ES" and ref.lookup("ES", "I").class_group == "00018"))

# 9. Futures are RBH-only: excluded from a customer account
r_ = cpm.run_cpm(one("ES", "F", -2, exp=date(2026, 12, 18)), mkt, ref, today=T0)
results.append(check("ES future excluded from CPM", len(r_["excluded"]) == 1 and r_["detail"].empty))

# 10. Minimum charge per contract from the products file (SPY options $3.75)
r_ = cpm.run_cpm(one("SPY", "O", -1, pc="C", exp=date(2026, 11, 20), k=900.0), mkt, ref, today=T0)
results.append(check(f"far-OTM short SPY call hits $3.75 minimum (${r_['accounts'].requirement.iloc[0]:.2f})",
    abs(r_["accounts"].requirement.iloc[0] - 3.75) < 1e-9))

# 11. MMAF: 1,000 SQQQ shares (-3x) lose 3 x 10% x value on a +10% Nasdaq move
r_ = cpm.run_cpm(one("SQQQ", "S", 1000), mkt, ref, today=T0)
exp_loss = 1000 * mkt.loc["SQQQ", "spot"] * 0.30
results.append(check("SQQQ -3x MMAF scales the move", abs(r_["accounts"].requirement.iloc[0] - exp_loss) < 1e-6))

# 12. Unlisted symbol: default 15%, no offsets (OCC FAQ #9)
m2 = pd.concat([mkt, pd.DataFrame({"spot": [50.0], "atm_vol": [0.3], "skew": [0.0], "div_yield": [0.0]}, index=["ZZZZ"])])
r_ = cpm.run_cpm(one("ZZZZ", "S", 100), m2, ref, today=T0)
results.append(check("unlisted stock: 15% of value", abs(r_["accounts"].requirement.iloc[0] - 750) < 1e-6))

# 13. Portfolio groups cascade highest offset first (BBIDX before USIDX)
results.append(check("portfolio group order BBIDX → USIDX", list(ref.portfolio_groups)[:2] == ["BBIDX", "USIDX"]))

# 14. Full sample: offsets never increase the requirement, at every level
res = cpm.run_cpm(cpm.read_pmc_file("sample_positions.csv"), mkt, ref, today=T0)
ok = (res["accounts"]["requirement"] <= res["accounts"]["no_offsets"] + 1e-6).all() and \
     (res["portfolio_steps"]["saving"] >= -1e-6).all()
results.append(check("offsets never increase the requirement", ok))

# 15. Excess = NAV - requirement (OCC FAQ #12)
a = res["accounts"]
results.append(check("excess = NAV - requirement", np.allclose(a["excess"], a["nav"] - a["requirement"])))

# 16. Basket: 5% minimum charge of basket value binds a well-hedged basket
b = res["final"][res["final"].account == "1003"].iloc[0]
results.append(check("basket minimum charge applied", b["binding"] == "Minimum"))

# 17. Files agree on MMAF for every leveraged ETF
eq = ref.products[ref.products["Product Type"] == "EQUI"].set_index("Symbol")
common = [s_ for s_ in ref.enhanced.index if s_ in eq.index]
bad = [s_ for s_ in common if abs(float(eq.loc[s_, "Market Move Adjustment Factor"] if not isinstance(eq.loc[s_], pd.DataFrame) else eq.loc[s_].iloc[0]["Market Move Adjustment Factor"]) - float(ref.enhanced.loc[s_, "MMAF"])) > 1e-9]
results.append(check(f"MMAF consistent across files ({len(common)} ETFs)", not bad))

# 18. PMC file round trip
import io
p0 = cpm.read_pmc_file("sample_positions.csv")
results.append(check("PMC CSV export/import round trip", cpm.read_pmc_file(io.StringIO(cpm.to_pmc_csv(p0))).equals(p0)))

print(f"\n{sum(results)}/{len(results)} checks passed")
