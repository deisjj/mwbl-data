#!/usr/bin/env python3
"""MWBL trade surplus calculator — deterministic implementation of the
mwbl-trade-eval model. Usage:

    python3 score.py trade.json

trade.json: {"players": [ {...}, ... ]}. Per player:
  name, side            side = who RECEIVES the player (e.g. "HAV")
  type                  LT | ML0-ML3 | OPT | O1 | O2
  yr, amt               LT years remaining and annual $M (ignored otherwise)
  age                   age on April 1 of the sim year
  role                  "H" hitter | "P" pitcher
  pa | ip               playing time
  war                   pitchers: FanGraphs WAR (war.csv `war`)
  base_war              hitters, mWAR model: war.csv `fg_war_ex_fld` (FanGraphs WAR minus real fielding)
  off_war               hitters, legacy model: war.csv `off_war` (FanGraphs Offense / 9.83)
                        (or pass total_war to skip the defense/platoon math in both models)
  pos, range, err, arm  hitter DMB defense (pos lowercase, range Pr..Ex)
  bats, pa_vr, ops_vr, pa_vl, ops_vl     hitter platoon inputs
  premium               prospect premium $M (ML players), default 0
"""
import json, sys

# Two models run side by side:
#   legacy: 2025 method. Hitters = off_war (above average) + DMB fielding with Av=+1;
#           pitchers = FanGraphs WAR (above MLB replacement). $2M per WAR.
#   mwbl:   everyone above MWBL replacement (mWAR); range centered at Av=0.
LEGACY_PER_WAR = 2.0
PER_WAR = 4.5   # $M per mWAR; league LT contracts pay ~$4.7M (2026 rosters)
# MWBL replacement level (24 x 26 = 624th-best MLB player, as a rate). Recompute each
# offseason with tools/replacement.py (rate at which 312 hitters / 312 pitchers are above it).
REPL_H_PER_600PA = 1.05
REPL_P_PER_180IP = 1.48
RANGE = {"Pr": -2, "Fr": -1, "Av": 0, "Vg": 1, "Ex": 2}  # centered: Av = average fielder
LEGACY_RANGE = {"Pr": -1, "Fr": 0, "Av": 1, "Vg": 2, "Ex": 3}
ARM = {"Pr": -1, "Fr": -0.5, "Av": 0, "Vg": 0.5, "Ex": 1}
ERR_W = {"c": .5, "1b": .4, "2b": .5, "3b": .8, "ss": .8, "lf": .2, "cf": .2, "rf": .2}
F_DMB = {("L", "R"): .85, ("L", "L"): .40, ("R", "L"): .45, ("R", "R"): .80,
         ("S", "R"): .80, ("S", "L"): .40}


def fielding(p, scale=None):
    scale = scale or RANGE
    pos = p.get("pos", "").lower()
    if not pos or pos == "dh":
        return 0.0
    rng = 0 if pos == "c" else scale.get(p.get("range"), 0)
    err = (100 - p.get("err", 100)) / 100 * ERR_W.get(pos, 0)
    arm = ARM.get(p.get("arm"), 0) if pos in ("c", "lf", "cf", "rf") else 0
    return rng + err + arm


def platoon(p):
    try:
        vr, vl, pr, pl = p["ops_vr"], p["ops_vl"], p["pa_vr"], p["pa_vl"]
    except KeyError:
        return 0.0
    tot = pr + pl
    if tot == 0:
        return 0.0
    pref = "R" if vr >= vl else "L"
    hi, lo = (vr, vl) if pref == "R" else (vl, vr)
    f = F_DMB.get((p.get("bats", "R"), pref), 0.5)
    actual = (pr * vr + pl * vl) / tot
    dmb = f * hi + (1 - f) * lo
    return max(-1.0, min(3.0, (dmb - actual) * (tot / 600) * 20))


def mlb_war(p, model="mwbl"):
    """Total WAR before any MWBL replacement adjustment (used for Star Bonus tiers)."""
    if p["role"] == "P":
        return p["war"]
    if "total_war" in p:
        return p["total_war"]
    if model == "legacy":
        return p["off_war"] + fielding(p, LEGACY_RANGE) + platoon(p)
    return p["base_war"] + fielding(p) + platoon(p)


def mwbl_war(p, w):
    """WAR above MWBL replacement (used for Production Value and FYV)."""
    if p["role"] == "P":
        return w - REPL_P_PER_180IP * p.get("ip", 0) / 180
    return w - REPL_H_PER_600PA * p.get("pa", 0) / 600


def pt_mult(p):
    return min(1.0, p.get("ip", 0) / 120) if p["role"] == "P" else min(1.0, p.get("pa", 0) / 400)


def star(w):
    if w < 4: return 0
    if w < 5: return 1.5
    if w < 6: return 3.0
    if w < 7: return 5.0
    return 7.5 + (w - 7)


def cap_eff(pv, cost):
    r = pv / max(cost, 1.0)
    if r < 2: return 0
    if r < 4: return 1.5
    if r < 8: return 3.0
    return 5.0


def age_delta(a):
    if a < 23: return .3
    if a <= 26: return .1
    if a <= 29: return -.3
    if a <= 32: return -.5
    if a <= 35: return -.8
    return -1.0


def fyv(w, age, ptm, year_costs, per_war):
    """year_costs: costs for years 2..N."""
    total, wk = 0.0, w
    for i, cost in enumerate(year_costs):
        k = i + 2
        wk += age_delta(age + k - 2)
        total += max(0.0, (wk * per_war * ptm - cost) * 0.85 ** (k - 1))
    return total


def value(p, model="mwbl"):
    t = p["type"].upper()
    w, ptm = mlb_war(p, model), pt_mult(p)
    if model == "legacy":
        mw, per_war = w, LEGACY_PER_WAR
    else:
        mw, per_war = mwbl_war(p, w), PER_WAR
    pv = mw * per_war * ptm
    if t == "LT":
        n, amt = int(p["yr"]), float(p["amt"])
        cost, future, floor = amt, [amt] * (n - 1), -amt * n
    elif t in ("O1", "OPT"):
        cost, future, floor = 3.0, [5.0], -8.0
    elif t == "O2":
        cost, future, floor = 5.0, [], -5.0
    else:  # ML0-ML3
        cost = 0.0 if t == "ML0" else 0.2
        future, floor = [], 0.0
    s, c = star(w), cap_eff(pv, cost) if pv > 0 else 0
    f = fyv(mw, p["age"], ptm, future, per_war)
    raw = pv - cost + s + c + f + p.get("premium", 0)
    surplus = max(raw, floor)
    if t == "OPT":  # option not yet exercised: holder can decline for free
        surplus = max(surplus, 0.0)
    return dict(name=p["name"], side=p["side"], type=t, war=round(w, 2), mwar=round(mw, 2), age=p["age"],
                pv=pv, cost=cost, star=s, cap=c, fyv=f, prem=p.get("premium", 0),
                raw=raw, floor=floor, surplus=surplus)


def table(rows, label):
    print(f"== {label}")
    hdr = f"{'Player':22}{'To':6}{'Ctr':5}{'WAR':>6}{'mWAR':>6}{'Age':>4}{'PV':>7}{'Cost':>6}{'Star':>6}{'CapE':>6}{'FYV':>6}{'Prem':>6}{'Raw':>7}{'Floor':>7}{'Surplus':>9}"
    print(hdr)
    for r in rows:
        print(f"{r['name'][:21]:22}{r['side']:6}{r['type']:5}{r['war']:6.2f}{r['mwar']:6.2f}{r['age']:4}"
              f"{r['pv']:7.1f}{r['cost']:6.1f}{r['star']:6.1f}{r['cap']:6.1f}{r['fyv']:6.1f}"
              f"{r['prem']:6.1f}{r['raw']:7.1f}{r['floor']:7.1f}{r['surplus']:9.1f}")
    tot = {s: sum(r["surplus"] for r in rows if r["side"] == s) for s in sorted({r["side"] for r in rows})}
    print("  " + " | ".join(f"{s} receives ${v:.1f}M" for s, v in tot.items()))
    print()
    return tot


def main(path, models=("legacy", "mwbl")):
    players = json.load(open(path))["players"]
    labels = {"legacy": f"LEGACY (2025 method, ${LEGACY_PER_WAR}M/WAR)",
              "mwbl": f"MWBL REPLACEMENT (mWAR, ${PER_WAR}M/mWAR; repl {REPL_H_PER_600PA}/600PA, {REPL_P_PER_180IP}/180IP)"}
    totals = {m: table([value(p, m) for p in players], labels[m]) for m in models}
    if len(models) == 2:
        print("Summary (surplus received):")
        for s in totals[models[0]]:
            print(f"  {s:6} legacy ${totals['legacy'][s]:6.1f}M   mWAR ${totals['mwbl'][s]:6.1f}M")


if __name__ == "__main__":
    # python3 score.py trade.json [legacy|mwbl]   (default: both)
    main(sys.argv[1], tuple(sys.argv[2:]) or ("legacy", "mwbl"))
