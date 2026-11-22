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
  pos                   position he'll play (c, 1b, 2b, 3b, ss, lf, cf, rf, dh)
  ratings               hitters: DMB ratings by position, e.g. {"2b": "Vg/193", "3b": "Vg/157"}.
                        Fielding comes from the Flood013 DMB defense study (dmb/defense_study.json):
                        runs saved when a player rated at X plays `pos`, best rated position wins.
                        Omit to use range/err as an in-position rating at `pos`; {} = unrated.
  range, err            shorthand for ratings = {pos: "range/err"}
  arm                   OF arm (LF/CF/RF) or catcher throwing arm; pb = catcher passed-ball rating
  pos_runs              hitters: war.csv `fg_pos_runs` (FanGraphs Positional runs he actually earned).
                        When given, the positional adjustment is re-based to `pos` (DH included).
  mlb_track             ML players: true if past prospect status (150+ PA or 50+ IP in MLB);
                        defaults from pa/ip. These get Future Year Value for remaining control.
  bats, pa_vr, ops_vr, pa_vl, ops_vl     hitter platoon inputs
  premium               prospect premium $M (ML players), default 0
"""
import json, os, sys

# Default: two market rates on two WAR scales, side by side.
#   mlb:    WAR above MLB replacement (FanGraphs WAR, DMB fielding centered at Av=0) at MLB_PER_WAR
#   mwbl:   WAR above MWBL replacement (mWAR) at PER_WAR
# Optional: legacy = the 2025 method (offense above average + DMB range Av=+1) at LEGACY_PER_WAR.
MLB_PER_WAR = 2.0
PER_WAR = 4.5   # $M per mWAR; league LT contracts pay ~$4.7M (2026 rosters)
LEGACY_PER_WAR = 2.0
# Star Bonus multiplier on the MWBL scale. At $4.5M/mWAR, production value already pays
# stars most of what the full bonus covered at $2M/WAR, so the bonus is cut to ~$2/$4.5.
STAR_SCALE_MWBL = 0.4
# MWBL replacement level (24 x 26 = 624th-best MLB player, as a rate). Recompute each
# offseason with tools/replacement.py (rate at which 312 hitters / 312 pitchers are above it).
REPL_H_PER_600PA = 1.05
REPL_P_PER_180IP = 1.48
RANGE = {"Pr": -2, "Fr": -1, "Av": 0, "Vg": 1, "Ex": 2}  # centered: Av = average fielder
LEGACY_RANGE = {"Pr": -1, "Fr": 0, "Av": 1, "Vg": 2, "Ex": 3}
# FanGraphs positional adjustment, runs per full season (~650 PA); RUNS_PER_WIN from the 2026 Value tab
POS_RUNS = {"c": 12.5, "ss": 7.5, "2b": 2.5, "3b": 2.5, "cf": 2.5, "lf": -7.5, "rf": -7.5, "1b": -12.5, "dh": -17.5}
RUNS_PER_WIN = 9.83
# Defense study runs are neutral era (~4.8 R/G); scale toward modern scoring (~4.45 R/G).
DMB_ERA_SCALE = 0.93
_STUDY_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dmb", "defense_study.json")
STUDY = json.load(open(_STUDY_PATH)) if os.path.exists(_STUDY_PATH) else None
_ERRS = [0, 25, 50, 75, 100, 125, 150, 175, 200]


def _runs_at(played, rated, rng, err):
    row = STUDY["played"][played]["by_rated"][rated][rng]
    ys = [row[str(e)] for e in _ERRS]
    err = max(0.0, min(float(err), 300.0))
    if err >= 200:  # extrapolate the last segment
        return ys[-1] + (ys[-1] - ys[-2]) * (err - 200) / 25
    i = int(err // 25)
    return ys[i] + (ys[i + 1] - ys[i]) * (err - _ERRS[i]) / 25


def dmb_fielding_runs(p):
    """Runs saved per full season vs an Av/100 fielder at the played position."""
    pos = p.get("pos", "").lower()
    if not pos or pos == "dh" or STUDY is None:
        return 0.0
    ratings = p.get("ratings")
    if ratings is None:
        ratings = {pos: f"{p['range']}/{p.get('err', 100)}"} if p.get("range") else {}
    table = STUDY["played"][pos]
    vals = []
    for rp, rt in ratings.items():
        rp = rp.lower()
        if rp not in table["by_rated"]:
            continue
        rng, _, err = str(rt).partition("/")
        vals.append(_runs_at(pos, rp, rng.capitalize(), err or 100))
    runs = max(vals) if vals else table["unrated"]
    arm = p.get("arm")
    if pos in ("lf", "cf", "rf") and arm:
        runs += STUDY["arm"]["of"][pos].get(arm.capitalize(), 0)
    if pos == "c" and "c" in {k.lower() for k in ratings}:
        if arm:
            runs += STUDY["arm"]["c"].get(arm.capitalize(), 0)
        if "pb" in p:
            runs += STUDY["passed_balls"].get(str(min(int(p["pb"]), 9)), 0)
    return runs


def dmb_fielding_war(p):
    return dmb_fielding_runs(p) * p.get("pa", 0) / 650 * DMB_ERA_SCALE / RUNS_PER_WIN
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


def pos_adj(p):
    """Re-base the positional adjustment in base_war to the position he'll actually play."""
    pos = p.get("pos", "").lower()
    if "pos_runs" not in p or pos not in POS_RUNS:
        return 0.0
    target = POS_RUNS[pos] * p.get("pa", 0) / 650
    return (target - p["pos_runs"]) / RUNS_PER_WIN


def mlb_war(p, model="mwbl"):
    """Total WAR before any MWBL replacement adjustment (used for Star Bonus tiers)."""
    if p["role"] == "P":
        return p["war"]
    if "total_war" in p:
        return p["total_war"]
    if model == "legacy":
        return p["off_war"] + fielding(p, LEGACY_RANGE) + platoon(p)
    fld = dmb_fielding_war(p) if STUDY is not None else fielding(p)
    return p["base_war"] + pos_adj(p) + fld + platoon(p)


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


def fyv(w, age, ptm, years, per_war):
    """years: [(cost, committed)] for years 2..N. Committed years (LT salary) still cost the
    cap when production falls short, so a bad year counts as max(PV, 0) - cost, undiscounted.
    Optional years (ML, O1/O2 options) are declined or cut for free, so they floor at 0."""
    total, wk = 0.0, w
    for i, (cost, committed) in enumerate(years):
        k = i + 2
        wk += age_delta(age + k - 2)
        pv = wk * per_war * ptm
        net = pv - cost
        if net >= 0:
            total += net * 0.85 ** (k - 1)
        elif committed:
            total += max(pv, 0.0) - cost
    return total


def value(p, model="mwbl"):
    t = p["type"].upper()
    w, ptm = mlb_war(p, model), pt_mult(p)
    if model == "legacy":
        mw, per_war = w, LEGACY_PER_WAR
    elif model == "mlb":
        mw, per_war = w, MLB_PER_WAR
    else:
        mw, per_war = mwbl_war(p, w), PER_WAR
    pv = mw * per_war * ptm
    if t == "LT":
        n, amt = int(p["yr"]), float(p["amt"])
        cost, future, floor = amt, [(amt, True)] * (n - 1), -amt * n
    elif t in ("O1", "OPT"):
        cost, future, floor = 3.0, [(5.0, False)], -8.0
    elif t == "O2":
        cost, future, floor = 5.0, [], -5.0
    else:  # ML0-ML3: cheap control, then optional O1 ($3M) and O2 ($5M)
        lvl = int(t[2])
        cost, floor = (0.0 if lvl == 0 else 0.2), 0.0
        track = p.get("mlb_track", p.get("pa", 0) >= 150 or p.get("ip", 0) >= 50)
        future = ([(0.2, False)] * (3 - lvl) + [(3.0, False), (5.0, False)]) if track else []
    s = star(w) * (STAR_SCALE_MWBL if model == "mwbl" else 1.0)
    c = cap_eff(pv, cost) if pv > 0 else 0
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


def main(path, models=("mlb", "mwbl")):
    players = json.load(open(path))["players"]
    labels = {"mlb": f"MLB SCALE (WAR above MLB replacement, ${MLB_PER_WAR}M/WAR)",
              "mwbl": f"MWBL SCALE (WAR above MWBL replacement, ${PER_WAR}M/mWAR; repl {REPL_H_PER_600PA}/600PA, {REPL_P_PER_180IP}/180IP; star x{STAR_SCALE_MWBL})",
              "legacy": f"LEGACY (2025 method, ${LEGACY_PER_WAR}M/WAR)"}
    totals = {m: table([value(p, m) for p in players], labels[m]) for m in models}
    if len(models) > 1:
        print("Summary (surplus received):")
        for s in totals[models[0]]:
            print("  " + f"{s:6}" + "   ".join(f"{m} ${totals[m][s]:6.1f}M" for m in models))


if __name__ == "__main__":
    # python3 score.py trade.json [mlb] [mwbl] [legacy]   (default: mlb mwbl)
    main(sys.argv[1], tuple(sys.argv[2:]) or ("mlb", "mwbl"))
