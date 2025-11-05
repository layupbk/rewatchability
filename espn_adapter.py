# espn_adapter.py
# Full replacement: FINAL-like event listing + robust national TV detection
# + Win Probability fetching with two fallbacks (summary, play-by-play).

import requests
from typing import List, Dict, Optional

# -------------------------------------------------
# Maps leagues to ESPN paths (pros active; college optional later)
# -------------------------------------------------
SPORT_PATH = {
    "NBA":  "basketball/nba",
    "NFL":  "football/nfl",
    "MLB":  "baseball/mlb",
    # "NCAAF": "football/college-football",                 # enable later
    # "NCAAM": "basketball/mens-college-basketball",        # enable later
}

# -------------------------------------------------
# Small HTTP helper
# -------------------------------------------------
def _http_get_json(url: str, timeout: int = 10):
    try:
        r = requests.get(url, timeout=timeout)
        if r.status_code != 200:
            print(f"[DEBUG] GET {url} -> {r.status_code}", flush=True)
            return None
        return r.json()
    except Exception as e:
        print(f"[DEBUG] HTTP/JSON error for {url}: {e}", flush=True)
        return None

def _normalize(s: str) -> str:
    return (s or "").strip().lower()

# -------------------------------------------------
# Status helpers
# -------------------------------------------------
def _is_final_like(event: dict) -> bool:
    """
    Consider an event 'FINAL-like' if ESPN marks it completed/post or says 'Final'.
    """
    try:
        stat = event.get("status") or {}
        t = stat.get("type") or {}
        if t.get("completed") is True:
            return True
        if _normalize(t.get("state")) == "post":
            return True
        # Fallback string checks
        if "final" in _normalize(t.get("shortDetail")):
            return True
        if "final" in _normalize(t.get("description")):
            return True
    except Exception:
        pass
    return False

def _extract_competitors(event: dict):
    """
    Return (road_name, home_name, neutral_site_bool, comp_id) from first competition.
    """
    comps = event.get("competitions") or []
    if not comps:
        return None, None, False, None
    comp0 = comps[0]
    comp_id = str(comp0.get("id") or "")
    neutral = bool(comp0.get("neutralSite") or False)

    road = home = None
    for c in comp0.get("competitors", []):
        name = (c.get("team", {}) or {}).get("displayName") or (c.get("team", {}) or {}).get("name")
        if c.get("homeAway") == "home":
            home = name
        elif c.get("homeAway") == "away":
            road = name

    return road, home, neutral, comp_id

def _extract_event_name(event: dict) -> Optional[str]:
    """
    Try to pull a meaningful event/tournament name if present.
    Skip generic "Team A vs Team B" titles.
    """
    title = (event.get("name") or "").strip()
    low = title.lower()
    if title and not any(k in low for k in [" vs ", " vs.", " at "]):
        return title

    comps = event.get("competitions") or []
    if comps:
        notes = comps[0].get("notes") or []
        for n in notes:
            txt = (n.get("headline") or "").strip()
            if txt:
                return txt
    return None

# -------------------------------------------------
# National broadcast detection (robust)
# -------------------------------------------------
def _extract_network_national(event: dict) -> Optional[str]:
    """
    Return a national network string (e.g., 'NBC/Peacock', 'ESPN') or None if not national.
    Uses ESPN's market flag when present, and falls back to alias matching.
    """
    comps = event.get("competitions") or []
    if not comps:
        return None
    comp0 = comps[0]

    broadcasts = comp0.get("broadcasts") or []
    if not broadcasts:
        return None

    # Broad set of national aliases, normalized
    NATIONAL_ALIASES = {
        "abc", "espn", "espn2", "espnu", "espn u", "espnews",
        "nbc", "peacock", "cbs", "cbs sports network", "cbssn",
        "fox", "fs1", "fox sports 1", "fs2", "fox sports 2",
        "tnt", "tbs", "truetv", "true tv", "nba tv", "nbatv",
        "mlb network", "nfl network",
        "big ten network", "btn", "b1g network", "b1g", "b1g+",
        "sec network", "secn", "secn+",
        "acc network", "accn", "accnx",
        "prime video", "amazon prime", "amazon", "espn+",
    }

    national_names: list[str] = []

    # Pass 1: trust ESPN market flag
    for b in broadcasts:
        market = _normalize(b.get("market", ""))
        names = [str(n) for n in (b.get("names") or []) if n]
        if market == "national" and names:
            national_names.extend(names)

    # Pass 2: if market not set, alias-match
    if not national_names:
        for b in broadcasts:
            names = [str(n) for n in (b.get("names") or []) if n]
            lowers = [_normalize(n) for n in names]
            if any(n in NATIONAL_ALIASES for n in lowers):
                national_names.extend(names)

    if not national_names:
        return None

    # Dedup + join (e.g., "NBC/Peacock")
    seen = set()
    uniq = []
    for n in national_names:
        if n not in seen:
            seen.add(n)
            uniq.append(n)

    return "/".join(uniq)

# -------------------------------------------------
# Public: list FINAL-like events per date
# -------------------------------------------------
def list_final_events_for_date(date_iso: str, leagues: List[str]) -> List[Dict]:
    """
    Return list of dicts with keys:
      sport, road, home, network, neutral_site, event_name, event_id, comp_id
    Only includes FINAL-like events.
    """
    out: List[Dict] = []
    for league in leagues:
        sport_path = SPORT_PATH.get(league.upper())
        if not sport_path:
            continue

        url = f"https://site.api.espn.com/apis/site/v2/sports/{sport_path}/scoreboard?dates={date_iso}"
        data = _http_get_json(url)
        if not data:
            print(f"[DEBUG] scoreboard load failed for {league}", flush=True)
            continue

        events = data.get("events") or []
        finals = 0
        for ev in events:
            if not _is_final_like(ev):
                continue

            event_id = str(ev.get("id") or "")
            road, home, neutral, comp_id = _extract_competitors(ev)
            if not (event_id and road and home and comp_id):
                continue

            network = _extract_network_national(ev)   # None if non-national
            event_name = _extract_event_name(ev)      # may be None

            out.append({
                "sport": league.upper(),
                "road": road,
                "home": home,
                "network": network,
                "neutral_site": neutral,
                "event_name": event_name,
                "event_id": event_id,
                "comp_id": comp_id,
            })
            finals += 1

        print(f"[DEBUG] {league} events={len(events)}", flush=True)
        print(f"[DEBUG] {league} finals_like={finals}", flush=True)

    return out

# -------------------------------------------------
# Public: Win Probability series (HOME WP in [0,1])
# Tries primary (stub) -> summary -> play-by-play
# -------------------------------------------------
def fetch_win_probability_series(sport: str, event_id: str, comp_id: str) -> Optional[List[float]]:
    # 1) Primary (leave as stub; add your direct endpoint later if desired)
    try:
        primary = _fetch_wp_primary(sport, event_id, comp_id)
        if primary and len(primary) >= 2:
            print(f"[DEBUG] WP primary ok: {event_id}", flush=True)
            return primary
    except Exception as e:
        print(f"[DEBUG] WP primary error {event_id}: {e}", flush=True)

    # 2) Fallback A: summary?event=... → winprobability
    series = _wp_from_summary(sport, event_id)
    if series and len(series) >= 2:
        print(f"[DEBUG] WP fallback SUMMARY ok: {event_id} points={len(series)}", flush=True)
        return series

    # 3) Fallback B: playbyplay?event=... → scan plays for WP
    series = _wp_from_playbyplay(sport, event_id)
    if series and len(series) >= 2:
        print(f"[DEBUG] WP fallback PBP ok: {event_id} points={len(series)}", flush=True)
        return series

    print(f"[DEBUG] WP unavailable for {event_id}", flush=True)
    return None

# -------------------- internals --------------------

def _fetch_wp_primary(sport: str, event_id: str, comp_id: str) -> Optional[List[float]]:
    """
    Stub for a direct probabilities endpoint if you add one later.
    Returning None makes the fallbacks run.
    """
    return None

def _wp_from_summary(sport: str, event_id: str) -> Optional[List[float]]:
    sport_path = SPORT_PATH.get(sport.upper())
    if not sport_path:
        return None
    url = f"https://site.api.espn.com/apis/site/v2/sports/{sport_path}/summary?event={event_id}"
    data = _http_get_json(url, timeout=8)
    if not data:
        return None

    wp_list = data.get("winprobability")
    if not isinstance(wp_list, list) or len(wp_list) < 2:
        return None

    home_series: List[float] = []
    for pt in wp_list:
        if "homeWinPercentage" in pt:
            try:
                home_series.append(float(pt["homeWinPercentage"]))
                continue
            except Exception:
                pass
        if "awayWinPercentage" in pt:
            try:
                aw = float(pt["awayWinPercentage"])
                home_series.append(max(0.0, min(1.0, 1.0 - aw)))
                continue
            except Exception:
                pass
        # else skip point

    return home_series if len(home_series) >= 2 else None

def _wp_from_playbyplay(sport: str, event_id: str) -> Optional[List[float]]:
    """
    Scan ESPN play-by-play for winprobability records.
    Some sports store WP at the root, some on each play item.
    """
    sport_path = SPORT_PATH.get(sport.upper())
    if not sport_path:
        return None
    url = f"https://site.api.espn.com/apis/site/v2/sports/{sport_path}/playbyplay?event={event_id}"
    data = _http_get_json(url, timeout=8)
    if not data:
        return None

    # Case 1: root-level winprobability list (same shape as summary)
    wp_list = data.get("winprobability")
    if isinstance(wp_list, list) and len(wp_list) >= 2:
        home_series: List[float] = []
        for pt in wp_list:
            if "homeWinPercentage" in pt:
                try:
                    home_series.append(float(pt["homeWinPercentage"]))
                except Exception:
                    pass
            elif "awayWinPercentage" in pt:
                try:
                    aw = float(pt["awayWinPercentage"])
                    home_series.append(max(0.0, min(1.0, 1.0 - aw)))
                except Exception:
                    pass
        if len(home_series) >= 2:
            return home_series

    # Case 2: per-play embedding (rare; scan plays)
    try:
        comps = data.get("competitions") or []
        plays = comps[0].get("plays") if comps else None
        if isinstance(plays, list) and plays:
            home_series2: List[float] = []
            for p in plays:
                wp = p.get("winprobability") or {}
                if "homeWinPercentage" in wp:
                    try:
                        home_series2.append(float(wp["homeWinPercentage"]))
                    except Exception:
                        pass
                elif "awayWinPercentage" in wp:
                    try:
                        aw = float(wp["awayWinPercentage"])
                        home_series2.append(max(0.0, min(1.0, 1.0 - aw)))
                    except Exception:
                        pass
            if len(home_series2) >= 2:
                return home_series2
    except Exception:
        pass

    return None
