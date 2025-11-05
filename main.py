import time
from datetime import datetime, timedelta

from espn_adapter import list_final_events_for_date, fetch_win_probability_series
from scoring import score_game
from vibe_tags import vibe_tag_from_score
from posting_rules import format_post, format_video_caption

# Leagues to watch
LEAGUES = ["NBA", "NFL", "MLB", "NCAAM", "NCAAF"]

# How often to poll ESPN (seconds)
POLL_EVERY_SECONDS = 60

# Quick retry schedule for Win Probability per event (seconds from start of this pass)
# This gives you ~35 seconds of quick tries on each loop for fast posting.
WP_RETRY_SCHEDULE = [0, 10, 20, 35]


# -------------- helpers --------------

def to_mm_d_yy(date_iso: str) -> str:
    """YYYY-MM-DD -> M/D/YY"""
    d = datetime.strptime(date_iso, "%Y-%m-%d")
    return d.strftime("%m/%d/%y").lstrip("0").replace("/0", "/")

def today_iso_utc() -> str:
    return datetime.utcnow().strftime("%Y-%m-%d")

def yesterday_iso_utc() -> str:
    return (datetime.utcnow() - timedelta(days=1)).strftime("%Y-%m-%d")

def calc_ei_from_home_series(home_series: list[float]) -> float:
    """EI = sum of absolute changes in WP. Using HOME series is fine (same deltas as ROAD)."""
    if not home_series or len(home_series) < 2:
        return 0.0
    total = 0.0
    prev = home_series[0]
    for p in home_series[1:]:
        total += abs(p - prev)
        prev = p
    return total

def fetch_wp_quick(sport: str, event_id: str, comp_id: str) -> list[float] | None:
    """Try a few times quickly so we post fast when WP appears."""
    start = time.time()
    for i, target_s in enumerate(WP_RETRY_SCHEDULE):
        # wait until this attempt’s time
        sleep_for = target_s - (time.time() - start)
        if sleep_for > 0:
            time.sleep(sleep_for)

        series = fetch_win_probability_series(sport, event_id, comp_id)
        if series:
            if i > 0:
                print(f"[INFO] WP arrived on quick attempt {i+1}/{len(WP_RETRY_SCHEDULE)}")
            return series
    return None


# -------------- main posting core --------------

def post_once(ev: dict, date_iso: str) -> bool:
    """
    Try to fetch WP and post outputs for a single event.
    Returns True if posted, False if WP not ready yet.
    """
    sport = ev["sport"]
    road = ev["road"]
    home = ev["home"]
    network = ev["network"]        # shown in header text only if national
    neutral = ev["neutral_site"]
    event_name = ev["event_name"]  # added as 5th hashtag in video captions (when present)
    event_id = ev["event_id"]
    comp_id = ev["comp_id"]

    # Fast WP fetch
    home_wp = fetch_wp_quick(sport, event_id, comp_id)
    if not home_wp:
        # Not ready yet; the outer loop will try again next minute
        return False

    # EI -> Score -> Vibe
    ei = calc_ei_from_home_series(home_wp)
    score = score_game(sport, ei).score
    vibe = vibe_tag_from_score(score)

    # Build final outputs
    game = {"away": road, "home": home}
    date_line = to_mm_d_yy(date_iso)

    tweet = format_post(
        game=game,
        score=score,
        vibe=vibe,
        date=date_line,
        sport=sport,
        neutral_site=neutral,
        network=network
    )
    print(tweet.strip())
    print("-" * 40)

    caption = format_video_caption(
        game=game,
        score=score,
        vibe=vibe,
        date=date_line,
        sport=sport,
        neutral_site=neutral,
        network=network,
        is_national=bool(network),
        event_name=event_name
    )
    print(caption.strip())
    print("=" * 60)

    return True


def main():
    """
    Cloud mode:
      - Runs forever.
      - Every minute: checks yesterday + today.
      - For each “final-like” event: tries WP quickly, posts when ready.
      - Remembers posted events so it never duplicates.
    """
    posted_ids: set[str] = set()
    print("[RUN] Cloud worker started. Polling every 60s.")

    while True:
        try:
            today = today_iso_utc()
            yday = yesterday_iso_utc()

            # Check both dates to catch games that end near midnight ET
            for date_iso in (yday, today):
                events = list_final_events_for_date(date_iso, LEAGUES)
                for ev in events:
                    eid = ev.get("event_id")
                    if not eid or eid in posted_ids:
                        continue
                    if post_once(ev, date_iso):
                        posted_ids.add(eid)
        except Exception as e:
            # Keep running even if ESPN hiccups
            print(f"[WARN] loop error: {e}")

        time.sleep(POLL_EVERY_SECONDS)


if __name__ == "__main__":
    main()
