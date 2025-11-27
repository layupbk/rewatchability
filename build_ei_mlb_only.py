import csv
import time
import datetime as dt

from espn_adapter import list_final_events_for_date, fetch_wp_quick
from main import calc_ei_from_home_series

REQUEST_SLEEP = 0.05


def daterange(start, end):
    """Yield dates from start to end inclusive."""
    current = start
    one_day = dt.timedelta(days=1)
    while current <= end:
        yield current
        current += one_day


def build_mlb_dataset(start_season=2021, end_season=2025, out_csv="ei_mlb_2021_2025.csv"):
    sport = "mlb"
    league = "MLB"

    print(f"\n[CONFIG] MLB EI build {start_season}–{end_season} → {out_csv}")
    print("[INFO] This run will OVERWRITE the file if it exists.\n")

    total_games = 0

    # Overwrite and write fresh header
    with open(out_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)

        writer.writerow(
            [
                "sport",
                "league",
                "season_year",
                "date",
                "event_id",
                "competition_id",
                "away_team",
                "home_team",
                "num_wp_points",
                "ei_raw",
            ]
        )

        for season in range(start_season, end_season + 1):
            if season == 2020:
                print("[SKIP] MLB 2020 skipped (COVID season)")
                continue

            start_date = dt.date(season, 3, 15)
            end_date = dt.date(season, 10, 5)

            print(f"[SEASON] MLB {season}: {start_date} → {end_date}")

            for day in daterange(start_date, end_date):
                date_iso = day.isoformat()

                try:
                    events = list_final_events_for_date(date_iso, [league])
                except Exception as ex:
                    print(f"[ERROR] Failed to fetch events for {date_iso}: {ex}")
                    continue

                if not events:
                    continue

                print(f"[DAY] {date_iso}: {len(events)} games")

                for ev in events:
                    event_id = ev.get("event_id")
                    comp_id = ev.get("comp_id", "")
                    away = ev.get("road", "")
                    home = ev.get("home", "")

                    # Get WP series for this game
                    try:
                        series = fetch_wp_quick(sport, event_id, comp_id)
                    except Exception as ex:
                        print(f"  [WARN] fetch_wp_quick failed for {event_id}: {ex}")
                        time.sleep(REQUEST_SLEEP)
                        continue

                    if not series:
                        print(f"  [WARN] No WP data for {event_id}, skipping.")
                        time.sleep(REQUEST_SLEEP)
                        continue

                    # EI calc: handle both (ei_raw, ei_scaled) and (ei_raw, ei_scaled, score)
                    try:
                        result = calc_ei_from_home_series(series)

                        if isinstance(result, tuple):
                            if len(result) == 3:
                                ei_raw, ei_scaled, _ = result
                            elif len(result) == 2:
                                ei_raw, ei_scaled = result
                            else:
                                print(
                                    f"  [WARN] Unexpected EI tuple size for {event_id}, len={len(result)}"
                                )
                                time.sleep(REQUEST_SLEEP)
                                continue
                        else:
                            print(f"  [WARN] EI result not a tuple for {event_id}")
                            time.sleep(REQUEST_SLEEP)
                            continue

                    except Exception as ex:
                        print(f"  [WARN] EI calc error for {event_id}: {ex}")
                        time.sleep(REQUEST_SLEEP)
                        continue

                    # Write row
                    writer.writerow(
                        [
                            sport.upper(),      # MLB
                            league,             # MLB
                            season,             # 2021–2025
                            date_iso,
                            event_id,
                            comp_id,
                            away,
                            home,
                            len(series),
                            f"{ei_raw:.6f}",
                        ]
                    )

                    total_games += 1

                    print(
                        f"  [EI] MLB {season} {date_iso} "
                        f"{away} @ {home}: EI={ei_raw:.6f}"
                    )

                    time.sleep(REQUEST_SLEEP)

    print(
        f"\n[DONE] MLB EI dataset written to {out_csv} "
        f"({total_games} games total).\n"
    )


if __name__ == "__main__":
    build_mlb_dataset()
