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


# ---------------- Env + global knobs ---------------- #

POLL_SECONDS = int(os.getenv("POLL_SECONDS", "120"))

# ESPN's raw EI (sum of |ΔWP|) is much larger than our calibrated ranges.
# Default: 1.0 (i.e., EI_raw is passed directly to scoring.py).
EI_SCALE = float(os.getenv("ESPN_EI_SCALE", "1.0"))

# Minimum score to actually POST a game to X (legacy guard; we now use
# explicit posting rules below, but this can still be used if needed).
MIN_POST_SCORE = int(os.getenv("MIN_POST_SCORE", "90"))


# ---------------- Posting rules helper ---------------- #

def _meets_posting_rules(sport_up: str, score_val: int, network: str) -> bool:
    """
    PRO (NBA / NFL / MLB):
      - Post ALL national TV games (network != "Streaming / Local")
      - Post any other game with score >= 70

    COLLEGE (NCAAF / NCAAB):
      - Post ONLY if national TV AND score >= 70
    """
    sport_up = sport_up.upper()
    network = (network or "").strip() or "Streaming / Local"
    is_national = network != "Streaming / Local"
    is_college = sport_up in ("NCAAF", "NCAAB", "NCAAM", "CBB")

    if is_college:
        return is_national and score_val >= 70
    else:
        return is_national or score_val >= 70


# -----
# EI / scoring helpers
# -----

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
        if val < 0.0:
            val = 0.0
        if val > 1.0:
            val = 1.0
        series.append(val)

    if len(series) < 2:
        return 0.0, 0.0

    ei_raw = 0.0
    prev = series[0]
    for x in series[1:]:
        ei_raw += abs(x - prev)
        prev = x

    ei_scaled = ei_raw * EI_SCALE
    return ei_scaled, ei_raw


def _date_line_from_iso(date_iso: str) -> str:
    d = datetime.date.fromisoformat(date_iso)
    return to_weekday_mm_d_yy(d)


def _compute_game_text(sport_lower: str, event_id: str, comp_id, game: dict, date_iso: str):
    """
    Fetch WP, compute EI, score, vibe, and render the final post text.
    Returns:
      (score_val, text) or (None, None) on failure.
    """
    sport_up = sport_lower.upper()

    # Fetch win-probability series and compute EI
    series = fetch_wp_quick(sport_lower, event_id, comp_id)
    if not series:
        print(f"[WARN] no WP series for {sport_up} {event_id}", flush=True)
        return None, None

    ei_scaled, ei_raw = calc_ei_from_home_series(series)

    scored = score_game(sport_up, ei_scaled)
    score_val = scored.score

    # Log EI + score so we can see how things look:
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


# ---------------- Recap for already-posted games ---------------- #

def recap_already_posted(
    sport_lower: str,
    event_id: str,
    comp_id,
    game: dict,
    date_iso: str,
) -> None:
    """
    Used when ledger says we've already posted this game.
    We still want a recap in logs if it's worth talking about,
    but avoid duplicate X posts.
    """
    score_val, text = _compute_game_text(sport_lower, event_id, comp_id, game, date_iso)
    if score_val is None:
        return

    sport_up = sport_lower.upper()
    network = (game.get("broadcast") or "").strip() or "Streaming / Local"
    if not _meets_posting_rules(sport_up, score_val, network):
        print(
            f"[RECAP SKIP] {sport_up} {event_id} score={score_val} "
            f"network='{network}' (posting rules)",
            flush=True,
        )
        return

    print(f"[RECAP] already posted {event_id} — preview only", flush=True)
    print(text, flush=True)
    print("-" * 40, flush=True)


# ---------------- Posting for new games ---------------- #

def post_once(sport_lower: str, event_id: str, comp_id, game: dict, date_iso: str, ledger: dict) -> bool:
    """
    Full posting flow for a *new* game (not in ledger yet):
      - compute EI & score
      - apply national-TV + 70+ posting rules
      - print post text
      - call post_to_x
      - mark as posted in ledger on success
    """
    score_val, text = _compute_game_text(sport_lower, event_id, comp_id, game, date_iso)
    if score_val is None:
        return False

    sport_up = sport_lower.upper()
    network = (game.get("broadcast") or "").strip() or "Streaming / Local"
    if not _meets_posting_rules(sport_up, score_val, network):
        print(
            f"[SKIP] {sport_up} {event_id} score={score_val} "
            f"network='{network}' (posting rules)",
            flush=True,
        )
        return False

    print(text, flush=True)
    print("-" * 40, flush=True)

    # This calls the post stub in publisher_x.py (wired to X in production).
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
    Poll both today (UTC) and "yesterday" so that late-night games
    still get picked up correctly regardless of timezone.
    """
    today = now_utc.date()
    yesterday = today - datetime.timedelta(days=1)
    return [
        yesterday.isoformat(),
        today.isoformat(),
    ]


def run_once(now_utc: datetime.datetime | None = None):
    """
    One full polling cycle across all supported sports.
    """
    if now_utc is None:
        now_utc = datetime.datetime.utcnow()

    dates = _date_range_to_poll(now_utc)

    # Load and prune ledger (to prevent it from growing forever)
    ledger = load_ledger()
    prune_ledger(ledger)

    sports = [
        ("nba", "NBA"),
        ("nfl", "NFL"),
        ("mlb", "MLB"),
        ("ncaaf", "NCAAF"),
        ("ncaab", "NCAAB"),
    ]

    for sport_lower, sport_up in sports:
        for date_iso in dates:
            print(f"[LOOP] checking {sport_up} for {date_iso}", flush=True)
            events = get_final_like_events(sport_lower, date_iso)
            print(
                f"[FOUND] {len(events)} final-like {sport_up} games on {date_iso}",
                flush=True,
            )

            for game in events:
                event_id = str(game["id"])
                comp_id = game.get("competition_id")

                if already_posted(ledger, event_id):
                    recap_already_posted(sport_lower, event_id, comp_id, game, date_iso)
                else:
                    post_once(sport_lower, event_id, comp_id, game, date_iso, ledger)


def main():
    print("[RUN] starting Rewatchability autopilot", flush=True)
    while True:
        try:
            now_utc = datetime.datetime.utcnow()
            run_once(now_utc)
        except Exception as e:
            print(f"[ERROR] top-level loop error: {e}", flush=True)
        print(f"[SLEEP] {POLL_SECONDS} seconds", flush=True)
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
