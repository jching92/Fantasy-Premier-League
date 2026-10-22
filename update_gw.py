import csv
import os
import sys

from getters import get_data, get_individual_player_data
from parsers import parse_player_gw_history, parse_players
from cleaners import id_players
from collector import collect_gw, merge_gw


SEASON = "2026-27"
BASE_DIR = f"data/{SEASON}"
PLAYER_DIR = f"{BASE_DIR}/players"
GW_DIR = f"{BASE_DIR}/gws"


def get_requested_gw():
    if len(sys.argv) != 2:
        print("Usage: python update_gw.py <gameweek>")
        sys.exit(1)

    try:
        gw = int(sys.argv[1])
    except ValueError:
        print("Gameweek must be an integer.")
        sys.exit(1)

    if gw < 1:
        print("Gameweek must be >= 1.")
        sys.exit(1)

    return gw


def generate_xp(data, gw):
    """
    Generate xP{gw}.csv from bootstrap-static ep_this.
    """

    os.makedirs(GW_DIR, exist_ok=True)

    output_file = os.path.join(
        GW_DIR,
        f"xP{gw}.csv"
    )

    print(f"[1/3] Writing {output_file}")

    with open(output_file, "w", newline="") as outf:
        writer = csv.DictWriter(
            outf,
            ["id", "xP"]
        )

        writer.writeheader()

        for player in data["elements"]:
            writer.writerow({
                "id": player["id"],
                "xP": player["ep_this"],
            })

    print(f"      Wrote {len(data['elements'])} players")


def refresh_player_metadata(data):
    """
    Rewrite players_raw.csv and player_idlist.csv from bootstrap-static,
    so players who debut mid-season (outside a transfer window) get a
    name, position and canonical directory before collect_gw() runs.
    """

    old_ids = set()
    idlist = os.path.join(BASE_DIR, "player_idlist.csv")
    if os.path.exists(idlist):
        with open(idlist, encoding="utf-8") as fin:
            old_ids = {int(r["id"]) for r in csv.DictReader(fin)}

    parse_players(data["elements"], BASE_DIR + "/")
    id_players(os.path.join(BASE_DIR, "players_raw.csv"), BASE_DIR + "/")

    new = [p for p in data["elements"] if p["id"] not in old_ids]
    print(f"      players_raw.csv / player_idlist.csv: "
          f"{len(data['elements'])} players")
    for p in new:
        print(f"      NEW: {p['first_name']} {p['second_name']} ({p['id']})")


def refresh_player_gw_data(data):
    """
    Refresh player-level gw.csv files from the FPL
    element-summary API.

    Only the current player GW histories are updated;
    existing player directories are reused.
    """

    print("[2/3] Updating player GW histories")

    # bootstrap-static contains the player IDs
    players = data["elements"]

    total = len(players)

    for count, player in enumerate(players, start=1):

        player_id = player["id"]

        # Same '<first>_<second>' naming as global_scraper.py /
        # player_idlist.csv. Using web_name here created a second
        # directory per player (e.g. A.Becker_350 next to
        # Alisson_Becker_350).
        name = f"{player['first_name']}_{player['second_name']}"

        print(
            f"      [{count}/{total}] "
            f"{name} ({player_id})"
        )

        player_data = get_individual_player_data(
            player_id
        )

        parse_player_gw_history(
            player_data["history"],
            PLAYER_DIR + "/",
            name,
            player_id,
        )


def generate_gw(gw):
    """
    Generate gw{gw}.csv and update merged_gw.csv.
    """

    print(f"[3/3] Generating GW{gw}")

    collect_gw(
        gw,
        PLAYER_DIR + "/",
        GW_DIR + "/",
        BASE_DIR,
    )

    gw_file = os.path.join(
        GW_DIR,
        f"gw{gw}.csv"
    )

    print(f"      Created {gw_file}")

    print("      Updating merged_gw.csv")

    merge_gw(
        gw,
        GW_DIR + "/"
    )

    print()
    print("      Update complete")


def main():

    gw = get_requested_gw()

    print("=" * 60)
    print(
        f"FPL WEEKLY UPDATE — "
        f"{SEASON} GW{gw}"
    )
    print("=" * 60)

    print("Downloading FPL bootstrap data...")

    data = get_data()

    # Make sure the requested GW exists.
    available_gws = {
        event["id"]
        for event in data["events"]
    }

    if gw not in available_gws:
        print(
            f"WARNING: GW{gw} is not present "
            f"in bootstrap-static."
        )

    # 0. players_raw.csv + player_idlist.csv
    refresh_player_metadata(
        data
    )

    # 1. xP{gw}.csv
    generate_xp(
        data,
        gw
    )

    # 2. Player gw.csv files
    refresh_player_gw_data(
        data
    )

    # 3. gw{gw}.csv + merged_gw.csv
    generate_gw(
        gw
    )

    print()
    print("=" * 60)
    print("UPDATE COMPLETE")
    print("=" * 60)

    print(
        f"xP file:     "
        f"{GW_DIR}/xP{gw}.csv"
    )

    print(
        f"GW file:     "
        f"{GW_DIR}/gw{gw}.csv"
    )

    print(
        f"Merged file: "
        f"{GW_DIR}/merged_gw.csv"
    )


if __name__ == "__main__":
    main()
