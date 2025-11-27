"""
build_ei_dataset.py

Build EI dataset CSVs for NBA, NFL, MLB, NCAAM, NCAAF using the exact SAME
ESPN pipeline and EI function as your live autopilot.

You can:
    - Run everything:
        py build_ei_dataset.py

    - Run ONLY one sport:
        py build_ei_dataset.py --sport ncaaf

    - Run ONLY one sport + one season, APPENDING to existing CSV:
        py build_ei_dataset.py --sport ncaaf --season 2024 --append
        py build_ei_dataset.py --sport mlb  --season 2025 --append
"""

import csv
import time
import os
import argparse
import datetime as dt

from espn_adapter import list_final_events_for_date, fetch_wp_quick
from main import calc_ei_from_home_series

# --------------------------------------------------------------------
# SEASON CONFIG (regular seasons only; older ones lacking WP skipped)
# season_year = start year of the season (e.g. 2021 for 2021-22 NBA)
# --------------------------------------------------------------------
SPORT_CONFIG = {
    "nba": {
        "league": "NBA",
        # 2021-22, 2022-23, 2023-24, 2024-25 (regular seasons)
        "seasons": [2021, 2022, 2023, 2024],
        "date_range": lambda y: (dt.date(y, 10, 15), dt.date(y + 1, 4, 20)),
    },
    "nfl": {
        "league": "NFL",
        # 2021–2024 regular seasons
        "seasons": [2021, 2022, 2023, 2024],
        "date_range": lambda y: (dt.date(y, 9, 1), dt.date(y + 1, 1, 20)),
    },
    "mlb": {
        "league": "MLB",
        # 2019–2025 regular seasons (2020 omitted for COVID)
        "seasons": [2019, 2021, 2022, 2023, 2024, 2025],
        "date_range": lambda y: (dt.date(y, 3, 15), dt.date(y, 10, 5)),
    },
    "ncaam": {
        "league": "NCAAM",
        # 2021-22, 2022-23, 2023-24, 2024-25 regular seasons
        "seasons": [2021, 2022, 2023, 2024],
        "date_range": lambda y: (dt.date(y, 11, 1), dt.date(y + 1, 3, 31)),
    },
    "ncaaf": {
        "league": "NCAAF",
        # 2021–2024 regular seasons
        "seasons": [2021, 2022, 2023, 2024],
        "date_range": lambda y: (dt.date(y, 8, 20), dt.date(y + 1, 1, 15)),
    },
}

# Use fixed output filenames so we can safely append missing seasons
OUTFILE_MAP = {
    "nba": "ei_nba_2021_2024.csv",
    "nfl": "ei_nfl_2021_2024.csv",
    "mlb": "ei_mlb_2019_2024.csv",   # we will append 2025 into this file
    "ncaam": "ei_ncaam_2021_2024.csv",
    "ncaaf": "ei_ncaaf_2021_2024.csv",  # we will append 2024 into this file
}

# Small delay between WP fetches so we don't hammer ESPN
REQUEST_SLEEP = 0.05


def daterange(start: dt.date, end: dt.date):
    """Yield dates from start to end inclusive."""
    d = start
    one_day = dt.timedelta(days=1)
    while d <= end:
        yield d
        d += one_day


def build_for_sport(sport: str, cfg: dict, seasons: list[int], append: bool = False):
    """
    Build EI CSV for a single sport.

    sport: 'nba', 'nfl', 'mlb', 'ncaam', 'ncaaf'
    seasons: list of season_year ints to process (e.g. [2024])
    append: if True, append rows to existing CSV instead of overwriting
    """
    league = cfg["league"]
    date_range_fn = cfg["date_range"]

    out_csv = OUTFILE_MAP[sport]

    existing_ids = set()
    file_exists = os.path.exists(out_csv)

    # If we're appending, load existing event_ids to avoid duplicates
    if append and file_exists:
        try:
            with open(out_csv, "r", newline="", encoding="utf-8") as f_in:
                reader = csv.DictReader(f_in)
                for row in reader:
                    eid = row.get("event_id")
                    if eid:
                        existing_ids.add(eid)
            print(f"[INFO] Loaded {len(existing_ids)} existing IDs from {out_csv}", flush=True)
        except Exception as ex:
            print(f"[WARN] Failed to read existing IDs from {out_csv}: {ex}", flush=True)

    # Decide file mode
    mode = "a" if append and file_exists else "w"
    write_header = not (append and file_exists)

    print(
        f"\n[SPORT] {sport.upper()} -> {out_csv} "
        f"(seasons={seasons}, mode={'append' if append else 'write'})",
        flush=True,
    )

    with open(out_csv, mode, newline="", encoding="utf-8") as f:
        writer = csv.writer(f)

        if write_header:
            writer.writerow(
                [
                    "sport",          # NBA / NFL / MLB / NCAAM / NCAAF
                    "league",         # ESPN league key
                    "season_year",    # start year of season
                    "date",           # game date (YYYY-MM-DD)
                    "event_id",
                    "competition_id",
                    "away_team",
                    "home_team",
                    "num_wp_points",
                    "ei_raw",         # Σ|ΔWP| on home series
                ]
            )

        total_games = 0

        for season in seasons:
            start_date, end_date = date_range_fn(season)
            print(
                f"[SEASON] {sport.upper()} {season}: {start_date} → {end_date}",
                flush=True,
            )

            for day in daterange(start_date, end_date):
                date_iso = day.isoformat()

                # This will print its own logs ([ESPN] ...) from espn_adapter
                try:
                    events = list_final_events_for_date(date_iso, [league])
                except Exception as ex:
                    print(
                        f"  [ERROR] list_final_events_for_date({league}, {date_iso}) -> {ex}",
                        flush=True,
                    )
                    continue

                if not events:
                    continue

                print(f"  [DAY] {date_iso}: {len(events)} games", flush=True)

                for ev in events:
                    event_id = ev["event_id"]

                    # If appending and we've already seen this event, skip
                    if append and event_id in existing_ids:
                        # Optional: uncomment to see skips
                        # print(f"    [SKIP] already have event {event_id}", flush=True)
                        continue

                    comp_id = ev.get("comp_id")
                    away = ev.get("road", "")
                    home = ev.get("home", "")

                    # Fetch WP series using the same helper as autopilot
                    try:
                        series = fetch_wp_quick(sport, event_id, comp_id)
                    except Exception as ex:
                        print(
                            f"    [WARN] fetch_wp_quick error for {event_id}: {ex}",
                            flush=True,
                        )
                        time.sleep(REQUEST_SLEEP)
                        continue

                    if not series:
                        # espn_adapter will usually have already logged why
                        time.sleep(REQUEST_SLEEP)
                        continue

                    # EI calculation: same function that live autopilot uses
                    try:
                        ei_raw, ei_scaled, score = calc_ei_from_home_series(series)
                    except Exception as ex:
                        print(
                            f"    [WARN] EI calc error for {event_id}: {ex}",
                            flush=True,
                        )
                        time.sleep(REQUEST_SLEEP)
                        continue

                    writer.writerow(
                        [
                            sport.upper(),
                            league,
                            season,
                            date_iso,
                            event_id,
                            comp_id or "",
                            away,
                            home,
                            len(series),
                            f"{ei_raw:.6f}",
                        ]
                    )
                    total_games += 1

                    print(
                        f"    [EI] {ei_raw:.3f} from {len(series)} pts",
                        flush=True,
                    )

                    time.sleep(REQUEST_SLEEP)

        print(
            f"[DONE] {sport.upper()}: {total_games} games written to {out_csv}",
            flush=True,
        )


def main():
    parser = argparse.ArgumentParser(description="Build EI datasets from ESPN WP.")
    parser.add_argument(
        "--sport",
        choices=list(SPORT_CONFIG.keys()),
        help="Limit to a single sport (nba, nfl, mlb, ncaam, ncaaf).",
    )
    parser.add_argument(
        "--season",
        type=int,
        help="Limit to a single season_year (e.g. 2024). "
             "Must be within the configured seasons for that sport.",
    )
    parser.add_argument(
        "--append",
        action="store_true",
        help="Append to existing CSV instead of overwriting it.",
    )

    args = parser.parse_args()

    print("[RUN] Starting EI dataset build (regular seasons only)...", flush=True)

    # Determine which sports to run
    if args.sport:
        sports = [args.sport]
    else:
        sports = list(SPORT_CONFIG.keys())

    for sport in sports:
        cfg = SPORT_CONFIG[sport]
        seasons = cfg["seasons"]

        # If a specific season is requested, restrict to that
        if args.season is not None:
            if args.season not in seasons:
                print(
                    f"[WARN] season {args.season} not in configured seasons for {sport}. "
                    f"Proceeding anyway with date_range for {args.season}.",
                    flush=True,
                )
                seasons_to_run = [args.season]
            else:
                seasons_to_run = [args.season]
        else:
            seasons_to_run = seasons

        build_for_sport(sport, cfg, seasons_to_run, append=args.append)

    print("\n[COMPLETE] All requested EI datasets built.\n", flush=True)


if __name__ == "__main__":
    main()
