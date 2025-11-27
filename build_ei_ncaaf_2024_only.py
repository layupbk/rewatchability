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


def build_ncaaf_2024(out_csv="ei_ncaaf_2024.csv"):
    sport = "ncaaf"
    league = "NCAAF"
    season_year = 2024

    start_date = dt.date(2024, 8, 20)
    end_date = dt.date(2025, 1, 15)

    print(f"\n[CONFIG] Building NCAAF EI dataset for 2024 → {out_csv}")
    print("[INFO] This run will OVERWRITE the file if it exists.\n")
    print(f"[SEASON] NCAAF 2024: {start_date} → {end_date}")

    total_games = 0

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

                try:
                    result = calc_ei_from_home_series(series)

                    if isinstance(result, tuple):
                        if len(result) == 3:
                            ei_raw, ei_scaled, _ = result
                        elif len(result) == 2:
                            ei_raw, ei_scaled = result
                        else:
                            print(f"  [WARN] Unexpected EI tuple size for {event_id}.")
                            time.sleep(REQUEST_SLEEP)
                            continue
                    else:
                        print(f"  [WARN] EI result not tuple for {event_id}.")
                        time.sleep(REQUEST_SLEEP)
                        continue

                except Exception as ex:
                    print(f"  [WARN] EI calc error for {event_id}: {ex}")
                    time.sleep(REQUEST_SLEEP)
                    continue

                writer.writerow(
                    [
                        sport.upper(),
                        league,
                        season_year,
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
                    f"  [EI] EI={ei_raw:.6f} | {away} @ {home} on {date_iso}"
                )

                time.sleep(REQUEST_SLEEP)

    print(
        f"\n[DONE] Completed NCAAF 2024 build → {out_csv} ({total_games} games)\n"
    )


if __name__ == "__main__":
    build_ncaaf_2024()
