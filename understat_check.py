"""
understat_check.py — compare a fresh Understat download with the files in the
repo before copying it in.

  python understat_check.py --old data/2024-25/understat \
                            --new /tmp/us_test/2024-25/understat --season-year 2024

Checks
  1. Files: player files only in old / only in new, and the same Understat id
     under two different names (a renamed player -> duplicate file after copying)
  2. Existing rows unchanged: every match row in an old file is in the new file
     (same player id + match id) with the same values
  3. New rows: how many, and their date range (should be after the old data ended)
  4. Coverage of the season: EPL matches per month and in total (380 expected),
     counting a match once however many player files it appears in

Exit code 0 = safe to copy (no changed or lost rows), 1 = look at the report.
"""
import argparse, glob, os, re, sys
import numpy as np
import pandas as pd

KEY = ["id"]                        # Understat match id (one row per player per match)
NUM = ["goals", "shots", "xG", "time", "h_goals", "a_goals", "xA", "assists",
       "key_passes", "npg", "npxG", "xGChain", "xGBuildup", "season"]   # compared as numbers
TXT = ["position", "h_team", "a_team"]                                   # compared as text
# "date" is compared as a calendar date, so "2025-04-07" == "2025-04-07 19:00:00"


def player_files(folder):
    out = {}
    for f in glob.glob(os.path.join(folder, "*.csv")):
        m = re.match(r"(.+)_(\d+)\.csv$", os.path.basename(f))
        if m and not os.path.basename(f).startswith("understat_"):
            out.setdefault(m.group(2), []).append(f)
    return out


def read(f):
    df = pd.read_csv(f, low_memory=False)
    return df.drop_duplicates(KEY) if "id" in df else df


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--old", required=True); ap.add_argument("--new", required=True)
    ap.add_argument("--season-year", type=int, required=True, help="2024 for 2024-25")
    a = ap.parse_args(argv)
    old, new = player_files(a.old), player_files(a.new)
    problems = 0

    # 1. Files
    only_old = sorted(set(old) - set(new)); only_new = sorted(set(new) - set(old))
    renamed = [(i, [os.path.basename(x) for x in old[i]], [os.path.basename(x) for x in new[i]])
               for i in set(old) & set(new)
               if sorted(map(os.path.basename, old[i])) != sorted(map(os.path.basename, new[i]))]
    print(f"1. Player files: old {len(old)}, new {len(new)}, in both {len(set(old) & set(new))}")
    print(f"   only in old: {len(only_old)}   only in new: {len(only_new)}   same id, different name: {len(renamed)}")
    for i, o, n in renamed[:20]:
        print(f"     id {i}: {o} -> {n}")
    for i in only_old[:20]:
        print(f"     only in old: {[os.path.basename(x) for x in old[i]]}")

    # 2./3. Rows
    changed, lost, added, minfo = [], 0, [], {}
    for i in sorted(set(old) & set(new)):
        o = read(old[i][0]); n = read(new[i][0])
        for r in o[["id", "date", "h_team", "a_team"]].itertuples(index=False):
            minfo[r.id] = (str(r.date)[:10], r.h_team, r.a_team)
        j = o.merge(n, on=KEY, how="left", suffixes=("_o", "_n"), indicator=True)
        lost += int((j._merge == "left_only").sum())
        b = j[j._merge == "both"]
        for c in NUM:
            if c + "_o" in b and c + "_n" in b:
                x = pd.to_numeric(b[c + "_o"], errors="coerce"); y = pd.to_numeric(b[c + "_n"], errors="coerce")
                bad = ~(np.isclose(x, y, atol=1e-6, equal_nan=True))
                changed += [(i, r["id"], c, r[c + "_o"], r[c + "_n"]) for _, r in b[bad].iterrows()]
        for c in TXT:
            if c + "_o" in b and c + "_n" in b:
                bad = b[c + "_o"].astype(str) != b[c + "_n"].astype(str)
                changed += [(i, r["id"], c, r[c + "_o"], r[c + "_n"]) for _, r in b[bad].iterrows()]
        if "date_o" in b and "date_n" in b:
            bad = (pd.to_datetime(b["date_o"], errors="coerce").dt.date
                   != pd.to_datetime(b["date_n"], errors="coerce").dt.date)
            changed += [(i, r["id"], "date", r["date_o"], r["date_n"]) for _, r in b[bad].iterrows()]
        added.append(n[~n["id"].isin(o["id"])].assign(player_id=i))
    added = pd.concat(added) if added else pd.DataFrame()
    print(f"2. Existing rows: lost {lost}, changed values {len(changed)}")
    if changed:
        # Summary by match: were missing values (0) filled in, or did real values change?
        ch = pd.DataFrame(changed, columns=["player_id", "match_id", "column", "old", "new"])
        o_num = pd.to_numeric(ch.old, errors="coerce"); n_num = pd.to_numeric(ch.new, errors="coerce")
        ch["kind"] = np.select([(o_num == 0) & (n_num != 0), (o_num != 0) & (n_num == 0)],
                               ["0 -> value", "value -> 0"], "value -> other value")
        print("   by match (date, teams, players affected, changed values by kind):")
        for mid, g in ch.groupby("match_id"):
            d, h, aw = minfo.get(mid, ("?", "?", "?"))
            kinds = ", ".join(f"{k} {v}" for k, v in g.kind.value_counts().items())
            print(f"     match {mid} {d} {h} v {aw}: {g.player_id.nunique()} players; {kinds}")
        ch.to_csv("understat_changes.csv", index=False)
        print("   every changed value: understat_changes.csv")
    problems += lost + len(changed)
    if len(added):
        d = pd.to_datetime(added["date"])
        s = added[pd.to_numeric(added["season"], errors="coerce") == a.season_year]
        print(f"3. New rows: {len(added)} (dates {d.min().date()} to {d.max().date()}); "
              f"{len(s)} in season {a.season_year}, from {s['id'].nunique()} matches")
    else:
        print("3. New rows: none")

    # 4. Season coverage (EPL matches = matches between two clubs in understat_player.csv team list)
    for label, folder, files in [("old", a.old, old), ("new", a.new, new)]:
        teams = set()
        tp = os.path.join(folder, "understat_player.csv")
        if os.path.exists(tp):
            for t in pd.read_csv(tp).team_title.dropna():
                teams.update(x.strip() for x in str(t).split(","))
        rows = pd.concat([read(f[0])[["id", "date", "season", "h_team", "a_team"]] for f in files.values()])
        rows = rows[(pd.to_numeric(rows.season, errors="coerce") == a.season_year)
                    & rows.h_team.isin(teams) & rows.a_team.isin(teams)].drop_duplicates("id")
        by_month = pd.to_datetime(rows.date).dt.to_period("M").value_counts().sort_index()
        print(f"4. {label}: {len(rows)} EPL matches (380 expected), last {pd.to_datetime(rows.date).max().date()}  "
              + "  ".join(f"{k}:{v}" for k, v in by_month.items()))

    print("RESULT:", "OK to copy (no existing rows lost or changed)" if problems == 0
          else "CHECK the report before copying")
    return 0 if problems == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
