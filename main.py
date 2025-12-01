# main.py
import os
import time
import datetime
from zoneinfo import ZoneInfo
from typing import Dict, Any, List, Tuple

from espn_adapter import get_scoreboard
from inpredictable import fetch_excitement_map
from scoring import score_game
from vibe_tags import pick_vibe
from formatting import to_weekday_mm_d_yy
from posting_rules import should_auto_post
from ledger import (
    load_ledger,
    save_ledger,
    prune_ledger,
    already_posted,
    mark_posted,
)

# ----------------------------------------------------------------------
# Config
# ----------------------------------------------------------------------

POLL_SECONDS: int = int(os.getenv("POLL_SECONDS", "60"))
LEDGER_DAYS: int = int(os.getenv("LEDGER_DAYS", "7"))

# Basketball-only:
SPORTS: List[str] = ["NBA", "WNBA"]

# Use Los Angeles time (Pacific) for defining the "game day"
LOCAL_TZ = ZoneInfo("America/Los_Angeles")


def _today_iso_local() -> str:
    """
    Game-day date in Los Angeles time as YYYY-MM-DD.

    Rule:
      - From midnight until 5:59 AM PT, we still consider the "game day"
        to be *yesterday* (so late-night games and EI backfill are included).
      - From 6:00 AM PT onward, the game day is *today*.
    """
    now = datetime.datetime.now(LOCAL_TZ)
    if now.hour < 6:
        game_day = now.date() - datetime.timedelta(days=1)
    else:
        game_day = now.date()
    return game_day.isoformat()


def _date_line_from_iso(date_iso: str) -> str:
    """Format 'YYYY-MM-DD' -> 'Wed · 11/26/25' for console output."""
    try:
        return to_weekday_mm_d_yy(date_iso)
    except Exception:
        return date_iso


def _format_console_block(
    game: Dict[str, Any],
    sport: str,
    score_val: int,
    excite_raw: float,
    date_iso: str,
) -> str:
    """Build the console text we print for a single game."""
    vibe = pick_vibe(score_val)
    date_line = _date_line_from_iso(date_iso)
    network = (game.get("broadcast") or "").strip() or "Streaming / Local"

    # Full names preferred for display; abbreviations only as backup.
    away = game.get("away") or game.get("away_short") or "Away"
    home = game.get("home") or game.get("home_short") or "Home"

    lines = [
        f"🏀 {away} @ {home} — {network} — FINAL",
        f"Rewatchability Score™: {score_val}",
        vibe,
        date_line,
        f"(Excitement {excite_raw:.1f})",
        "-" * 40,
    ]
    return "\n".join(lines)


def _process_league_for_date(
    sport: str,
    date_iso: str,
    ledger: Dict[str, str],
) -> None:
    """
    Process one league (NBA or WNBA) for a given date.

    Logic:
      - Get full scoreboard from ESPN (no preseason – handled in espn_adapter).
      - Get Excitement map from inpredictable (PreCap pages).
      - Score every FINAL game that has Excitement.
      - Auto-post if national TV or score >= 70.
      - If (all games final) AND (every final game has Excitement) AND (no auto-posts),
        then post the single highest-scoring game as a fallback.
    """
    sport_up = sport.upper()
    print(f"[LOOP] checking {sport_up} for {date_iso}", flush=True)

    games = get_scoreboard(sport_up, date_iso)
    print(f"[ESPN] {len(games)} total {sport_up} events on {date_iso}", flush=True)

    if not games:
        return

    # ESPN perspective: are ALL games for this league/date marked final?
    all_final_flag = all(g.get("is_final") for g in games)

    # Pull Excitement from inpredictable PreCap for this league
    excite_map = fetch_excitement_map(sport_up)

    # Collect:
    #   - all_scored: games where we have Excitement and scored them
    #   - finals_without_ei: final games (per ESPN) that currently have no Excitement
    all_scored: List[Tuple[Dict[str, Any], int, float, bool]] = []
    finals_without_ei: List[Dict[str, Any]] = []

    for g in games:
        if not g.get("is_final"):
            continue

        away_short = g.get("away_short") or g.get("away") or ""
        home_short = g.get("home_short") or g.get("home") or ""
        key: Tuple[str, str] = (away_short, home_short)

        excite_raw = excite_map.get(key)
        if excite_raw is None:
            finals_without_ei.append(g)
            print(
                f"[WAIT] {sport_up} {g['id']} ({away_short} @ {home_short}) is FINAL "
                f"on ESPN but has no Excitement on PreCap yet.",
                flush=True,
            )
            continue

        # Score = 40 + 4 * Excitement (no scaling, capped at 99).
        result = score_game(sport_up, excite_raw)
        score_val = result.score

        network = (g.get("broadcast") or "").strip() or "Streaming / Local"
        auto_rule = should_auto_post(score_val, network, sport_up)

        all_scored.append((g, score_val, excite_raw, auto_rule))

        text_block = _format_console_block(
            game=g,
            sport=sport_up,
            score_val=score_val,
            excite_raw=excite_raw,
            date_iso=date_iso,
        )

        event_id = g["id"]

        if already_posted(ledger, event_id):
            print("[RECAP ONLY] (already posted this game before)", flush=True)
            print(text_block, flush=True)
            continue

        if auto_rule:
            # National TV or score >= threshold – this is a "featured" game.
            print(text_block, flush=True)
            mark_posted(ledger, event_id)
        else:
            # Below threshold & not national TV – just show as recap.
            print("[RECAP ONLY] (below threshold & not national)", flush=True)
            print(text_block, flush=True)

    # If we couldn't score *any* games, there's nothing more to do.
    if not all_scored:
        if finals_without_ei:
            print(
                f"[INFO] {sport_up} {date_iso}: final games missing Excitement; "
                "waiting for PreCap to catch up.",
                flush=True,
            )
        return

    any_auto = any(auto for (_, _, _, auto) in all_scored)

    # If at least one game met the auto-post rule, we do *not* need fallback.
    if any_auto:
        return

    # If not all games are final yet (per ESPN), DO NOT pick a fallback yet.
    if not all_final_flag:
        print(
            f"[FALLBACK] {sport_up} {date_iso}: no 70+ or national TV yet, "
            "but not all games are final. Waiting.",
            flush=True,
        )
        return

    # If some final games are still missing Excitement, DO NOT fallback yet.
    if finals_without_ei:
        print(
            f"[FALLBACK] {sport_up} {date_iso}: all games final on ESPN, "
            "but some finals have no Excitement on PreCap yet. Waiting.",
            flush=True,
        )
        return

    # At this point:
    #   - all games are final on ESPN,
    #   - every final game has Excitement,
    #   - none hit national / 70+.
    # Safe to pick the single highest-scoring game as fallback.
    best_game, best_score, best_raw, _ = max(
        all_scored,
        key=lambda tup: tup[1],
    )

    best_id = best_game["id"]
    if already_posted(ledger, best_id):
        print(
            f"[FALLBACK] {sport_up} {date_iso}: highest game {best_id} "
            "already marked posted.",
            flush=True,
        )
        return

    print(
        f"[FALLBACK] {sport_up} {date_iso}: no 70+ or national TV games; "
        f"posting top game {best_id}.",
        flush=True,
    )
    fb_text = _format_console_block(
        game=best_game,
        sport=sport_up,
        score_val=best_score,
        excite_raw=best_raw,
        date_iso=date_iso,
    )
    print(fb_text, flush=True)
    mark_posted(ledger, best_id)


def run() -> None:
    print("[RUN] starting Rewatchability autopilot (basketball only)", flush=True)
    ledger = load_ledger()
    prune_ledger(ledger, days=LEDGER_DAYS)

    while True:
        # Use "basketball night" based on Los Angeles time.
        date_iso = _today_iso_local()

        for sport in SPORTS:
            try:
                _process_league_for_date(sport, date_iso, ledger)
            except Exception as ex:
                print(f"[ERROR] exception while processing {sport}: {ex}", flush=True)

        save_ledger(ledger)
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    run()
