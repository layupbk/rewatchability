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

# -------------------------------------------------------------------
# SPORTS: only run in-season sports to keep logs clean.
# Add "mlb" / "ncaaf" back in when those are active and endpoints work.
# -------------------------------------------------------------------
SPORTS = ["nba", "nfl", "ncaam"]

# -------------------------------------------------------------------
# Tuning knobs (can also be overridden via Render env vars)
# -------------------------------------------------------------------

# ESPN's raw EI (sum of |ΔWP|) is much larger than our calibrated ranges.
# We shrink it before feeding into scoring.py so scores don't slam into 100.
# Default: 0.02 (i.e., EI_raw * 0.02).
EI_SCALE = float(os.getenv("ESPN_EI_SCALE", "0.02"))

# Minimum score to actually POST a game to X. Everything below just prints
# debug info and is skipped for posting.
MIN_POST_SCORE = int(os.getenv("MIN_POST_SCORE", "90"))


# ---------------- EI / scoring helpers ---------------- #

def calc_ei_from_home_series(series_raw):
    """
    Convert a raw home-win-probability series into Excitement Index (EI).

    EI_raw = Σ |ΔWP| where WP is in [0,1].

    Returns:
      (ei_scaled, ei_raw)
      - ei_raw: the raw sum of |ΔWP|
      - ei_scaled: ei_raw * EI_SCALE, which is what we pass into scoring.py
    """
    if not series_raw or len(series_raw) < 2:
        return 0.0, 0.0

    series = []
    for p in series_raw:
        try:
            val = float(p)
        except (TypeError, ValueError):
            continue

        # Normalize 0–100 -> 0–1 if needed
        if val > 1.0:
            val /= 100.0

        # Clamp to [0,1]
        if val < 0.0:
            val = 0.0
        if val > 1.0:
            val = 1.0

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
        return "NCAAB"   # scoring.py expects NCAAB for college hoops
    if s == "ncaaf":
        return "NCAAF"
    return s.upper()     # NBA, NFL, MLB


def _date_line_from_iso(date_iso: str) -> str:
    """
    Format an ISO date string (YYYY-MM-DD) into a short "weekday · mm/dd/yy" string.
    """
    try:
        return to_weekday_mm_d_yy(date_iso)
    except Exception:
        return date_iso


# ---------------- Core game evaluation ---------------- #

def _compute_game_text(sport_lower: str, event_id: str, comp_id, game: dict, date_iso: str):
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

    series = fetch_wp_quick(sport_lower, event_id, comp_id)
    if not series:
        print(f"[WP] no series for {event_id}", flush=True)
        return None, None

    ei_scaled, ei_raw = calc_ei_from_home_series(series)
    if ei_scaled <= 0.0:
        print(f"[EI] zero or invalid EI for {event_id}", flush=True)
        return None, None

    score_key = _scoring_key_for_sport(sport_lower)
    scored = score_game(score_key, ei_scaled)
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


def _preview_game_only(sport_lower: str, event_id: str, comp_id, game: dict, date_iso: str) -> None:
    """
    Recompute EI/score and print the formatted text for an already-posted game,
    WITHOUT posting to X or touching the ledger.

    This gives you the "continuous showing of games" you liked,
    but avoids duplicate X posts.
    """
    score_val, text = _compute_game_text(sport_lower, event_id, comp_id, game, date_iso)
    if score_val is None:
        return

    # Only preview games that meet the posting threshold, so logs stay meaningful.
    if score_val < MIN_POST_SCORE:
        print(
            f"[RECAP SKIP] score {score_val} < MIN_POST_SCORE={MIN_POST_SCORE} "
            f"for already-posted {event_id}",
            flush=True,
        )
        return

    print(f"[RECAP] already posted {event_id} — preview only", flush=True)
    print(text, flush=True)
    print("-" * 40, flush=True)


# ---------------- Single-game posting flow ---------------- #

def post_once(sport_lower: str, event_id: str, comp_id, game: dict, date_iso: str, ledger: dict) -> bool:
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


# ---------------- Main autopilot loop ---------------- #

def _date_range_to_poll(now_utc: datetime.datetime) -> list[str]:
    """
    Poll both yesterday and today in UTC date terms.
    """
    today = now_utc.date()
    yesterday = today - datetime.timedelta(days=1)
    return [yesterday.isoformat(), today.isoformat()]


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
                        # NEW: instead of just "[SKIP] already posted", we
                        # recompute and print a preview without posting to X.
                        _preview_game_only(sport_lower, event_id, comp_id, g, date_iso)
                        continue

                    post_once(sport_lower, event_id, comp_id, g, date_iso, ledger)

        # Sleep between polls
        time.sleep(60)


if __name__ == "__main__":
    run()
