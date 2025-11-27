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

POLL_SECONDS: int = int(os.getenv("POLL_SECONDS", "120"))
LOOKBACK_DAYS: int = int(os.getenv("LOOKBACK_DAYS", "1"))
MIN_POST_SCORE: int = int(os.getenv("MIN_POST_SCORE", "70"))

# EI_SCALE keeps the live EI on the same scale as the offline CSVs we used
# to derive the constants in scoring.py. With 0.01 we’re in the 0.0–0.4 range
# that matches those distributions.
EI_SCALE: float = float(os.getenv("EI_SCALE", "0.01"))  # global scale so EI matches offline CSVs


# ----------------
# EI / WP helpers
# ----------------

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
        # formatting.to_weekday_mm_d_yy expects a string, so we pass date_iso through
        return to_weekday_mm_d_yy(date_iso)
    except Exception:
        return date_iso


def _date_range_to_poll(now_utc: datetime.datetime) -> list[str]:
    """
    Decide which dates (as ISO strings) to poll based on current UTC time.

    We generally want:
      - today (in UTC)
      - and a configurable lookback window in days (yesterday, day before, etc.)
    """
    today = now_utc.date()
    dates = []
    for delta in range(LOOKBACK_DAYS, -1, -1):
        d = today - datetime.timedelta(days=delta)
        dates.append(d.isoformat())
    return dates


# ----------------
# Core game logic
# ----------------

def _compute_game_text(
    sport_lower: str,
    event_id: str,
    comp_id,
    game: dict,
    date_iso: str,
):
    """
    Fetch WP series, compute EI and score, pick vibe tags, and render final text.

    Returns:
      (score_val: int | None, text: str | None)
    """
    sport_up = sport_lower.upper()
    scoring_key = _scoring_key_for_sport(sport_lower)

    # 1) Fetch win probability series
    series = fetch_wp_quick(sport_lower, event_id)
    if not series:
        print(f"[WARN] No WP data for {sport_up} {event_id}, skipping.", flush=True)
        return None, None

    # 2) Compute EI
    ei_scaled, ei_raw = calc_ei_from_home_series(series)

    # 3) Compute score (piecewise per sport)
    scored = score_game(scoring_key, ei_scaled)
    score_val = scored.score

    print(
        f"[EI] {sport_up} {event_id} raw={ei_raw:.3f} scaled={ei_scaled:.3f} score={score_val}",
        flush=True,
    )

    # 4) Pick vibe tags and format final text
    vibes = pick_vibe(
        sport=scoring_key,
        score=score_val,
        ei=ei_scaled,
        meta=game,
    )

    date_line = _date_line_from_iso(date_iso)
    text = format_post(
        sport=scoring_key,
        meta=game,
        score=score_val,
        ei=ei_scaled,
        vibes=vibes,
        date_line=date_line,
    )
    return score_val, text


# ---------------- Preview (no posting) ---------------- #

def _preview_game_only(
    sport_lower: str,
    event_id: str,
    comp_id,
    game: dict,
    date_iso: str,
):
    """
    Recompute EI & score and just print the would-be post text for a game
    that is already in the ledger.

    This is useful so the Render logs still show something for these games.
    """
    score_val, text = _compute_game_text(sport_lower, event_id, comp_id, game, date_iso)
    if score_val is None or text is None:
        return

    print(f"[PREVIEW-ONLY] {event_id} score={score_val}", flush=True)
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

    print(f"[ERROR] Failed to post {event_id}", flush=True)
    return False


# ---------------- Main autopilot loop ---------------- #

SPORTS = ["nba", "nfl", "mlb", "ncaaf", "ncaam"]


def run():
    """
    Main polling loop:
      - load / prune ledger
      - loop over sports
      - for each, figure out which dates to poll
      - fetch final-like events for those dates
      - for each event, decide whether to post or preview
      - sleep, repeat
    """
    print("[RUN] starting Rewatchability autopilot", flush=True)

    ledger = load_ledger()
    prune_ledger(ledger)
    save_ledger(ledger)

    while True:
        try:
            # Always use timezone-aware UTC now to avoid deprecation warnings.
            now_utc = datetime.datetime.now(datetime.timezone.utc)

            for sport_lower in SPORTS:
                # Determine which dates to poll for this sport
                dates_to_poll = _date_range_to_poll(now_utc)

                for date_iso in dates_to_poll:
                    print(f"[LOOP] checking {sport_lower.upper()} for {date_iso}", flush=True)

                    games = get_final_like_events(sport_lower, date_iso=date_iso)
                    if not games:
                        print(
                            f"[FOUND] 0 final-like {sport_lower.upper()} games on {date_iso}",
                            flush=True,
                        )
                        continue

                    print(
                        f"[FOUND] {len(games)} final-like {sport_lower.upper()} games on {date_iso}",
                        flush=True,
                    )

                    for g in games:
                        event_id = g.get("id")
                        comp = g.get("competitions", [{}])[0]
                        comp_id = comp.get("id")

                        if not event_id or not comp_id:
                            continue

                        # If we've already posted this game, just preview.
                        if already_posted(ledger, event_id):
                            _preview_game_only(sport_lower, event_id, comp_id, g, date_iso)
                            continue

                        # Otherwise, attempt a full post.
                        post_once(sport_lower, event_id, comp_id, g, date_iso, ledger)

        except Exception as e:
            print(f"[ERROR] top-level loop error: {e}", flush=True)

        # Sleep between polls
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    run()
