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

SPORTS = ["nba", "nfl", "mlb", "ncaaf", "ncaam"]


# ---------------- EI / scoring helpers ---------------- #

def calc_ei_from_home_series(series_raw):
    """
    Convert a raw home-win-probability series into Excitement Index (EI).
    EI = Σ |ΔWP| where WP is in [0,1].
    """
    if not series_raw or len(series_raw) < 2:
        return 0.0

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
        return 0.0

    diffs = [abs(series[i] - series[i - 1]) for i in range(1, len(series))]
    return float(sum(diffs))


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
    try:
        return to_weekday_mm_d_yy(date_iso)
    except Exception:
        return date_iso


# ---------------- Single-game posting flow ---------------- #

def post_once(sport_lower: str, event_id: str, comp_id, game: dict, date_iso: str, ledger: dict) -> bool:
    sport_up = sport_lower.upper()
    print(f"[GAME] {sport_up} {event_id} — fetching WP", flush=True)

    series = fetch_wp_quick(sport_lower, event_id, comp_id)
    if not series:
        print(f"[WP] no series for {event_id}", flush=True)
        return False

    ei = calc_ei_from_home_series(series)
    if ei <= 0.0:
        print(f"[EI] zero or invalid EI for {event_id}", flush=True)
        return False

    score_key = _scoring_key_for_sport(sport_lower)
    scored = score_game(score_key, ei)
    score_val = scored.score
    vibe = pick_vibe(score_val)

    date_line = _date_line_from_iso(date_iso)
    network = (game.get("broadcast") or "").strip() or "Streaming / Local"

    # Unified formatting (X/Threads style)
    text = format_post(
        game=game,
        score=score_val,
        vibe=vibe,
        date=date_line,
        sport=sport_up,
        neutral_site=False,  # can be wired later if needed
        network=network,
    )

    print(text, flush=True)
    print("-" * 40, flush=True)

    # This now calls the NO-OP stub in publisher_x.py
    if post_to_x(text):
        print(f"[POSTED] {event_id} ({sport_up})", flush=True)
        mark_posted(ledger, event_id)
        save_ledger(ledger)
        return True

    print(f"[FAIL] X post failed for {event_id}", flush=True)
    return False


# ---------------- Main autopilot loop ---------------- #

def _date_range_to_poll(now_utc: datetime.datetime) -> list[str]:
    today = now_utc.date()
    yesterday = today - datetime.timedelta(days=1)
    return [yesterday.isoformat(), today.isoformat()]

def run():
    print("[RUN] starting Rewatchability autopilot", flush=True)
    ledger = load_ledger()
    prune_ledger(ledger)

    while True:
        now_utc = datetime.datetime.utcnow()
        dates = _date_range_to_poll(now_utc)

        prune_ledger(ledger)

        for sport_lower in SPORTS:
            sport_up = sport_lower.upper()
            print(f"[LOOP] checking {sport_up}", flush=True)

            for date_iso in dates:
                games = get_final_like_events(sport_lower, date_iso)
                if not games:
                    continue

                print(f"[FOUND] {len(games)} final-like {sport_up} games on {date_iso}", flush=True)

                for g in games:
                    event_id = g["id"]
                    comp_id = g.get("competition_id")

                    if already_posted(ledger, event_id):
                        print(f"[SKIP] already posted {event_id}", flush=True)
                        continue

                    post_once(sport_lower, event_id, comp_id, g, date_iso, ledger)

        time.sleep(60)


if __name__ == "__main__":
    run()
