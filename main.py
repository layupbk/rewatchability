import os, time, datetime
from dotenv import load_dotenv

from espn_adapter import get_final_like_events, fetch_wp_quick
from scoring import score_game
from vibe_tags import pick_vibe
from post_x import post_to_x

load_dotenv()

LEDGER_FILE = "/data/posted_ledger.json"


# ---------------- Ledger ---------------- #

def load_ledger():
    try:
        import json
        with open(LEDGER_FILE, "r") as f:
            ids = json.load(f)
            print(f"[RUN] ledger ready with {len(ids)} ids", flush=True)
            return set(ids)
    except:
        print("[LEDGER] saved 0 ids to /data/posted_ledger.json", flush=True)
        return set()


def save_ledger(ids):
    import json
    with open(LEDGER_FILE, "w") as f:
        json.dump(list(ids), f)
    print(f"[LEDGER] saved {len(ids)} ids to /data/posted_ledger.json", flush=True)


posted_ids = load_ledger()


# ----------- EI Fix Logic ----------- #

def calc_ei_from_home_series(series_raw):
    """
    Build EI = Σ|Δ homeWP|.
    Accepts raw ESPN WP list and normalizes percent→decimal when needed.
    """
    if not series_raw or len(series_raw) < 2:
        return 0.0

    clean = []
    for v in series_raw:
        try:
            f = float(v)
            if f == f:  # not NaN
                clean.append(f)
        except:
            pass

    if len(clean) < 2:
        return 0.0

    # Normalize if looks like percentages
    if max(clean) > 1.5:
        clean = [x / 100.0 for x in clean]

    total = 0.0
    prev = clean[0]
    for p in clean[1:]:
        total += abs(p - prev)
        prev = p

    return total


# ----------- Posting Logic ----------- #

def format_post_text(sport, game, score_val, vibe):
    """
    Build the tweet text (abbreviated style)
    """
    emoji = "🏀" if sport == "nba" else "🏈" if sport == "nfl" else "⚾"
    matchup = f"{emoji} {game['away']} @ {game['home']}"
    net = f" — {game['broadcast']}" if game.get("broadcast") else ""
    date_str = datetime.datetime.now().strftime("%a · %-m/%-d/%y")

    return (
        f"{matchup}{net} — FINAL\n"
        f"Rewatchability Score™: {score_val}\n"
        f"{vibe}\n"
        f"{date_str}"
    )


def post_once(sport, event_id, comp_id, game):
    """
    Fetch WP, compute EI, score, post.
    """

    # Load WP series
    series = fetch_wp_quick(sport, event_id, comp_id)
    if not series:
        print(f"[WAIT] no WP yet {event_id}", flush=True)
        return False

    # Debug WP info
    try:
        s_min, s_max = min(series), max(series)
    except:
        s_min = s_max = None

    ei = calc_ei_from_home_series(series)
    print(f"[EI] {sport} {event_id} len={len(series)} "
          f"min={s_min} max={s_max} EI={ei:.3f}", flush=True)

    # Reject placeholder WP series
    if ei < 0.02:
        print(f"[WAIT] EI too small (likely placeholder WP). Will retry {event_id}.", flush=True)
        return False

    # Score + vibe
    scored = score_game(sport, ei)
    score_val = scored.score
    vibe = pick_vibe(score_val)

    text = format_post_text(sport, game, score_val, vibe)

    print(text)
    print("-" * 40)

    # Post to X (if tokens present)
    ok = post_to_x(text)
    if not ok:
        print(f"[X] post failed for {event_id}", flush=True)
        return False

    print(f"[POSTED] {event_id} ({sport})", flush=True)
    posted_ids.add(event_id)
    save_ledger(posted_ids)
    return True


# ----------- Main Loop ----------- #

def run():
    while True:
        now = datetime.datetime.utcnow()
        d0 = (now - datetime.timedelta(days=1)).strftime("%Y%m%d")
        d1 = now.strftime("%Y%m%d")

        print(f"[HB] checking dates: {d0} and {d1}", flush=True)

        for sport in ["nba", "nfl", "mlb"]:
            for date in [d0, d1]:
                games = get_final_like_events(sport, date)
                print(f"[INFO] {date} FINAL-like events found: {len(games)}", flush=True)

                for g in games:
                    event_id = g["id"]
                    comp_id = g.get("competition_id")

                    if event_id in posted_ids:
                        print(f"[SKIP] already posted {event_id}", flush=True)
                        continue

                    # Attempt post
                    posted = post_once(sport, event_id, comp_id, g)
                    if not posted:
                        # Save skip state? No, allow retry
                        pass

        time.sleep(60)


if __name__ == "__main__":
    run()

