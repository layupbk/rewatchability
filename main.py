# main.py — Basketball-only, Inpredictable EI, ESPN scoreboard, clean formatting
import os
import time
import datetime
from zoneinfo import ZoneInfo
from typing import Dict, Any, List, Tuple, Optional

from espn_adapter import get_scoreboard
from inpredictable import fetch_excitement_map
from scoring import score_game
from vibe_tags import pick_vibe
from formatting import to_weekday_mm_d_yy
from posting_rules import should_auto_post
from ledger import load_ledger, save_ledger, prune_ledger, already_posted, mark_posted

# ----------------------------------------------------------------------
# Config
# ----------------------------------------------------------------------

POLL_SECONDS: int = int(os.getenv("POLL_SECONDS", "60"))
LEDGER_DAYS: int = int(os.getenv("LEDGER_DAYS", "7"))

# Basketball-only:
SPORTS: List[str] = ["NBA", "WNBA"]

# Use Los Angeles time (Pacific) for defining the "game day"
LOCAL_TZ = ZoneInfo("America/Los_Angeles")

# Mapping you provided: ESPN scores-page team name -> Inpredictable code
NAME_TO_INPRED: Dict[str, str] = {
    # NBA
    "Hawks": "ATL",
    "Nets": "BKN",
    "Celtics": "BOS",
    "Hornets": "CHA",
    "Bulls": "CHI",
    "Cavaliers": "CLE",
    "Mavericks": "DAL",
    "Nuggets": "DEN",
    "Pistons": "DET",
    "Warriors": "GSW",
    "Rockets": "HOU",
    "Pacers": "IND",
    "Clippers": "LAC",
    "Lakers": "LAL",
    "Grizzlies": "MEM",
    "Heat": "MIA",
    "Bucks": "MIL",
    "Timberwolves": "MIN",
    "Pelicans": "NOP",
    "Knicks": "NYK",
    "Thunder": "OKC",
    "Magic": "ORL",
    "76ers": "PHI",
    "Suns": "PHX",
    "Trail Blazers": "POR",
    "Kings": "SAC",
    "Spurs": "SAS",
    "Raptors": "TOR",
    "Jazz": "UTA",
    "Wizards": "WAS",

    # WNBA
    "Lynx": "MIN",
    "Dream": "ATL",
    "Fever": "IND",
    "Aces": "LVA",
    "Liberty": "NYL",
    "Sparks": "LAS",
    "Mercury": "PHX",
    "Storm": "SEA",
    "Valkyries": "GSV",
    "Wings": "DAL",
    "Mystics": "WAS",
    "Sky": "CHI",
    "Sun": "CON",
}


# ----------------------------------------------------------------------
# Date logic – 8:59 AM PT cutoff
# ----------------------------------------------------------------------

def _today_iso_local() -> str:
    """
    Game-day date in Los Angeles time as YYYY-MM-DD.

    Rule:
      - From midnight up to 8:59 AM PT (hour 0–8), we still consider the "game day"
        to be *yesterday* (to catch all late games + late EI updates).
      - From 9:00 AM PT onward (hour >= 9), the game day is *today*.
    """
    now = datetime.datetime.now(LOCAL_TZ)
    if now.hour < 9:
        game_day = now.date() - datetime.timedelta(days=1)
    else:
        game_day = now.date()
    return game_day.isoformat()


def _format_date(date_iso: str) -> str:
    """Format 'YYYY-MM-DD' -> 'Sun · 11/30/25' for console output."""
    try:
        return to_weekday_mm_d_yy(date_iso)
    except Exception:
        return date_iso


# ----------------------------------------------------------------------
# Formatting
# ----------------------------------------------------------------------

def _format_block(
    game: Dict[str, Any],
    score_val: int,
    excite_raw: Optional[float],
    date_iso: str,
) -> str:
    """
    Build the console block for a single game.

    - Uses team nicknames only (e.g. "Celtics", "Knicks").
    - Shows network only if it's national/international (set in espn_adapter).
    - Shows Excitement at the bottom for *internal reference only*.
    """
    away = game.get("away") or game.get("away_short") or "Away"
    home = game.get("home") or game.get("home_short") or "Home"

    network = (game.get("broadcast") or "").strip()
    headline = f"🏀 {away} @ {home}"
    if network:
        headline += f" — {network}"
    headline += " — FINAL"

    vibe = pick_vibe(score_val)
    date_line = _format_date(date_iso)

    if excite_raw is None:
        excite_line = "(Excitement unavailable yet)"
    else:
        excite_line = f"(Excitement {excite_raw:.1f})"

    lines = [
        headline,
        f"Rewatchability Score™: {score_val}",
        vibe,
        date_line,
        excite_line,
        "-" * 40,
    ]
    return "\n".join(lines)


# ----------------------------------------------------------------------
# League processing
# ----------------------------------------------------------------------

def _process_league(
    sport: str,
    date_iso: str,
    ledger: Dict[str, str],
) -> None:
    """
    Process NBA or WNBA for a given date.

    Flow:
      - Get ESPN scoreboard (no preseason – handled in espn_adapter).
      - Pull Excitement map from inpredictable (PreCap).
      - For every FINAL game:
          * Map ESPN team names -> Inpredictable codes
          * Look up Excitement
          * Compute score = 40 + 4 * EI (capped at 99 in scoring.py)
          * Apply auto-post rules (national TV or 70+)
          * Print block for EVERY game (posted or recap)
      - Fallback: if *no* game is national/70+ and all games are final & have EI,
        post the single top game.
    """
    sport_up = sport.upper()
    print(f"[LOOP] checking {sport_up} for {date_iso}", flush=True)

    games = get_scoreboard(sport_up, date_iso)
    print(f"[ESPN] {len(games)} total {sport_up} events on {date_iso}", flush=True)

    if not games:
        return

    # Are all games for this date & league final (per ESPN)?
    all_final_flag = all(g.get("is_final") for g in games)

    # Excitement from Inpredictable PreCap (cached inside module)
    excite_map = fetch_excitement_map(sport_up)

    # Keep all scored outcomes + track finals missing EI
    scored_rows: List[Tuple[Dict[str, Any], int, Optional[float], bool]] = []
    finals_missing_ei: List[Dict[str, Any]] = []

    for g in games:
        if not g.get("is_final"):
            continue

        away_name = g.get("away") or ""
        home_name = g.get("home") or ""

        away_code = NAME_TO_INPRED.get(away_name)
        home_code = NAME_TO_INPRED.get(home_name)

        excite_raw: Optional[float] = None
        if away_code and home_code:
            excite_raw = excite_map.get((away_code, home_code))

        if excite_raw is None:
            finals_missing_ei.append(g)
            print(
                f"[WAIT] {sport_up} {g.get('id')} "
                f"({away_name} @ {home_name}) has no Excitement yet.",
                flush=True,
            )

        # Score: if EI is missing, we still compute from 0 for display,
        # but we will NOT use those games in fallback until EI is present.
        raw_for_scoring = excite_raw if excite_raw is not None else 0.0
        result = score_game(sport_up, raw_for_scoring)
        score_val = result.score

        network = (g.get("broadcast") or "").strip()
        auto_rule = should_auto_post(score_val, network, sport_up)

        block = _format_block(
            game=g,
            score_val=score_val,
            excite_raw=excite_raw,
            date_iso=date_iso,
        )

        event_id = g["id"]

        if already_posted(ledger, event_id):
            print("[RECAP ONLY] (already posted this game before)", flush=True)
            print(block, flush=True)
        else:
            if auto_rule:
                print(block, flush=True)
                mark_posted(ledger, event_id)
            else:
                print("[RECAP ONLY] (below threshold / not national)", flush=True)
                print(block, flush=True)

        scored_rows.append((g, score_val, excite_raw, auto_rule))

    # If nothing was final / scored, we're done.
    if not scored_rows:
        if finals_missing_ei:
            print(
                f"[INFO] {sport_up} {date_iso}: finals missing Excitement; "
                "waiting for PreCap.",
                flush=True,
            )
        return

    # If any game already met auto-post rules (national or 70+),
    # we don't need fallback.
    if any(auto for (_, _, _, auto) in scored_rows):
        return

    # If not all games are final, don't fallback yet.
    if not all_final_flag:
        print(
            f"[FALLBACK] {sport_up} {date_iso}: no 70+ or national TV yet, "
            "but not all games are final. Waiting.",
            flush=True,
        )
        return

    # If some finals are still missing EI, don't fallback yet.
    if finals_missing_ei:
        print(
            f"[FALLBACK] {sport_up} {date_iso}: all games final, "
            "but some have no EI yet. Waiting.",
            flush=True,
        )
        return

    # Fallback: all finals, all EI present, none 70+/national.
    # Choose highest score.
    best_game, best_score, best_raw, _ = max(
        scored_rows,
        key=lambda tup: tup[1],
    )

    best_id = best_game["id"]
    if already_posted(ledger, best_id):
        print(
            f"[FALLBACK] {sport_up} {date_iso}: top game {best_id} "
            "already posted.",
            flush=True,
        )
        return

    print(
        f"[FALLBACK] {sport_up} {date_iso}: posting top game {best_id}.",
        flush=True,
    )
    fb_block = _format_block(
        game=best_game,
        score_val=best_score,
        excite_raw=best_raw,
        date_iso=date_iso,
    )
    print(fb_block, flush=True)
    mark_posted(ledger, best_id)


# ----------------------------------------------------------------------
# Main loop
# ----------------------------------------------------------------------

def run() -> None:
    print("[RUN] starting Rewatchability autopilot (basketball only)", flush=True)
    ledger = load_ledger()
    prune_ledger(ledger, days=LEDGER_DAYS)

    while True:
        date_iso = _today_iso_local()

        for sport in SPORTS:
            try:
                _process_league(sport, date_iso, ledger)
            except Exception as ex:
                print(f"[ERROR] exception while processing {sport}: {ex}", flush=True)

        save_ledger(ledger)
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    run()
