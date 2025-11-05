import os, time, datetime, json

from espn_adapter import get_final_like_events, fetch_wp_quick
from scoring import score_game
from vibe_tags import pick_vibe
from publisher_x import post_to_x  # uses OAuth1 v1.1 poster

LEDGER_FILE = "/data/posted_ledger.json"

# ---------------- Ledger ---------------- #

def load_ledger():
    try:
        with open(LEDGER_FILE, "r", encoding="utf-8") as f:
            ids = json.load(f)
            print(f"[RUN] ledger ready with {len(ids)} ids", flush=True)
            return set(ids)
    except FileNotFoundError:
        print("[LEDGER] no ledger found; starting fresh", flush=True)
        return set()
    except Exception as e:
        print(f"[LEDGER] load error: {e}; starting empty", flush=True)
        return set()

def save_ledger(ids: set[str]):
    try:
        with open(LEDGER_FILE, "w", encoding="utf-8") as f:
            json.dump(sorted(list(ids)), f)
        print(f"[LEDGER] saved {len(ids)} ids to {LEDGER_FILE}", flush=True)
    except Exception as e:
        print(f"[LEDGER] save error: {e}", flush=True)

posted_ids = load_ledger()

# ----------- EI Logic ----------- #

def calc_ei_from_home_series(series_raw):
    """
    EI = Σ|Δ homeWP|
    - Accepts 0..1 or 0..100.
    - Drops bad values.
    - Auto-converts percents to decimals.
    """
    if not series_raw or len(series_raw) < 2:
        return 0.0

    clean = []
    for v in series_raw:
        try:
            f = float(v)
            if f == f:  # not NaN
                clean.append(f)
        except Exception:
            pass

    if len(clean) < 2:
        return 0.0

    if max(clean) > 1.5:  # looks like percent points
        clean = [x / 100.0 for x in clean]

    total = 0.0
    prev = clean[0]
    for p in clean[1:]:
        total += abs(p - prev)
        prev = p
    return total

# ----------- Formatting ----------- #

def sport_emoji(s_up: str) -> str:
    return "🏀" if s_up == "NBA" else "🏈" if s_up == "NFL" else "⚾"

def date_line_now() -> str:
    # Weekday + mm/dd/yy; Windows can't use %-m so we strip leading zero
    now = datetime.datetime.now()
    if os.name == "nt":
        return now.strftime("%a") + " · " + now.strftime("%m/%d/%y").lstrip("0").replace("/0", "/")
    return now.strftime("%a") + " · " + now.strftime("%-m/%-d/%y")

def format_post_text(s_up: str, game: dict, score_val: int, vibe: str) -> str:
    emoji = sport_emoji(s_up)
    matchup = f"{emoji} {game['away']} @ {game['home']}"
    net = f" — {game['broadcast']}" if game.get("broadcast") else ""
    return (
        f"{matchup}{net} — FINAL\n"
        f"Rewatchability Score™: {score_val}\n"
        f"{vibe}\n"
        f"{date_line_now()}"
    )

# ----------- Posting Flow ----------- #

def post_once(sport_lower: str, event_id: str, comp_id: str | None, game: dict) -> bool:
    # Normalize sport for scoring/vibes
    sport_up = sport_lower.upper()

    # Try to get WP quickly (adapter includes small internal retries)
    series = fetch_wp_quick(sport_lower, event_id, comp_id)
    if not series:
        print(f"[WAIT] no WP yet {event_id}", flush=True)
        return False

    # Debug WP stats
    try:
        s_min, s_max = min(series), max(series)
    except Exception:
        s_min = s_max = None

    ei = calc_ei_from_home_series(series)
    print(f"[EI] {sport_up} {event_id} len={len(series)} min={s_min} max={s_max} EI={ei:.3f}", flush=True)

    # If EI looks like placeholder, wait and retry next loop
    if ei < 0.02:
        print(f"[WAIT] EI too small (likely placeholder WP). Will retry {event_id}.", flush=True)
        return False

    # Score + vibe
    scored = score_game(sport_up, ei)
    score_val = scored.score
    vibe = pick_vibe(score_val)

    text = format_post_text(sport_up, game, score_val, vibe)

    print(text, flush=True)
    print("-" * 40, flush=True)

    # Try to tweet; only mark as posted on success
    if post_to_x(text):
        print(f"[POSTED] {event_id} ({sport_up})", flush=True)
        posted_ids.add(event_id)
        save_ledger(posted_ids)
        return True

    print(f"[X] post failed for {event_id}", flush=True)
    return False

# ----------- Main Loop ----------- #

def run():
    print("[RUN] Cloud worker started. Polling every 60s.", flush=True)
    while True:
        now = datetime.datetime.utcnow()
        d0 = (now - datetime.timedelta(days=1)).strftime("%Y%m%d")
        d1 = now.strftime("%Y%m%d")

        print(f"[HB] checking dates: {d0} and {d1}", flush=True)

        for sport_lower in ["nba", "nfl", "mlb"]:
            for date in [d0, d1]:
                games = get_final_like_events(sport_lower, date)
                print(f"[INFO] {date} FINAL-like events found: {len(games)}", flush=True)

                for g in games:
                    event_id = g["id"]
                    comp_id = g.get("competition_id")

                    if event_id in posted_ids:
                        print(f"[SKIP] already posted {event_id}", flush=True)
                        continue

                    _ = post_once(sport_lower, event_id, comp_id, g)
                    # if False, we just retry next loop

        time.sleep(60)

if __name__ == "__main__":
    run()
