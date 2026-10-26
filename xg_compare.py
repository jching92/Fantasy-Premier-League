"""
xg_compare.py — compare player xG between this fork and its upstream
(vaastav/Fantasy-Premier-League) for one season, gameweek by gameweek.

For each gameweek it reports:
  - rows, players (by FPL `code`) and clubs in each source
  - players present in only one source
  - a black-and-white scatter of player xG per fixture:
    upstream on the x-axis, this fork on the y-axis, with y = x dashed

NULL xG is treated as 0: the sources are OUTER-joined, so a player missing
from one source is plotted with xG 0 on that axis (and counted), and a blank
xG cell is also read as 0. No player drops out of the comparison.

Players are matched on (code, GW, fixture); `code` comes from each source's
own players_raw.csv (id -> code), so differing FPL ids don't matter.

Output (in --out):
  xg_compare_<season><tag>.pdf          summary page + one page per GW
  xg_compare_<season>_gwN<tag>.pdf       one PDF per GW
  xg_compare_<season>_summary<tag>.csv   the summary table
  xg_compare_<season>_mismatches<tag>.csv  players missing from one side or
                                         with xG off y = x (GWs in both)

Exit codes: 0 = sources agree on every GW present in both,
            2 = differences found (missing players/clubs or xG off y = x),
            1 = error (e.g. season folder missing).
A GW present in only one source (one repo ahead of the other) is reported
but is not counted as a difference.

Usage:
    python xg_compare.py --season 2026-27 --fork-dir . --upstream-dir upstream --out out
"""

import argparse, hashlib, os, sys

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages

plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 8})
TOL = 1e-6          # |xG fork - xG upstream| above this counts as off y = x
A4_LANDSCAPE = (11.69, 8.27)


def load(root: str, season: str) -> pd.DataFrame:
    gw_path  = os.path.join(root, "data", season, "gws", "merged_gw.csv")
    raw_path = os.path.join(root, "data", season, "players_raw.csv")
    m   = pd.read_csv(gw_path, low_memory=False)
    raw = pd.read_csv(raw_path, low_memory=False)
    m["code"] = m["element"].map(raw.set_index("id")["code"])
    unmapped = m["code"].isna().sum()
    if unmapped:
        print(f"WARNING: {root}: {unmapped} merged_gw rows have an element not in players_raw.csv")
    if "position" in m:
        m = m[m["position"] != "AM"]     # assistant-manager rows, if any
    return m[["code", "name", "team", "GW", "fixture", "minutes", "expected_goals"]]


def sha1(path: str) -> str:
    try:
        with open(path, "rb") as fh:
            return hashlib.sha1(fh.read()).hexdigest()
    except FileNotFoundError:
        return "missing"


def gw_page(season, g, up, fk, labels):
    a, b = up[up.GW == g], fk[fk.GW == g]
    j = a.merge(b, on=["code", "GW", "fixture"], how="outer",
                suffixes=("_u", "_f"), indicator=True)
    # NULL xG -> 0: covers a player missing from one source (outer join leaves
    # his xG NaN there) and a blank xG cell in a source that has the player.
    # So every player in either source is plotted and compared; none drop out.
    null_u = int(a.expected_goals.isna().sum()); null_f = int(b.expected_goals.isna().sum())
    j["xg_u"] = j.expected_goals_u.fillna(0.0)
    j["xg_f"] = j.expected_goals_f.fillna(0.0)
    j["who"]  = j.name_u.fillna(j.name_f)
    j["dxg"]  = (j.xg_f - j.xg_u).abs()
    both  = j[j._merge == "both"]
    onlyu = j[j._merge == "left_only"]
    onlyf = j[j._merge == "right_only"]
    off   = j[j.dxg > TOL]
    in_both_sources = len(a) > 0 and len(b) > 0
    r = dict(GW=g, rows_u=len(a), rows_f=len(b),
             players_u=a.code.nunique(), players_f=b.code.nunique(),
             clubs_u=a.team.nunique(), clubs_f=b.team.nunique(),
             only_u=len(onlyu), only_f=len(onlyf), null_xg_u=null_u, null_xg_f=null_f,
             matched=len(both),
             off_diag=len(off) if in_both_sources else 0,
             max_abs=float(j.dxg.max()) if in_both_sources and len(j) else np.nan,
             in_both=in_both_sources)

    # Rows for the mismatch CSV (only where both sources have this GW)
    mism = pd.DataFrame()
    if in_both_sources and len(off) + len(onlyu) + len(onlyf):
        x = pd.concat([onlyu, onlyf, off[off._merge == "both"]])
        mism = pd.DataFrame({
            "GW": g, "fixture": x.fixture, "code": x.code, "name": x.who,
            "team": x.team_u.fillna(x.team_f),
            f"xG_{labels[0]}": x.expected_goals_u, f"xG_{labels[1]}": x.expected_goals_f,
            f"xG_{labels[0]}_used": x.xg_u, f"xG_{labels[1]}_used": x.xg_f,
            "issue": np.select([x._merge == "left_only", x._merge == "right_only",
                                x.expected_goals_f.isna(), x.expected_goals_u.isna()],
                               [f"missing in {labels[1]} (xG taken as 0)",
                                f"missing in {labels[0]} (xG taken as 0)",
                                f"NULL xG in {labels[1]} (taken as 0)",
                                f"NULL xG in {labels[0]} (taken as 0)"], "xG off y=x")})

    fig = plt.figure(figsize=A4_LANDSCAPE)
    fig.suptitle(f"{season}  GW{g}  —  player xG per fixture: {labels[0]} (x) vs {labels[1]} (y)",
                 fontsize=12, fontweight="bold")
    ax = fig.add_axes([0.06, 0.1, 0.5, 0.78])
    if in_both_sources:
        m = max(j.xg_u.max(), j.xg_f.max(), 0.1) * 1.05
        ax.plot([0, m], [0, m], "k--", lw=0.8, label="y = x")
        ax.scatter(both.xg_u, both.xg_f, s=14, facecolors="none", edgecolors="black",
                   lw=0.6, label=f"in both sources (n={len(both)})")
        if len(onlyu):
            ax.scatter(onlyu.xg_u, onlyu.xg_f, s=40, marker="v", c="black",
                       label=f"missing in {labels[1]}, xG = 0 (n={len(onlyu)})")
        if len(onlyf):
            ax.scatter(onlyf.xg_u, onlyf.xg_f, s=40, marker="<", c="black",
                       label=f"missing in {labels[0]}, xG = 0 (n={len(onlyf)})")
        offb = off[off._merge == "both"]
        if len(offb):
            ax.scatter(offb.xg_u, offb.xg_f, s=40, marker="x", c="black", lw=1,
                       label=f"in both, xG off y = x (n={len(offb)})")
        for _, p in off.nlargest(10, "dxg").iterrows():
            ax.annotate(p.who, (p.xg_u, p.xg_f), fontsize=6)
        ax.set_xlim(-0.02, m); ax.set_ylim(-0.02, m)
        ax.legend(loc="upper left", frameon=False)
    else:
        missing = labels[0] if not len(a) else labels[1]
        ax.text(0.5, 0.5, f"No {missing} data for this GW\n(nothing to plot)",
                ha="center", va="center", transform=ax.transAxes, fontsize=12)
    ax.set_xlabel(f"xG — {labels[0]}"); ax.set_ylabel(f"xG — {labels[1]}")
    ax.set_aspect("equal", adjustable="box"); ax.grid(lw=0.3, color="0.8")

    tx = fig.add_axes([0.6, 0.1, 0.38, 0.78]); tx.axis("off")
    w = max(len(labels[0]), len(labels[1]))
    lines = [
        f"Rows (player-fixtures):  {labels[0]:<{w}} {r['rows_u']:>4}   {labels[1]:<{w}} {r['rows_f']:>4}",
        f"Players (by code):       {labels[0]:<{w}} {r['players_u']:>4}   {labels[1]:<{w}} {r['players_f']:>4}",
        f"Clubs:                   {labels[0]:<{w}} {r['clubs_u']:>4}   {labels[1]:<{w}} {r['clubs_f']:>4}",
        f"Only in {labels[0]}: {r['only_u']}   Only in {labels[1]}: {r['only_f']}",
        f"NULL xG cells (taken as 0): {labels[0]} {null_u}   {labels[1]} {null_f}",
        (f"Matched: {r['matched']}   xG off y=x: {r['off_diag']}   max |Δ xG|: {r['max_abs']:.3f}"
         if in_both_sources else "Matched: 0"),
    ]
    tx.text(0, 1, "\n".join(lines), va="top", family="DejaVu Sans Mono", fontsize=7.5)
    cu = a.groupby("team").code.nunique(); cf = b.groupby("team").code.nunique()
    ct = (pd.concat([cu.rename(labels[0]), cf.rename(labels[1])], axis=1)
            .fillna(0).astype(int))
    ct["diff"] = ct[labels[1]] - ct[labels[0]]
    if len(ct):
        tbl = tx.table(cellText=[[t, *map(str, x)] for t, x in zip(ct.index, ct.values)],
                       colLabels=["Club", labels[0], labels[1], "diff"],
                       loc="upper left", bbox=[0, 0.0, 1, 0.8], cellLoc="center")
        tbl.auto_set_font_size(False); tbl.set_fontsize(7)
        for (i, _), c in tbl.get_celld().items():
            c.set_edgecolor("0.6"); c.set_linewidth(0.4)
            if i == 0 or (in_both_sources and ct["diff"].iloc[i - 1] != 0):
                c.set_text_props(fontweight="bold")
    tx.text(0, 0.815, "Players per club (by code)", fontweight="bold", fontsize=8)
    if in_both_sources and 0 < (r["only_u"] + r["only_f"]) <= 15:
        miss = j[j._merge != "both"]
        tx.text(0, -0.04, "Missing: " + "; ".join(
            f"{x.who} "
            f"(not in {labels[1] if x._merge == 'left_only' else labels[0]})"
            for _, x in miss.iterrows()), fontsize=6, wrap=True, va="top")
    return fig, r, mism


def summary_page(season, rows, labels, note):
    fig = plt.figure(figsize=A4_LANDSCAPE)
    fig.suptitle(f"{season}  —  xG data comparison summary: {labels[0]} vs {labels[1]}",
                 fontsize=13, fontweight="bold")
    cols = ["GW", "rows_u", "rows_f", "players_u", "players_f", "clubs_u", "clubs_f",
            "only_u", "only_f", "matched", "off_diag", "max_abs"]
    hdr  = ["GW", f"Rows\n{labels[0]}", f"Rows\n{labels[1]}", f"Players\n{labels[0]}",
            f"Players\n{labels[1]}", f"Clubs\n{labels[0]}", f"Clubs\n{labels[1]}",
            f"Only in\n{labels[0]}", f"Only in\n{labels[1]}", "Matched", "xG off\ny=x", "max\n|Δ xG|"]
    n = len(rows)
    # Row height shrinks so up to 38 GWs (+ a note) fit on one page
    table_h = min(0.72, 0.06 * (n + 1))
    ax = fig.add_axes([0.04, 0.88 - table_h, 0.92, table_h]); ax.axis("off")
    cell = [[("—" if pd.isna(r[c]) else f"{r[c]:.3f}") if c == "max_abs" else str(int(r[c]))
             for c in cols] for r in rows]
    t = ax.table(cellText=cell, colLabels=hdr, loc="upper center", cellLoc="center",
                 bbox=[0, 0, 1, 1])
    t.auto_set_font_size(False); t.set_fontsize(7 if n > 20 else 8)
    for (i, _), c in t.get_celld().items():
        c.set_edgecolor("0.6"); c.set_linewidth(0.4)
        if i == 0:
            c.set_text_props(fontweight="bold")
        elif rows[i - 1]["in_both"] and (rows[i - 1]["only_u"] or rows[i - 1]["only_f"]
                                         or rows[i - 1]["off_diag"]):
            c.set_text_props(fontweight="bold")
    fig.text(0.04, 0.86 - table_h - 0.02, note, fontsize=7.5, va="top", wrap=True)
    return fig


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--season", required=True, help="e.g. 2026-27")
    ap.add_argument("--fork-dir", default=".", help="root of this fork (contains data/)")
    ap.add_argument("--upstream-dir", required=True, help="root of the upstream clone (contains data/)")
    ap.add_argument("--out", default="xg_compare_output")
    ap.add_argument("--fork-label", default="jching92")
    ap.add_argument("--upstream-label", default="vaastav")
    ap.add_argument("--tag", default="", help="suffix added to every file name, e.g. _20261026152500")
    ap.add_argument("--note", default="", help="extra text for the summary page (e.g. commit ids)")
    args = ap.parse_args(argv)

    S, labels = args.season, (args.upstream_label, args.fork_label)
    for root in (args.upstream_dir, args.fork_dir):
        if not os.path.isfile(os.path.join(root, "data", S, "gws", "merged_gw.csv")):
            print(f"ERROR: {root}/data/{S}/gws/merged_gw.csv not found")
            return 1
    up, fk = load(args.upstream_dir, S), load(args.fork_dir, S)
    os.makedirs(args.out, exist_ok=True)

    same = {f: sha1(os.path.join(args.upstream_dir, "data", S, f)) == sha1(os.path.join(args.fork_dir, "data", S, f))
            for f in ("gws/merged_gw.csv", "players_raw.csv")}
    rows, mism, figs = [], [], []
    for g in sorted(set(up.GW) | set(fk.GW)):
        fig, r, mm = gw_page(S, g, up, fk, labels)
        rows.append(r); mism.append(mm); figs.append(fig)
        fig.savefig(os.path.join(args.out, f"xg_compare_{S}_gw{g}{args.tag}.pdf"))

    ahead_f = [r["GW"] for r in rows if not r["in_both"] and r["rows_f"]]
    ahead_u = [r["GW"] for r in rows if not r["in_both"] and r["rows_u"]]
    diff_gws = [r["GW"] for r in rows if r["in_both"] and (r["only_u"] or r["only_f"] or r["off_diag"])]
    note = "\n".join(filter(None, [
        args.note,
        f"Players keyed by FPL 'code' (players_raw id -> code), matched on (code, GW, fixture). "
        f"NULL xG (a blank cell, or a player missing from one source) is taken as 0, so every player in either "
        f"source is compared. 'Off y=x' = |xG {labels[1]} - xG {labels[0]}| > {TOL:g} after that.",
        "File identity: " + ", ".join(f"{f} {'identical' if s else 'different'}" for f, s in same.items()) + ".",
        f"GWs only in {labels[1]}: {ahead_f}" if ahead_f else "",
        f"GWs only in {labels[0]}: {ahead_u}" if ahead_u else "",
        (f"RESULT: differences in GW {diff_gws} (bold rows)." if diff_gws
         else "RESULT: every GW present in both sources matches (players, clubs and xG)."),
    ]))
    with PdfPages(os.path.join(args.out, f"xg_compare_{S}{args.tag}.pdf")) as pdf:
        pdf.savefig(summary_page(S, rows, labels, note))
        for fg in figs:
            pdf.savefig(fg); plt.close(fg)

    summ = pd.DataFrame(rows).rename(columns=lambda c: c.replace("_u", f"_{labels[0]}").replace("_f", f"_{labels[1]}")
                                     if c != "off_diag" else c)
    summ.to_csv(os.path.join(args.out, f"xg_compare_{S}_summary{args.tag}.csv"), index=False)
    mism_df = pd.concat([m for m in mism if len(m)]) if any(len(m) for m in mism) else pd.DataFrame(
        columns=["GW", "fixture", "code", "name", "team", f"xG_{labels[0]}", f"xG_{labels[1]}", "issue"])
    mism_df.to_csv(os.path.join(args.out, f"xg_compare_{S}_mismatches{args.tag}.csv"), index=False)

    print(summ.drop(columns=["in_both"]).to_string(index=False))
    print(note)
    return 2 if diff_gws else 0


if __name__ == "__main__":
    sys.exit(main())
