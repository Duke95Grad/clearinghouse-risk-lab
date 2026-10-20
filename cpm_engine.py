"""
cpm_engine.py — TIMS-style portfolio margin engine (CPM and RBH), driven by
OCC's nightly RBH/CPM reference files (see occ_reference.py).

How a requirement is built:
  1. Each position is looked up on OCC's files: class group, product group,
     contract multiplier, market move adjustment factor (MMAF), minimum
     charge per contract, and eligibility for the account type (C/F/M).
     Ineligible positions are excluded and reported, never silently priced.
  2. Its product group sets the valuation range for the account type
     (e.g. PG 9 customer: -8% / +6%; PG 999: ±15%), split into 10 points:
     -5 ... -1 down, +1 ... +5 up.
  3. Every position is repriced at each point. A leveraged or inverse
     product moves MMAF x the class group (TQQQ +3x, SQQQ -3x).
  4. CLASS GROUP: positions on the same underlying net 100% (SPX, SPY, XSP
     are all class group 00018). Stocks tagged with a valid OCC basket ID
     join that index's class group at the basket offset (95%), with a basket
     minimum charge (% of basket market value).
  5. PRODUCT GROUP: at each point, gains in one class group offset losses in
     another at the product group's offset % (PG 9 = 90%). Offset 0
     (PG 999 single stocks): each class group stands alone at its own worst
     point.
  6. PORTFOLIO GROUP: highest offset first (OCC FAQ #10). BBIDX (85%) nets its
     product groups; that result then joins USIDX (50%) with PG 8, 45, 47.
  7. Requirement for each final group = max(worst net loss, sum of
     per-contract minimums). Excess = NAV - requirement (OCC FAQ #12).
"""
from datetime import date, datetime
import numpy as np
import pandas as pd
from pricing import price, bsm

PMC_COLUMNS = ["trans_id", "blank1", "clearing_member", "account_id", "put_call",
               "symbol", "blank2", "exercise_style", "settlement_style",
               "series_date", "expiration_date", "strike", "function",
               "security_type", "market_value", "net_position", "account_type",
               "basket_id"]
PCOLS = [f"P{k}" for k in range(1, 11)]
POINT_LABELS = ["-5", "-4", "-3", "-2", "-1", "+1", "+2", "+3", "+4", "+5"]  # OCC's labels
DERIVATIVES = ("O", "I", "F", "W")


# ---------------------------------------------------------------------------
# 1. Position files
# ---------------------------------------------------------------------------
def _parse_date(x):
    s = str(x).strip().split(".")[0]
    if not s or s in ("0", "nan", "None"):
        return None
    if len(s) == 7:                                   # CYYMMDD
        s = ("19" if s[0] == "0" else "20") + s[1:]
    return datetime.strptime(s, "%Y%m%d").date()


def read_pmc_file(path_or_buffer):
    """OCC PMC CSV upload layout (Trans-ID 346). Header/trailer optional."""
    raw = pd.read_csv(path_or_buffer, header=None, dtype=str,
                      keep_default_na=False, names=PMC_COLUMNS,
                      usecols=range(len(PMC_COLUMNS)))
    raw = raw[raw["trans_id"].str.strip() == "346"]
    raw = raw[~raw["blank1"].str.strip().isin(["H", "T"])]
    return normalize_positions(raw)


def normalize_positions(df):
    out = pd.DataFrame({
        "account": df["account_id"].str.strip().replace("", "ACCT"),
        "acct_type": df["account_type"].str.strip().str.upper().replace("", "C"),
        "symbol": df["symbol"].str.strip().str.upper(),
        "sec_type": df["security_type"].str.strip().str.upper(),
        "put_call": df["put_call"].str.strip().str.upper(),
        "expiry": df["series_date"].apply(_parse_date),
        "strike": pd.to_numeric(df["strike"], errors="coerce").fillna(0.0),
        "exercise": df["exercise_style"].str.strip().str.upper().replace("", "A"),
        "qty": pd.to_numeric(df["net_position"], errors="coerce").fillna(0),
        "basket_id": df["basket_id"].str.strip(),
    })
    sign = np.where(df["function"].str.strip().str.upper() == "S", -1, 1)
    out["qty"] = out["qty"].abs() * sign
    return out.reset_index(drop=True)


def to_pmc_csv(positions, clearing_member="0"):
    rows = []
    for _, p in positions.iterrows():
        rows.append(["346", "", clearing_member, p["account"],
                     p["put_call"] if p["sec_type"] in ("O", "I", "W") else "",
                     p["symbol"], "", p.get("exercise", ""), "",
                     p["expiry"].strftime("%Y%m%d") if p["expiry"] else "",
                     "", p["strike"], "S" if p["qty"] < 0 else "L",
                     p["sec_type"], 0, abs(int(p["qty"])), p.get("acct_type", "C"),
                     p.get("basket_id", "")])
    return pd.DataFrame(rows).to_csv(header=False, index=False)


# ---------------------------------------------------------------------------
# 2. Valuation
# ---------------------------------------------------------------------------
def valuation_points(lo, hi):
    """5 equal steps down to `lo`, 5 up to `hi` (OCC points -5..-1, +1..+5)."""
    return np.array([lo * k / 5 for k in range(5, 0, -1)] + [hi * k / 5 for k in range(1, 6)])


def skewed_vol(atm_vol, skew, K, S):
    return max(atm_vol - skew * np.log(K / S) / 0.10, 0.01)


def unit_value(pos, mkt, S, r, model, vol_shift, today):
    if pos["sec_type"] in ("S", "F"):
        return S
    T = max((pos["expiry"] - today).days, 0) / 365.0
    cp = 1 if pos["put_call"] == "C" else -1
    b = 0.0 if pos["sec_type"] == "I" else r - mkt["div_yield"]
    vol = skewed_vol(mkt["atm_vol"], mkt["skew"], pos["strike"], mkt["spot"]) + vol_shift
    if pos.get("exercise", "A") == "E" or pos["sec_type"] == "I":
        return bsm(S, pos["strike"], T, r, b, vol, cp)
    return price(model, S, pos["strike"], T, r, b, vol, cp)


def combine(arrays, offset):
    """Partial offset at each point: losses + offset x gains."""
    a = np.vstack(arrays)
    gains = np.clip(a, 0, None).sum(axis=0)
    losses = np.clip(a, None, 0).sum(axis=0)
    return losses + offset * gains, losses, gains


# ---------------------------------------------------------------------------
# 3. The calculation
# ---------------------------------------------------------------------------
def run_cpm(positions, market, ref, r=0.04, model="Bjerksund-Stensland 2002",
            today=None, vol_up_on_down=0.0):
    today = today or date.today()
    rows, excluded = [], []
    for i, pos in positions.iterrows():
        at = pos.get("acct_type", "C") or "C"
        tr = ref.lookup(pos["symbol"], pos["sec_type"], at)
        if not tr.eligible:
            excluded.append({"account": pos["account"], "symbol": pos["symbol"],
                             "description": tr.description, "qty": pos["qty"],
                             "reason": f"Not {'CPM' if at == 'C' else 'RBH'}-eligible on OCC's file"})
            continue
        cg, pg, notes = tr.class_group, tr.product_group, list(tr.notes)
        basket = None
        bid = str(pos.get("basket_id", "") or "").strip()
        if bid:
            basket = ref.basket(bid) if pos["sec_type"] == "S" else None
            if basket:
                cg = basket["class_group"]
                pg = ref.class_groups.loc[cg, "Product Group"]
                notes.append(f"Basket {bid}: joins class group {cg} at "
                             f"{basket['offset']:.0%} offset (validity is the user's responsibility, OCC FAQ #7)")
            else:
                notes.append(f"Basket ID {bid} not on OCC's file or not a stock: ignored")
        if pos["symbol"] not in market.index:
            raise KeyError(f"No market data for {pos['symbol']}")
        m = market.loc[pos["symbol"]]
        lo, hi = ref.range_for(pg, at)
        pts = valuation_points(lo, hi)
        mmaf = 1.0 if basket else tr.mmaf          # a basket tracks its index 1:1
        base = unit_value(pos, m, m["spot"], r, model, 0.0, today)
        vals = []
        for move in pts:
            shift = vol_up_on_down * abs(mmaf) * (move / lo) if move < 0 else 0.0
            S = m["spot"] * max(1 + mmaf * move, 0.01)
            vals.append(unit_value(pos, m, S, r, model, shift, today))
        is_deriv = pos["sec_type"] in DERIVATIVES
        mult = tr.multiplier if is_deriv else 1.0
        pnl = (np.array(vals) - base) * pos["qty"] * mult
        mv = 0.0 if pos["sec_type"] == "F" else base * pos["qty"] * mult
        rows.append({
            "pos_id": i, "account": pos["account"], "acct_type": at,
            "symbol": pos["symbol"], "description": describe(pos), "qty": pos["qty"],
            "class_group": cg, "product_group": pg, "mmaf": mmaf,
            "multiplier": mult, "range": f"{lo:+.1%} / {hi:+.1%}",
            "basket": bid if basket else "",
            "basket_offset": basket["offset"] if basket else np.nan,
            "basket_min_pct": basket["min_charge_pct"] if basket else 0.0,
            "theo_price": base, "market_value": mv,
            "minimum": tr.min_charge * abs(pos["qty"]) if is_deriv else 0.0,
            "notes": "; ".join(notes),
            **dict(zip(PCOLS, pnl)),
        })
    detail = pd.DataFrame(rows)
    excl = pd.DataFrame(excluded, columns=["account", "symbol", "description", "qty", "reason"])
    if detail.empty:
        return {"detail": detail, "excluded": excl, "class_groups": pd.DataFrame(),
                "product_groups": pd.DataFrame(), "portfolio_steps": pd.DataFrame(),
                "final": pd.DataFrame(), "accounts": pd.DataFrame()}

    # ---- class groups (with baskets)
    cg_rows = []
    for (acct, pg, cg), g in detail.groupby(["account", "product_group", "class_group"]):
        core, bsk = g[g.basket == ""], g[g.basket != ""]
        core_arr = core[PCOLS].sum().to_numpy() if len(core) else np.zeros(10)
        minimum = g["minimum"].sum()
        if len(bsk):
            off = bsk["basket_offset"].iloc[0]
            arr, _, _ = combine([core_arr, bsk[PCOLS].sum().to_numpy()], off)
            minimum += bsk["basket_min_pct"].iloc[0] * abs(bsk["market_value"].sum())
        else:
            arr = core_arr
        risk = max(-arr.min(), 0.0)
        cg_rows.append({"account": acct, "product_group": pg, "class_group": cg,
                        "class_group_name": ref.class_group_name(cg),
                        "risk": risk, "minimum": minimum,
                        "standalone_req": max(risk, minimum),
                        "market_value": g["market_value"].sum(),
                        **dict(zip(PCOLS, arr))})
    cgs = pd.DataFrame(cg_rows)

    # ---- product groups
    pg_rows = []
    for (acct, pg), g in cgs.groupby(["account", "product_group"]):
        off = ref.product_group_offset(pg)
        arrs = [row[PCOLS].to_numpy(dtype=float) for _, row in g.iterrows()]
        standalone = len(g) > 1 and off == 0
        if standalone:
            net = np.sum(arrs, axis=0)
            risk = (-np.clip(g[PCOLS].min(axis=1), None, 0)).sum()
            gross, credit = risk, 0.0
        else:
            net, losses, gains = combine(arrs, off if len(g) > 1 else 1.0)
            w = int(np.argmin(net))
            risk = max(-net.min(), 0.0)
            gross, credit = (-losses[w], (off if len(g) > 1 else 1.0) * gains[w]) if risk > 0 else (0.0, 0.0)
            if len(g) == 1:
                gross, credit = risk, 0.0
        pg_rows.append({"account": acct, "product_group": pg,
                        "product_group_name": ref.product_group_name(pg),
                        "offset_pct": off, "class_groups": len(g),
                        "standalone": standalone,
                        "gross_loss": gross, "offset_credit": credit, "risk": risk,
                        "minimum": g["minimum"].sum(),
                        "requirement_alone": g["standalone_req"].sum() if standalone else max(risk, g["minimum"].sum()),
                        "portfolio_groups": ", ".join(ref.portfolio_groups_for(pg)),
                        **dict(zip(PCOLS, net))})
    pgs = pd.DataFrame(pg_rows)

    # ---- portfolio groups, highest offset first; then final requirements
    steps, finals = [], []
    for acct, ga in pgs.groupby("account"):
        units = {}                                  # unit id -> dict
        pg2unit = {}
        for _, row in ga.iterrows():
            if row["standalone"]:
                finals.append({"account": acct, "group": f"PG {row['product_group']} {row['product_group_name']}",
                               "path": "Each class group alone (0% offset)",
                               "product_groups": row["product_group"],
                               "gross_loss": row["gross_loss"], "offset_credit": 0.0,
                               "risk": row["risk"], "minimum": row["minimum"],
                               "requirement": row["requirement_alone"], "binding": "Each class group's own worst point",
                               "worst_point": None, **{c: row[c] for c in PCOLS}})
                continue
            uid = f"PG {row['product_group']}"
            path = f"PG {row['product_group']} {row['offset_pct']:.0%}" if row["class_groups"] > 1 \
                else f"PG {row['product_group']} (one class group)"
            units[uid] = {"arr": row[PCOLS].to_numpy(dtype=float), "min": row["minimum"],
                          "pgs": [row["product_group"]], "path": path,
                          "gross": row["gross_loss"], "credit": row["offset_credit"],
                          "name": f"PG {row['product_group']} {row['product_group_name']}"}
            pg2unit[row["product_group"]] = uid
        for name, pf in ref.portfolio_groups.items():
            ids = sorted({pg2unit[p] for p in pf["product_groups"] if p in pg2unit})
            if len(ids) < 2:
                continue
            before = sum(max(max(-units[u]["arr"].min(), 0), units[u]["min"]) for u in ids)
            net, losses, gains = combine([units[u]["arr"] for u in ids], pf["offset"])
            w = int(np.argmin(net)); risk = max(-net.min(), 0.0)
            new = {"arr": net, "min": sum(units[u]["min"] for u in ids),
                   "pgs": sum((units[u]["pgs"] for u in ids), []),
                   "path": " → ".join(dict.fromkeys(units[u]["path"] for u in ids)) + f" → {name} {pf['offset']:.0%}",
                   "gross": -losses[w] if risk > 0 else 0.0,
                   "credit": pf["offset"] * gains[w] if risk > 0 else 0.0, "name": name}
            steps.append({"account": acct, "portfolio_group": name, "offset_pct": pf["offset"],
                          "inputs": ", ".join(units[u]["name"] for u in ids),
                          "requirement_before": before,
                          "requirement_after": max(risk, new["min"]),
                          "saving": before - max(risk, new["min"])})
            for u in ids:
                del units[u]
            units[name] = new
            for p in new["pgs"]:
                pg2unit[p] = name
        for u in units.values():
            risk = max(-u["arr"].min(), 0.0)
            w = int(np.argmin(u["arr"]))
            finals.append({"account": acct, "group": u["name"], "path": u["path"],
                           "product_groups": ", ".join(u["pgs"]),
                           "gross_loss": u["gross"], "offset_credit": u["credit"],
                           "risk": risk, "minimum": u["min"],
                           "requirement": max(risk, u["min"]),
                           "binding": "Minimum" if u["min"] >= risk else f"Point {POINT_LABELS[w]}",
                           "worst_point": w, **dict(zip(PCOLS, u["arr"]))})
    final = pd.DataFrame(finals)
    psteps = pd.DataFrame(steps, columns=["account", "portfolio_group", "offset_pct", "inputs",
                                          "requirement_before", "requirement_after", "saving"])

    acct = final.groupby("account")["requirement"].sum().rename("requirement").to_frame()
    acct["nav"] = detail.groupby("account")["market_value"].sum()
    acct["no_offsets"] = cgs.groupby("account")["standalone_req"].sum()
    acct["offset_benefit"] = acct["no_offsets"] - acct["requirement"]
    acct["excess"] = acct["nav"] - acct["requirement"]          # OCC FAQ #12
    acct["acct_type"] = detail.groupby("account")["acct_type"].first()
    return {"detail": detail, "excluded": excl, "class_groups": cgs,
            "product_groups": pgs, "portfolio_steps": psteps, "final": final,
            "accounts": acct.reset_index()}


def describe(pos):
    if pos["sec_type"] == "S":
        return f"{pos['symbol']} shares"
    if pos["sec_type"] == "F":
        return f"{pos['symbol']} future {pos['expiry']:%b-%y}"
    kind = "Call" if pos["put_call"] == "C" else "Put"
    fut = " (fut opt)" if pos["sec_type"] == "I" else ""
    return f"{pos['symbol']} {pos['expiry']:%d-%b-%y} {pos['strike']:g} {kind}{fut}"


def top_contributors(result, account, group, n=6):
    """Positions driving the loss at the binding point of one final group."""
    f = result["final"]
    row = f[(f.account == account) & (f.group == group)].iloc[0]
    d = result["detail"]
    pgs = [p.strip() for p in str(row["product_groups"]).split(",")]
    d = d[(d.account == account) & (d.product_group.isin(pgs))].copy()
    if row["worst_point"] is None or pd.isna(row["worst_point"]):
        cg = result["class_groups"]
        worst = cg.set_index(["account", "class_group"])[PCOLS].idxmin(axis=1)
        d["pnl_at_binding_point"] = [r[worst[(account, r["class_group"])]] for _, r in d.iterrows()]
    else:
        d["pnl_at_binding_point"] = d[PCOLS[int(row["worst_point"])]]
    return d[["description", "class_group", "qty", "pnl_at_binding_point"]] \
        .sort_values("pnl_at_binding_point").head(n)
