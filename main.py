import os
import time
import datetime

from espn_adapter import get_final_like_events, fetch_wp_quick
from scoring import score_game
from vibe_tags import pick_vibe
from publisher_x import post_to_x
from formatting import to_weekday_mm_d_yy
from posting_rules import format_post
from ledger import (
    load_ledger,
    save_ledger,
    prune_ledger,
    already_posted,
    mark_posted,
)

# ------
# Config
# ------

# All sports we want the bot to cover
SPORTS = ["nba", "nfl", "mlb", "ncaaf", "ncaab"]

# ESPN's raw EI (sum of |ΔWP|) is much larger than our calibrated ranges.
# We discovered that the historical EI CSVs used a scale of 0.01 on that raw sum.
# So to keep live scores aligned with those constants, we must use the same scale.
EI_SCALE = float(os.getenv("ESPN_EI_SCALE", "0.01"))

# Minimum score to actually POST to X (preview still shows everything).
# This can be overridden via env, but default is set to 70 for "must-watch" tier.
MIN_POST_SCORE = int(os.getenv("MIN_POST_SCORE", "70"))


# -----------------------------
# EI computation helper
# -----------------------------
def calc_ei_from_home_series(series_raw: list[float]) -> tuple[float, float]:
    """
    Given a list of home win probabilities (0.0–1.0),
    compute the Excitement Index (EI).

    Returns:
      (ei_scaled, ei_raw)

    Where:
      - ei_raw = sum(|ΔWP|)
      - ei_scaled = ei_raw * EI_SCALE, which is what we pass into scoring.py
        (and what the historical EI CSVs are based on).
    """
    series: list[float] = []

    for val in series_raw:
        # Some ESPN feeds may be 0–100; normalize those.
        if val > 1.0:
            val = val / 100.0
        # Clamp to [0, 1] defensively.
        if val < 0.0 or val > 1.0:
            continue
        series.append(val)

    if len(series) < 2:
        return 0.0, 0.0

    diffs = [abs(series[i] - series[i - 1]) for i in range(1, len(series))]
    ei_raw = float(sum(diffs))

    # Shrink to better match our calibrated EI range.
    ei_scaled = ei_raw * EI_SCALE
    return ei_scaled, ei_raw


def _scoring_key_for_sport(sport_lower: str) -> str:
    """
    Map ESPN sport keys into scoring.py keys.
    """
    s = sport_lower.lower()
    if s == "ncaam":
        return "ncaab"  # scoring uses "ncaab"
    return s


def _date_line_from_iso(date_iso: str) -> str:
    """
    Turn 'YYYY-MM-DD' into the pretty line used in the post copy,
    e.g. "Wednesday 11/26/25".
    """
    return to_weekday_mm_d_yy(date_iso)


# -----------------------------
# Core per-game compute + text
# -----------------------------
def _compute_game_text(
    sport_lower: str,
    event_id: str,
    comp_id,
    game: dict,
    date_iso: str,
):
    """
    Shared logic to:
      - fetch WP series
      - compute EI (raw + scaled)
      - compute Rewatchability Score
      - build the formatted text post

    Returns:
      (score_val, text) on success, or (None, None) if something went wrong.
    """
    sport_up = sport_lower.upper()
    print(f"[GAME] {sport_up} {event_id} — fetching WP", flush=True)

    # NOTE: fetch_wp_quick now requires competition_id as well.
    series = fetch_wp_quick(sport_lower, event_id, comp_id)
    if not series:
        print(f"[WARN] no WP data for {event_id}, skipping.", flush=True)
        return None, None

    ei_scaled, ei_raw = calc_ei_from_home_series(series)

    scoring_key = _scoring_key_for_sport(sport_lower)
    scored = score_game(scoring_key, ei_scaled)
    score_val = scored.score

    # Debug line so we can see how things look:
    print(
        f"[EI] {sport_up} {event_id} raw={ei_raw:.3f} "
        f"scaled={ei_scaled:.3f} score={score_val}",
        flush=True,
    )

    vibe = pick_vibe(score_val)
    date_line = _date_line_from_iso(date_iso)
    network = (game.get("broadcast") or "").strip() or "Streaming / Local"

    text = format_post(
        game=game,
        score=score_val,
        vibe=vibe,
        date=date_line,
        sport=sport_up,
        neutral_site=False,  # can be wired later if needed
        network=network,
    )

    return score_val, text


def _preview_game_only(
    sport_lower: str,
    event_id: str,
    comp_id,
    game: dict,
    date_iso: str,
) -> None:
    """
    Recompute EI/score and print the formatted text for an already-posted game,
    WITHOUT posting to X or touching the ledger.

    This gives you the "continuous showing of games" you liked,
    but avoids duplicate X posts.
    """
    score_val, text = _compute_game_text(sport_lower, event_id, comp_id, game, date_iso)
    if score_val is None:
        return

    print("[RECAP ONLY] (already posted)", flush=True)
    print(text, flush=True)
    print("-" * 40, flush=True)


def post_once(
    sport_lower: str,
    event_id: str,
    comp_id,
    game: dict,
    date_iso: str,
    ledger: dict,
) -> bool:
    """
    Full posting flow for a *new* game (not in ledger yet):
      - compute EI & score
      - skip if below MIN_POST_SCORE
      - print post text
      - call post_to_x
      - mark as posted in ledger on success
    """
    score_val, text = _compute_game_text(sport_lower, event_id, comp_id, game, date_iso)
    if score_val is None:
        return False

    # Don't post low/medium games – only strong ones.
    if score_val < MIN_POST_SCORE:
        print(
            f"[SKIP] score {score_val} < MIN_POST_SCORE={MIN_POST_SCORE} "
            f"for {event_id}",
            flush=True,
        )
        return False

    print(text, flush=True)
    print("-" * 40, flush=True)

    # This calls the NO-OP stub in publisher_x.py for now.
    if post_to_x(text):
        sport_up = sport_lower.upper()
        print(f"[POSTED] {event_id} ({sport_up})", flush=True)
        mark_posted(ledger, event_id)
        save_ledger(ledger)
        return True

    print(f"[FAIL] X post failed for {event_id}", flush=True)
    return False


# -----------------------------
# Date polling window
# -----------------------------
def _date_range_to_poll(now_utc: datetime.datetime) -> list[str]:
    """
    Poll both yesterday and today in UTC date terms.

    We return ISO date strings, not datetime objects, so that:
      - get_final_like_events(...) sees a date string
      - to_weekday_mm_d_yy(...) also sees a date string
    """
    today = now_utc.date()
    yesterday = today - datetime.timedelta(days=1)
    return [yesterday.isoformat(), today.isoformat()]


# -----------------------------
# Main loop
# -----------------------------
def run():
    print("[RUN] starting Rewatchability autopilot", flush=True)
    ledger = load_ledger()
    prune_ledger(ledger)

    while True:
        # Use timezone-aware UTC to avoid deprecation warning
        now_utc = datetime.datetime.now(datetime.timezone.utc)
        dates = _date_range_to_poll(now_utc)

        prune_ledger(ledger)

        for sport_lower in SPORTS:
            sport_up = sport_lower.upper()
            print(f"[LOOP] checking {sport_up}", flush=True)

            for date_iso in dates:
                # IMPORTANT: get_final_like_events(sport_lower, date_str)
                # We pass the date as a positional arg (string), not date_iso=...
                games = get_final_like_events(sport_lower, date_iso)
                if not games:
                    continue

                print(
                    f"[FOUND] {len(games)} final-like {sport_up} games on {date_iso}",
                    flush=True,
                )

                for g in games:
                    event_id = g["id"]
                    comp_id = g.get("competition_id")

                    if already_posted(ledger, event_id):
                        # Instead of just skipping silently, recompute and print
                        # a preview so the console always shows all games.
                        _preview_game_only(sport_lower, event_id, comp_id, g, date_iso)
                        continue

                    post_once(sport_lower, event_id, comp_id, g, date_iso, ledger)

        # Sleep between polls
        time.sleep(60)


if __name__ == "__main__":
    run()
