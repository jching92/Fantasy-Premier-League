"""
understat.py — download Understat EPL data for one season into
data/<season>/understat/ (same files and columns as before):

  understat_player.csv        season totals, one row per player
  understat_<Team>.csv        one per club: match-by-match team history
  <Player_Name>_<id>.csv      one per player: every match of his career
                              (goals, shots, xG, time, position, h_team, a_team,
                              date, id, season, ...). `position` is the slot the
                              club played him in that match (FW, AMC, DC, Sub ...)

Understat changed its site in 2025: pages no longer embed the data as
JSON.parse('...') blobs, which is why the old scraper stopped returning data
after 7 Apr 2025. The data now comes from JSON endpoints that answer only
requests sent with "X-Requested-With: XMLHttpRequest":
  https://understat.com/getLeagueData/EPL/<start year>   -> teams, players, dates
  https://understat.com/getPlayerData/<player id>        -> matches, shots, groups, ...
The old HTML parsing is kept as a fallback in case a page still embeds the data.

Usage:
  python understat.py --season 2025-26                # download, then write id_dict.csv
  python understat.py --season 2026-27 --limit 5      # quick test: first 5 players only
  python understat.py --season 2024-25 --ids-only     # only rebuild data/<season>/id_dict.csv
"""

import argparse
import codecs
import csv
import json
import os
import re
import sys
import time

import pandas as pd
import requests
from bs4 import BeautifulSoup

BASE = "https://understat.com"
HEADERS = {
    "X-Requested-With": "XMLHttpRequest",          # required, otherwise 404
    "User-Agent": ("Mozilla/5.0 (X11; Linux aarch64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
    "Referer": BASE + "/",
    "Accept": "application/json, text/javascript, */*; q=0.01",
}
# Column order of the existing per-player files; any new fields go after these
MATCH_COLUMNS = ["goals", "shots", "xG", "time", "position", "h_team", "a_team",
                 "h_goals", "a_goals", "date", "id", "season", "roster_id", "xA",
                 "assists", "key_passes", "npg", "npxG", "xGChain", "xGBuildup"]

_session = requests.Session()
_session.headers.update(HEADERS)


# ── HTTP ──────────────────────────────────────────────────────────────────

def _get(url, retries=4, pause=1.0):
    """GET with retries and back-off; returns the Response."""
    last = None
    for attempt in range(retries):
        try:
            r = _session.get(url, timeout=30)
            if r.status_code == 200:
                return r
            last = f"HTTP {r.status_code}"
            if r.status_code in (403, 404):        # won't change on retry
                break
        except requests.RequestException as e:
            last = str(e)
        time.sleep(pause * (2 ** attempt))
    raise ConnectionError(f"{url}: {last}")


def _get_json(path):
    r = _get(BASE + path)
    try:
        return r.json()                             # requests handles gzip
    except ValueError:
        raise ValueError(f"{BASE + path}: response is not JSON "
                         f"(starts {r.text[:80]!r})")


def _embedded(url, names):
    """Old method: JSON.parse('...') blobs inside the page's <script> tags."""
    html = _get(url).text
    out = {}
    for script in BeautifulSoup(html, "html.parser").find_all("script"):
        for c in script.contents:
            split = str(c).split("=", 1)
            var = split[0].strip()
            for name in names:
                if var == f"var {name}" and len(split) > 1:
                    blob = re.findall(r"JSON\.parse\('(.*)'\)", split[1])
                    if blob:
                        out[name] = json.loads(codecs.escape_decode(blob[0], "hex")[0].decode("utf-8"))
    return out


# ── Fetchers ──────────────────────────────────────────────────────────────

def get_epl_data(season_year):
    """(teams dict, players list) for the EPL season starting in season_year."""
    try:
        d = _get_json(f"/getLeagueData/EPL/{season_year}")
        return d.get("teams", {}), d.get("players", [])
    except Exception as e:
        print(f"  getLeagueData failed ({e}); trying the old page format")
        d = _embedded(f"{BASE}/league/EPL/{season_year}", ["teamsData", "playersData"])
        if not d:
            raise
        return d.get("teamsData", {}), d.get("playersData", [])


def get_player_data(player_id):
    """(matches, shots, groups) for one player — all seasons of his career."""
    try:
        d = _get_json(f"/getPlayerData/{player_id}")
        return d.get("matches", []), d.get("shots", []), d.get("groups", {})
    except Exception as e:
        try:
            d = _embedded(f"{BASE}/player/{player_id}", ["matchesData", "shotsData", "groupsData"])
        except Exception as e2:
            raise ConnectionError(f"getPlayerData: {e} | old page: {e2}") from None
        if not d:
            raise e
        return d.get("matchesData", []), d.get("shotsData", []), d.get("groupsData", {})


# ── Writers ───────────────────────────────────────────────────────────────

def _season_year(season_or_dir):
    """'2025-26' or 'data/2025-26/understat' -> 2025."""
    m = re.search(r"(\d{4})-\d{2}", str(season_or_dir))
    if not m:
        raise ValueError(f"cannot tell the season from {season_or_dir!r}")
    return int(m.group(1))


def _safe(name):
    return str(name).replace(" ", "_").replace("/", "_")


def parse_epl_data(outfile_base, season=None, limit=None, pause=0.5):
    """
    Download one season into outfile_base (e.g. data/2025-26/understat).
    `season` defaults to the season in the folder name, so the old call
    parse_epl_data('data/2025-26/understat') in global_scraper.py still works.
    Returns (players written, players failed).
    """
    year = _season_year(season or outfile_base)
    os.makedirs(outfile_base, exist_ok=True)
    print(f"Understat EPL {year}-{str(year + 1)[-2:]} -> {outfile_base}")

    teams, players = get_epl_data(year)
    if not players:
        raise RuntimeError(f"Understat returned no players for EPL {year}")
    teams = teams.values() if isinstance(teams, dict) else teams
    for t in teams:
        pd.DataFrame.from_records(t["history"]).to_csv(
            os.path.join(outfile_base, f"understat_{_safe(t['title'])}.csv"), index=False)
    pd.DataFrame.from_records(players).to_csv(
        os.path.join(outfile_base, "understat_player.csv"), index=False)
    print(f"  {len(list(teams))} teams, {len(players)} players")

    todo = players[:limit] if limit else players
    written, failed = 0, []
    for i, p in enumerate(todo, 1):
        try:
            matches, _, _ = get_player_data(int(p["id"]))
            df = pd.DataFrame.from_records(matches)
            cols = [c for c in MATCH_COLUMNS if c in df] + [c for c in df if c not in MATCH_COLUMNS]
            df[cols].to_csv(os.path.join(outfile_base, f"{_safe(p['player_name'])}_{p['id']}.csv"),
                            index=False)
            written += 1
        except Exception as e:
            failed.append((p["id"], p["player_name"], str(e)))
            print(f"  FAILED {p['player_name']} ({p['id']}): {e}")
        if i % 50 == 0:
            print(f"  {i}/{len(todo)} players")
        time.sleep(pause)                            # be polite to Understat
    print(f"  wrote {written} player files, {len(failed)} failed")
    return written, failed


class PlayerID:
    def __init__(self, us_id, fpl_id, us_name, fpl_name):
        self.us_id = str(us_id)
        self.fpl_id = str(fpl_id)
        self.us_name = us_name
        self.fpl_name = fpl_name


def match_ids(understat_dir, data_dir):
    """Write data_dir/id_dict.csv: Understat id <-> FPL id, matched on full name."""
    with open(os.path.join(understat_dir, 'understat_player.csv'), encoding='utf-8') as understat_file:
        ustat_players = {row['player_name']: row['id'] for row in csv.DictReader(understat_file)}
    with open(os.path.join(data_dir, 'player_idlist.csv'), encoding='utf-8') as fpl_file:
        fpl_players = {row['first_name'] + ' ' + row['second_name']: row['id']
                       for row in csv.DictReader(fpl_file)}
    players, found = [], {}
    for k, v in ustat_players.items():
        if k in fpl_players:
            players.append(PlayerID(v, fpl_players[k], k, k))
            found[k] = True
        else:
            players.append(PlayerID(v, -1, k, ""))
    for k, v in fpl_players.items():
        if k not in found:
            players.append(PlayerID(-1, v, "", k))
    with open(os.path.join(data_dir, 'id_dict.csv'), 'w+', encoding='utf-8') as outf:
        outf.write('Understat_ID, FPL_ID, Understat_Name, FPL_Name\n')
        for p in players:
            outf.write(p.us_id + "," + p.fpl_id + "," + p.us_name + "," + p.fpl_name + "\n")
    print(f"  id_dict.csv: {len(found)} of {len(ustat_players)} Understat players matched to FPL by name")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--season", required=True, help="e.g. 2025-26")
    ap.add_argument("--data-dir", default="data", help="folder holding the season folders")
    ap.add_argument("--limit", type=int, help="only the first N players (for a quick test)")
    ap.add_argument("--pause", type=float, default=0.5, help="seconds between player requests")
    ap.add_argument("--ids-only", action="store_true", help="only rebuild id_dict.csv")
    ap.add_argument("--max-failed", type=float, default=0.05,
                    help="exit 1 if more than this share of players fail (default 5%%)")
    args = ap.parse_args(argv)

    season_dir = os.path.join(args.data_dir, args.season)
    us_dir = os.path.join(season_dir, "understat")
    if not args.ids_only:
        written, failed = parse_epl_data(us_dir, args.season, args.limit, args.pause)
        if failed and len(failed) > args.max_failed * (written + len(failed)):
            print(f"ERROR: {len(failed)} players failed")
            return 1
    if os.path.exists(os.path.join(season_dir, "player_idlist.csv")):
        match_ids(us_dir, season_dir)
    else:
        print(f"  no {season_dir}/player_idlist.csv, skipping id_dict.csv")
    return 0


if __name__ == '__main__':
    sys.exit(main())
