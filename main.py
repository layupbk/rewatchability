# main.py — Basketball-only, Inpredictable EI, ESPN scoreboard, clean formatting
import os
import time
import datetime
from zoneinfo import ZoneInfo
from typing import Dict, Any, List

from espn_adapter import get_scoreboard
from inpredictable import fetch_excitement_map
from scoring import score_game
from vibe_tags import pick_vibe
from formatting import to_weekday_mm_d_yy
from posting_rules import should_auto_post
from ledger import load_ledger, save_ledger, prune_ledger, already_posted, mark_posted

# --- CONFIG ---------------------------------------------------------------

POLL_SECONDS: int = int(os.getenv("POLL_SECONDS", "60"))
LEDGER_DAYS: int = int(os.getenv("LEDGER_DAYS", "7"))
SPORTS: List[str] = ["NBA", "WNBA"]

LOCAL_TZ = ZoneInfo("America/Los_Angeles")

# Mapping user provided: ESPN name → Inpredictable 3-letter code
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


# --- DATE LOGIC -----------------------------------------------------------

def _today_iso_local() -> str:
    """
    LA-based game day:
      - From midnight up to 8:59 AM PT, we still treat the "game day" as *yesterday*.
      - From 9:00 AM PT onward, the game day is *today*.
    """
    now = datetime.datetime.now(LOCAL_TZ)
    if now.hour < 9:
        day = now.date() - datetime.timedelta(days=1)
    else:
        day = now.date()
    return day.isoformat()


def _format_date(date_iso: str) -> str:
    try:
        return to_weekday_mm_d_yy(date_iso)
    except Exception:
        return date_iso


# --- FORMATTING -----------------------------------------------------------

def _format_block(
    game: Dict[str, Any],
    score_val: int,
    excite_raw: float | None,
    date_iso: str,
) -> str:
    """Print block for Render logs."""
    away = game["away"]
    home = game["home"]

    date_line = _format_date(date_iso)
    vibe = pick_vibe(score_val)

    if excite_raw is None:
        excite_line = "(Excitement unavailable yet)"
    else:
        # Internal-only reference; never public-facing.
        excite_line = f"(Excitement {excite_raw:.1f})"

    lines = [
        f"🏀 {away} @ {home} — FINAL",
        f"Rewatchability Score™: {score_val}",
        vibe,
        date_line,
        excite_line,
        "-" * 40,
    ]
    return "\n".join(lines)


# --- MAIN PROCESSING ------------------------------------------------------

def _process_league(sport: str, date_iso: str, ledger: Dict[str, str]) -> None:
    print(f"[LOOP] checking {sport} for {date_iso}", flush=True)

    games = get_scoreboard(sport, date_iso)
    print(f"[ESPN] {len(games)} total {sport} events on {date_iso}", flush=True)
    if not games:
        return

    all_final = all(g["is_final"] for g in games)

    # Uses the newer inpredictable.py signature: (league, date_iso)
    excite_map = fetch_excitement_map(sport, date_iso)

    scored = []
    finals_missing_ei = []

    for g in games:
        if not g["is_final"]:
            continue

        away = g["away"]
        home = g["home"]

        away_code = NAME_TO_INPRED.get(away)
        home_code = NAME_TO_INPRED.get(home)

        excite_raw = None
        if away_code and home_code:
            excite_raw = excite_map.get((away_code, home_code))

        if excite_raw is None:
            finals_missing_ei.append(g)
            print(
                f"[WAIT] {sport} {g['id']} ({away} @ {home}) has no Excitement yet.",
                flush=True,
            )

        # If EI missing, we still compute a placeholder score from 0 for display,
        # but this game will not be used for fallback until EI is present.
        score_val = score_game(sport, excite_raw or 0).score
        auto_rule = should_auto_post(score_val, g.get("broadcast"), sport)

        block = _format_block(g, score_val, excite_raw, date_iso)

        if already_posted(ledger, g["id"]):
            print("[RECAP ONLY] (already posted this game before)", flush=True)
            print(block, flush=True)
        else:
            if auto_rule:
                print(block, flush=True)
                mark_posted(ledger, g["id"])
            else:
                print("[RECAP ONLY]", flush=True)
                print(block, flush=True)

        scored.append((g, score_val, excite_raw, auto_rule))

    # --- Fallback logic ---------------------------------------------------

    # If any game met auto-post rules (national TV or 70+), no fallback.
    if any(a for (_, _, _, a) in scored):
        return

    # If not all games are final yet, do nothing.
    if not all_final:
        print(
            f"[FALLBACK] {sport} {date_iso}: no 70+ or national TV yet, "
            "but not all games are final. Waiting.",
            flush=True,
        )
        return

    # If some finals still don’t have EI, don’t fallback yet.
    if finals_missing_ei:
        print(
            f"[FALLBACK] {sport} {date_iso}: all games final, "
            "but some have no EI yet. Waiting.",
            flush=True,
        )
        return

    # Safe fallback: highest score among all fully-EI games.
    best_game, best_score, best_raw, _ = max(
        scored,
        key=lambda t: t[1],
    )

    if not already_posted(ledger, best_game["id"]):
        print(f"[FALLBACK] {sport} posting top game {best_game['id']}", flush=True)
        print(_format_block(best_game, best_score, best_raw, date_iso), flush=True)
        mark_posted(ledger, best_game["id"])


# --- MAIN LOOP ------------------------------------------------------------

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
                print(f"[ERROR] {sport}: {ex}", flush=True)

        save_ledger(ledger)
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    run()
