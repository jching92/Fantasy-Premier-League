import argparse
import os
import re
import sys
import pandas as pd


def check_full_row_duplicates(folder_path, export_path=None):
  print(f"--- Phase 1: Checking full-row duplicates in: {folder_path} ---")
  total_duplicates_found = 0
  all_duplicates = []

  for filename in sorted(os.listdir(folder_path)):
    if filename.endswith(".csv"):
      file_path = os.path.join(folder_path, filename)
      try:
        df = pd.read_csv(file_path, low_memory=False)
        duplicates = df[df.duplicated(keep=False)]

        if not duplicates.empty:
          num_dupes = len(duplicates)
          total_duplicates_found += num_dupes
          print(f"⚠️ [Found] {filename}: {num_dupes} duplicate rows.")
          if export_path:
            duplicates["source_file"] = filename
            all_duplicates.append(duplicates)
        else:
          print(f"✔ [Clean] {filename}: No full-row duplicates.")
      except Exception as e:
        print(f"❌ Error reading {filename}: {e}")

  if export_path and all_duplicates:
    combined_dupes = pd.concat(all_duplicates, ignore_index=True)
    combined_dupes.to_csv(export_path, index=False)
    print(f"\n📁 Exported all row duplicates to: {export_path}")

  return total_duplicates_found


def check_merged_gw_fixtures(folder_path):
  print(
      "\n--- Phase 2: Checking fixture logic in merged_gw.csv (team,"
      " kickoff_time, opponent_team) ---"
  )
  merged_file_path = os.path.join(folder_path, "merged_gw.csv")

  if not os.path.exists(merged_file_path):
    print("❌ merged_gw.csv not found. Skipping merged fixture check.")
    return 1

  print(f"Analyzing {merged_file_path}...")
  try:
    df = pd.read_csv(merged_file_path, low_memory=False)
    required_cols = ["team", "kickoff_time", "opponent_team"]
    missing_cols = [col for col in required_cols if col not in df.columns]
    if missing_cols:
      print(f"❌ Missing columns in merged_gw.csv: {missing_cols}")
      return 1

    grouped = (
        df.groupby(["team", "kickoff_time"])["opponent_team"]
        .nunique()
        .reset_index(name="unique_opponents")
    )
    conflicts = grouped[grouped["unique_opponents"] > 1]

    if not conflicts.empty:
      print(
          f"❌ Found {len(conflicts)} fixture conflict(s) in merged_gw.csv"
          " (multiple opponents at same kickoff time):"
      )
      print(conflicts.to_string(index=False))
      return len(conflicts)
    else:
      print("✔ merged_gw.csv fixture check passed.")
      return 0
  except Exception as e:
    print(f"❌ Error checking merged_gw.csv: {e}")
    return 1


def check_single_gw_fixtures(folder_path):
  print(
      "\n--- Phase 3: Checking fixture logic & row counts in gw{i}.csv files ---"
  )
  total_issues = 0

  for filename in sorted(os.listdir(folder_path)):
    if filename.startswith("gw") and filename.endswith(".csv"):
      file_path = os.path.join(folder_path, filename)
      try:
        df = pd.read_csv(file_path, low_memory=False)
        required_cols = ["team", "opponent_team"]
        missing_cols = [col for col in required_cols if col not in df.columns]
        if missing_cols:
          print(f"⚠️ {filename}: Missing columns {missing_cols}. Skipped.")
          continue

        team_opp_df = df[["team", "opponent_team"]].drop_duplicates()

        # Rule A: Exactly 20 team-opponent entry rows per gameweek file
        row_count = len(team_opp_df)
        if row_count != 20:
          print(
              f"❌ [{filename}] Row count mismatch: Expected 20 team-opponent"
              f" rows, found {row_count}."
          )
          total_issues += 1

        # Rule B: Only 1 unique opponent_team per team
        team_counts = (
            team_opp_df.groupby("team")["opponent_team"]
            .nunique()
            .reset_index(name="opponent_count")
        )
        invalid_teams = team_counts[team_counts["opponent_count"] != 1]

        if not invalid_teams.empty:
          print(
              f"❌ [{filename}] Teams with invalid number of opponents:"
              f" {invalid_teams.to_dict(orient='records')}"
          )
          total_issues += 1

        if row_count == 20 and invalid_teams.empty:
          print(f"✔ [Clean] {filename}")

      except Exception as e:
        print(f"❌ Error processing {filename}: {e}")
        total_issues += 1

  return total_issues


def check_gw_xp_pairing(folder_path):
  print("\n--- Phase 4: Checking pairing of gw{i}.csv and xP{i}.csv files ---")
  gw_indices = set()
  xp_indices = set()

  for filename in os.listdir(folder_path):
    m_gw = re.match(r"^gw(\d+)\.csv$", filename)
    if m_gw:
      gw_indices.add(int(m_gw.group(1)))
    m_xp = re.match(r"^xP(\d+)\.csv$", filename)
    if m_xp:
      xp_indices.add(int(m_xp.group(1)))

  all_indices = sorted(list(gw_indices.union(xp_indices)))
  issues = 0

  for i in all_indices:
    has_gw = i in gw_indices
    has_xp = i in xp_indices

    if not has_gw:
      print(f"❌ [Missing GW] xP{i}.csv exists, but gw{i}.csv is missing.")
      issues += 1
    elif not has_xp:
      print(f"❌ [Missing xP] gw{i}.csv exists, but xP{i}.csv is missing.")
      issues += 1
    else:
      print(f"✔ [Pair Matched] gw{i}.csv & xP{i}.csv")

  return issues


def check_merged_row_count_sum(folder_path):
  print(
      "\n--- Phase 5: Checking merged_gw.csv row count vs sum of gw{i}.csv rows"
      " ---"
  )
  merged_file_path = os.path.join(folder_path, "merged_gw.csv")

  if not os.path.exists(merged_file_path):
    print("❌ merged_gw.csv not found. Skipping sum comparison.")
    return 1

  try:
    merged_df = pd.read_csv(merged_file_path, low_memory=False)
    merged_rows = len(merged_df)

    sum_gw_rows = 0
    gw_file_count = 0
    for filename in os.listdir(folder_path):
      if filename.startswith("gw") and filename.endswith(".csv"):
        file_path = os.path.join(folder_path, filename)
        df = pd.read_csv(file_path, low_memory=False)
        sum_gw_rows += len(df)
        gw_file_count += 1

    print(f"Total rows in merged_gw.csv: {merged_rows}")
    print(f"Sum of rows across {gw_file_count} gw{{i}}.csv files: {sum_gw_rows}")

    if merged_rows != sum_gw_rows:
      print(
          f"❌ Row count mismatch! merged_gw.csv has {merged_rows} rows,"
          f" but the sum of gw{{i}}.csv files is {sum_gw_rows}."
      )
      return 1
    else:
      print(
          "✔ Row count match passed: merged_gw.csv matches the sum of all"
          " gw{i}.csv files."
      )
      return 0
  except Exception as e:
    print(f"❌ Error during row sum comparison: {e}")
    return 1


def main():
  parser = argparse.ArgumentParser(
      description=(
          "FPL Data Quality Checker: Duplicates, Fixtures, Pairings, and"
          " Totals."
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

  args = parser.parse_args()

  if not os.path.isdir(args.folder):
    print(f"❌ Error: Directory '{args.folder}' does not exist.")
    sys.exit(1)

  row_dupes = check_full_row_duplicates(args.folder, args.output)
  merged_conflicts = check_merged_gw_fixtures(args.folder)
  gw_issues = check_single_gw_fixtures(args.folder)
  pairing_issues = check_gw_xp_pairing(args.folder)
  sum_issues = check_merged_row_count_sum(args.folder)

  total_issues = (
      row_dupes
      + merged_conflicts
      + gw_issues
      + pairing_issues
      + sum_issues
  )

  print("\n=======================================")
  if total_issues > 0:
    print(
        f"❌ Data Quality Gate FAILED. Total issues found: {total_issues}"
    )
    sys.exit(1)
  else:
    print("✔ Data Quality Gate PASSED. All files clean.")
    sys.exit(0)


if __name__ == "__main__":
  main()
