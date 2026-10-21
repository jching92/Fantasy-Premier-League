import argparse
import os
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
    parent_path = os.path.join(os.path.dirname(folder_path), "merged_gw.csv")
    if os.path.exists(parent_path):
      merged_file_path = parent_path
    else:
      print("ℹ️ merged_gw.csv not found. Skipping merged fixture check.")
      return 0

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

        # Group-by team and opponent_team to get unique matchups per team in this GW
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


def main():
  parser = argparse.ArgumentParser(
      description=(
          "FPL Data Quality Checker: Full-row duplicates and fixture logic."
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

  total_issues = row_dupes + merged_conflicts + gw_issues

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
