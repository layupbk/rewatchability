from __future__ import annotations
import time
from typing import Any, Dict, List, Optional
import requests

Session = requests.Session()

NBA_PATH = "basketball/nba"
NFL_PATH = "football/nfl"
MLB_PATH = "baseball/mlb"

SPORT_PATH = {
    "NBA": NBA_PATH,
    "NFL": NFL_PATH,
    "MLB": MLB_PATH,
}

def _url_scoreboard(sport: str, date_iso: str) -> str:
    path = SPORT_PATH.get(str(sport).upper(), "")
    return f"https://site.api.espn.com/apis/site/v2/sports/{path}/scoreboard?dates={date_iso}"

def _get_json(url: str, attempts: int = 3, backoff: float = 0.6) -> Optional[dict]:
    for i in range(attempts):
        try:
            r = Session.get(url, timeout=10)
            if r.status_code == 200:
                return r.json()
            else:
                print(f"[DEBUG] GET {url} -> {r.status_code}", flush=True)
        except Exception as e:
            print(f"[DEBUG] GET {url} raised {e}", flush=True)
        time.sleep(backoff * (i + 1))
    return None

# Abbreviations for tweets (short codes)
_ABBR = {
    "ABC": "ABC", "NBC": "NBC", "CBS": "CBS", "FOX": "FOX",
    "ESPN": "ESPN", "ESPN2": "ESPN2", "ESPNU": "ESPNU", "ESPNEWS": "ESPNEWS",
    "TNT": "TNT", "TBS": "TBS", "TRUTV": "truTV", "TRU": "truTV",
    "NBATV": "NBATV", "MLBN": "MLBN", "NFLN": "NFLN",
    "FS1": "FS1", "FS2": "FS2", "BTN": "BTN", "SECN": "SECN",
    "ACCN": "ACCN", "CBSSN": "CBSSN", "LHN": "LHN",
    "PEACOCK": "Peacock",
    "APPLE TV+": "Apple TV+", "APPLETV+": "Apple TV+",
    "PRIME VIDEO": "Prime", "AMAZON PRIME": "Prime", "AMAZON": "Prime", "PRIME": "Prime",
    "YOUTUBE": "YouTube", "YOUTUBE TV": "YouTube",
}

def _norm(s: Any) -> str:
    return str(s or "").strip()

def _up(s: Any) -> str:
    return _norm(s).upper()

def _pick_network_short_for_tweet(game: Dict[str, Any]) -> Optional[str]:
    comps = game.get("competitions") or []
    if not comps:
        return None
    c0 = comps[0]
    bcasts = c0.get("geoBroadcasts") or c0.get("broadcasts") or []
    for b in bcasts:
        name = _up((b.get("media") or {}).get("shortName") or b.get("shortName") or b.get("name") or b.get("channel"))
        market = _up(b.get("market"))
        # Prefer ESPN's national flag, else known name list
        if market == "NATIONAL" or name in _ABBR:
            if name in _ABBR:
                return _ABBR[name]
            if "PRIME" in name or "AMAZON" in name:
                return "Prime"
            if "APPLE" in name:
                return "Apple TV+"
            if "PEACOCK" in name:
                return "Peacock"
            if "YOUTUBE" in name:
                return "YouTube"
            short = name[:12] if name else None
            if short:
                print(f"[BCAST] unknown national '{name}' -> '{short}'", flush=True)
                return short
    return None

def _teams_from_comp(c0: Dict[str, Any]) -> tuple[str, str, bool]:
    # Return road, home, neutral_site?
    neutral = bool(c0.get("neutralSite"))
    teams = c0.get("competitors") or []
    away, home = "", ""
    for t in teams:
        side = _up(t.get("homeAway"))
        name = _norm((t.get("team") or {}).get("displayName") or (t.get("team") or {}).get("shortDisplayName"))
        if side == "AWAY":
            away = name
        elif side == "HOME":
            home = name
    return away, home, neutral

def list_final_events_for_date(date_iso: str, leagues: List[str]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for lg in leagues:
        url = _url_scoreboard(lg, date_iso)
        data = _get_json(url)
        if not data:
            print(f"[DEBUG] scoreboard load failed for {lg}", flush=True)
            continue

        events = data.get("events") or []
        finals_like = 0
        for ev in events:
            comps = ev.get("competitions") or []
            if not comps:
                continue
            c0 = comps[0]

            # Treat status.type.completed True as final
            st = (c0.get("status") or {}).get("type") or {}
            completed = bool(st.get("completed"))
            # Some nights ESPN lags the completed flag; consider a small set of over-timeouts as "final-like" only if needed.
            if not completed:
                continue

            # Build record
            road, home, neutral = _teams_from_comp(c0)
            event_id = _norm(ev.get("id"))
            comp_id  = _norm(c0.get("id"))
            # Abbreviated national broadcaster for tweet
            net_short = _pick_network_short_for_tweet(ev)
            event_name = _norm(ev.get("name"))

            out.append({
                "sport": _up(lg),
                "road": road,
                "home": home,
                "network": net_short,          # short code or None
                "neutral_site": neutral,
                "event_name": event_name,
                "event_id": event_id,
                "comp_id": comp_id,
            })
            finals_like += 1

        print(f"[DEBUG] {lg} events={len(events)}", flush=True)
        print(f"[DEBUG] {lg} finals_like={finals_like}", flush=True)

    return out

# Win probability series (home team probability 0..1 over time)
def fetch_win_probability_series(sport: str, event_id: str, comp_id: str) -> Optional[List[float]]:
    # Try game cast PBPs endpoint first (this is commonly available for national TV)
    try_paths = []
    path = SPORT_PATH.get(_up(sport))
    if path:
        # v2 pbp feed that often contains winprobabilities series
        try_paths.append(f"https://site.web.api.espn.com/apis/v2/sports/{path}/playbyplay?event={event_id}")
        # legacy site feed
        try_paths.append(f"https://site.api.espn.com/apis/site/v2/sports/{path}/playbyplay?event={event_id}")

    for url in try_paths:
        j = _get_json(url)
        if not j:
            continue
        # Look for win prob series
        # Structure differs; search common locations
        # Option A: j["winprobability"]["home"] as a list of floats
        wp = j.get("winprobability") or j.get("winProbability") or {}
        home_series = None
        if isinstance(wp, dict):
            hs = wp.get("home") or wp.get("homeSeries")
            if isinstance(hs, list) and hs:
                home_series = [float(x) for x in hs if x is not None]
        # Option B: timeline items with "homeWinPercentage"
        if not home_series:
            timeline = j.get("gamepackageJSON", {}).get("winprobability") or j.get("drives") or j.get("items")
            seq = []
            if isinstance(timeline, list):
                for it in timeline:
                    v = None
                    if isinstance(it, dict):
                        v = it.get("homeWinPercentage") or it.get("homeWinProb") or it.get("homeWinProbability")
                    if v is not None:
                        try:
                            seq.append(float(v))
                        except Exception:
                            pass
            if seq:
                home_series = seq

        if home_series:
            return home_series

    # If nothing, return None so the caller can retry later
    return None


