import os
import time
import datetime

from espn_adapter import get_final_like_events, fetch_wp_quick
from scoring import score_game
from vibe_tags import pick_vibe
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


# -----------------------------
# EI computation
# -----------------------------
def calc_ei_from_home_series(series_raw: list[float]) -> tuple[float, float]:
    """
    Given a raw home-team WP series (0..1 floats), compute:

        - ei_raw:   Σ |ΔWP|
        - ei_scaled: ei_raw * EI_SCALE, which is what we pass into scoring.py

    If the series is too short or malformed, returns (0.0, 0.0).
    """
    if not series_raw or len(series_raw) < 2:
        return 0.0, 0.0

    # Defensive copy + sanitize
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


# -----------------------------
# Formatting helpers
# -----------------------------
def _teams_line(game: dict) -> str:
    """
    Build a human-readable matchup string like:

        "Pistons @ Celtics — ESPN — FINAL"

    The broadcasting network is handled later; here we only assemble teams.
    """
    away = game.get("away") or {}
    home = game.get("home") or {}

    away_name = away.get("name") or away.get("abbrev") or "Away"
    home_name = home.get("name") or home.get("abbrev") or "Home"

    # Use scores if present
    away_score = away.get("score")
    home_score = home.get("score")

    if away_score is not None and home_score is not None:
        return f"{away_name} {away_score} @ {home_name} {home_score}"

    return f"{away_name} @ {home_name}"


def _date_line_from_iso(date_iso: str) -> str:
    """
    Convert an ISO date (YYYY-MM-DD) into a nice human-readable line like:

        "Wed · 11/26/25"
    """
    return to_weekday_mm_d_yy(date_iso)


def _compute_game_text(
    sport_lower: str,
    event_id: str,
    comp_id,
    game: dict,
    date_iso: str,
) -> tuple[int | None, str]:
    """
    Fetch WP, compute EI & score, and build the final post text string.
    """
    sport_up = sport_lower.upper()

    # Fetch WP series for this event; ESPN uses the event id for summary.
    series = fetch_wp_quick(sport_up, event_id)
    if not series:
        print(f"[WARN] no WP series for {sport_up} {event_id}", flush=True)
        return None, ""

    ei_scaled, ei_raw = calc_ei_from_home_series(series)
    result = score_game(sport_up, ei_scaled)
    score_val = result.score

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
    without touching the ledger. This keeps the console view complete.
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
    Logging flow for a *new* game (not in ledger yet):

      - compute EI & Rewatchability Score™
      - print the formatted text to stdout (Render logs)
      - mark as logged in the ledger so future runs do recap-only

    There is **no** posting to X here – this is purely a console/autopilot view.
    """
    score_val, text = _compute_game_text(sport_lower, event_id, comp_id, game, date_iso)
    if score_val is None:
        return False

    # Always show every scored game once in the logs.
    print(text, flush=True)
    print("-" * 40, flush=True)

    sport_up = sport_lower.upper()
    print(f"[LOGGED] {event_id} ({sport_up})", flush=True)

    # Mark as logged so future loops show recap-only instead of re-logging.
    mark_posted(ledger, event_id)
    save_ledger(ledger)
    return True


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
                games = get_final_like_events(sport_up, date_iso)
                if not games:
                    print(
                        f"[INFO] {date_iso} FINAL-like events found: 0",
                        flush=True,
                    )
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
