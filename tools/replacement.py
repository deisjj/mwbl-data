#!/usr/bin/env python3
"""MWBL replacement level: 24 teams x 26 active spots (13 hitters + 13 pitchers).

Finds the per-playing-time rate r at which exactly 24*13 = 312 MLB hitters (and 312
pitchers) are above replacement, i.e. WAR - r * PT > 0 with PT = PA/600 or IP/180.
The 312th player is then the MWBL replacement player. Rate-based, so ties among
low-WAR part-timers don't move it.

    python3 tools/replacement.py 2026/fg_war_leaderboard.csv
Paste the printed rates into score.py.
"""
import csv, sys
SLOTS = 24 * 13


def ip(x):
    if not x: return 0.0
    a, _, b = x.partition('.')
    return int(a) + (int(b) / 3 if b else 0)


H, P = [], []
for r in csv.DictReader(open(sys.argv[1])):
    f = lambda k: float(r[k]) if r[k] else 0.0
    pa, inn = float(r['PA'] or 0), ip(r['IP'])
    if pa: H.append((f('bat_war'), pa / 600))
    if inn: P.append((f('pit_war'), inn / 180))


def rate(players):
    lo, hi = -5.0, 10.0
    for _ in range(60):
        mid = (lo + hi) / 2
        above = sum(1 for w, pt in players if w - mid * pt > 0)
        lo, hi = (mid, hi) if above > SLOTS else (lo, mid)
    return (lo + hi) / 2


print(f"REPL_H_PER_600PA = {rate(H):.2f}   # {len(H)} hitters")
print(f"REPL_P_PER_180IP = {rate(P):.2f}   # {len(P)} pitchers")
