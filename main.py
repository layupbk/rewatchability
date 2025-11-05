import time
from datetime import datetime, timedelta, timezone

# ESPN + scoring stack
from espn_adapter import list_final_events_for_date, fetch_win_probability_series
from scoring import score_game
from vibe_tags import vibe_tag_from_score
from posting_rules import format_post, format_video_caption
from formatting import to_weekday_mm_d_yy

# Twitter publisher (returns True on success)
from publisher_x import post_to_x

# Rolling duplicate guard
from ledger import (
    load_ledger,
    save_ledger,
    prune_ledger,
    already_posted,
    mark_posted,
)

# Pro only for now. Add NCAAF/NCAAM later when you lock their formulas.
LEAGUES = ["NBA", "NFL", "MLB"]
ALLOWED_SPORTS = {"NBA", "NFL", "MLB"}

POLL_EVERY_SECONDS = 60
# seconds since the start of the attempt when we try pulling WP
WP_RETRY_SCHEDULE = [0, 10, 20, 35]


def today_iso_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def yesterday_iso_utc() -> str:
    return (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")


def calc_ei_from_home_series(home_series: list[float]) -> float:
    """Sum of absolute deltas across the home-team WP series."""
    if not home_series or len(home_series) < 2:
        return 0.0
    total = 0.0
    prev = home_series[0]
    for p in home_series[1:]:
        total += abs(p - prev)
        prev = p
    return total


def fetch_wp_quick(sport: str, event_id: str, comp_id: str) -> list[float] | None:
    """Try several times quickly to catch ESPN's late WP publish."""
    start = time.time()
    for i, target_s in enumerate(WP_RETRY_SCHEDULE):
        sleep_for = target_s - (time.time() - start)
        if sleep_for > 0:
            time.sleep(sleep_for)
        series = fetch_win_probability_series(sport, event_id, comp_id)
        if series:
            if i > 0:
                print(
                    f"[WP] arrived on quick attempt {i+1}/{len(WP_RETRY_SCHEDULE)}",
                    flush=True,
                )
            return series
    return None


def post_once(ev: dict, date_iso: str) -> bool:
    """
    Build tweet + caption and post to X.
    Returns True only if the tweet was successfully posted.
    """
    sport = ev["sport"].upper()
    if sport not in ALLOWED_SPORTS:
        print(f"[SKIP] {sport} disabled (college scoring not enabled yet)", flush=True)
        return False

    road = ev["road"]
    home = ev["home"]
    network = ev["network"]               # '' or None when not national
    neutral = ev["neutral_site"]          # bool
    event_name = ev["event_name"]         # tournament/special label if present
    event_id = ev["event_id"]
    comp_id = ev["comp_id"]

    # Fast WP fetch window. If not ready yet, the main loop will revisit later.
    series = fetch_wp_quick(sport, event_id, comp_id)
    if not series:
        return False

    # EI -> Score -> Vibe
    ei = calc_ei_from_home_series(series)
    score = score_game(sport, ei).score
    vibe = vibe_tag_from_score(score)

    # Date line with weekday (game date, not post time)
    date_line = to_weekday_mm_d_yy(date_iso)  # e.g., 'Tue · 11/4/25'
    game = {"away": road, "home": home}

    # Text post (tweet)
    tweet = format_post(
        game=game,
        score=score,
        vibe=vibe,
        date=date_line,
        sport=sport,
        neutral_site=neutral,
        network=network,
    )
    print(tweet.strip(), flush=True)
    print("-" * 40, flush=True)

    # Future: short caption for video post
    caption = format_video_caption(
        game=game,
        score=score,
        vibe=vibe,
        date=date_line,
        sport=sport,
        neutral_site=neutral,
        network=network,
        is_national=bool(network),
        event_name=event_name,
    )
    print(caption.strip(), flush=True)
    print("=" * 60, flush=True)

    # Publish to X. Only return True if it actually posts (prevents false positives).
    posted = post_to_x(tweet)
    return posted


def main():
    # Prepare rolling ledger (7-day window by default; see LEDGER_DAYS in ledger.py)
    ledger = load_ledger()
    prune_ledger(ledger)
    save_ledger(ledger)
    print(f"[RUN] ledger ready with {len(ledger)} ids", flush=True)

    print("[RUN] Cloud worker started. Polling every 60s.", flush=True)

    while True:
        try:
            yday = yesterday_iso_utc()
            today = today_iso_utc()

            print(f"[HB] checking dates: {yday} and {today}", flush=True)

            for date_iso in (yday, today):
                events = list_final_events_for_date(date_iso, LEAGUES)
                print(
                    f"[INFO] {date_iso} FINAL-like events found: {len(events)}",
                    flush=True,
                )

                for ev in events:
                    eid = ev.get("event_id")
                    if not eid:
                        continue

                    # Rolling ledger duplicate guard
                    if already_posted(ledger, eid):
                        print(f"[SKIP] already posted {eid}", flush=True)
                        continue

                    posted = post_once(ev, date_iso)
                    if posted:
                        # Only mark success if X accepted the tweet
                        mark_posted(ledger, eid)
                        save_ledger(ledger)
                        print(f"[POSTED] {eid} ({ev['sport']})", flush=True)
                    else:
                        print(
                            f"[WAIT] data not ready or post failed for {eid}; will retry",
                            flush=True,
                        )
        except Exception as e:
            print(f"[WARN] loop error: {e}", flush=True)

        time.sleep(POLL_EVERY_SECONDS)


if __name__ == "__main__":
    main()

