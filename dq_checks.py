"""FPL data quality checks for one season's gws/ folder.

Every check (phase) runs once per gameweek, so a failure points at the GW
that caused it. Optionally writes one JUnit XML file per gameweek
(season<season>_gw<NN>.xml) for Jenkins.

Phases (per gameweek j):
   1. Full-row duplicates in gw{j}.csv, xP{j}.csv and merged_gw.csv[GW=j]
   2. merged_gw.csv: no team with two opponents at the same kickoff time
   3. gw{j}.csv: exactly 20 team-opponent rows, one opponent per team
   4. gw{j}.csv and xP{j}.csv both exist
   5. merged_gw.csv[GW=j] has the same row count as gw{j}.csv
   6. No duplicate (element, fixture) rows
   7. GW j present in gw{j}.csv and merged_gw.csv
   8. No players with position UNK
   9. No team xG above MAX_TEAM_XG in a single fixture
  10. Player goals + opponent own goals reconcile with the final score

Usage:
  python dq_checks.py data/2026-27/gws
  python dq_checks.py data/2026-27/gws --gw 8
  python dq_checks.py data/2026-27/gws --junit-dir results/2026-27
  python dq_checks.py data/2026-27/gws -o duplicates.csv

Exit code 0 when every check passes, 1 otherwise.
"""
import argparse
import os
import re
import sys
import time
import xml.etree.ElementTree as ET

import pandas as pd

MAX_TEAM_XG = 6.0  # max plausible team xG in a single fixture
EXPECTED_TEAM_ROWS = 20  # team-opponent pairs per gameweek (Phase 3)

PASS, FAIL, SKIP = "pass", "fail", "skip"


# ── Data access ──────────────────────────────────────────────────────────────


class SeasonData:
  """Lazily loads the CSVs in a season's gws/ folder."""

  def __init__(self, folder_path):
    self.folder = folder_path
    self.gw_files, self.xp_files = {}, {}
    for filename in os.listdir(folder_path):
      m_gw = re.match(r"^gw(\d+)\.csv$", filename)
      if m_gw:
        self.gw_files[int(m_gw.group(1))] = filename
      m_xp = re.match(r"^xP(\d+)\.csv$", filename)
      if m_xp:
        self.xp_files[int(m_xp.group(1))] = filename

    self._cache = {}
    self.merged_path = os.path.join(folder_path, "merged_gw.csv")
    self.merged = None
    if os.path.exists(self.merged_path):
      self.merged = pd.read_csv(self.merged_path, low_memory=False)
      if "GW" in self.merged.columns:
        self.merged["GW"] = pd.to_numeric(self.merged["GW"], errors="coerce")

  def _read(self, filename):
    if filename not in self._cache:
      self._cache[filename] = pd.read_csv(
          os.path.join(self.folder, filename), low_memory=False
      )
    return self._cache[filename]

  def gw(self, gw):
    filename = self.gw_files.get(gw)
    return self._read(filename) if filename else None

  def xp(self, gw):
    filename = self.xp_files.get(gw)
    return self._read(filename) if filename else None

  def merged_for(self, gw):
    """Rows of merged_gw.csv for this GW (empty if absent), None if no file."""
    if self.merged is None or "GW" not in self.merged.columns:
      return None
    return self.merged[self.merged["GW"] == gw]

  def gameweeks(self, expected_gw=None):
    gws = set(self.gw_files) | set(self.xp_files)
    if self.merged is not None and "GW" in self.merged.columns:
      gws |= set(int(g) for g in self.merged["GW"].dropna().unique())
    if expected_gw:
      gws |= set(range(1, expected_gw + 1))
    return sorted(gws)


def _frames(data, gw):
  """(label, DataFrame) for gw{j}.csv and merged_gw.csv[GW=j], when present."""
  frames = []
  df = data.gw(gw)
  if df is not None:
    frames.append((f"gw{gw}.csv", df))
  merged = data.merged_for(gw)
  if merged is not None and not merged.empty:
    frames.append((f"merged_gw.csv[GW={gw}]", merged))
  return frames


def _is_home(series):
  """was_home as a bool Series, whether pandas read it as bool or as text."""
  return series.astype(str).str.lower() == "true"


def _missing(df, cols):
  return [c for c in cols if c not in df.columns]


# ── Phases ───────────────────────────────────────────────────────────────────
# Each takes (data, gw, export) and returns (status, [detail lines]).


def check_full_row_duplicates(data, gw, export):
  targets = _frames(data, gw)
  if data.xp(gw) is not None:
    targets.insert(1, (f"xP{gw}.csv", data.xp(gw)))
  if not targets:
    return SKIP, [f"No files for GW{gw} (see phase 07)"]

  details, failed = [], False
  for label, df in targets:
    dupes = df[df.duplicated(keep=False)]
    if dupes.empty:
      details.append(f"{label}: no full-row duplicates")
    else:
      failed = True
      details.append(f"{label}: {len(dupes)} duplicate rows")
      if export is not None:
        export.append(dupes.assign(source_file=label))
  return (FAIL if failed else PASS), details


def check_merged_fixture_conflicts(data, gw, export):
  merged = data.merged_for(gw)
  if merged is None:
    return FAIL, ["merged_gw.csv not found or has no GW column"]
  if merged.empty:
    return SKIP, [f"GW{gw} not in merged_gw.csv (see phase 07)"]
  missing = _missing(merged, ["team", "kickoff_time", "opponent_team"])
  if missing:
    return FAIL, [f"merged_gw.csv missing columns {missing}"]

  grouped = (
      merged.groupby(["team", "kickoff_time"])["opponent_team"]
      .nunique()
      .reset_index(name="unique_opponents")
  )
  conflicts = grouped[grouped["unique_opponents"] > 1]
  if conflicts.empty:
    return PASS, ["No team has two opponents at the same kickoff time"]
  return FAIL, [
      f"{len(conflicts)} fixture conflict(s) (multiple opponents at the same"
      " kickoff time):",
      conflicts.to_string(index=False),
  ]


def check_gw_fixture_logic(data, gw, export):
  df = data.gw(gw)
  if df is None:
    return SKIP, [f"gw{gw}.csv not found (see phase 07)"]
  missing = _missing(df, ["team", "opponent_team"])
  if missing:
    return SKIP, [f"gw{gw}.csv missing columns {missing}"]

  team_opp = df[["team", "opponent_team"]].drop_duplicates()
  details, failed = [], False

  # Rule A: exactly 20 team-opponent rows (assumes no blank/double GW)
  if len(team_opp) != EXPECTED_TEAM_ROWS:
    failed = True
    details.append(
        f"Expected {EXPECTED_TEAM_ROWS} team-opponent rows, found"
        f" {len(team_opp)}"
    )
  # Rule B: one opponent per team
  counts = team_opp.groupby("team")["opponent_team"].nunique()
  invalid = counts[counts != 1]
  if not invalid.empty:
    failed = True
    details.append(f"Teams with != 1 opponent: {invalid.to_dict()}")

  if not failed:
    details.append(f"{len(team_opp)} team-opponent rows, one opponent each")
  return (FAIL if failed else PASS), details


def check_gw_xp_pairing(data, gw, export):
  has_gw, has_xp = gw in data.gw_files, gw in data.xp_files
  if has_gw and has_xp:
    return PASS, [f"gw{gw}.csv and xP{gw}.csv both present"]
  if has_gw:
    return FAIL, [f"gw{gw}.csv exists but xP{gw}.csv is missing"]
  if has_xp:
    return FAIL, [f"xP{gw}.csv exists but gw{gw}.csv is missing"]
  return FAIL, [f"Neither gw{gw}.csv nor xP{gw}.csv exists"]


def check_merged_row_count(data, gw, export):
  df, merged = data.gw(gw), data.merged_for(gw)
  if df is None or merged is None:
    return SKIP, ["gw file or merged_gw.csv missing (see phase 07)"]
  if len(df) != len(merged):
    return FAIL, [
        f"merged_gw.csv has {len(merged)} rows for GW{gw}, gw{gw}.csv has"
        f" {len(df)}"
    ]
  return PASS, [f"{len(df)} rows in both gw{gw}.csv and merged_gw.csv"]


def check_player_fixture_duplicates(data, gw, export):
  # Catches near-duplicates that phase 01 misses (rows identical apart from
  # e.g. 'selected'), with no false positives for namesakes or double GWs.
  frames = _frames(data, gw)
  if not frames:
    return SKIP, [f"No data for GW{gw} (see phase 07)"]

  details, failed = [], False
  for label, df in frames:
    missing = _missing(df, ["element", "fixture"])
    if missing:
      failed = True
      details.append(f"{label}: missing columns {missing}")
      continue
    dupes = df[df.duplicated(subset=["element", "fixture"], keep=False)]
    if dupes.empty:
      details.append(f"{label}: no duplicate (element, fixture) rows")
    else:
      failed = True
      cols = [c for c in ["name", "element", "fixture", "team"] if c in df]
      details.append(f"{label}: {len(dupes)} rows share an (element, fixture)")
      details.append(dupes[cols].head(10).to_string(index=False))
  return (FAIL if failed else PASS), details


def check_gw_present(data, gw, export):
  details = []
  if gw not in data.gw_files:
    details.append(f"gw{gw}.csv is missing")
  merged = data.merged_for(gw)
  if merged is None:
    details.append("merged_gw.csv not found or has no GW column")
  elif merged.empty:
    details.append(f"merged_gw.csv has no rows for GW{gw}")
  if details:
    return FAIL, details
  return PASS, [f"GW{gw} present in gw{gw}.csv and merged_gw.csv"]


def check_unknown_positions(data, gw, export):
  # collector.collect_gw() writes 'UNK' for a player missing from
  # players_raw.csv (e.g. a mid-season debut that was never refreshed).
  frames = [(l, df) for l, df in _frames(data, gw) if "position" in df.columns]
  if not frames:
    return SKIP, ["No position column to check"]

  details, failed = [], False
  for label, df in frames:
    unk = df[df["position"] == "UNK"]
    if unk.empty:
      details.append(f"{label}: all positions known")
    else:
      failed = True
      cols = [c for c in ["name", "element", "team"] if c in df.columns]
      details.append(f"{label}: {len(unk)} rows with position UNK")
      details.append(unk[cols].drop_duplicates().to_string(index=False))
  return (FAIL if failed else PASS), details


def check_team_xg_sanity(data, gw, export):
  # Summed per fixture so double GWs aren't added together; duplicates are
  # deliberately NOT dropped first, as they are what this looks for.
  frames = [
      (l, df) for l, df in _frames(data, gw)
      if not _missing(df, ["fixture", "team", "expected_goals"])
  ]
  if not frames:
    return SKIP, ["No expected_goals data to check"]

  details, failed = [], False
  for label, df in frames:
    team_xg = df.groupby(["fixture", "team"])["expected_goals"].sum()
    suspect = team_xg[team_xg > MAX_TEAM_XG]
    if suspect.empty:
      details.append(
          f"{label}: max team xG {team_xg.max():.2f} (threshold {MAX_TEAM_XG})"
      )
    else:
      failed = True
      details.append(f"{label}: {len(suspect)} team xG totals > {MAX_TEAM_XG}")
      details.append(suspect.reset_index().to_string(index=False))
  return (FAIL if failed else PASS), details


def check_score_reconciliation(data, gw, export):
  # Home score = home goals_scored + away own_goals, and vice versa. A
  # mismatch means missing or duplicated player rows.
  required = ["fixture", "was_home", "goals_scored", "own_goals",
              "team_h_score", "team_a_score"]
  frames = [(l, df) for l, df in _frames(data, gw) if not _missing(df, required)]
  if not frames:
    return SKIP, ["Columns needed for score reconciliation not present"]

  details, failed, any_played = [], False, False
  for label, df in frames:
    home_mask = _is_home(df["was_home"])
    mismatches, checked = [], 0
    for fixture, d in df.groupby("fixture"):
      h_score, a_score = d["team_h_score"].iloc[0], d["team_a_score"].iloc[0]
      if pd.isna(h_score) or pd.isna(a_score):
        continue  # not played yet
      home, away = d[home_mask.loc[d.index]], d[~home_mask.loc[d.index]]
      calc_h = home["goals_scored"].sum() + away["own_goals"].sum()
      calc_a = away["goals_scored"].sum() + home["own_goals"].sum()
      checked += 1
      if calc_h != h_score or calc_a != a_score:
        h_team = home["team"].iloc[0] if not home.empty else "?"
        a_team = away["team"].iloc[0] if not away.empty else "?"
        mismatches.append(
            f"  fixture {fixture}: {h_team} {int(h_score)}-{int(a_score)}"
            f" {a_team} -> player rows give {int(calc_h)}-{int(calc_a)}"
        )
    any_played = any_played or checked > 0
    if mismatches:
      failed = True
      details.append(f"{label}: {len(mismatches)} of {checked} fixtures"
                     " don't reconcile")
      details.extend(mismatches)
    else:
      details.append(f"{label}: {checked} played fixtures reconcile")

  if not failed and not any_played:
    return SKIP, [f"No played fixtures in GW{gw} yet"]
  return (FAIL if failed else PASS), details


PHASES = [
    ("01", "full_row_duplicates", check_full_row_duplicates),
    ("02", "merged_fixture_conflicts", check_merged_fixture_conflicts),
    ("03", "gw_fixture_logic", check_gw_fixture_logic),
    ("04", "gw_xp_pairing", check_gw_xp_pairing),
    ("05", "merged_row_count", check_merged_row_count),
    ("06", "player_fixture_duplicates", check_player_fixture_duplicates),
    ("07", "gw_present", check_gw_present),
    ("08", "unknown_positions", check_unknown_positions),
    ("09", "team_xg_sanity", check_team_xg_sanity),
    ("10", "score_reconciliation", check_score_reconciliation),
]


# ── Runner + reporting ───────────────────────────────────────────────────────


def run_checks(data, gws, export=None):
  """{gw: [(phase_id, phase_name, status, details, seconds)]}"""
  results = {}
  for gw in gws:
    rows = []
    for phase_id, name, fn in PHASES:
      start = time.time()
      try:
        status, details = fn(data, gw, export)
      except Exception as e:  # report, don't abort the other checks
        status, details = FAIL, [f"Error: {type(e).__name__}: {e}"]
      rows.append((phase_id, name, status, details, time.time() - start))
    results[gw] = rows
  return results


def print_results(season, results):
  icons = {PASS: "✔", FAIL: "❌", SKIP: "➖"}
  for gw, rows in results.items():
    print(f"\n--- season {season} GW{gw} ---")
    for phase_id, name, status, details, _ in rows:
      first = details[0] if details else ""
      print(f"{icons[status]} [{phase_id} {name}] {first}")
      if status == FAIL:
        for line in details[1:]:
          print("      " + line.replace("\n", "\n      "))


def write_junit(season, results, junit_dir):
  os.makedirs(junit_dir, exist_ok=True)
  paths = []
  for gw, rows in results.items():
    suite_name = f"season{season}_gw{gw:02d}"
    suite = ET.Element(
        "testsuite",
        name=suite_name,
        tests=str(len(rows)),
        failures=str(sum(r[2] == FAIL for r in rows)),
        errors="0",
        skipped=str(sum(r[2] == SKIP for r in rows)),
        time=f"{sum(r[4] for r in rows):.3f}",
    )
    for phase_id, name, status, details, seconds in rows:
      case = ET.SubElement(
          suite,
          "testcase",
          classname=f"season{season}.gw{gw:02d}",
          name=f"phase{phase_id}_{name}",
          time=f"{seconds:.3f}",
      )
      text = "\n".join(details)
      if status == FAIL:
        failure = ET.SubElement(case, "failure",
                                message=details[0] if details else "failed")
        failure.text = text
      elif status == SKIP:
        ET.SubElement(case, "skipped",
                      message=details[0] if details else "skipped")
      else:
        ET.SubElement(case, "system-out").text = text

    root = ET.Element("testsuites")
    root.append(suite)
    ET.indent(root)
    path = os.path.join(junit_dir, f"{suite_name}.xml")
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)
    paths.append(path)
  return paths


def _season_from_folder(folder):
  parts = os.path.normpath(os.path.abspath(folder)).split(os.sep)
  return parts[-2] if parts[-1] == "gws" and len(parts) > 1 else parts[-1]


def main():
  parser = argparse.ArgumentParser(
      description=(
          "FPL Data Quality Checker: runs every check per gameweek; optional"
          " JUnit XML output (one file per season/gameweek)."
      )
  )
  parser.add_argument(
      "folder",
      type=str,
      help="Path to directory containing FPL CSVs (e.g., data/2026-27/gws)",
  )
  parser.add_argument(
      "-o",
      "--output",
      type=str,
      default=None,
      help="Optional path to export duplicated rows into a CSV file",
  )
  parser.add_argument(
      "--gw",
      type=int,
      default=None,
      help=(
          "Latest gameweek expected. GWs 1..N are checked even if their files"
          " are missing, so CI fails when GW N was not written."
      ),
  )
  parser.add_argument(
      "--season",
      type=str,
      default=None,
      help="Season label for reports (default: taken from the folder path)",
  )
  parser.add_argument(
      "--junit-dir",
      type=str,
      default=None,
      help="Write JUnit XML here, one file per gameweek: season<S>_gw<NN>.xml",
  )
  args = parser.parse_args()

  if not os.path.isdir(args.folder):
    print(f"❌ Error: Directory '{args.folder}' does not exist.")
    sys.exit(1)

  season = args.season or _season_from_folder(args.folder)
  data = SeasonData(args.folder)
  gws = data.gameweeks(args.gw)
  if not gws:
    print(f"❌ No gameweek files found in {args.folder}")
    sys.exit(1)

  export = [] if args.output else None
  results = run_checks(data, gws, export)
  print_results(season, results)

  if export:
    pd.concat(export, ignore_index=True).to_csv(args.output, index=False)
    print(f"\n📁 Exported all row duplicates to: {args.output}")

  if args.junit_dir:
    paths = write_junit(season, results, args.junit_dir)
    print(f"\n📁 Wrote {len(paths)} JUnit XML files to {args.junit_dir}")

  all_rows = [r for rows in results.values() for r in rows]
  failures = sum(r[2] == FAIL for r in all_rows)
  skipped = sum(r[2] == SKIP for r in all_rows)
  failed_gws = [gw for gw, rows in results.items()
                if any(r[2] == FAIL for r in rows)]

  print("\n=======================================")
  print(f"Season {season}: {len(gws)} GWs x {len(PHASES)} checks ="
        f" {len(all_rows)} tests, {failures} failed, {skipped} skipped")
  if failures:
    print(f"❌ Data Quality Gate FAILED. GWs with failures: {failed_gws}")
    sys.exit(1)
  print("✔ Data Quality Gate PASSED. All files clean.")
  sys.exit(0)


if __name__ == "__main__":
  main()
