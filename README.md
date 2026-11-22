# mwbl-data

Reference data and scoring code for the Monte Ward Baseball League (MWBL) Claude skills
(`mwbl-trade-eval`, `mwbl-data`, `mwbl-rules`). Skills sync to Claude sessions as SKILL.md only,
so the data lives here and each skill downloads what it needs at the start of a session.

## Layout

```
<season>/            season = the MLB stats year (2026 stats → the 2027 sim disk)
  contracts.csv      MWBL roster + contracts, from the league player list
  roster-stats.csv   MLB stats carried on the player list (PA, OPS splits, IP, OPS-against splits)
  war.csv            FanGraphs WAR export (to add): ID, off_war, war, def
  defense.txt        DMB fielding ratings from the season disk (to add when the disk ships)
score.py             surplus value calculator (python3 score.py trade.json)
```

`ID` is the FanGraphs player ID (numeric for MLB players, `sa…` for minor leaguers) and is the
join key across every file.

## contracts.csv

`ID, Team, First, LAST, Name, playID, DOB, Type, YR, AMT, BatElig, PitchElig`

- `Type`: `LT`, `ML0`–`ML3`, `OPT` (option decision pending, due 12/31), `O1`, `O2`
- `YR`: LT years remaining; `AMT`: annual $M
- `Cap Charge (Team)` rows are dead cap from cuts, so skip them for player lookups

## Fetching from a skill

```bash
S=2026; B=https://raw.githubusercontent.com/deisjj/mwbl-data/main
mkdir -p mwbl && for f in contracts.csv roster-stats.csv war.csv defense.txt; do
  curl -sfL "$B/$S/$f" -o "mwbl/$f" || echo "missing: $f"; done
curl -sfL "$B/score.py" -o mwbl/score.py
```

## Season rollover checklist

1. Export the league player list after cuts/options → `<season>/contracts.csv` + `roster-stats.csv`
2. Export FanGraphs batting + pitching leaderboards (all players, min 0 PA/IP) → `war.csv`
3. Add the DMB disk fielding file → `defense.txt` (December release)
4. Bump `S=` in each SKILL.md
