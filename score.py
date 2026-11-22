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
  war                   pitchers: WAR. hitters: either total_war, or off_war plus
                        the defense/platoon fields below
  off_war, pos, range, err, arm          hitter defense (pos lowercase, range Pr..Ex)
  bats, pa_vr, ops_vr, pa_vl, ops_vl     hitter platoon inputs
  premium               prospect premium $M (ML players), default 0
"""
import json, sys

PER_WAR = 2.0
RANGE = {"Pr": -1, "Fr": 0, "Av": 1, "Vg": 2, "Ex": 3}
ARM = {"Pr": -1, "Fr": -0.5, "Av": 0, "Vg": 0.5, "Ex": 1}
ERR_W = {"c": .5, "1b": .4, "2b": .5, "3b": .8, "ss": .8, "lf": .2, "cf": .2, "rf": .2}
F_DMB = {("L", "R"): .85, ("L", "L"): .40, ("R", "L"): .45, ("R", "R"): .80,
         ("S", "R"): .80, ("S", "L"): .40}


def fielding(p):
    pos = p.get("pos", "").lower()
    if not pos or pos == "dh":
        return 0.0
    rng = 0 if pos == "c" else RANGE.get(p.get("range"), 0)
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


def total_war(p):
    if p["role"] == "P":
        return p["war"]
    if "total_war" in p:
        return p["total_war"]
    return p["off_war"] + fielding(p) + platoon(p)


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


def fyv(w, age, ptm, year_costs):
    """year_costs: costs for years 2..N."""
    total, wk = 0.0, w
    for i, cost in enumerate(year_costs):
        k = i + 2
        wk += age_delta(age + k - 2)
        total += max(0.0, (wk * PER_WAR * ptm - cost) * 0.85 ** (k - 1))
    return total


def value(p):
    t = p["type"].upper()
    w, ptm = total_war(p), pt_mult(p)
    pv = w * PER_WAR * ptm
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
    f = fyv(w, p["age"], ptm, future)
    raw = pv - cost + s + c + f + p.get("premium", 0)
    surplus = max(raw, floor)
    if t == "OPT":  # option not yet exercised: holder can decline for free
        surplus = max(surplus, 0.0)
    return dict(name=p["name"], side=p["side"], type=t, war=round(w, 2), age=p["age"],
                pv=pv, cost=cost, star=s, cap=c, fyv=f, prem=p.get("premium", 0),
                raw=raw, floor=floor, surplus=surplus)


def main(path):
    rows = [value(p) for p in json.load(open(path))["players"]]
    hdr = f"{'Player':22}{'To':6}{'Ctr':5}{'WAR':>6}{'Age':>4}{'PV':>7}{'Cost':>6}{'Star':>6}{'CapE':>6}{'FYV':>6}{'Prem':>6}{'Raw':>7}{'Floor':>7}{'Surplus':>9}"
    print(hdr)
    for r in rows:
        print(f"{r['name'][:21]:22}{r['side']:6}{r['type']:5}{r['war']:6.2f}{r['age']:4}"
              f"{r['pv']:7.1f}{r['cost']:6.1f}{r['star']:6.1f}{r['cap']:6.1f}{r['fyv']:6.1f}"
              f"{r['prem']:6.1f}{r['raw']:7.1f}{r['floor']:7.1f}{r['surplus']:9.1f}")
    print()
    for side in sorted({r["side"] for r in rows}):
        print(f"{side} receives: ${sum(r['surplus'] for r in rows if r['side'] == side):.1f}M")


if __name__ == "__main__":
    main(sys.argv[1])
